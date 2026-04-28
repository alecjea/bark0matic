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

# When piped through curl | bash, BASH_SOURCE[0] is empty — clone the repo first
INSTALL_DIR="/home/$(whoami)/barkomatic"
if [ -z "${BASH_SOURCE[0]}" ] || [ "${BASH_SOURCE[0]}" = "bash" ]; then
  echo -e "${YELLOW}[0/2] Cloning Barkomatic repository...${NC}"
  if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${GREEN}✓ Repo already exists at $INSTALL_DIR, pulling latest...${NC}"
    git -C "$INSTALL_DIR" pull origin master -q
  else
    git clone https://github.com/alecjea/bark0matic.git "$INSTALL_DIR" -q
    echo -e "${GREEN}✓ Cloned to $INSTALL_DIR${NC}"
  fi
  echo ""
  exec bash "$INSTALL_DIR/install.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/barkomatic.service"

if [ ! -f "$SERVICE_FILE" ]; then
  echo -e "${RED}✗ barkomatic.service not found in $SCRIPT_DIR${NC}"
  exit 1
fi

# ────────────────────────────────────────────────────────────
# Step 0: Install ReSpeaker HAT driver if needed
# ────────────────────────────────────────────────────────────
if ! arecord -l 2>/dev/null | grep -qi 'seeed\|wm8960'; then
  echo -e "${YELLOW}[0/2] Checking for audio HAT driver...${NC}"
  # Check if a ReSpeaker-style HAT is physically connected via I2C
  if command -v i2cdetect &>/dev/null && i2cdetect -y 1 2>/dev/null | grep -q '1a'; then
    echo -e "${YELLOW}  ReSpeaker HAT detected but driver not installed. Installing...${NC}"
    VOICECARD_DIR="/tmp/seeed-voicecard"
    rm -rf "$VOICECARD_DIR"
    git clone https://github.com/HinTak/seeed-voicecard "$VOICECARD_DIR"
    cd "$VOICECARD_DIR" && sudo ./install.sh
    cd "$SCRIPT_DIR"
    echo -e "${GREEN}✓ ReSpeaker driver installed${NC}"
    echo -e "${YELLOW}  ⚠ A reboot is required. Run: sudo reboot${NC}"
    echo -e "${YELLOW}  Then re-run: bash install.sh${NC}"
    exit 0
  else
    echo -e "${GREEN}✓ No HAT detected, skipping driver install${NC}"
  fi
  echo ""
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
