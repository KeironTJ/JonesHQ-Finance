# Simple LXC Deployment - Behind Existing Nginx Proxy

This guide is for deploying JonesHQ Finance in a new LXC container when you **already have Nginx Proxy Manager** running.

---

## 🎯 Architecture

```
Internet → Router → Nginx Proxy Manager (existing) → JonesHQ Finance LXC (new)
                    ↓
                    Handles SSL/HTTPS
                    finance.joneshq.co.uk
```

---

## 📋 Quick Setup

### **Step 1: Create Ubuntu LXC Container in Proxmox**

From Proxmox web interface:

1. **Create CT** button
2. **General:**
   - CT ID: (next available, e.g., 104)
   - Hostname: `joneshq-finance`
   - Password: (set secure password)
   - SSH public key: (optional)

3. **Template:**
   - Storage: local
   - Template: `ubuntu-22.04-standard`

4. **Disks:**
   - Disk size: `10 GB` (plenty for this app)

5. **CPU:**
   - Cores: `1` (can be 2 if you want)

6. **Memory:**
   - RAM: `1024 MB` (1GB is enough)
   - Swap: `512 MB`

7. **Network:**
   - Bridge: `vmbr0` (or your LAN bridge)
   - DHCP: ✅ (or set static IP)
   - IPv4: DHCP or Static (e.g., `192.168.1.104/24`)

8. **DNS:**
   - Use host settings: ✅

9. **Confirm** and **Finish**

10. ✅ **Start on boot**

11. **Start** the container

---

### **Step 2: Initial Container Setup**

Access the container console from Proxmox or SSH:

```bash
# From Proxmox console or
ssh root@<container-ip>

# Update system
apt update && apt upgrade -y

# Install Python and required packages
apt install -y python3 python3-pip python3-venv git sqlite3

# Create app user
useradd -m -s /bin/bash joneshq
passwd joneshq  # Set password

# Switch to app user
su - joneshq
```

---

### **Step 3: Deploy Application**

```bash
# Create app directory
cd ~
mkdir app
cd app

# Upload files from Windows
# (Run this from Windows PowerShell)
# scp -r "C:\Users\keiro\OneDrive\Documents\Programming\JonesHQ Finance\*" joneshq@<container-ip>:~/app/

# OR use git if you have a repo
# git clone <your-repo> .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# Create production environment file
nano .env.production
```

Add to `.env.production`:
```bash
FLASK_ENV=production
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
DATABASE_URL=sqlite:////home/joneshq/app/instance/joneshq_finance.db
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
```

Save and continue:
```bash
# Set permissions
chmod 600 .env.production

# Initialize database
export $(cat .env.production | xargs)
flask db upgrade

# Create users
python3 create_initial_users.py
# Follow prompts to create accounts for you and your wife
```

---

### **Step 4: Create Systemd Service**

```bash
# Exit to root user
exit

# Create service file
nano /etc/systemd/system/joneshq-finance.service
```

Paste this configuration:
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
ExecStart=/home/joneshq/app/venv/bin/gunicorn \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 60 \
    --access-logfile /home/joneshq/app/logs/access.log \
    --error-logfile /home/joneshq/app/logs/error.log \
    "app:create_app()"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save and enable:
```bash
# Create logs directory
mkdir -p /home/joneshq/app/logs
chown -R joneshq:joneshq /home/joneshq/app/logs

# Enable and start service
systemctl daemon-reload
systemctl enable joneshq-finance
systemctl start joneshq-finance

# Check status
systemctl status joneshq-finance

# Check it's listening
ss -tlnp | grep 8000
# Should show: 0.0.0.0:8000
```

---

### **Step 5: Configure Nginx Proxy Manager**

Now configure your existing Nginx Proxy Manager to forward to this container:

1. **Login to Nginx Proxy Manager** (usually at `http://<npm-ip>:81`)

2. **Add Proxy Host:**
   - Click **"Hosts"** → **"Proxy Hosts"** → **"Add Proxy Host"**

3. **Details Tab:**
   ```
   Domain Names: finance.joneshq.co.uk
   Scheme: http
   Forward Hostname/IP: <joneshq-finance-container-ip>
   Forward Port: 8000
   Cache Assets: ✅
   Block Common Exploits: ✅
   Websockets Support: ❌ (not needed)
   ```

4. **SSL Tab:**
   ```
   SSL Certificate: Request a new SSL Certificate
   ✅ Force SSL
   ✅ HTTP/2 Support
   ✅ HSTS Enabled
   ✅ HSTS Subdomains
   Email Address for Let's Encrypt: your@email.com
   ✅ I Agree to the Let's Encrypt Terms of Service
   ```

