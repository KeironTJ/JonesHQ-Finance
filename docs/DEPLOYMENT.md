# Deployment Guide - JonesHQ Finance

## 🚀 Quick Deployment Steps

### 1. Generate Secret Key
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```
Save this output - you'll need it as `SECRET_KEY`.

### 2. Set Environment Variables

On your server (Linux/VPS):
```bash
export FLASK_ENV=production
export SECRET_KEY="your-generated-secret-key-here"
export DATABASE_URL="postgresql://user:password@host:5432/joneshq_finance"  # Optional: for PostgreSQL
```

On Windows Server:
```powershell
$env:FLASK_ENV = "production"
$env:SECRET_KEY = "your-generated-secret-key-here"
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
pip install gunicorn  # For production server (Linux)
```

### 4. Run Database Migrations
```bash
python -m flask db upgrade
```

### 5. Create User Accounts
```bash
python scripts/maintenance/create_users.py
```
This will create accounts for you and your wife.

### 6. Run in Production

**Option A: Using Gunicorn (Recommended for Linux)**
```bash
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app('production')"
```

**Option B: Using Flask (Simple deployment)**
```bash
FLASK_ENV=production python -m flask run --host=0.0.0.0 --port=8000
```

**Option C: Using systemd service (Linux)**
Create `/etc/systemd/system/joneshq-finance.service`:
```ini
[Unit]
Description=JonesHQ Finance Application
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/JonesHQ Finance
Environment="FLASK_ENV=production"
Environment="SECRET_KEY=your-secret-key"
Environment="DATABASE_URL=postgresql://..."
ExecStart=/usr/bin/gunicorn -w 4 -b 127.0.0.1:8000 "app:create_app('production')"
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable joneshq-finance
sudo systemctl start joneshq-finance
```

---

## 🔒 Security Checklist

### Before Going Live:

- [ ] **Change SECRET_KEY** - Never use the dev key!
- [ ] **Set FLASK_ENV=production** - Disables debug mode
- [ ] **Use HTTPS** - Essential for secure cookies
- [ ] **Configure Firewall** - Only allow ports 80, 443
- [ ] **Set up Reverse Proxy** - Nginx or Apache
- [ ] **Use PostgreSQL** - Not SQLite for production
- [ ] **Regular Backups** - Database and uploaded files
- [ ] **Update Dependencies** - Keep packages up-to-date
- [ ] **Monitor Logs** - Set up logging and monitoring

---

## 🌐 Web Server Configuration

### Nginx Reverse Proxy

Create `/etc/nginx/sites-available/joneshq.co.uk`:
```nginx
server {
    listen 80;
    server_name joneshq.co.uk www.joneshq.co.uk;
    
    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name joneshq.co.uk www.joneshq.co.uk;
    
    # SSL Configuration (use Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/joneshq.co.uk/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/joneshq.co.uk/privkey.pem;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Proxy to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Static files (optional optimization)
    location /static {
        alias /path/to/JonesHQ Finance/static;
        expires 30d;
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/joneshq.co.uk /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### SSL Certificate (Let's Encrypt)
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d joneshq.co.uk -d www.joneshq.co.uk
```

---

## 📊 Database Migration (SQLite to PostgreSQL)

If you want to move from SQLite to PostgreSQL:

### 1. Install PostgreSQL
```bash
sudo apt install postgresql postgresql-contrib
```

### 2. Create Database
```bash
sudo -u postgres createdb joneshq_finance
sudo -u postgres createuser joneshq_user
sudo -u postgres psql
```
```sql
ALTER USER joneshq_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE joneshq_finance TO joneshq_user;
\q
```

### 3. Export SQLite Data
```bash
pip install pgloader
pgloader sqlite:///instance/joneshq_finance.db postgresql://joneshq_user:password@localhost/joneshq_finance
```

### 4. Update DATABASE_URL
```bash
export DATABASE_URL="postgresql://joneshq_user:password@localhost:5432/joneshq_finance"
```

---

## 🔐 Additional Security Options

### Option 1: IP Whitelist (Nginx)
Add to your Nginx server block:
```nginx
# Only allow your IP addresses
allow 123.456.789.0;  # Your home IP
allow 98.765.432.1;   # Your wife's IP
deny all;
```

### Option 2: VPN Access Only
- Set up WireGuard/OpenVPN
- Only bind app to VPN interface
- Access only through VPN connection

### Option 3: Cloudflare Access
- Use Cloudflare Zero Trust
- Add Access policy for email-based auth
- Free for small teams (2 users)

---

## 📱 Domain & DNS Setup

For **joneshq.co.uk**:

1. Point A record to your server IP:
   ```
   A    @              123.456.789.0
   A    www            123.456.789.0
   ```

2. If using Cloudflare:
   - Enable "Proxied" mode (orange cloud)
   - SSL/TLS mode: "Full (strict)"
   - Enable "Always Use HTTPS"

---

## 🔄 Updates & Maintenance

### Updating the Application
```bash
cd /path/to/JonesHQ\ Finance
git pull origin main
pip install -r requirements.txt
python -m flask db upgrade
sudo systemctl restart joneshq-finance
```

### Database Backups
```bash
# Automated daily backup (crontab)
0 2 * * * pg_dump joneshq_finance > /backups/joneshq_$(date +\%Y\%m\%d).sql

# Or for SQLite
0 2 * * * cp /path/to/instance/joneshq_finance.db /backups/joneshq_$(date +\%Y\%m\%d).db
```

---

## 🆘 Troubleshooting

### Login redirect loops
- Check `SESSION_COOKIE_SECURE` is True only when using HTTPS
- Ensure `X-Forwarded-Proto` header is set in reverse proxy

### Can't log in
- Verify users were created: `python -c "from app import create_app; from models.users import User; app=create_app(); app.app_context().push(); print(User.query.all())"`
- Reset password if needed

### Database locked errors (SQLite)
- Switch to PostgreSQL for production
- SQLite doesn't handle concurrent writes well

---

## 📞 Support

For issues or questions, check:
- Application logs: `journalctl -u joneshq-finance -f`
- Nginx logs: `/var/log/nginx/error.log`
- Database connections: `netstat -tulpn | grep 5432`

---

**Remember**: This contains sensitive financial data. Always use HTTPS, strong passwords, and keep backups!
