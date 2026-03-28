#!/bin/bash

# ============================================================
# BARKOMATIC - ReSpeaker HAT Audio Fix
# ============================================================
# Diagnoses and fixes WM8960 MCLK issues on Raspberry Pi
# Run with: bash fix-hat-audio.sh

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}🐕 BARKOMATIC - HAT Audio Diagnostics${NC}"
echo ""

NEEDS_REBOOT=false
CONFIG="/boot/firmware/config.txt"
# Older Pi OS uses /boot/config.txt
if [ ! -f "$CONFIG" ]; then
  CONFIG="/boot/config.txt"
fi

echo -e "${YELLOW}[1/5] System info${NC}"
echo "  Kernel: $(uname -r)"
echo "  Pi OS:  $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"')"
echo "  Config: $CONFIG"
echo ""

# ── Check I2C device ──────────────────────────────────────
echo -e "${YELLOW}[2/5] Checking I2C for WM8960 codec...${NC}"
if command -v i2cdetect &>/dev/null; then
  if i2cdetect -y 1 2>/dev/null | grep -q '1a'; then
    echo -e "${GREEN}  ✓ WM8960 found at I2C address 0x1a${NC}"
  else
    echo -e "${RED}  ✗ WM8960 not found on I2C bus${NC}"
    echo "    Make sure the HAT is seated properly on the GPIO header"
    exit 1
  fi
else
  echo -e "${YELLOW}  ⚠ i2cdetect not available, installing i2c-tools...${NC}"
  sudo apt-get install -y i2c-tools > /dev/null 2>&1
  if i2cdetect -y 1 2>/dev/null | grep -q '1a'; then
    echo -e "${GREEN}  ✓ WM8960 found at I2C address 0x1a${NC}"
  else
    echo -e "${RED}  ✗ WM8960 not found on I2C bus${NC}"
    echo "    Make sure the HAT is seated properly on the GPIO header"
    exit 1
  fi
fi
echo ""

# ── Check dtoverlay ───────────────────────────────────────
echo -e "${YELLOW}[3/5] Checking device tree overlay...${NC}"

if ! grep -q "^dtparam=i2s=on" "$CONFIG" 2>/dev/null; then
  echo -e "${YELLOW}  Adding dtparam=i2s=on...${NC}"
  echo "" | sudo tee -a "$CONFIG" > /dev/null
  echo "dtparam=i2s=on" | sudo tee -a "$CONFIG" > /dev/null
  NEEDS_REBOOT=true
else
  echo -e "${GREEN}  ✓ I2S enabled${NC}"
fi

if ! grep -q "^dtoverlay=seeed-2mic-voicecard" "$CONFIG" 2>/dev/null; then
  echo -e "${YELLOW}  Adding dtoverlay=seeed-2mic-voicecard...${NC}"
  echo "dtoverlay=seeed-2mic-voicecard" | sudo tee -a "$CONFIG" > /dev/null
  NEEDS_REBOOT=true
else
  echo -e "${GREEN}  ✓ seeed-2mic-voicecard overlay present${NC}"
fi
echo ""

# ── Check driver ──────────────────────────────────────────
echo -e "${YELLOW}[4/5] Checking seeed-voicecard driver...${NC}"

if ! dpkg -l 2>/dev/null | grep -q seeed-voicecard && \
   [ ! -f /etc/asound.conf ] || ! grep -q "seeed2micvoicec" /etc/asound.conf 2>/dev/null; then
  echo -e "${YELLOW}  Driver not found. Installing...${NC}"
  VOICECARD_DIR="/tmp/seeed-voicecard"
  rm -rf "$VOICECARD_DIR"
  git clone https://github.com/HinTak/seeed-voicecard "$VOICECARD_DIR"
  cd "$VOICECARD_DIR" && sudo ./install.sh
  cd -
  NEEDS_REBOOT=true
else
  echo -e "${GREEN}  ✓ seeed-voicecard driver installed${NC}"
fi
echo ""

# ── Check MCLK ────────────────────────────────────────────
echo -e "${YELLOW}[5/5] Checking WM8960 MCLK status...${NC}"

if dmesg 2>/dev/null | grep -qi "No MCLK configured"; then
  echo -e "${RED}  ✗ WM8960 reports 'No MCLK configured'${NC}"

  # Check if the kernel module is loaded
  if lsmod | grep -q snd_soc_wm8960; then
    echo -e "${YELLOW}  Removing and reloading WM8960 module...${NC}"
    sudo modprobe -r snd_soc_wm8960 2>/dev/null
    sudo modprobe snd_soc_wm8960 2>/dev/null
  fi

  NEEDS_REBOOT=true
else
  echo -e "${GREEN}  ✓ No MCLK errors detected${NC}"
fi
echo ""

# ── Test recording ────────────────────────────────────────
if [ "$NEEDS_REBOOT" = false ]; then
  echo -e "${YELLOW}Testing audio capture...${NC}"
  TEST_FILE="/tmp/barkomatic_test.wav"
  rm -f "$TEST_FILE"

  # Try the default ALSA device first, then plughw
  for DEV in "default" "plughw:CARD=seeed2micvoicec,DEV=0"; do
    if arecord -D "$DEV" -f S16_LE -r 16000 -c 2 -d 1 "$TEST_FILE" 2>/dev/null; then
      echo -e "${GREEN}  ✓ Recording works with device: $DEV${NC}"
      rm -f "$TEST_FILE"
      echo ""
      echo -e "${GREEN}════════════════════════════════════════${NC}"
      echo -e "${GREEN}✓ HAT audio is working!${NC}"
      echo -e "${GREEN}════════════════════════════════════════${NC}"
      exit 0
    fi
  done

  echo -e "${RED}  ✗ Recording still failing${NC}"
  echo ""
  echo "  Relevant kernel messages:"
  dmesg | grep -i 'wm8960\|seeed\|i2s' | tail -5
  echo ""
  echo "  Please share this output for further debugging."
  exit 1
fi

# ── Reboot needed ─────────────────────────────────────────
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${YELLOW}⚠ A reboot is required for changes to take effect.${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
read -p "Reboot now? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
  sudo reboot
else
  echo "Run 'sudo reboot' when ready, then re-run this script to verify."
fi
