#!/bin/bash
#
# Quick Update Script for JonesHQ Finance
# Automates: git pull, db migration, dependency install, and service restart
#
# Usage (as root on the server):
#   bash /home/joneshq/joneshq-finance/deployment/quick_update.sh
#
# Or from Windows in one line:
#   ssh root@<server-ip> "bash /home/joneshq/joneshq-finance/deployment/quick_update.sh"
#

set -euo pipefail
umask 077

APP_DIR="/home/joneshq/joneshq-finance"
APP_USER="joneshq"
SERVICE_NAME="joneshq-finance"
BACKUP_DIR="/home/joneshq/backups"
RECOVERY_MARKER="$BACKUP_DIR/postgres-update-incomplete"
LOCK_FILE="/var/lock/joneshq-quick-update.lock"
HEALTH_URL="http://127.0.0.1:8000/healthz"
BACKUP_FILE=""
PREV_COMMIT=""
PG_MAINTENANCE=0
UPDATE_COMPLETE=0
MAINTENANCE_TIMER_ACTIVE=0
RECOVERY_DIR=""

update_exit() {
    result=$?
    trap - EXIT
    if [ "$PG_MAINTENANCE" -eq 1 ] && [ "$UPDATE_COMPLETE" -ne 1 ]; then
        set +e
        systemctl stop "$SERVICE_NAME" joneshq-maintenance.timer joneshq-maintenance.service
        echo "ERROR: PostgreSQL update did not complete. Do NOT reopen the app to writes."
        echo "No database restore or code rollback was attempted."
        echo "Previous commit: $PREV_COMMIT"
        echo "Recovery directory: $RECOVERY_DIR"
        echo "Recovery dump (usable only if backup success was reported): $BACKUP_FILE"
        echo "Check service/timer are stopped; follow 'Recovering from a failed update' in deployment/README.md."
        [ "$result" -ne 0 ] || result=1
    fi
    exit "$result"
}
trap update_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Re-exec under an exclusive lock so this can't run twice concurrently
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "ERROR: Another update is already in progress (lock: $LOCK_FILE)"
    exit 1
fi

# Mirror all output to a run log for later auditing
mkdir -p "$APP_DIR/logs"
exec > >(tee -a "$APP_DIR/logs/deploy.log") 2>&1

echo "========================================="
echo "  JonesHQ Finance - Quick Update"
echo "  $(date)"
echo "========================================="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Run this script as root (it needs to restart the systemd service)"
    exit 1
fi

if [ -n "$(sudo -u $APP_USER bash -c "cd $APP_DIR && git status --porcelain --untracked-files=no")" ]; then
    echo "ERROR: Working tree has uncommitted changes on the server. Resolve manually before updating."
    exit 1
fi

PREV_COMMIT=$(sudo -u $APP_USER bash -c "cd $APP_DIR && git rev-parse HEAD")

if [ -e "$RECOVERY_MARKER" ]; then
    echo "ERROR: A previous PostgreSQL update requires manual recovery."
    echo "Review $RECOVERY_MARKER and the recovery runbook before updating again."
    exit 1
fi

# Production is PostgreSQL-only: validate the configured URL and client tools before pulling code.
if ! sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && venv/bin/python deployment/postgres_update_backup.py --check"; then
    echo "ERROR: Unsupported database configuration. Update stopped before pulling code."
    exit 1
fi

install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$BACKUP_DIR"
RECOVERY_DIR=$(sudo -u "$APP_USER" mktemp -d "$BACKUP_DIR/postgres-update-XXXXXXXX")
BACKUP_FILE="$RECOVERY_DIR/database.dump"
printf '%s\n' "$PREV_COMMIT" > "$RECOVERY_DIR/previous-commit"
cp "$APP_DIR/.env.production" "$RECOVERY_DIR/env.production"
chown "$APP_USER:$APP_USER" "$RECOVERY_DIR/previous-commit" "$RECOVERY_DIR/env.production"
if systemctl is-active --quiet joneshq-maintenance.timer; then
    MAINTENANCE_TIMER_ACTIVE=1
fi
printf '%s\n' "$MAINTENANCE_TIMER_ACTIVE" > "$RECOVERY_DIR/maintenance-timer-active"
PG_MAINTENANCE=1
(set -o noclobber; printf '%s\n' "$RECOVERY_DIR" > "$RECOVERY_MARKER")
if systemctl cat joneshq-maintenance.timer >/dev/null 2>&1; then
    systemctl stop joneshq-maintenance.timer
fi
if systemctl cat joneshq-maintenance.service >/dev/null 2>&1; then
    systemctl stop joneshq-maintenance.service
fi
systemctl stop "$SERVICE_NAME"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && venv/bin/python deployment/postgres_update_backup.py --output '$BACKUP_FILE'"
echo "PostgreSQL recovery point: $RECOVERY_DIR"

echo "Step 1: Pulling latest changes from origin/main..."
sudo -u $APP_USER bash -c "cd $APP_DIR && git pull --ff-only origin main"

echo "Step 2: Installing/updating Python dependencies..."
sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pip install -r requirements-postgres.txt"

echo "Step 3: Verifying production configuration and Redis..."
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && venv/bin/python deployment/check_production_config.py"; then
    echo "If Redis is not set up yet, run: bash $APP_DIR/deployment/setup_redis.sh"
    exit 1
fi

echo "Step 4: Running test suite..."
sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pip install -q -r requirements-dev.txt"
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pytest -q"; then
    echo "ERROR: Tests failed; manual recovery required."
    exit 1
fi

echo "Step 5: Applying database migrations..."
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && venv/bin/python deployment/migrate_production.py"; then
    echo "ERROR: PostgreSQL migration failed; manual recovery required."
    exit 1
fi

echo "Step 6: Reloading systemd and restarting service..."
systemctl daemon-reload
systemctl restart $SERVICE_NAME

echo "Step 7: Checking service status..."
sleep 3
if ! systemctl is-active --quiet $SERVICE_NAME; then
    echo "ERROR: PostgreSQL-backed app failed to start; manual recovery required."
    exit 1
fi

echo "Step 8: Verifying the app responds to real requests..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" || echo "000")
if [ "$HTTP_STATUS" != "200" ]; then
    echo "ERROR: PostgreSQL-backed app health check failed (HTTP $HTTP_STATUS); manual recovery required."
    exit 1
fi
echo "Health check OK (HTTP $HTTP_STATUS)"

systemctl status $SERVICE_NAME --no-pager -l

if [ "$MAINTENANCE_TIMER_ACTIVE" -eq 1 ]; then
    systemctl start joneshq-maintenance.timer
fi
rm -- "$RECOVERY_MARKER"
UPDATE_COMPLETE=1

echo ""
echo "========================================="
echo "  Update Complete!"
echo "========================================="
