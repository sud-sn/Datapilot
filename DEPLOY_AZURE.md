# Azure Deployment for DataPilot

This directory contains everything you need to deploy DataPilot to Azure with PostgreSQL.

## 🚀 Quick Start (15-20 minutes)

### Prerequisites
1. Azure account with active subscription
2. Groq API key from https://console.groq.com (free)
3. Git repository with your code
4. Azure CLI installed

### Automated Deployment

**Step 1: Create Azure VM (from Windows PowerShell)**
```powershell
cd C:\Users\susan\Documents\Datapilot\datapilot
.\create_azure_vm.ps1
```

**Step 2: Upload scripts to VM**
```powershell
# Replace <VM_IP> with the IP from step 1
scp setup_vm.sh azureuser@<VM_IP>:~/
scp setup_application.sh azureuser@<VM_IP>:~/
```

**Step 3: SSH into VM and run setup**
```powershell
ssh azureuser@<VM_IP>
```

Then on the VM:
```bash
# Install system dependencies and PostgreSQL
chmod +x setup_vm.sh
./setup_vm.sh

# Deploy application
chmod +x setup_application.sh
./setup_application.sh
```

**Step 4: Access your application**
- Web Interface: `http://<VM_IP>`
- API Docs: `http://<VM_IP>/docs`

Done! 🎉

## 📁 Files in This Directory

### Deployment Scripts
- **`create_azure_vm.ps1`** - Creates Azure VM and resources (run from Windows)
- **`setup_vm.sh`** - Installs system dependencies and PostgreSQL (run on VM)
- **`setup_application.sh`** - Deploys and configures DataPilot app (run on VM)

### Documentation
For detailed guides, see the artifacts directory:
- **Quick Start Guide** - Three deployment options with timelines
- **Step-by-Step Checklist** - Detailed checklist with verification steps
- **Comprehensive Guide** - Full production deployment guide

## 💰 Cost Estimate

- **VM (Standard B2ms)**: ~$60-80/month (2 vCPU, 8GB RAM)
- **Storage**: ~$5/month
- **Network**: ~$2-5/month
- **Total**: ~$70-90/month

> Use Azure Free Tier to get $200 credit for first 12 months!

## 🛠️ What Gets Deployed

```
Azure VM (Ubuntu 22.04)
├── PostgreSQL 15
│   └── datapilot_db
├── Python 3.11
│   └── DataPilot FastAPI App
├── Nginx (Reverse Proxy)
│   └── Port 80 → App:8000
└── systemd Service (Auto-start)
```

## 📝 Useful Commands

### Application Management
```bash
# Restart application
sudo systemctl restart datapilot

# View logs
sudo journalctl -u datapilot -f

# Check status
sudo systemctl status datapilot
```

### Database Access
```bash
# Connect to database
psql -h localhost -U datapilot_user -d datapilot_db
```

### Update Application
```bash
cd /home/azureuser/datapilot/datapilot
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart datapilot
```

## 🔧 Troubleshooting

### Application won't start
```bash
sudo journalctl -u datapilot -n 100
```

### Database connection issues
```bash
sudo systemctl status postgresql
psql -h localhost -U datapilot_user -d datapilot_db
```

### Check logs
```bash
# Application
sudo journalctl -u datapilot -f

# Nginx
sudo tail -f /var/log/nginx/error.log

# PostgreSQL
sudo tail -f /var/log/postgresql/postgresql-15-main.log
```

## 🔐 Security Recommendations

1. Set up HTTPS with Let's Encrypt
2. Configure firewall (done by scripts)
3. Use strong database passwords
4. Enable regular security updates
5. Set up Azure monitoring

## 📚 Additional Resources

- Groq API: https://console.groq.com
- Azure CLI: https://aka.ms/installazurecliwindows
- Azure Portal: https://portal.azure.com

## Need Help?

Check the comprehensive documentation in the artifacts directory or review the deployment logs with `sudo journalctl -u datapilot -f`.
