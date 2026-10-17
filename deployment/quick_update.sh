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
DB_BACKEND=""
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

# Reverts code to the pre-update commit and reinstalls matching dependencies
rollback_code() {
    echo "Rolling back code to previous commit $PREV_COMMIT..."
    sudo -u $APP_USER bash -c "cd $APP_DIR && git reset --hard $PREV_COMMIT"
    sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pip install -r requirements.txt"
}

# Full rollback: code + database, then restart on the known-good state
rollback_full() {
    if [ "$DB_BACKEND" = "postgresql" ]; then
        echo "ERROR: PostgreSQL recovery requires operator review; leaving service stopped."
        return 1
    fi
    rollback_code
    if [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ]; then
        echo "Restoring database from $BACKUP_FILE..."
        sudo -u $APP_USER bash -c "gunzip -c '$BACKUP_FILE' > '$APP_DIR/instance/joneshq_finance.db'"
    fi
    systemctl restart $SERVICE_NAME
    echo "Rollback complete. Service restarted on previous code/database."
}

if [ -n "$(sudo -u $APP_USER bash -c "cd $APP_DIR && git status --porcelain --untracked-files=no")" ]; then
    echo "ERROR: Working tree has uncommitted changes on the server. Resolve manually before updating."
    exit 1
fi

PREV_COMMIT=$(sudo -u $APP_USER bash -c "cd $APP_DIR && git rev-parse HEAD")

if ! DB_BACKEND=$(sudo -u $APP_USER bash -c "cd $APP_DIR && venv/bin/python deployment/rehearse_update_guard.py --backend"); then
    echo "ERROR: Unsupported database configuration. Update stopped before pulling code."
    exit 1
fi

if [ -e "$RECOVERY_MARKER" ]; then
    echo "ERROR: A previous PostgreSQL update requires manual recovery."
    echo "Review $RECOVERY_MARKER and the recovery runbook before updating again."
    exit 1
fi

if [ "$DB_BACKEND" = "postgresql" ]; then
    sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && venv/bin/python deployment/postgres_update_backup.py --check"
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
fi

echo "Step 1: Pulling latest changes from origin/main..."
sudo -u $APP_USER bash -c "cd $APP_DIR && git pull --ff-only origin main"

echo "Step 2: Installing/updating Python dependencies..."
REQUIREMENTS="requirements.txt"
if [ "$DB_BACKEND" = "postgresql" ]; then
    REQUIREMENTS="requirements-postgres.txt"
fi
sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pip install -r '$REQUIREMENTS'"

echo "Step 2b: Verifying production configuration and Redis..."
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && venv/bin/python deployment/check_production_config.py"; then
    if [ "$DB_BACKEND" = "postgresql" ]; then
        exit 1
    fi
    echo "ERROR: Production configuration is not ready. Rolling back code (service not restarted)."
    echo "If Redis is not set up yet, run: bash $APP_DIR/deployment/setup_redis.sh"
    rollback_code
    exit 1
fi

echo "Step 3: Backing up database before migration..."
if [ "$DB_BACKEND" = "sqlite" ]; then
    bash $APP_DIR/deployment/backup.sh
    BACKUP_FILE=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'joneshq_finance_*.db.gz' -printf '%T@ %p\n' | sort -nr | sed -n '1s/^[^ ]* //p')
    if [ -z "$BACKUP_FILE" ]; then
        echo "ERROR: SQLite recovery backup not found."
        exit 1
    fi
else
    echo "PostgreSQL recovery dump already taken with app and maintenance writers stopped."
fi

echo "Step 4: Running test suite..."
sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pip install -q -r requirements-dev.txt"
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pytest -q"; then
    if [ "$DB_BACKEND" = "postgresql" ]; then
        exit 1
    fi
    echo "ERROR: Tests failed. Rolling back code (database untouched, service not restarted)."
    rollback_code
    exit 1
fi

echo "Step 5: Applying database migrations..."
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && venv/bin/python deployment/migrate_production.py"; then
    if [ "$DB_BACKEND" = "postgresql" ]; then
        echo "ERROR: PostgreSQL migration failed; manual recovery required."
        exit 1
    fi
    echo "ERROR: Migration failed. Rolling back code and database."
    rollback_full
    exit 1
fi

echo "Step 6: Reloading systemd and restarting service..."
systemctl daemon-reload
systemctl restart $SERVICE_NAME

echo "Step 7: Checking service status..."
sleep 3
if ! systemctl is-active --quiet $SERVICE_NAME; then
    if [ "$DB_BACKEND" = "postgresql" ]; then
        echo "ERROR: PostgreSQL-backed app failed to start; manual recovery required."
        exit 1
    fi
    echo "ERROR: Service failed to start after update. Rolling back code and database."
    rollback_full
    exit 1
fi

echo "Step 8: Verifying the app responds to real requests..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" || echo "000")
if [ "$HTTP_STATUS" != "200" ]; then
    if [ "$DB_BACKEND" = "postgresql" ]; then
        echo "ERROR: PostgreSQL-backed app health check failed (HTTP $HTTP_STATUS); manual recovery required."
        exit 1
    fi
    echo "ERROR: Health check got HTTP $HTTP_STATUS from $HEALTH_URL. Rolling back code and database."
    rollback_full
    exit 1
fi
echo "Health check OK (HTTP $HTTP_STATUS)"

systemctl status $SERVICE_NAME --no-pager -l

if [ "$MAINTENANCE_TIMER_ACTIVE" -eq 1 ]; then
    systemctl start joneshq-maintenance.timer
fi
if [ "$DB_BACKEND" = "postgresql" ]; then
    rm -- "$RECOVERY_MARKER"
fi
UPDATE_COMPLETE=1

echo ""
echo "========================================="
echo "  Update Complete!"
echo "========================================="
