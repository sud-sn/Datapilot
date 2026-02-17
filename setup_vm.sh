#!/bin/bash
#############################################################
# DataPilot - Azure VM Setup Script
# Run this script on your Ubuntu VM after connecting via SSH
#############################################################

set -e  # Exit on error

echo "======================================"
echo "  DataPilot VM Setup - Starting"
echo "======================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

#############################################################
# Step 1: Update System
#############################################################
echo "Step 1/7: Updating system..."
sudo apt update -qq && sudo apt upgrade -y -qq
print_status "System updated"
echo ""

#############################################################
# Step 2: Install Python 3.11
#############################################################
echo "Step 2/7: Installing Python 3.11..."
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update -qq
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Verify installation
PYTHON_VERSION=$(python3.11 --version)
print_status "Python installed: $PYTHON_VERSION"
echo ""

#############################################################
# Step 3: Install PostgreSQL
#############################################################
echo "Step 3/7: Installing PostgreSQL..."
sudo apt install -y postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
print_status "PostgreSQL installed and started"
echo ""

#############################################################
# Step 4: Install Additional Tools
#############################################################
echo "Step 4/7: Installing additional tools..."
sudo apt install -y git build-essential curl nginx htop
print_status "Additional tools installed"
echo ""

#############################################################
# Step 5: PostgreSQL Database Setup
#############################################################
echo "Step 5/7: Setting up PostgreSQL database..."
echo ""
print_warning "You need to provide database credentials:"
read -p "Enter database name [datapilot_db]: " DB_NAME
DB_NAME=${DB_NAME:-datapilot_db}

read -p "Enter database username [datapilot_user]: " DB_USER
DB_USER=${DB_USER:-datapilot_user}

read -sp "Enter database password: " DB_PASSWORD
echo ""

if [ -z "$DB_PASSWORD" ]; then
    echo "Error: Password cannot be empty!"
    exit 1
fi

# Create database and user
sudo -u postgres psql <<EOF
CREATE DATABASE $DB_NAME;
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
\c $DB_NAME
GRANT ALL ON SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
EOF

print_status "Database '$DB_NAME' created with user '$DB_USER'"
echo ""

# Configure PostgreSQL access
print_warning "Configuring PostgreSQL access..."
PG_HBA_FILE="/etc/postgresql/15/main/pg_hba.conf"

# Add access rules if they don't exist
if ! grep -q "# DataPilot access" "$PG_HBA_FILE"; then
    sudo bash -c "cat >> $PG_HBA_FILE" <<EOF

# DataPilot access
local   $DB_NAME    $DB_USER                          md5
host    $DB_NAME    $DB_USER  127.0.0.1/32           md5
EOF
    print_status "PostgreSQL access configured"
else
    print_status "PostgreSQL access already configured"
fi

# Restart PostgreSQL
sudo systemctl restart postgresql
print_status "PostgreSQL restarted"
echo ""

#############################################################
# Step 6: Test PostgreSQL Connection
#############################################################
echo "Step 6/7: Testing PostgreSQL connection..."
export PGPASSWORD="$DB_PASSWORD"
if psql -h localhost -U $DB_USER -d $DB_NAME -c "\q" 2>/dev/null; then
    print_status "PostgreSQL connection successful!"
else
    print_warning "PostgreSQL connection test failed. Please check credentials."
fi
unset PGPASSWORD
echo ""

#############################################################
# Step 7: Save Configuration
#############################################################
echo "Step 7/7: Saving configuration..."

# Save database credentials for later use
mkdir -p ~/datapilot-setup
cat > ~/datapilot-setup/db_config.txt <<EOF
Database Name: $DB_NAME
Database User: $DB_USER
Database Password: $DB_PASSWORD
Database Host: localhost
Database Port: 5432
EOF

chmod 600 ~/datapilot-setup/db_config.txt
print_status "Configuration saved to ~/datapilot-setup/db_config.txt"
echo ""

#############################################################
# Summary
#############################################################
echo "======================================"
echo "  VM Setup Complete!"
echo "======================================"
echo ""
echo "✓ Python 3.11 installed"
echo "✓ PostgreSQL installed and configured"
echo "✓ Database '$DB_NAME' ready"
echo "✓ Additional tools installed"
echo ""
echo "Next Steps:"
echo "1. Get your Groq API key from https://console.groq.com"
echo "2. Run the application setup script: ./setup_application.sh"
echo ""
echo "Database credentials saved in: ~/datapilot-setup/db_config.txt"
echo ""
