# DataPilot Azure Deployment - PowerShell Script
# Run this on your Windows machine to create Azure resources

# Configuration
$ResourceGroup = "datapilot-rg"
$VMName = "datapilot-vm"
$Location = "eastus"
$VMSize = "Standard_B2ms"
$AdminUsername = "azureuser"

Write-Host "======================================"
Write-Host "  DataPilot Azure Resource Creation"
Write-Host "======================================"
Write-Host ""

# Check if Azure CLI is installed
try {
    az --version | Out-Null
    Write-Host "[✓] Azure CLI is installed" -ForegroundColor Green
} catch {
    Write-Host "[✗] Azure CLI is not installed!" -ForegroundColor Red
    Write-Host "    Please install from: https://aka.ms/installazurecliwindows"
    exit 1
}

Write-Host ""

# Login to Azure
Write-Host "Step 1/5: Logging into Azure..."
az login
if ($LASTEXITCODE -ne 0) {
    Write-Host "[✗] Azure login failed!" -ForegroundColor Red
    exit 1
}
Write-Host "[✓] Logged into Azure" -ForegroundColor Green
Write-Host ""

# Create Resource Group
Write-Host "Step 2/5: Creating resource group..."
az group create --name $ResourceGroup --location $Location --output none
Write-Host "[✓] Resource group '$ResourceGroup' created" -ForegroundColor Green
Write-Host ""

# Create Virtual Machine
Write-Host "Step 3/5: Creating virtual machine (this takes 2-3 minutes)..."
az vm create `
    --resource-group $ResourceGroup `
    --name $VMName `
    --image Ubuntu2204 `
    --size $VMSize `
    --admin-username $AdminUsername `
    --generate-ssh-keys `
    --public-ip-sku Standard `
    --output none

Write-Host "[✓] Virtual machine '$VMName' created" -ForegroundColor Green
Write-Host ""

# Open Ports
Write-Host "Step 4/5: Opening network ports..."
az vm open-port --port 80 --resource-group $ResourceGroup --name $VMName --priority 1001 --output none
az vm open-port --port 443 --resource-group $ResourceGroup --name $VMName --priority 1002 --output none
az vm open-port --port 8000 --resource-group $ResourceGroup --name $VMName --priority 1003 --output none
Write-Host "[✓] Ports opened (80, 443, 8000)" -ForegroundColor Green
Write-Host ""

# Get Public IP
Write-Host "Step 5/5: Retrieving VM information..."
$VMInfo = az vm list-ip-addresses --resource-group $ResourceGroup --name $VMName | ConvertFrom-Json
$PublicIP = $VMInfo[0].virtualMachine.network.publicIpAddresses[0].ipAddress

Write-Host ""
Write-Host "======================================"
Write-Host "  Azure Resources Created!"
Write-Host "======================================"
Write-Host ""
Write-Host "VM Name:       $VMName"
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Location:      $Location"
Write-Host "VM Size:       $VMSize"
Write-Host "Public IP:     $PublicIP"
Write-Host ""
Write-Host "SSH Command:"
Write-Host "  ssh $AdminUsername@$PublicIP"
Write-Host ""
Write-Host "Next Steps:"
Write-Host "1. SSH into the VM using the command above"
Write-Host "2. Upload and run setup_vm.sh"
Write-Host "3. Upload and run setup_application.sh"
Write-Host ""

# Save info to file
$InfoFile = "azure_vm_info.txt"
@"
DataPilot Azure VM Information
==============================

VM Name: $VMName
Resource Group: $ResourceGroup
Location: $Location
VM Size: $VMSize
Public IP: $PublicIP
SSH Username: $AdminUsername

SSH Command:
ssh $AdminUsername@$PublicIP

Created: $(Get-Date)
"@ | Out-File -FilePath $InfoFile -Encoding UTF8

Write-Host "[✓] VM information saved to: $InfoFile" -ForegroundColor Green
Write-Host ""
