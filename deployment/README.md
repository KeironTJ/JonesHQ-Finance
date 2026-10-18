# Production Operations Runbook

This is the **authoritative, current** guide for operating JonesHQ Finance in
production. Where any other document disagrees with this one, this one wins.
Older guides ([DEPLOYMENT_CHECKLIST](DEPLOYMENT_CHECKLIST.md),
[LXC_SIMPLE_DEPLOYMENT](LXC_SIMPLE_DEPLOYMENT.md),
[docs/PROXMOX_DEPLOYMENT](../docs/PROXMOX_DEPLOYMENT.md),
[docs/DEPLOYMENT](../docs/DEPLOYMENT.md)) describe the original SQLite install and
are kept for history only. [POSTGRES_REHEARSAL](POSTGRES_REHEARSAL.md) is the record
of the completed migration; do not re-run it.

## Current production

| Item | Value |
|---|---|
| Host | Proxmox LXC behind Nginx Proxy Manager (TLS terminated at the proxy) |
| App directory | `/home/joneshq/joneshq-finance` (Linux user `joneshq`) |
| App service | `joneshq-finance` (Gunicorn on port 8000) |
| Retention job | `joneshq-maintenance.timer` → `joneshq-maintenance.service` |
| Rate-limit store | Redis on localhost (`redis-server`) |
| Database | PostgreSQL 17, local peer authentication as `joneshq`, UTF8, `postgresql+psycopg` driver |
| Database name | `joneshq_finance_cutover_rehearsal` |
| Configuration | `/home/joneshq/joneshq-finance/.env.production` (private; never print or commit) |

> **The database named `joneshq_finance_cutover_rehearsal` is PRODUCTION.**
> The name is left over from the October 2026 SQLite → PostgreSQL cutover. Never
> drop, clear, restore over or run tests against it.

**SQLite is no longer used in production.** The file
`instance/joneshq_finance.db` on the server is the obsolete pre-cutover copy and
has not received writes since the cutover. Do not point the app back at it, back
it up as if it were current, or "restore" it: that would silently discard every
change made since the cutover. SQLite remains the default only for local
development and tests.

## Updating production

As root inside the LXC:

```bash
bash /home/joneshq/joneshq-finance/deployment/quick_update.sh
```

On PostgreSQL the updater:

1. Records the current commit and a private copy of `.env.production` in a new
   `/home/joneshq/backups/postgres-update-*` recovery directory.
2. Stops the retention timer/service and the app, then writes a custom-format
   `database.dump` as the app user and verifies its archive listing. A failed
   dump stops the update before any code is pulled.
3. Pulls code, installs `requirements.txt` and `requirements-postgres.txt`,
   checks production configuration and runs the test suite.
4. Runs migrations against the database in `.env.production`, restarts the app
   and checks `/healthz`.
5. Restarts the retention timer only if it was active beforehand.

Stop any other writers you have added before running it. Requirements: the
`joneshq` user can reach PostgreSQL by peer authentication, and `pg_dump` /
`pg_restore` matching the server version are installed. The helpers parse
`.env.production` literally; do not `source` it in your own scripts.

