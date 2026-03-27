#!/bin/bash

# ============================================================
# BARKOMATIC - Fresh Raspberry Pi Installation Script
# ============================================================
# Complete setup from zero to running web dashboard
# Run with: bash install.sh
# Requires: Raspberry Pi OS 64-bit (arm64)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════╗"
echo "║         🐕 BARKOMATIC - Fresh Install Setup            ║"
echo "║    AI Sound Detection for Raspberry Pi                 ║"
echo "╚════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ────────────────────────────────────────────────────────────
# Root user guard — must run as a normal user, not root
# ────────────────────────────────────────────────────────────
if [ "$(id -u)" -eq 0 ]; then
  echo -e "${RED}✗ Do not run this installer as root or with sudo.${NC}"
  echo ""
  echo "Running as root installs Barkomatic into /root and runs the"
  echo "service as root, which is a security risk and not supported."
  echo ""
  echo "Run as your normal Pi user instead:"
  echo -e "  ${BLUE}bash install.sh${NC}"
  echo ""
  exit 1
fi

# ────────────────────────────────────────────────────────────
# Step 1: Architecture check
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/9] Checking system architecture...${NC}"

ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)

if [ "$ARCH" != "arm64" ] && [ "$ARCH" != "aarch64" ]; then
  echo -e "${RED}"
  echo "╔════════════════════════════════════════════════════════╗"
  echo "║                  ✗ UNSUPPORTED PLATFORM                ║"
  echo "╚════════════════════════════════════════════════════════╝"
  echo -e "${NC}"
  echo -e "${RED}Architecture detected: $ARCH${NC}"
  echo ""
  echo "Barkomatic's AI/YAMNet mode requires a 64-bit operating system."
  echo "The ai-edge-litert package (TFLite runtime) only publishes"
  echo "aarch64 wheels and does not support 32-bit ARM (armhf)."
  echo ""
  echo "To fix this, reinstall with Raspberry Pi OS 64-bit:"
  echo -e "  ${BLUE}https://www.raspberrypi.com/software/${NC}"
  echo ""
  echo "On the Raspberry Pi Imager, choose:"
  echo "  Raspberry Pi OS (64-bit)"
  echo ""
  exit 1
fi

echo -e "${GREEN}✓ Architecture: $ARCH (supported)${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 2: Update package lists
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/9] Updating package lists...${NC}"
sudo apt-get update -qq
echo -e "${GREEN}✓ Package lists updated${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 3: Install system packages
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/9] Installing git, Python 3, pip, and audio libraries...${NC}"
sudo apt-get install -y -qq git python3 python3-pip python3-full libportaudio2 alsa-utils
PYTHON_VERSION=$(python3 --version 2>&1)
echo -e "${GREEN}✓ $PYTHON_VERSION installed${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 4: Install and configure UFW firewall
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/9] Setting up firewall (UFW)...${NC}"
sudo apt-get install -y -qq ufw

# Add allow rules BEFORE enabling so a remote SSH session is never locked out
sudo ufw allow 22/tcp > /dev/null 2>&1 || true
sudo ufw allow 8080/tcp > /dev/null 2>&1 || true

# Enable UFW without prompting (rules are already in place)
echo "y" | sudo ufw enable > /dev/null 2>&1 || true

echo -e "${GREEN}✓ Firewall configured${NC}"
echo "  - SSH (port 22) allowed"
echo "  - Barkomatic (port 8080) allowed"
echo ""

# ────────────────────────────────────────────────────────────
# Step 5: Clone or update repository
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[5/9] Cloning Barkomatic repository...${NC}"

if [ -d "$HOME/bark0matic" ]; then
  echo "  Repository already exists, updating..."
  cd "$HOME/bark0matic"
  git fetch origin -q
  git checkout master -q 2>/dev/null || true
  git pull origin master -q
else
  cd "$HOME"
  git clone -b master https://github.com/alecjea/bark0matic.git -q
  cd bark0matic
fi

echo -e "${GREEN}✓ Repository ready at $HOME/bark0matic${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 6: Install Python dependencies
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[6/9] Installing Python dependencies...${NC}"
pip install --break-system-packages -q -r requirements.txt 2>/dev/null || pip install --break-system-packages -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 7: Download and verify YAMNet model files
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[7/9] Downloading YAMNet model files...${NC}"

MODELS_DIR="$HOME/bark0matic/models"
mkdir -p "$MODELS_DIR"

YAMNET_MODEL_URL="https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/audio_classification/android/lite-model_yamnet_classification_tflite_1.tflite"
YAMNET_CLASS_MAP_URL="https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"
YAMNET_MODEL_SHA256="10c95ea3eb9a7bb4cb8bddf6feb023250381008177ac162ce169694d05c317de"
YAMNET_CLASS_MAP_SHA256="cdf24d193e196d9e95912a2667051ae203e92a2ba09449218ccb40ef787c6df2"

