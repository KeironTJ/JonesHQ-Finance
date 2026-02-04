# Production Deployment Guide - Proxmox Server
## finance.joneshq.co.uk

This guide will help you deploy JonesHQ Finance on your Proxmox home server with SSL/HTTPS support.

---

## 📋 Prerequisites

- Proxmox server with Ubuntu/Debian LXC container or VM
- Domain: `joneshq.co.uk` with ability to add DNS records
- Root/sudo access to the server
- Port 80 and 443 accessible from internet

---

## 🚀 Step-by-Step Deployment

### **Step 1: DNS Configuration**

Add an A record for your subdomain:

```
Type: A
Name: finance
Value: <your-home-public-IP>
TTL: 3600
```

**Result**: `finance.joneshq.co.uk` → Your home server IP

**Port Forwarding** (on your router):
- Forward port `80` → Proxmox server IP:80
- Forward port `443` → Proxmox server IP:443

---

### **Step 2: Create Ubuntu LXC Container in Proxmox**

1. In Proxmox web UI: **Create CT**
2. Settings:
   - Template: `Ubuntu 22.04`
   - Disk: `20GB`
   - CPU: `2 cores`
   - Memory: `2048 MB`
   - Network: Bridge to your LAN
   - Start on boot: ✅

3. Start the container and access console

---

### **Step 3: Initial Server Setup**

SSH into your container and run:

```bash
# Update system
apt update && apt upgrade -y

# Install required packages
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

# Create app user
useradd -m -s /bin/bash joneshq
usermod -aG sudo joneshq

# Switch to app user
su - joneshq
```

---

### **Step 4: Deploy Application**

```bash
# Create app directory
cd /home/joneshq
mkdir -p app
cd app

# Upload your code (use SCP, SFTP, or git)
# Option 1: From your Windows machine using SCP
# From Windows PowerShell:
# scp -r "C:\Users\keiro\OneDrive\Documents\Programming\JonesHQ Finance\*" joneshq@<server-ip>:/home/joneshq/app/

# Option 2: Using git (if you have a private repo)
# git clone <your-repo-url> .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn psycopg2-binary  # For PostgreSQL
```

---

### **Step 5: Configure Environment**

Create production environment file:

```bash
nano /home/joneshq/app/.env.production
```

Add the following (replace with your values):

```bash
# Production Environment Configuration
FLASK_ENV=production
SECRET_KEY=<generate-new-key-with-python-secrets>
DATABASE_URL=sqlite:////home/joneshq/app/instance/joneshq_finance.db

# For PostgreSQL (recommended):
# DATABASE_URL=postgresql://joneshq:secure_password@localhost/joneshq_finance

# Security
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
```

**Generate new SECRET_KEY:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Set permissions:
```bash
chmod 600 /home/joneshq/app/.env.production
```

---

### **Step 6: Initialize Database**

```bash
# Load environment
source venv/bin/activate
export $(cat .env.production | xargs)

# Run migrations
flask db upgrade

# Create your user accounts
python3 create_initial_users.py
```

---

### **Step 7: Create Systemd Service**

Create service file:

```bash
sudo nano /etc/systemd/system/joneshq-finance.service
```

Copy the configuration from `deployment/joneshq-finance.service` or use this:

```ini
[Unit]
Description=JonesHQ Finance Application
After=network.target

[Service]
Type=notify
User=joneshq
Group=joneshq
WorkingDirectory=/home/joneshq/app
Environment="PATH=/home/joneshq/app/venv/bin"
EnvironmentFile=/home/joneshq/app/.env.production
ExecStart=/home/joneshq/app/venv/bin/gunicorn --config /home/joneshq/app/deployment/gunicorn_config.py app:create_app()
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable joneshq-finance
sudo systemctl start joneshq-finance
sudo systemctl status joneshq-finance
```

---

### **Step 8: Configure Nginx Reverse Proxy**

Create nginx config:

```bash
sudo nano /etc/nginx/sites-available/finance.joneshq.co.uk
```

Use the configuration from `deployment/nginx.conf` or:

```nginx
server {
    listen 80;
    server_name finance.joneshq.co.uk;

    # Redirect to HTTPS (will be configured by certbot)
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name finance.joneshq.co.uk;

    # SSL certificates (certbot will add these)
    # ssl_certificate /etc/letsencrypt/live/finance.joneshq.co.uk/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/finance.joneshq.co.uk/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Max upload size
    client_max_body_size 10M;

    # Proxy to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Static files (optional - if you want nginx to serve them directly)
    location /static {
        alias /home/joneshq/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

Enable site:
```bash
sudo ln -s /etc/nginx/sites-available/finance.joneshq.co.uk /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

