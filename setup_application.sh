#!/bin/bash
#############################################################
# DataPilot - Application Setup Script
# Run this script after setup_vm.sh is complete
#############################################################

set -e  # Exit on error

echo "======================================"
echo "  DataPilot Application Setup"
echo "======================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

#############################################################
# Step 1: Get Repository URL
#############################################################
echo "Step 1/8: Repository Setup"
echo ""
read -p "Enter your Git repository URL: " REPO_URL

if [ -z "$REPO_URL" ]; then
    print_error "Repository URL cannot be empty!"
    exit 1
fi

#############################################################
# Step 2: Clone Repository
#############################################################
echo ""
echo "Step 2/8: Cloning repository..."
cd /home/azureuser

if [ -d "datapilot" ]; then
    print_warning "Directory 'datapilot' already exists. Removing..."
    rm -rf datapilot
fi

git clone $REPO_URL datapilot
cd datapilot/datapilot
print_status "Repository cloned"
echo ""

#############################################################
# Step 3: Create Virtual Environment
#############################################################
echo "Step 3/8: Creating Python virtual environment..."
python3.11 -m venv venv
source venv/bin/activate
print_status "Virtual environment created"
echo ""

#############################################################
# Step 4: Install Dependencies
#############################################################
echo "Step 4/8: Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
print_status "Dependencies installed"
echo ""

#############################################################
# Step 5: Configure Environment Variables
#############################################################
echo "Step 5/8: Configuring environment variables..."
echo ""

# Check if db_config exists
if [ -f ~/datapilot-setup/db_config.txt ]; then
    print_status "Found database configuration"
    DB_NAME=$(grep "Database Name:" ~/datapilot-setup/db_config.txt | cut -d: -f2 | xargs)
    DB_USER=$(grep "Database User:" ~/datapilot-setup/db_config.txt | cut -d: -f2 | xargs)
    DB_PASSWORD=$(grep "Database Password:" ~/datapilot-setup/db_config.txt | cut -d: -f2 | xargs)
else
    print_warning "Database configuration not found. Please enter manually:"
    read -p "Database name: " DB_NAME
    read -p "Database user: " DB_USER
    read -sp "Database password: " DB_PASSWORD
    echo ""
fi

read -p "Enter your Groq API key (from console.groq.com): " GROQ_API_KEY

if [ -z "$GROQ_API_KEY" ]; then
    print_error "Groq API key is required!"
    exit 1
fi

# Create .env file
cat > .env <<EOF
# Database Configuration
DATAPILOT_DB_SOURCE=postgresql
DATAPILOT_DB_HOST=localhost
DATAPILOT_DB_PORT=5432
DATAPILOT_DB_USER=$DB_USER
DATAPILOT_DB_PASSWORD=$DB_PASSWORD
DATAPILOT_DB_DATABASE=$DB_NAME
DATAPILOT_DB_SCHEMA=public
DATAPILOT_DB_SSL_MODE=prefer

# LLM Configuration
DATAPILOT_LLM_PROVIDER=groq
DATAPILOT_LLM_MODEL=llama-3.3-70b-versatile
DATAPILOT_API_KEY=$GROQ_API_KEY

# Server Configuration
DATAPILOT_HOST=0.0.0.0
DATAPILOT_PORT=8000
DATAPILOT_DEBUG=false

# Security
DATAPILOT_MAX_ROWS=10000
DATAPILOT_QUERY_TIMEOUT=30
EOF

chmod 600 .env
print_status "Environment variables configured"
echo ""

#############################################################
# Step 6: Test Application
#############################################################
echo "Step 6/8: Testing application..."
print_warning "Starting application in test mode (will auto-stop in 10 seconds)..."
echo ""

# Start app in background
timeout 10 python run.py || true

# Test if it started properly
if [ -f "src/app.py" ]; then
    print_status "Application files verified"
else
    print_error "Application files not found!"
    exit 1
fi
echo ""

#############################################################
# Step 7: Create systemd Service
#############################################################
echo "Step 7/8: Creating systemd service..."

sudo tee /etc/systemd/system/datapilot.service > /dev/null <<EOF
[Unit]
Description=DataPilot FastAPI Application
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=azureuser
Group=azureuser
WorkingDirectory=/home/azureuser/datapilot/datapilot
Environment="PATH=/home/azureuser/datapilot/datapilot/venv/bin"
ExecStart=/home/azureuser/datapilot/datapilot/venv/bin/python run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable datapilot
sudo systemctl start datapilot

# Wait for service to start
sleep 3

if sudo systemctl is-active --quiet datapilot; then
    print_status "DataPilot service started successfully"
else
    print_error "DataPilot service failed to start. Check logs with: sudo journalctl -u datapilot -n 50"
    exit 1
fi
echo ""

#############################################################
# Step 8: Configure Nginx
#############################################################
echo "Step 8/8: Configuring Nginx reverse proxy..."

# Get VM public IP
PUBLIC_IP=$(curl -s ifconfig.me)

sudo tee /etc/nginx/sites-available/datapilot > /dev/null <<EOF
server {
    listen 80;
    server_name $PUBLIC_IP;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/datapilot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Configure firewall
sudo ufw --force enable
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH

print_status "Nginx configured and started"
echo ""

#############################################################
# Step 9: Create Backup Script
#############################################################
echo "Creating backup script..."

cat > ~/backup_db.sh <<EOF
#!/bin/bash
BACKUP_DIR="/home/azureuser/backups"
DATE=\$(date +%Y%m%d_%H%M%S)
mkdir -p \$BACKUP_DIR

PGPASSWORD='$DB_PASSWORD' pg_dump -h localhost -U $DB_USER -d $DB_NAME -F c -f "\$BACKUP_DIR/datapilot_\$DATE.backup"

# Keep only last 7 days
find \$BACKUP_DIR -name "datapilot_*.backup" -mtime +7 -delete

echo "Backup completed: datapilot_\$DATE.backup"
EOF

chmod +x ~/backup_db.sh
print_status "Backup script created at ~/backup_db.sh"
echo ""

#############################################################
# Summary
#############################################################
echo "======================================"
echo "  Application Setup Complete!"
echo "======================================"
echo ""
print_status "DataPilot is now running!"
echo ""
echo "Access your application:"
echo "  Web Interface: http://$PUBLIC_IP"
echo "  API Docs:      http://$PUBLIC_IP/docs"
echo ""
echo "Useful commands:"
echo "  View logs:     sudo journalctl -u datapilot -f"
echo "  Restart app:   sudo systemctl restart datapilot"
echo "  Check status:  sudo systemctl status datapilot"
echo ""
echo "To schedule daily backups:"
echo "  crontab -e"
echo "  Add: 0 2 * * * /home/azureuser/backup_db.sh >> /home/azureuser/backup.log 2>&1"
echo ""
deactivate