5. **Advanced Tab** (optional, for extra security):
   ```nginx
   # Security headers
   add_header X-Content-Type-Options "nosniff" always;
   add_header X-Frame-Options "SAMEORIGIN" always;
   add_header X-XSS-Protection "1; mode=block" always;
   add_header Referrer-Policy "strict-origin-when-cross-origin" always;
   
   # Timeouts
   proxy_connect_timeout 60s;
   proxy_send_timeout 60s;
   proxy_read_timeout 60s;
   ```

6. **Save**

---

### **Step 6: DNS Configuration**

In your DNS provider for `joneshq.co.uk`:

```
Type: A
Name: finance
Value: <your-public-IP>  # Same IP that points to your Nginx Proxy Manager
TTL: 3600
```

Wait 5-10 minutes for DNS propagation.

---

### **Step 7: Test It!**

1. **Test from inside your network:**
   ```bash
   curl http://<container-ip>:8000
   # Should get HTML response
   ```

2. **Test via domain:**
   ```bash
   curl https://finance.joneshq.co.uk
   # Should get HTML with valid SSL
   ```

3. **Access from browser:**
   - Visit: `https://finance.joneshq.co.uk`
   - Should see login page with valid SSL certificate
   - Log in and test features

---

## 🔧 Container Management

### View Logs
```bash
# From container
sudo journalctl -u joneshq-finance -f

# Or check log files
tail -f /home/joneshq/app/logs/error.log
tail -f /home/joneshq/app/logs/access.log
```

### Restart Application
```bash
sudo systemctl restart joneshq-finance
```

### Update Application
```bash
su - joneshq
cd ~/app
source venv/bin/activate
git pull  # or upload new files
pip install -r requirements.txt --upgrade
flask db upgrade
exit
sudo systemctl restart joneshq-finance
```

### Backup Database
```bash
# Create backup
cp /home/joneshq/app/instance/joneshq_finance.db ~/joneshq_finance_backup_$(date +%Y%m%d).db

# Restore backup
cp ~/joneshq_finance_backup_YYYYMMDD.db /home/joneshq/app/instance/joneshq_finance.db
sudo systemctl restart joneshq-finance
```

---

## 📊 Resource Usage

This container should use:
- **RAM**: ~100-200 MB idle, 200-400 MB under load
- **CPU**: <5% idle, 10-20% when processing
- **Disk**: ~500 MB initial, grows with database

You can monitor from Proxmox web interface.

---

## 🔒 Security Notes

Since Nginx Proxy Manager handles SSL:
- App container only needs HTTP (port 8000)
- No SSL certificates needed in container
- Nginx Proxy Manager handles all HTTPS
- App is not directly exposed to internet

**Container Firewall (optional):**
```bash
# Only allow from Nginx Proxy Manager
apt install ufw
ufw default deny incoming
ufw allow from <npm-container-ip> to any port 8000
ufw allow ssh  # Only if you SSH directly to this container
ufw enable
```

---

## 🐛 Troubleshooting

### App won't start
```bash
# Check logs
sudo journalctl -u joneshq-finance -n 50

# Test manually
su - joneshq
cd ~/app
source venv/bin/activate
export $(cat .env.production | xargs)
python3 -c "from app import create_app; app = create_app(); print('App created successfully')"
```

### Can't access from Nginx Proxy Manager
```bash
# Verify app is listening
ss -tlnp | grep 8000

# Check firewall
ufw status

# Test from NPM container
# From Nginx Proxy Manager container:
curl http://<joneshq-container-ip>:8000
```

### Database errors
```bash
# Check permissions
ls -la /home/joneshq/app/instance/

# Fix if needed
chown -R joneshq:joneshq /home/joneshq/app/
```

---

## ✅ Quick Checklist

- [ ] LXC container created and running
- [ ] Ubuntu updated (`apt update && apt upgrade`)
- [ ] Python and dependencies installed
- [ ] App files uploaded/cloned
- [ ] Virtual environment created
- [ ] `.env.production` configured with new SECRET_KEY
- [ ] Database initialized (`flask db upgrade`)
- [ ] User accounts created
- [ ] Systemd service running (`systemctl status joneshq-finance`)
- [ ] App listening on port 8000 (`ss -tlnp | grep 8000`)
- [ ] Nginx Proxy Manager configured
- [ ] DNS A record added for `finance`
- [ ] SSL certificate obtained (via NPM)
- [ ] Can access `https://finance.joneshq.co.uk`
- [ ] Login works and features tested

---

**Container Details:**

```
CT ID: ___________
Hostname: joneshq-finance
IP Address: ___________
RAM: 1024 MB
Disk: 10 GB
App Port: 8000
NPM Proxy: finance.joneshq.co.uk → http://<container-ip>:8000
```
