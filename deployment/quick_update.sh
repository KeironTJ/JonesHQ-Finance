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

set -e  # Exit on error

APP_DIR="/home/joneshq/joneshq-finance"
APP_USER="joneshq"
SERVICE_NAME="joneshq-finance"
BACKUP_DIR="/home/joneshq/backups"
LOCK_FILE="/var/lock/joneshq-quick-update.lock"
HEALTH_URL="http://127.0.0.1:8000/login"
BACKUP_FILE=""
PREV_COMMIT=""

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
    rollback_code
    if [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ]; then
        echo "Restoring database from $BACKUP_FILE..."
        sudo -u $APP_USER bash -c "gunzip -c '$BACKUP_FILE' > '$APP_DIR/instance/joneshq_finance.db'"
    fi
    systemctl restart $SERVICE_NAME
    echo "Rollback complete. Service restarted on previous code/database."
}

if [ -n "$(sudo -u $APP_USER bash -c "cd $APP_DIR && git status --porcelain")" ]; then
    echo "ERROR: Working tree has uncommitted changes on the server. Resolve manually before updating."
    exit 1
fi

PREV_COMMIT=$(sudo -u $APP_USER bash -c "cd $APP_DIR && git rev-parse HEAD")

echo "Step 1: Pulling latest changes from origin/main..."
sudo -u $APP_USER bash -c "cd $APP_DIR && git pull origin main"

echo "Step 2: Installing/updating Python dependencies..."
sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pip install -r requirements.txt"

echo "Step 3: Backing up database before migration..."
bash $APP_DIR/deployment/backup.sh
BACKUP_FILE=$(ls -t $BACKUP_DIR/joneshq_finance_*.db.gz 2>/dev/null | head -1)

echo "Step 4: Running test suite..."
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && pytest -q"; then
    echo "ERROR: Tests failed. Rolling back code (database untouched, service not restarted)."
    rollback_code
    exit 1
fi

echo "Step 5: Applying database migrations..."
if ! sudo -u $APP_USER bash -c "cd $APP_DIR && source venv/bin/activate && flask db upgrade"; then
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
    echo "ERROR: Service failed to start after update. Rolling back code and database."
    rollback_full
    exit 1
fi

echo "Step 8: Verifying the app responds to real requests..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" || echo "000")
if [ "$HTTP_STATUS" != "200" ]; then
    echo "ERROR: Health check got HTTP $HTTP_STATUS from $HEALTH_URL. Rolling back code and database."
    rollback_full
    exit 1
fi
echo "Health check OK (HTTP $HTTP_STATUS)"

systemctl status $SERVICE_NAME --no-pager -l

echo ""
echo "========================================="
echo "  Update Complete!"
echo "========================================="