**If an update fails after maintenance begins, the app and retention jobs are
left stopped. There is no automatic restore or code rollback.** A marker at
`/home/joneshq/backups/postgres-update-incomplete` blocks further updater runs
until you resolve it; follow [Recovering from a failed update](#recovering-from-a-failed-update).

## Backups

- **Primary:** Proxmox LXC backups (vzdump) of the whole container, including
  the PostgreSQL data directory, stored on two separate SSDs. A full LXC restore
  has been tested. Check the Proxmox backup job's task history periodically.
- **Per update:** each `quick_update.sh` run leaves a point-in-time
  `database.dump` in its recovery directory.
- **Not a backup:** [backup.sh](backup.sh) is a legacy SQLite script. It now
  refuses to run against a PostgreSQL configuration. Do not schedule it; remove
  any old `joneshq-backup` cron entry.

A PostgreSQL dump/restore rehearsal matched every row and sequence. To take an
ad-hoc dump (for example before risky manual work), as root:

```bash
install -d -o joneshq -g joneshq -m 700 /home/joneshq/backups/manual-$(date +%Y%m%d-%H%M%S)
sudo -u joneshq bash -c 'umask 077; PGCLIENTENCODING=UTF8 pg_dump --format=custom --file=/home/joneshq/backups/manual-YYYYMMDD-HHMMSS/database.dump joneshq_finance_cutover_rehearsal'
sudo -u joneshq pg_restore --list /home/joneshq/backups/manual-YYYYMMDD-HHMMSS/database.dump > /dev/null && echo "archive readable"
```

Replace `manual-YYYYMMDD-HHMMSS` with the directory actually created. A
readable archive listing is not a restore test.

### Recovery artifacts

Recovery directories (`/home/joneshq/backups/postgres-update-*`,
`/home/joneshq/postgres-rehearsal/cutover-*`) contain credentials and personal
data. They are never pruned automatically. Set a retention period, and delete
only specific, reviewed directories once they are no longer needed.

## Recovering from a failed update

- Keep the app, retention jobs and any other writers stopped. Preserve logs and
  the failed database for diagnosis; do not delete it or blindly reset code.
- Decide whether a forward fix is safer. Dependency/test failures before
  migration do not themselves require restoring the database.
- If a restore is needed, create a **new**, explicitly named UTF8 database owned
  by the app role, using `template0` and the original locale. Never restore over
  the failed database as the first recovery step.
- Restore the confirmed `database.dump` into that empty database as the app user
  with `pg_restore --single-transaction --exit-on-error`. Treat a dump as
  confirmed only if the updater reported backup success. Verify the migration
  version, row counts, sequences and application behaviour before using it.
- Restore the recorded compatible code/dependencies and privately review the
  saved environment file. Deliberately point `.env.production` at the recovered
  database; keep all other credentials/settings unchanged.
- Run `deployment/check_production_config.py`, restart the app, verify
  `/healthz` and sign-in, and only then re-enable the retention timer if it was
  previously enabled (the recovery directory's `maintenance-timer-active` file
  records `1` or `0`).
- Once recovery is confirmed, remove only the reviewed
  `/home/joneshq/backups/postgres-update-incomplete` marker.
- Writes accepted after the dump (including during the post-restart health
  check) are not in it. Reconcile them before a restore-based recovery.

For whole-container failures, restore the latest good Proxmox LXC backup instead.

## Monitoring

Monitoring must run outside the application process. Point your monitor at:

- `GET http://127.0.0.1:8000/healthz` (inside the LXC) or
  `https://finance.joneshq.co.uk/healthz` (end-to-end): expect HTTP 200 and
  `{"status":"ok"}` (database + Redis reachable).
- `systemctl is-failed joneshq-maintenance.service`: non-zero exit means healthy;
  `failed` means the last retention run errored.
- `systemctl is-active joneshq-finance redis-server postgresql`.

A monitor inside the LXC cannot report the LXC itself being down; check from
another host too if you need that.

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

Also restrict port 8000 so only the Nginx Proxy Manager container can reach it. See
[Restricting direct access to port 8000](#restricting-direct-access-to-port-8000).

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

## Daily retention cleanup

The server-only `flask maintenance cleanup` command deletes:

- security events strictly older than `SECURITY_EVENT_RETENTION_DAYS` (365 days);
- session records whose absolute expiry or revocation is strictly more than
  30 days ago. Idle expiry alone is not used for deletion.

It operates across all households, including inactive users, without depending
on anyone signing in again. Financial records, users, invites and recovery codes
are untouched. Both tables are cleaned in one transaction; database failures
roll back the transaction and exit non-zero. `--dry-run` counts matching records
without deleting or committing. Concurrent activity can change counts between
preview and execution.

After deploying the code, preview as root inside the LXC:

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && set -a && . ./.env.production && venv/bin/flask maintenance cleanup --dry-run'
```

Review the counts before enabling deletion. Install the units once (the update
script does **not** enable them automatically):

```bash
cd /home/joneshq/joneshq-finance
sudo cp deployment/joneshq-maintenance.service deployment/joneshq-maintenance.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start joneshq-maintenance.service
sudo journalctl -u joneshq-maintenance.service -n 50 --no-pager
sudo systemctl enable --now joneshq-maintenance.timer
sudo systemctl list-timers --all joneshq-maintenance.timer --no-pager
```

Starting the service above performs a real cleanup. The timer runs daily at
03:15 UTC with up to 15 minutes of randomized delay. `Persistent=true` schedules
a catch-up when the timer is activated after missing a run. The one-shot service
does not run in a Gunicorn worker, loads `.env.production`, runs as `joneshq`, and
forces production configuration. It requires a valid production configuration
and access to the database; it does not send mail or need to probe Redis.
Paths match the production layout above.

After later changes to the unit files, copy them again, run `daemon-reload` and
restart the timer. To pause scheduled deletion:

```bash
sudo systemctl disable --now joneshq-maintenance.timer
```

Verify runs periodically with `journalctl -u joneshq-maintenance.service`.
`RETENTION_CLEANUP_COMPLETED` records counts, while `RETENTION_CLEANUP_FAILED`
marks errors. A successful one-shot service normally becomes inactive afterwards;
check the exit result/journal, not whether it remains running. There are no
automatic failure notifications yet. Existing sign-in-triggered cleanup remains
as a fallback. Removing rows from the live database does not erase retained backup
copies or operational log files, and does not immediately shrink PostgreSQL's
on-disk size (autovacuum reclaims space for reuse).

## Household isolation check

Each household's data is separated by `family_id`. Writes that would link a
record to another household's record are blocked by the app and logged as
`TENANCY_REFERENCE_BLOCKED table=... column=...` in the application log. To scan
existing data for cross-household links (read-only; exits 1 if any are found):

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && set -a && . ./.env.production && venv/bin/flask maintenance check-tenancy'
```

Run it after each deployment and before onboarding new households. Any reported
`table.column` count is pre-existing data that needs investigation; do not
delete rows without a fresh dump.

## Income redesign (one-off, after deploying it)

Migration `d5a9c3e7f1b2` runs automatically during the update. It adds the
`income_changes` table and new columns to `recurring_income` / `income`; existing
sources are backfilled as employment, monthly, salary-sacrifice, so their
figures don't change. Nothing is deleted.

After the update, each household should open **Income → Sources → Tools →
Forecasts → Save & refresh** once (or simply open the Payslips page, which tops
up to the horizon). Forecasts are saved a household-chosen number of years ahead
(setting `income.forecast_years`, default 5, 1–10); the refresh also removes
unsettled forecasts beyond it, so older data that ran further out is tidied up.
Paid and actual payslips are never touched.

Sources that used fixed monthly figures keep them; the source page offers
"Switch to calculated" so pay rises and timeline changes take effect.

## Leftover income forecasts (one-off, after the income fixes)

Older versions left a deleted income template's future forecasts (and their
unpaid bank forecast transactions) in place. Migration `c4f8a2d6e0b1` runs
automatically during the update and only clears a wrong "Actual" flag; it deletes
nothing. To remove the leftovers, preview first (read-only):

```bash
sudo -u joneshq bash -c 'cd /home/joneshq/joneshq-finance && set -a && . ./.env.production && venv/bin/flask maintenance purge-orphan-income-forecasts'
```

Each line is one household/person/source run of future, unpaid rows no longer
linked to a template. Paid rows, rows with a paid transaction and a lone future
one-off income are never selected. If every line is expected, re-run with
`--apply` (optionally `--family ID` to do one household at a time). The update's
`database.dump` is your restore point; take an ad-hoc dump first if the update was
not run recently.

The command does not look for bank transactions that have no income record at
all (for example imported "Salary" forecasts); review those in the account view.

## Site admin area

`/site-admin` is the operator area, separate from your own household's pages.
It needs `is_site_admin` (`flask site-admin grant EMAIL`), two-factor login and a
recent password confirmation. The old `/admin` address redirects there.

- **Overview**: service counts and the effective, non-secret configuration,
  including database engine and migration revision.
- **Household invites**: one-time registration links for new households.
- **Service settings**: pause new household sign-ups and set an announcement
  banner. These are stored in the `site_settings` table (migration
  `b3e5d7f9a1c2`), take effect immediately without a restart and are audited.
- **Users & audit console** (`/site-admin/console`): deactivate, reactivate,
  unlock or sign out users; view households, invites (without tokens), sessions
  and security events; edit the global tax-year templates. It doesn't show
  household financial data and can't create, edit or delete users.

See [AUTHENTICATION_SETUP.md](../docs/AUTHENTICATION_SETUP.md#site-admin-area-site-admin).

## Restricting direct access to port 8000

Nginx Proxy Manager (NPM) runs in a separate LXC and forwards to this container
on port 8000, so Gunicorn must keep listening on the network (`0.0.0.0:8000`).
Without restrictions, any device on the LAN can open `http://<finance-IP>:8000`
directly, skipping HTTPS, and fake `X-Forwarded-For` to dodge login rate limits.
Two layers close this:

### 1. App: `TRUSTED_PROXY_IPS`

The NPM container needs a fixed address (static IP or DHCP reservation). Find it
in Proxmox → NPM container → **Network**. Then, as root in the finance LXC:

```bash
cd /home/joneshq/joneshq-finance
grep -q '^TRUSTED_PROXY_IPS=' .env.production \
  || echo 'TRUSTED_PROXY_IPS=<NPM-IP>' >> .env.production
sudo -u joneshq venv/bin/python deployment/check_production_config.py
systemctl restart joneshq-finance
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz   # 200
```

Then check the public site still loads and you can sign in. From another LAN
device, `curl -i http://<finance-IP>:8000/healthz` should return **403 Direct
access is not allowed**.

If the public site returns that 403 instead, the address is wrong: remove the
`TRUSTED_PROXY_IPS` line and restart, then recheck the NPM IP. The site admin
**Overview** shows "Direct connections: Proxy and local only" when it's active.

### 2. Proxmox firewall on the finance container

Guest firewalls only work when the datacenter firewall is enabled. **Enabling the
datacenter firewall also filters the Proxmox host itself**, so do it in this order:

1. Datacenter → Firewall → **Options**: set **Input Policy** to `ACCEPT` first
   (keeps the host's web UI and SSH reachable), then set **Firewall** to `Yes`.
2. Finance container → **Network** → `net0` → Edit: tick **Firewall**.
3. Finance container → Firewall → **Add** two rules, in this order (top first):
   - Direction `in`, Action `ACCEPT`, Protocol `tcp`, Dest. port `8000`,
     Source `<NPM-IP>`, Enable ticked.
   - Direction `in`, Action `DROP`, Protocol `tcp`, Dest. port `8000`,
     Source empty, Enable ticked.
4. Finance container → Firewall → **Options**: set **Firewall** to `Yes`. Leave
   Input Policy `ACCEPT` so SSH and anything else you use keep working.

Check again: the public site works; a LAN `curl` to port 8000 now times out
instead of returning 403. Local checks inside the LXC (`127.0.0.1`) are
unaffected. To undo, set the container's Firewall option back to `No`.

## Files

Current:

- **quick_update.sh** - Backs up (PostgreSQL dump), pulls, tests, migrates and restarts production
- **postgres_update_backup.py** - PostgreSQL dump/verify helper used by `quick_update.sh`
- **check_production_config.py** - Verifies `.env.production` and Redis before restarts
- **joneshq-finance.service** - App systemd unit
- **joneshq-maintenance.service / .timer** - Daily security-log/session retention job
- **gunicorn_config.py** - Gunicorn WSGI server configuration
- **setup_redis.sh** - One-time Redis setup for login rate limiting
- **migrate_production.py** - Runs migrations using `.env.production` (called by `quick_update.sh`)

Historical / do not use on current production:

- **POSTGRES_REHEARSAL.md**, **prepare_postgres_source.py**, **rehearse_postgres.py**,
  **rehearse_update_guard.py** - SQLite ? PostgreSQL migration tooling (completed October 2026)
- **backup.sh** - Legacy SQLite backup (used by `quick_update.sh` only on SQLite installs); refuses to run on PostgreSQL
- **deploy.sh** - Original fresh-install script; configures SQLite. Refuses to run unless `ALLOW_LEGACY_SQLITE_DEPLOY=1`
- **nginx.conf** - Only for a self-hosted Nginx; production uses Nginx Proxy Manager
- **DEPLOYMENT_CHECKLIST.md**, **LXC_SIMPLE_DEPLOYMENT.md** - Original SQLite install guides

## Building a new server

There is no current fresh-install script for PostgreSQL. `deploy.sh` and the older
guides create a SQLite installation. If you need to rebuild, restore the latest
Proxmox LXC backup rather than installing from scratch. If a from-scratch install is
ever required, install PostgreSQL and Redis as described in this runbook, restore a
confirmed `database.dump` into a new database, and verify health before opening it.