### **Step 9: SSL Certificate with Let's Encrypt**

```bash
# Stop nginx temporarily
sudo systemctl stop nginx

# Get certificate
sudo certbot --nginx -d finance.joneshq.co.uk

# Follow prompts:
# - Enter email address
# - Agree to terms
# - Choose to redirect HTTP to HTTPS (option 2)

# Start nginx
sudo systemctl start nginx

# Test auto-renewal
sudo certbot renew --dry-run
```

---

### **Step 10: Verify Deployment**

1. Visit: **https://finance.joneshq.co.uk**
2. Check SSL certificate is valid (padlock icon)
3. Log in with your credentials
4. Verify all features work

Check logs if there are issues:
```bash
# Application logs
sudo journalctl -u joneshq-finance -f

# Nginx logs
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

---

## 🔧 Maintenance Commands

### Update Application
```bash
cd /home/joneshq/app
source venv/bin/activate
git pull  # If using git
pip install -r requirements.txt --upgrade
flask db upgrade
sudo systemctl restart joneshq-finance
```

### Backup Database
```bash
# SQLite
cp /home/joneshq/app/instance/joneshq_finance.db ~/backups/joneshq_finance_$(date +%Y%m%d).db

# PostgreSQL
pg_dump joneshq_finance > ~/backups/joneshq_finance_$(date +%Y%m%d).sql
```

### View Logs
```bash
# Real-time app logs
sudo journalctl -u joneshq-finance -f

# Recent logs
sudo journalctl -u joneshq-finance -n 100

# Application log file (if configured)
tail -f /home/joneshq/app/logs/joneshq_finance.log
```

### Restart Services
```bash
sudo systemctl restart joneshq-finance
sudo systemctl restart nginx
```

---

## 🔒 Security Hardening

### Firewall (UFW)
```bash
sudo apt install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

### Fail2Ban (Brute Force Protection)
```bash
sudo apt install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### Automatic Updates
```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

---

## 📊 Monitoring

### Check Service Status
```bash
sudo systemctl status joneshq-finance
sudo systemctl status nginx
```

### Monitor Resources
```bash
# CPU and Memory
htop

# Disk usage
df -h

# App process
ps aux | grep gunicorn
```

---

## 🐛 Troubleshooting

### App Won't Start
```bash
# Check logs
sudo journalctl -u joneshq-finance -n 50

# Test manually
cd /home/joneshq/app
source venv/bin/activate
export $(cat .env.production | xargs)
gunicorn --bind 127.0.0.1:8000 "app:create_app()"
```

### SSL Issues
```bash
# Renew certificate
sudo certbot renew

# Check certificate expiry
sudo certbot certificates
```

### Database Issues
```bash
# Check permissions
ls -la /home/joneshq/app/instance/

# Fix permissions
sudo chown -R joneshq:joneshq /home/joneshq/app/
```

---

## 📱 Access from Outside Your Home

If you want to access from anywhere:

1. **Dynamic DNS** (if your ISP changes your IP):
   - Use services like DuckDNS, No-IP, or Cloudflare
   - Update DNS automatically when IP changes

2. **VPN Access** (more secure):
   - Set up WireGuard or OpenVPN on Proxmox
   - Access your home network securely

---

## ✅ Production Checklist

- [ ] DNS A record configured for finance.joneshq.co.uk
- [ ] Ports 80/443 forwarded to Proxmox server
- [ ] Ubuntu container created and running
- [ ] Application deployed to `/home/joneshq/app`
- [ ] Environment variables set in `.env.production`
- [ ] New SECRET_KEY generated
- [ ] Database initialized and migrated
- [ ] User accounts created
- [ ] Systemd service running
- [ ] Nginx configured and running
- [ ] SSL certificate obtained from Let's Encrypt
- [ ] HTTPS working with valid certificate
- [ ] Firewall configured (UFW)
- [ ] Fail2Ban installed
- [ ] Backup strategy implemented
- [ ] Application accessible from internet
- [ ] All features tested and working

---

## 🆘 Support

If you encounter issues:
1. Check logs: `sudo journalctl -u joneshq-finance -f`
2. Verify DNS: `nslookup finance.joneshq.co.uk`
3. Test SSL: `https://www.ssllabs.com/ssltest/`
4. Check firewall: `sudo ufw status`
5. Verify service: `sudo systemctl status joneshq-finance nginx`

---

**Deployment Date**: _________________  
**Deployed By**: Keiron Jones  
**Production URL**: https://finance.joneshq.co.uk
