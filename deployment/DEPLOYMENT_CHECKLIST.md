# Quick Deployment Checklist - finance.joneshq.co.uk

Print this checklist and follow step-by-step:

## Pre-Deployment (Do This First)

- [ ] **DNS Configuration**
  - Log into your domain registrar
  - Add A record: `finance` → Your home public IP
  - Wait 5-10 minutes for DNS propagation
  - Test: `nslookup finance.joneshq.co.uk`

- [ ] **Router Configuration**
  - Log into your router
  - Forward port 80 → Proxmox server local IP
  - Forward port 443 → Proxmox server local IP
  - Note your Proxmox server IP: ____________

## Proxmox Setup

- [ ] **Create Ubuntu Container**
  - Template: Ubuntu 22.04
  - Hostname: `joneshq-finance`
  - CPU: 2 cores
  - RAM: 2048 MB
  - Disk: 20 GB
  - Network: Bridge to LAN
  - Start on boot: YES
  - Start the container

- [ ] **Get Container IP**
  - From Proxmox console: `ip addr show`
  - Container IP: ____________

## Server Deployment

- [ ] **SSH into container**
  ```bash
  ssh root@<container-ip>
  ```

- [ ] **Run automated deployment**
  ```bash
  # Update system
  apt update && apt upgrade -y
  
  # Download deployment script
  curl -o deploy.sh https://raw.githubusercontent.com/.../deploy.sh
  # OR copy from Windows (see below)
  
  # Make executable
  chmod +x deploy.sh
  
  # Run deployment
  ./deploy.sh
  ```

- [ ] **Copy files from Windows**
  ```powershell
  # From Windows PowerShell (if not using git)
  scp -r "C:\Users\keiro\OneDrive\Documents\Programming\JonesHQ Finance\*" root@<container-ip>:/root/app/
  ```

## Post-Deployment

- [ ] **Test HTTP access**
  - Visit: `http://finance.joneshq.co.uk`
  - Should redirect to HTTPS

- [ ] **Verify SSL certificate**
  - Visit: `https://finance.joneshq.co.uk`
  - Check for padlock icon
  - Certificate should be valid (Let's Encrypt)

- [ ] **Login and test**
  - Username: ____________
  - Password: ____________
  - Test all features work

- [ ] **Set up automated backups**
  ```bash
  sudo crontab -e
  # Add: 0 2 * * * /usr/local/bin/joneshq-backup
  ```

- [ ] **Configure external access (Optional)**
  - If accessing from outside home network
  - Consider setting up VPN (WireGuard recommended)

## Verification Commands

```bash
# Check service status
sudo systemctl status joneshq-finance
sudo systemctl status nginx

# View logs
sudo journalctl -u joneshq-finance -f

# Test SSL
curl -I https://finance.joneshq.co.uk

# Check firewall
sudo ufw status
```

## Troubleshooting

**DNS not resolving?**
- Wait 10-15 minutes for propagation
- Check with: `nslookup finance.joneshq.co.uk`
- Verify A record in DNS settings

**Can't access from internet?**
- Check port forwarding on router
- Verify firewall allows ports 80 & 443
- Check from mobile data (outside home network)

**SSL certificate failed?**
- Ensure DNS is working first
- Run: `sudo certbot --nginx -d finance.joneshq.co.uk`
- Check nginx error log: `sudo tail -f /var/log/nginx/error.log`

**App not starting?**
- Check logs: `sudo journalctl -u joneshq-finance -n 100`
- Verify environment file exists
- Check database permissions

## Support

**Log Locations:**
- App logs: `/home/joneshq/app/logs/`
- System logs: `sudo journalctl -u joneshq-finance`
- Nginx logs: `/var/log/nginx/`

**Important Files:**
- Service: `/etc/systemd/system/joneshq-finance.service`
- Nginx: `/etc/nginx/sites-available/finance.joneshq.co.uk`
- App: `/home/joneshq/app/`
- Database: `/home/joneshq/app/instance/joneshq_finance.db`

## Emergency Recovery

**Restore from backup:**
```bash
cd /home/joneshq/backups
gunzip joneshq_finance_YYYYMMDD.db.gz
cp joneshq_finance_YYYYMMDD.db /home/joneshq/app/instance/joneshq_finance.db
sudo systemctl restart joneshq-finance
```

**Restart everything:**
```bash
sudo systemctl restart joneshq-finance
sudo systemctl restart nginx
```

---

**Deployment Date:** _______________  
**Deployed By:** _______________  
**Production URL:** https://finance.joneshq.co.uk  
**Container IP:** _______________  
