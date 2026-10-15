# Deployment Files

This directory contains production deployment configurations for JonesHQ Finance.

## Required authentication settings

Before restarting production after the authentication hardening update:

- Install the updated `requirements.txt` (includes the Redis client).
- Set `SECRET_KEY` to a stable, randomly generated secret of at least 32 characters.
  Do not rotate it casually: changing it invalidates existing signed sessions.
- Set `DATABASE_URL` or `SQLALCHEMY_DATABASE_URI`.
- Run a private Redis service and set `RATELIMIT_STORAGE_URI`, for example
  `redis://127.0.0.1:6379/0`. Use the same backend and database for all app workers.
  Do not expose Redis publicly; use authentication/TLS when appropriate.
- With the supplied single nginx reverse proxy, set `TRUSTED_PROXY_COUNT=1`.
  The default is `0` (forwarded headers are ignored). Only enable this when
  Gunicorn is inaccessible directly and the proxy supplies trusted forwarding
  headers. Additional proxies require reviewing the chain, not guessing a count.
- Use the production configuration and HTTPS. Both session and remember-me
  cookies are Secure, HttpOnly, and SameSite=Lax in production.

Production startup now rejects missing settings and in-memory rate-limit storage.
Redis errors are not silently bypassed: an unavailable backend can prevent requests
from succeeding. Monitor Redis availability. Development and tests use memory storage.

See [Authentication setup](../docs/AUTHENTICATION_SETUP.md) for limits, tests,
and the remaining public-launch work. No SMTP or database migration is required
for this foundation update.

## Upgrading an existing server (Redis setup)

**What is Redis?** A small in-memory service. Here it only holds short-lived login
attempt counters (e.g. "this IP tried 6 times this minute") so that both Gunicorn
workers share the same limits. It stores no financial data, needs no maintenance, and
only listens inside the app container. If it is lost or restarted, counters reset.

Run these once, as root, inside the app's Proxmox container **before** the next update
(the updated app refuses to start in production without Redis):

```bash
cd /home/joneshq/joneshq-finance
sudo -u joneshq git fetch origin
sudo -u joneshq git show origin/main:deployment/setup_redis.sh > /tmp/setup_redis.sh
bash /tmp/setup_redis.sh            # installs Redis, updates .env.production
bash deployment/quick_update.sh     # deploys the update as normal
```

`setup_redis.sh` is safe to re-run. It:

- installs `redis-server`, restricts it to localhost and checks it responds;
- backs up `.env.production`, then adds `RATELIMIT_STORAGE_URI` and `TRUSTED_PROXY_COUNT`
  (asks how many proxies; Nginx Proxy Manager alone = `1`);
- replaces a missing/weak `SECRET_KEY`, including a literal `$(python3 ...)` line from
  older guides (systemd never ran that command, so it was a guessable fixed string).
  This logs everyone out once;
- makes the app service start after Redis. It does not restart the app.

`quick_update.sh` now runs `deployment/check_production_config.py` before restarting
and rolls back the code if settings or Redis are not ready, so the live site stays up.
You can run the check yourself at any time:

```bash
sudo -u joneshq bash -c "cd /home/joneshq/joneshq-finance && venv/bin/python deployment/check_production_config.py"
```

If Redis fails to start in an unprivileged LXC with `226/NAMESPACE`, enable
Proxmox → container → Options → Features → **Nesting**, then re-run the setup script.

Also restrict port 8000 so only the Nginx Proxy Manager host can reach it (Proxmox
firewall or `ufw allow from <NPM-IP> to any port 8000`); otherwise LAN devices could
bypass HTTPS and spoof forwarded client IPs.

After updating, check through the public URL: login works, the browser shows the
session cookie as Secure/HttpOnly, and 11 rapid wrong-password attempts return
"Too many requests".

## Health checks and operational logs

### Readiness

`GET /healthz` performs a read-only `SELECT 1` against the configured database and
checks the configured rate-limit storage (Redis in production). It returns only:

- HTTP 200: `{"status":"ok"}`
- HTTP 503: `{"status":"unavailable"}`

The response is not cached, does not require login and does not expose connection
strings, versions, user data or failure details. It bypasses login-session loading
and rate limiting so a failed backend can be reported instead of blocking the
check. Checks run against shared backends, not worker-local status counters.
This checks connectivity, not migration correctness, data integrity, disk capacity,
SMTP delivery or backup freshness. Backend connection timeouts still apply.

