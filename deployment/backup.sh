#!/bin/bash
#
# FamilyHQ Finance - LEGACY SQLite backup script
#
# OBSOLETE FOR CURRENT PRODUCTION: production runs on PostgreSQL. This script only
# copies the old SQLite file, which no longer receives writes. quick_update.sh calls
# it only for SQLite installs; it refuses to run when .env.production points at a
# non-SQLite database. Do not schedule it.
# See deployment/README.md (Backups) for the current backup arrangements.
#

set -e

# Configuration
APP_DIR="/home/joneshq/joneshq-finance"
BACKUP_DIR="/home/joneshq/backups"
DB_PATH="$APP_DIR/instance/joneshq_finance.db"
RETENTION_DAYS=30  # Keep backups for 30 days
DATE=$(date +%Y%m%d_%H%M%S)

ENV_FILE="$APP_DIR/.env.production"
if [ -f "$ENV_FILE" ]; then
    DB_URL_LINE=$(grep -E '^[[:space:]]*(export[[:space:]]+)?(DATABASE_URL|SQLALCHEMY_DATABASE_URI)=' "$ENV_FILE" | tail -n 1 || true)
    DB_URL_VALUE=${DB_URL_LINE#*=}
    DB_URL_VALUE=${DB_URL_VALUE#[\"\']}
    if [ -n "$DB_URL_LINE" ] && [[ "$DB_URL_VALUE" != sqlite:* ]]; then
        echo "ERROR: Production is not configured for SQLite; this legacy script would back up an obsolete file."
        echo "See deployment/README.md (Backups). Nothing was backed up."
        exit 1
    fi
fi

# Create backup directory if it doesn't exist
mkdir -p $BACKUP_DIR

# Backup database
echo "Backing up database..."
if [ -f "$DB_PATH" ]; then
    sqlite3 $DB_PATH ".backup '$BACKUP_DIR/joneshq_finance_$DATE.db'"
    echo "Database backed up to: $BACKUP_DIR/joneshq_finance_$DATE.db"
else
    echo "ERROR: Database not found at $DB_PATH"
    exit 1
fi

# Backup environment file
if [ -f "$APP_DIR/.env.production" ]; then
    cp $APP_DIR/.env.production $BACKUP_DIR/.env.production_$DATE
    echo "Environment file backed up"
fi

# Backup logs
if [ -d "$APP_DIR/logs" ]; then
    tar -czf $BACKUP_DIR/logs_$DATE.tar.gz -C $APP_DIR logs/
    echo "Logs backed up"
fi

# Compress database backup
gzip $BACKUP_DIR/joneshq_finance_$DATE.db
echo "Database backup compressed"

# Remove old backups (older than RETENTION_DAYS)
echo "Removing backups older than $RETENTION_DAYS days..."
find $BACKUP_DIR -name "joneshq_finance_*.db.gz" -mtime +$RETENTION_DAYS -delete
find $BACKUP_DIR -name "logs_*.tar.gz" -mtime +$RETENTION_DAYS -delete
find $BACKUP_DIR -name ".env.production_*" -mtime +$RETENTION_DAYS -delete

# Set permissions
chown -R joneshq:joneshq $BACKUP_DIR
chmod 600 $BACKUP_DIR/*

# Show backup size
BACKUP_SIZE=$(du -sh $BACKUP_DIR | cut -f1)
echo "Total backup size: $BACKUP_SIZE"
echo "Backup completed successfully!"

# Optional: Sync to remote location (uncomment and configure)
# rsync -avz $BACKUP_DIR/ user@remote-server:/backups/joneshq-finance/
