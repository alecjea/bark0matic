#!/bin/bash

# ============================================================
# BARKOMATIC - Install Service
# ============================================================
# Sets up barkomatic as a systemd service
# Run with: bash install.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}🐕 BARKOMATIC - Install Service${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/barkomatic.service"

if [ ! -f "$SERVICE_FILE" ]; then
  echo -e "${RED}✗ barkomatic.service not found in $SCRIPT_DIR${NC}"
  exit 1
fi

# Update WorkingDirectory and User in the service file to match current setup
CURRENT_USER=$(whoami)
sed "s|User=.*|User=$CURRENT_USER|;s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|" \
  "$SERVICE_FILE" | sudo tee /etc/systemd/system/barkomatic.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable barkomatic
sudo systemctl start barkomatic

sleep 2
if systemctl is-active --quiet barkomatic; then
  echo -e "${GREEN}✓ Barkomatic service installed and running${NC}"
else
  echo -e "${RED}✗ Service failed to start - check: sudo journalctl -u barkomatic -n 20${NC}"
fi

echo ""
echo "Commands:"
echo "  sudo systemctl status barkomatic   - Check status"
echo "  sudo journalctl -u barkomatic -f   - View logs"
echo "  bash update.sh                     - Pull updates & restart"
echo ""