From the LXC:

```bash
curl --fail --show-error --max-time 10 http://127.0.0.1:8000/healthz
```

Also check `https://finance.joneshq.co.uk/healthz` from outside the LXC to exercise
DNS, HTTPS and the reverse proxy. An external monitor should check every 60 seconds,
require HTTP 200 and the `ok` status, and alert after repeated failures rather than
one missed probe. Set a request timeout. No external monitor or alerts are installed
by these changes.

For component-level output, as root in the LXC:

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && set -a && . ./.env.production && venv/bin/flask health'
```

This command exits 1 if either component fails, otherwise 0. Keep shell-sourced
environment values quoted where necessary. The update script now uses `/healthz`
for its post-restart check.

### Email failures

Real SMTP attempts produce searchable application log markers:

- `MAIL_SMTP_ACCEPTED`: the SMTP server accepted the message, **not** proof it
  reached the inbox. Review Resend's delivery/bounce information separately.
- `MAIL_DELIVERY_FAILED error_type=...`: SMTP delivery failed. Both synchronous
  test sends and background sends are covered. This marker excludes addresses,
  message bodies, reset links, API keys and provider error text.

Testing-mode captured messages do not represent SMTP attempts. Disabled email
does not generate a success marker. Background sends are still best-effort:
there is no durable queue, automatic retry, historical health counter or automatic
notification. Worker shutdown can interrupt a pending send.

Check recent events without copying sensitive log contents into public channels:

```bash
sudo journalctl -u joneshq-finance --since '24 hours ago' --no-pager
sudo grep -E 'MAIL_DELIVERY_FAILED|MAIL_SMTP_ACCEPTED|HEALTH_.*FAILED|HEALTH_.*UNAVAILABLE' \
    /home/joneshq/joneshq-finance/logs/joneshq_finance.log | tail -n 50
```

The application file is shared by CLI runs and workers; it is a diagnostic log,
not a durable multi-worker event store. For worker/service problems also inspect:

```bash
sudo systemctl is-active joneshq-finance redis-server
sudo journalctl -u redis-server --since '1 hour ago' --no-pager
sudo tail -n 100 /home/joneshq/joneshq-finance/logs/error.log
```

For an end-to-end email check, use `flask email test YOUR_ADDRESS` with the same
environment loading shown above, then confirm the message arrived. Health probes
do not send emails or contact SMTP. Configure future outage notifications on
another machine and use a channel independent of the app's SMTP provider.

## Files

- **nginx.conf** - Nginx reverse proxy configuration
- **joneshq-finance.service** - Systemd service file
- **gunicorn_config.py** - Gunicorn WSGI server configuration
- **deploy.sh** - Automated deployment script
- **quick_update.sh** - Pull, verify, test, migrate and restart an existing install
- **setup_redis.sh** - One-time Redis setup for login rate limiting
- **check_production_config.py** - Verifies `.env.production` and Redis before restarts
- **backup.sh** - Database backup script

## Quick Start

See [PROXMOX_DEPLOYMENT.md](../docs/PROXMOX_DEPLOYMENT.md) for complete deployment instructions.

## Manual Deployment

### 1. Copy files to server

```bash
# On server
sudo mkdir -p /home/joneshq/app/deployment
```

```powershell
# From Windows
scp deployment/* joneshq@<server-ip>:/home/joneshq/app/deployment/
```

### 2. Install service

```bash
sudo cp deployment/joneshq-finance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable joneshq-finance
```

### 3. Configure nginx

```bash
sudo cp deployment/nginx.conf /etc/nginx/sites-available/finance.joneshq.co.uk
sudo ln -s /etc/nginx/sites-available/finance.joneshq.co.uk /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 4. Set up backups

```bash
sudo cp deployment/backup.sh /usr/local/bin/joneshq-backup
sudo chmod +x /usr/local/bin/joneshq-backup

# Add to crontab (daily at 2 AM)
sudo crontab -e
# Add line: 0 2 * * * /usr/local/bin/joneshq-backup
```

## Automated Deployment

Run the automated deployment script:

```bash
sudo bash deployment/deploy.sh
```

This will:
- Install all dependencies
- Create user and directories
- Set up Python environment
- Configure nginx and SSL
- Install and start services
- Configure firewall
