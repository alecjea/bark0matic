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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-/}")" 2>/dev/null && pwd || echo "$HOME")"
SERVICE_FILE="$SCRIPT_DIR/barkomatic.service"

# If service file isn't alongside this script (e.g. curl | bash), clone the repo first
if [ ! -f "$SERVICE_FILE" ]; then
  INSTALL_DIR="$HOME/barkomatic"
  echo -e "${YELLOW}[0/2] Cloning Barkomatic repository to $INSTALL_DIR...${NC}"
  if ! command -v git &>/dev/null; then
    echo -e "${YELLOW}  git not found, installing...${NC}"
    sudo apt-get install -y git -q
  fi
  if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${GREEN}✓ Repo already exists, pulling latest...${NC}"
    git -C "$INSTALL_DIR" pull origin master -q
  else
    git clone https://github.com/alecjea/bark0matic.git "$INSTALL_DIR" -q
    echo -e "${GREEN}✓ Cloned to $INSTALL_DIR${NC}"
  fi
  echo ""
  exec bash "$INSTALL_DIR/install.sh"
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

# ────────────────────────────────────────────────────────────
# Step 1: Set up Python venv and install dependencies
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/2] Setting up Python environment...${NC}"
if ! dpkg -s python3-venv &>/dev/null 2>&1; then
  sudo apt-get install -y python3-venv -q
fi
python3 -m venv "$SCRIPT_DIR/venv"
"$SCRIPT_DIR/venv/bin/pip" install -q --upgrade pip
"$SCRIPT_DIR/venv/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓ Python environment ready${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 2: Install systemd service
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/2] Installing systemd service...${NC}"
CURRENT_USER=$(whoami)
sed "s|User=.*|User=$CURRENT_USER|;s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|;s|ExecStart=.*|ExecStart=$SCRIPT_DIR/venv/bin/python3 -u main.py|" \
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
