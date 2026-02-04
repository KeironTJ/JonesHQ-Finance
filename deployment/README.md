# Deployment Files

This directory contains production deployment configurations for JonesHQ Finance.

## Files

- **nginx.conf** - Nginx reverse proxy configuration
- **joneshq-finance.service** - Systemd service file
- **gunicorn_config.py** - Gunicorn WSGI server configuration
- **deploy.sh** - Automated deployment script
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
