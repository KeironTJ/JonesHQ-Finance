#!/bin/bash
#
# JonesHQ Finance - Automated Deployment Script
# Run this on your Proxmox Ubuntu container
#
# Usage: bash deployment/deploy.sh
#

set -e  # Exit on any error

echo "========================================="
echo "  JonesHQ Finance - Deployment Script"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
APP_USER="joneshq"
APP_DIR="/home/$APP_USER/app"
VENV_DIR="$APP_DIR/venv"
DOMAIN="finance.joneshq.co.uk"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

echo -e "${GREEN}Step 1: Installing system packages...${NC}"
apt update
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git sqlite3

echo -e "${GREEN}Step 2: Creating application user...${NC}"
if id "$APP_USER" &>/dev/null; then
    echo "User $APP_USER already exists"
else
    useradd -m -s /bin/bash $APP_USER
    echo "User $APP_USER created"
fi

echo -e "${GREEN}Step 3: Creating application directory...${NC}"
mkdir -p $APP_DIR/logs
mkdir -p $APP_DIR/instance
chown -R $APP_USER:$APP_USER $APP_DIR

echo -e "${YELLOW}Step 4: Deploying application files...${NC}"
echo "Please upload your application files to: $APP_DIR"
echo "From Windows, run:"
echo "  scp -r \"C:\\Users\\keiro\\OneDrive\\Documents\\Programming\\JonesHQ Finance\\*\" $APP_USER@<server-ip>:$APP_DIR/"
echo ""
read -p "Press Enter when files are uploaded..."

echo -e "${GREEN}Step 5: Setting up Python virtual environment...${NC}"
sudo -u $APP_USER python3 -m venv $VENV_DIR
sudo -u $APP_USER $VENV_DIR/bin/pip install --upgrade pip

echo -e "${GREEN}Step 6: Installing Python dependencies...${NC}"
sudo -u $APP_USER $VENV_DIR/bin/pip install -r $APP_DIR/requirements.txt
sudo -u $APP_USER $VENV_DIR/bin/pip install gunicorn

echo -e "${GREEN}Step 7: Creating production environment file...${NC}"
if [ ! -f "$APP_DIR/.env.production" ]; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > $APP_DIR/.env.production << EOF
# Production Environment Configuration
FLASK_ENV=production
SECRET_KEY=$SECRET_KEY
DATABASE_URL=sqlite:///$APP_DIR/instance/joneshq_finance.db

# Security
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
EOF
    chmod 600 $APP_DIR/.env.production
    chown $APP_USER:$APP_USER $APP_DIR/.env.production
    echo -e "${GREEN}Environment file created with new SECRET_KEY${NC}"
else
    echo "Environment file already exists"
fi

echo -e "${GREEN}Step 8: Initializing database...${NC}"
cd $APP_DIR
sudo -u $APP_USER bash << 'EOF'
source venv/bin/activate
# Load environment file safely: ignore comments and blank lines
if [ -f .env.production ]; then
    set -a
    . .env.production
    set +a
fi
flask db upgrade
EOF

echo -e "${YELLOW}Step 9: Creating user accounts...${NC}"
echo "You will be prompted to create user accounts..."
sudo -u $APP_USER bash << 'EOF'
echo "The interactive user-creation step is intentionally left manual."
echo "Run the following as the $APP_USER after deploy if you need to create users:"
echo "  sudo -u $APP_USER bash -ic 'cd $APP_DIR && source venv/bin/activate && . .env.production && python3 create_initial_users.py'"
echo "Skipping automatic user creation in automated deploy."
EOF

echo -e "${GREEN}Step 10: Installing systemd service...${NC}"
cp $APP_DIR/deployment/joneshq-finance.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable joneshq-finance
systemctl start joneshq-finance

echo -e "${GREEN}Step 11: Configuring nginx...${NC}"
cp $APP_DIR/deployment/nginx.conf /etc/nginx/sites-available/$DOMAIN
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx

echo -e "${GREEN}Step 12: Obtaining SSL certificate...${NC}"
echo "Make sure DNS is pointing to this server before continuing!"
read -p "Press Enter to obtain SSL certificate..."
certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email keiron@joneshq.co.uk || echo "Certificate already exists or DNS not ready"

echo -e "${GREEN}Step 13: Configuring firewall...${NC}"
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 'Nginx Full'
ufw --force enable

echo -e "${GREEN}Step 14: Installing Fail2Ban...${NC}"
apt install -y fail2ban
systemctl enable fail2ban
systemctl start fail2ban

echo ""
echo "========================================="
echo -e "${GREEN}  Deployment Complete! 🎉${NC}"
echo "========================================="
echo ""
echo "Application URL: https://$DOMAIN"
echo ""
echo "Useful commands:"
echo "  Service status:  sudo systemctl status joneshq-finance"
echo "  View logs:       sudo journalctl -u joneshq-finance -f"
echo "  Restart app:     sudo systemctl restart joneshq-finance"
echo "  Nginx logs:      sudo tail -f /var/log/nginx/error.log"
echo ""
echo "Next steps:"
echo "  1. Visit https://$DOMAIN and verify it works"
echo "  2. Log in with your credentials"
echo "  3. Set up automated backups"
echo ""
