#!/bin/bash
#
# One-time Redis setup for JonesHQ Finance login rate limiting.
#
# Redis is a small in-memory service used here only to hold short-lived
# login-attempt counters shared by all Gunicorn workers. It stores no
# financial data. It is installed on this container and only listens on
# localhost, so nothing outside this container can reach it.
#
# Safe to re-run. Does NOT restart the app; run quick_update.sh afterwards.
#
# Usage (as root, inside the app's LXC container):
#   bash setup_redis.sh [APP_DIR]
#
# Default APP_DIR: /home/joneshq/joneshq-finance
#

set -euo pipefail

APP_DIR="${1:-/home/joneshq/joneshq-finance}"
APP_USER="joneshq"
SERVICE_NAME="joneshq-finance"
ENV_FILE="$APP_DIR/.env.production"
REDIS_URI="redis://127.0.0.1:6379/0"
REDIS_CONF="/etc/redis/redis.conf"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}OK${NC}  $*"; }
warn() { echo -e "${YELLOW}!!${NC}  $*"; }
fail() { echo -e "${RED}ERROR${NC} $*"; exit 1; }

ask_yes() {
    # ask_yes "question" default(y|n) -> returns 0 for yes
    local prompt="$1" default="$2" reply
    if [ ! -t 0 ]; then [ "$default" = "y" ]; return; fi
    read -r -p "$prompt [$([ "$default" = y ] && echo Y/n || echo y/N)] " reply
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[Yy] ]]
}

set_env_var() {
    # Replace or append KEY=VALUE in the env file, keeping other lines intact.
    local key="$1" value="$2" tmp
    tmp="$(mktemp)"
    grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true
    echo "${key}=${value}" >> "$tmp"
    cat "$tmp" > "$ENV_FILE"
    rm -f "$tmp"
}

get_env_var() {
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
}

[ "$EUID" -eq 0 ] || fail "Run as root (sudo bash setup_redis.sh)."
[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found. Pass the app directory as the first argument."

echo "========================================="
echo "  JonesHQ Finance - Redis setup"
echo "  App directory: $APP_DIR"
echo "========================================="

# 1. Install Redis
if ! command -v redis-server >/dev/null 2>&1; then
    echo "Installing redis-server..."
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq redis-server
fi
ok "redis-server installed ($(redis-server --version | awk '{print $3}'))"

# 2. Keep Redis private to this container
bind_line="$(grep -E '^\s*bind\s' "$REDIS_CONF" | tail -n 1 || true)"
if [ -z "$bind_line" ] || echo "$bind_line" | sed -E 's/^\s*bind\s+//' | tr ' ' '\n' \
        | grep -vE '^(-?127\.0\.0\.1|-?::1|)$' | grep -q .; then
    cp "$REDIS_CONF" "$REDIS_CONF.bak.$(date +%Y%m%d_%H%M%S)"
    sed -i -E '/^\s*bind\s/d' "$REDIS_CONF"
    echo "bind 127.0.0.1" >> "$REDIS_CONF"
    warn "Redis was not restricted to localhost; set 'bind 127.0.0.1' (backup saved)."
fi
if ! grep -qE '^\s*protected-mode\s+yes' "$REDIS_CONF"; then
    sed -i -E '/^\s*protected-mode\s/d' "$REDIS_CONF"
    echo "protected-mode yes" >> "$REDIS_CONF"
fi

systemctl enable redis-server >/dev/null 2>&1
systemctl restart redis-server
sleep 1

[ "$(redis-cli -h 127.0.0.1 ping 2>/dev/null)" = "PONG" ] || fail "Redis is not responding. Check: journalctl -u redis-server -n 50
      (In an unprivileged Proxmox LXC, a 226/NAMESPACE error means enabling
       Options -> Features -> Nesting on the container, then re-running this script.)"
ok "Redis is running and responding"

exposed="$(ss -ltnH 'sport = :6379' | awk '{print $4}' | grep -vE '^(127\.0\.0\.1|\[::1\]):6379$' || true)"
[ -z "$exposed" ] || fail "Redis is listening on a non-local address: $exposed"
ok "Redis only accepts connections from inside this container"

# 3. Update the app's production environment file
cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d_%H%M%S)"
ok "Backed up $ENV_FILE"

if [ -z "$(get_env_var RATELIMIT_STORAGE_URI)" ]; then
    set_env_var RATELIMIT_STORAGE_URI "$REDIS_URI"
    ok "Set RATELIMIT_STORAGE_URI=$REDIS_URI"
else
    ok "RATELIMIT_STORAGE_URI already set ($(get_env_var RATELIMIT_STORAGE_URI))"
fi

if [ -z "$(get_env_var TRUSTED_PROXY_COUNT)" ]; then
    echo ""
    echo "How many reverse proxies sit in front of the app?"
    echo "  Internet -> Nginx Proxy Manager -> this container  = 1 (typical)"
    echo "  Internet -> Cloudflare (orange cloud) -> NPM -> app = 2"
    proxies=1
    if [ -t 0 ]; then
        read -r -p "Number of proxies [1]: " reply
        proxies="${reply:-1}"
    fi
    [[ "$proxies" =~ ^[0-9]+$ ]] || fail "Proxy count must be a whole number."
    set_env_var TRUSTED_PROXY_COUNT "$proxies"
    ok "Set TRUSTED_PROXY_COUNT=$proxies"
else
    ok "TRUSTED_PROXY_COUNT already set ($(get_env_var TRUSTED_PROXY_COUNT))"
fi

# 4. Make sure SECRET_KEY is a real generated value
secret="$(get_env_var SECRET_KEY)"
if [ -z "$secret" ] || [ "${#secret}" -lt 32 ] || [[ "$secret" == *'$('* ]] || [[ "$secret" == *'`'* ]]; then
    echo ""
    warn "SECRET_KEY is missing, too short, or is a literal shell command"
    warn "(systemd does not run \$(...) in env files, so it would be a guessable fixed string)."
    if ask_yes "Generate a new random SECRET_KEY now? (everyone will need to log in again)" y; then
        set_env_var SECRET_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
        ok "Generated a new SECRET_KEY"
    else
        warn "SECRET_KEY left unchanged; the app will refuse to start until it is fixed."
    fi
else
    ok "SECRET_KEY looks valid"
fi

chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# 5. Start the app only after Redis is up
mkdir -p "/etc/systemd/system/$SERVICE_NAME.service.d"
cat > "/etc/systemd/system/$SERVICE_NAME.service.d/redis.conf" <<EOF
[Unit]
Wants=redis-server.service
After=redis-server.service
EOF
systemctl daemon-reload
ok "App service now starts after Redis"

echo ""
echo "========================================="
echo -e "${GREEN}  Redis setup complete${NC}"
echo "========================================="
echo "The running app was not restarted. Next, deploy the update as usual:"
echo "  bash $APP_DIR/deployment/quick_update.sh"
echo ""
echo "Useful commands:"
echo "  Redis status:  systemctl status redis-server"
echo "  Ping Redis:    redis-cli ping            (expect PONG)"
echo "  Redis logs:    journalctl -u redis-server -n 50"
