#!/bin/bash
#
# JonesHQ Finance - Automated Backup Script
# Run daily via cron
#
# Installation:
#   sudo cp deployment/backup.sh /usr/local/bin/joneshq-backup
#   sudo chmod +x /usr/local/bin/joneshq-backup
#   
# Add to crontab (run daily at 2 AM):
#   sudo crontab -e
#   0 2 * * * /usr/local/bin/joneshq-backup
#

set -e

# Configuration
APP_DIR="/home/joneshq/app"
BACKUP_DIR="/home/joneshq/backups"
DB_PATH="$APP_DIR/instance/joneshq_finance.db"
RETENTION_DAYS=30  # Keep backups for 30 days
DATE=$(date +%Y%m%d_%H%M%S)

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
