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
# Step 2: Download YAMNet model files
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/3] Downloading YAMNet model files...${NC}"
if ! command -v wget &>/dev/null; then
  sudo apt-get install -y wget -q
fi
mkdir -p "$SCRIPT_DIR/models"

YAMNET_CSV="$SCRIPT_DIR/models/yamnet_class_map.csv"
YAMNET_MODEL="$SCRIPT_DIR/models/yamnet.tflite"

if [ ! -f "$YAMNET_CSV" ]; then
  wget -q -O "$YAMNET_CSV" \
    "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"
fi

if [ ! -f "$YAMNET_MODEL" ] || [ ! -s "$YAMNET_MODEL" ]; then
  rm -f "$YAMNET_MODEL"
  echo -e "${YELLOW}  Downloading YAMNet TFLite model (~3MB)...${NC}"
  "$SCRIPT_DIR/venv/bin/python3" -c "
import urllib.request, sys
urls = [
    'https://tfhub.dev/google/lite-model/yamnet/classification/tflite/1?lite-format=tflite',
    'https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/audio_classification/rpi/lite-model_yamnet_classification_tflite_1.tflite',
]
for url in urls:
    try:
        urllib.request.urlretrieve(url, sys.argv[1])
        print('Downloaded from', url)
        break
    except Exception as e:
        print('Failed:', url, e)
else:
    sys.exit(1)
" "$YAMNET_MODEL"
fi

# Update pinned SHA-256 hashes in sound_classifier.py to match downloaded files
CSV_HASH=$(sha256sum "$YAMNET_CSV" | cut -d' ' -f1)
MODEL_HASH=$(sha256sum "$YAMNET_MODEL" | cut -d' ' -f1)
sed -i "s|YAMNET_MODEL_SHA256 .*=.*|YAMNET_MODEL_SHA256     = \"$MODEL_HASH\"|" "$SCRIPT_DIR/sound_classifier.py"
sed -i "s|YAMNET_CLASS_MAP_SHA256 .*=.*|YAMNET_CLASS_MAP_SHA256 = \"$CSV_HASH\"|" "$SCRIPT_DIR/sound_classifier.py"
echo -e "${GREEN}✓ YAMNet model files ready${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 3: Install systemd service
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/3] Installing systemd service...${NC}"
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