download_and_verify() {
  local url="$1"
  local dest="$2"
  local expected_sha256="$3"
  local label="$4"

  # Skip if already present and verified
  if [ -f "$dest" ]; then
    actual=$(sha256sum "$dest" | awk '{print $1}')
    if [ "$actual" = "$expected_sha256" ]; then
      echo -e "  ${GREEN}✓ $label already verified${NC}"
      return 0
    else
      echo "  Existing $label has wrong hash, re-downloading..."
      rm -f "$dest"
    fi
  fi

  echo "  Downloading $label..."
  wget -q -O "$dest.tmp" "$url" || curl -fsSL -o "$dest.tmp" "$url"

  actual=$(sha256sum "$dest.tmp" | awk '{print $1}')
  if [ "$actual" != "$expected_sha256" ]; then
    rm -f "$dest.tmp"
    echo -e "${RED}✗ $label hash mismatch — aborting install${NC}"
    echo "  Expected: $expected_sha256"
    echo "  Got:      $actual"
    exit 1
  fi

  mv "$dest.tmp" "$dest"
  echo -e "  ${GREEN}✓ $label downloaded and verified${NC}"
}

download_and_verify "$YAMNET_MODEL_URL"     "$MODELS_DIR/yamnet.tflite"         "$YAMNET_MODEL_SHA256"     "YAMNet TFLite model"
download_and_verify "$YAMNET_CLASS_MAP_URL" "$MODELS_DIR/yamnet_class_map.csv"  "$YAMNET_CLASS_MAP_SHA256" "YAMNet class map"
echo ""

# ────────────────────────────────────────────────────────────
# Step 8: Optional ReSpeaker HAT setup
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[8/9] ReSpeaker 2-Mic HAT setup (optional)...${NC}"
echo ""
read -p "  Do you have a ReSpeaker 2-Mic Pi HAT attached? [y/N] " -n 1 -r RESPEAKER_REPLY
echo ""

if [[ $RESPEAKER_REPLY =~ ^[Yy]$ ]]; then
  CONFIG_FILE="/boot/firmware/config.txt"
  # Fall back to /boot/config.txt for older Pi OS
  [ -f "$CONFIG_FILE" ] || CONFIG_FILE="/boot/config.txt"

  # Enable I2C
  if grep -q "^#dtparam=i2c_arm=on" "$CONFIG_FILE"; then
    sudo sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "$CONFIG_FILE"
  elif ! grep -q "^dtparam=i2c_arm=on" "$CONFIG_FILE"; then
    echo "dtparam=i2c_arm=on" | sudo tee -a "$CONFIG_FILE" > /dev/null
  fi

  # Enable I2S
  if grep -q "^#dtparam=i2s=on" "$CONFIG_FILE"; then
    sudo sed -i 's/^#dtparam=i2s=on/dtparam=i2s=on/' "$CONFIG_FILE"
  elif ! grep -q "^dtparam=i2s=on" "$CONFIG_FILE"; then
    echo "dtparam=i2s=on" | sudo tee -a "$CONFIG_FILE" > /dev/null
  fi

  # Add WM8960 overlay if not already present
  if ! grep -q "dtoverlay=wm8960-soundcard" "$CONFIG_FILE"; then
    echo "dtoverlay=wm8960-soundcard" | sudo tee -a "$CONFIG_FILE" > /dev/null
  fi

  echo -e "${GREEN}✓ ReSpeaker HAT configured (I2C, I2S, WM8960 overlay)${NC}"
  echo -e "${YELLOW}  ⚠ Reboot required for HAT to be detected${NC}"
  NEEDS_REBOOT=true
else
  echo "  Skipping ReSpeaker setup."
  NEEDS_REBOOT=false
fi
echo ""

# ────────────────────────────────────────────────────────────
# Step 9: Systemd service setup
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[9/9] Setting up systemd service (auto-start on boot)...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sudo tee /etc/systemd/system/barkomatic.service > /dev/null << EOF
[Unit]
Description=Barkomatic - AI Sound Detection System
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 -u $SCRIPT_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable barkomatic
sudo systemctl restart barkomatic
echo -e "${GREEN}✓ Systemd service created and started${NC}"
echo "  - Auto-start on boot enabled"
echo "  - Service is now running"
echo ""

# ────────────────────────────────────────────────────────────
# Done
# ────────────────────────────────────────────────────────────
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ BARKOMATIC IS READY!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""

echo "Next steps:"
echo ""
echo "1. Start the app:"
echo -e "   ${BLUE}cd ~/bark0matic${NC}"
echo -e "   ${BLUE}python3 main.py${NC}"
echo ""
echo "2. Open dashboard in browser:"
echo -e "   ${BLUE}http://localhost:8080${NC}"
echo ""
echo "3. Or use systemd (auto-start on boot):"
echo -e "   ${BLUE}sudo systemctl start barkomatic${NC}"
echo -e "   ${BLUE}sudo systemctl status barkomatic${NC}"
echo ""
echo "Configuration:"
echo -e "  - Web Dashboard: http://<rpi-ip>:8080"
echo -e "  - Config file: ~/bark0matic/config.json"
echo -e "  - Logs DB: ~/bark0matic/detections.db"
echo -e "  - CSV Export: dashboard download"
echo ""
echo "Firewall status:"
sudo ufw status | grep -E "22/tcp|8080/tcp"
echo ""
echo -e "${GREEN}Happy barking! 🐕${NC}"

if [ "$NEEDS_REBOOT" = true ]; then
  echo ""
  echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${YELLOW}  ⚠ REBOOT REQUIRED for ReSpeaker HAT to be detected${NC}"
  echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  read -p "  Reboot now? [y/N] " -n 1 -r
  echo ""
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo reboot
  else
    echo "  Run 'sudo reboot' when ready."
  fi
fi
