#!/bin/bash
#
# Quick Update Script for JonesHQ Finance
# Run this on your production server to deploy latest changes
#
# Usage: 
#   From Windows: ssh joneshq@<server-ip> 'bash -s' < deployment/quick_update.sh
#   On server: bash /home/joneshq/app/deployment/quick_update.sh
#

set -e  # Exit on error

APP_DIR="/home/joneshq/app"
APP_USER="joneshq"

echo "========================================="
echo "  JonesHQ Finance - Quick Update"
echo "========================================="
echo ""

# Check if we're the app user or root
CURRENT_USER=$(whoami)
if [ "$CURRENT_USER" != "root" ] && [ "$CURRENT_USER" != "$APP_USER" ]; then
    echo "ERROR: Run as root (sudo) or as $APP_USER user"
    exit 1
fi

echo "Step 1: Navigating to app directory..."
cd $APP_DIR

echo "Step 2: Pulling latest changes from origin/main..."
if [ "$CURRENT_USER" = "root" ]; then
    sudo -u $APP_USER git fetch origin
    sudo -u $APP_USER git pull origin main
else
    git fetch origin
    git pull origin main
fi

echo "Step 3: Checking templates for CSRF tokens..."
echo "Sample check:"
grep -n "csrf_token" templates/vendors/add.html | head -1 || echo "WARNING: CSRF token not found!"

echo ""
echo "Step 4: Restarting application..."
if [ "$CURRENT_USER" = "root" ]; then
    systemctl restart joneshq-finance
    echo "Step 5: Checking service status..."
    systemctl status joneshq-finance --no-pager -l
else
    echo "Please restart the service manually with:"
    echo "  sudo systemctl restart joneshq-finance"
fi

echo ""
echo "========================================="
echo "  Update Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Clear your browser cache (Ctrl+Shift+Delete)"
echo "2. Open the site in an incognito/private window"
echo "3. Check F12 Network tab for the csrf_token hidden input"
echo ""
