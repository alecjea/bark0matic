#!/bin/bash

# ============================================================
# BARKOMATIC - ReSpeaker HAT Audio Fix
# ============================================================
# Diagnoses and fixes WM8960 audio on Raspberry Pi
# Supports kernel 6.12+ using pguyot/wm8960 driver
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

echo -e "${YELLOW}[1/6] System info${NC}"
KERNEL=$(uname -r)
echo "  Kernel: $KERNEL"
echo "  Pi OS:  $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"')"
echo "  Config: $CONFIG"
echo ""

# ── Enable I2C if needed ──────────────────────────────────
echo -e "${YELLOW}[2/6] Checking I2C bus...${NC}"

# Ensure i2c-tools is installed
if ! command -v i2cdetect &>/dev/null; then
  echo -e "${YELLOW}  Installing i2c-tools...${NC}"
  sudo apt-get install -y i2c-tools > /dev/null 2>&1
fi

# Check if I2C is enabled (raspi-config: 0=enabled, 1=disabled)
if command -v raspi-config &>/dev/null; then
  I2C_STATUS=$(sudo raspi-config nonint get_i2c 2>/dev/null)
  if [ "$I2C_STATUS" = "1" ]; then
    echo -e "${YELLOW}  I2C is disabled. Enabling...${NC}"
    sudo raspi-config nonint do_i2c 0
    NEEDS_REBOOT=true
  else
    echo -e "${GREEN}  ✓ I2C enabled${NC}"
  fi
fi

# Also ensure dtparam=i2c_arm=on is in config
if ! grep -q "^dtparam=i2c_arm=on" "$CONFIG" 2>/dev/null; then
  echo -e "${YELLOW}  Adding dtparam=i2c_arm=on to $CONFIG...${NC}"
  echo "dtparam=i2c_arm=on" | sudo tee -a "$CONFIG" > /dev/null
  NEEDS_REBOOT=true
fi
echo ""

# ── Check I2C device ──────────────────────────────────────
echo -e "${YELLOW}[3/6] Checking I2C for WM8960 codec...${NC}"

if [ "$NEEDS_REBOOT" = true ]; then
  echo -e "${YELLOW}  ⚠ I2C was just enabled — need to reboot before detecting codec${NC}"
elif i2cdetect -y 1 2>/dev/null | grep '10:' | grep -qE '1a|UU'; then
  echo -e "${GREEN}  ✓ WM8960 found at I2C address 0x1a${NC}"
else
  echo -e "${RED}  ✗ WM8960 not found on I2C bus${NC}"
  echo "    Make sure the HAT is seated properly on the GPIO header"
  echo "    Then reboot and run this script again"
  NEEDS_REBOOT=true
fi
echo ""

# ── Check dtoverlay ───────────────────────────────────────
echo -e "${YELLOW}[4/6] Checking device tree overlay...${NC}"

if ! grep -q "^dtparam=i2s=on" "$CONFIG" 2>/dev/null; then
  echo -e "${YELLOW}  Adding dtparam=i2s=on...${NC}"
  echo "" | sudo tee -a "$CONFIG" > /dev/null
  echo "dtparam=i2s=on" | sudo tee -a "$CONFIG" > /dev/null
  NEEDS_REBOOT=true
else
  echo -e "${GREEN}  ✓ I2S enabled${NC}"
fi

# Determine which overlay to use based on kernel version
# Kernel 6.12+ has MCLK issues with seeed-2mic-voicecard overlay
# Use the pguyot/wm8960 overlay instead which works on all kernels
KERNEL_MAJOR=$(echo "$KERNEL" | cut -d. -f1)
KERNEL_MINOR=$(echo "$KERNEL" | cut -d. -f2)

if [ "$KERNEL_MAJOR" -gt 6 ] || ([ "$KERNEL_MAJOR" -eq 6 ] && [ "$KERNEL_MINOR" -ge 12 ]); then
  echo -e "${YELLOW}  Kernel $KERNEL detected — using pguyot/wm8960 driver (fixes MCLK issue)${NC}"

  # Remove old seeed overlay if present
  if grep -q "^dtoverlay=seeed-2mic-voicecard" "$CONFIG" 2>/dev/null; then
    echo -e "${YELLOW}  Removing old seeed-2mic-voicecard overlay...${NC}"
    sudo sed -i '/^dtoverlay=seeed-2mic-voicecard/d' "$CONFIG"
    NEEDS_REBOOT=true
  fi

  # Add wm8960 overlay
  if ! grep -q "^dtoverlay=wm8960-soundcard" "$CONFIG" 2>/dev/null; then
    echo -e "${YELLOW}  Adding dtoverlay=wm8960-soundcard...${NC}"
    echo "dtoverlay=wm8960-soundcard" | sudo tee -a "$CONFIG" > /dev/null
    NEEDS_REBOOT=true
  else
    echo -e "${GREEN}  ✓ wm8960-soundcard overlay present${NC}"
  fi
else
  # Older kernels: use the seeed overlay
  if ! grep -q "^dtoverlay=seeed-2mic-voicecard" "$CONFIG" 2>/dev/null; then
    echo -e "${YELLOW}  Adding dtoverlay=seeed-2mic-voicecard...${NC}"
    echo "dtoverlay=seeed-2mic-voicecard" | sudo tee -a "$CONFIG" > /dev/null
    NEEDS_REBOOT=true
  else
    echo -e "${GREEN}  ✓ seeed-2mic-voicecard overlay present${NC}"
  fi
fi
echo ""

# ── Install driver ────────────────────────────────────────
echo -e "${YELLOW}[5/6] Checking audio driver...${NC}"

if [ "$KERNEL_MAJOR" -gt 6 ] || ([ "$KERNEL_MAJOR" -eq 6 ] && [ "$KERNEL_MINOR" -ge 12 ]); then
  # Use pguyot/wm8960 for kernel 6.12+
  if [ ! -f /boot/firmware/overlays/wm8960-soundcard.dtbo ] && \
     [ ! -f /boot/overlays/wm8960-soundcard.dtbo ]; then
    echo -e "${YELLOW}  Installing pguyot/wm8960 driver...${NC}"

    # Remove old seeed-voicecard if installed
    if [ -f /tmp/seeed-voicecard/uninstall.sh ]; then
      echo -e "${YELLOW}  Removing old seeed-voicecard driver...${NC}"
      cd /tmp/seeed-voicecard && sudo ./uninstall.sh 2>/dev/null
      cd -
    elif [ -d /usr/src/seeed-voicecard* ]; then
      echo -e "${YELLOW}  Removing old seeed-voicecard driver...${NC}"
      cd /usr/src/seeed-voicecard* && sudo ./uninstall.sh 2>/dev/null
      cd - 2>/dev/null
    fi

    # Install pguyot/wm8960
    WM8960_DIR="/tmp/wm8960"
    rm -rf "$WM8960_DIR"
    git clone https://github.com/pguyot/wm8960 "$WM8960_DIR"
    cd "$WM8960_DIR" && sudo make install
    cd -
    NEEDS_REBOOT=true
    echo -e "${GREEN}  ✓ pguyot/wm8960 driver installed${NC}"
  else
    echo -e "${GREEN}  ✓ wm8960 driver installed${NC}"
  fi
else
  # Use seeed-voicecard for older kernels
  if [ ! -f /etc/asound.conf ] || ! grep -q "seeed2micvoicec\|wm8960" /etc/asound.conf 2>/dev/null; then
    echo -e "${YELLOW}  Installing seeed-voicecard driver...${NC}"
    VOICECARD_DIR="/tmp/seeed-voicecard"
    rm -rf "$VOICECARD_DIR"
    git clone https://github.com/HinTak/seeed-voicecard "$VOICECARD_DIR"
    cd "$VOICECARD_DIR" && sudo ./install.sh
    cd -
    NEEDS_REBOOT=true
  else
    echo -e "${GREEN}  ✓ seeed-voicecard driver installed${NC}"
  fi
fi
echo ""

# ── Check MCLK ────────────────────────────────────────────
echo -e "${YELLOW}[6/6] Checking WM8960 status...${NC}"

if dmesg 2>/dev/null | grep -qi "No MCLK configured"; then
  echo -e "${RED}  ✗ WM8960 reports 'No MCLK configured'${NC}"
  if [ "$NEEDS_REBOOT" = false ]; then
    echo -e "${YELLOW}  This should be fixed by the driver update above${NC}"
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

  # Try various ALSA devices
  for DEV in "default" "plughw:CARD=wm8960soundcard,DEV=0" "plughw:CARD=seeed2micvoicec,DEV=0"; do
    for RATE in 16000 48000 44100; do
      for CH in 1 2; do
        if arecord -D "$DEV" -f S16_LE -r "$RATE" -c "$CH" -d 1 "$TEST_FILE" 2>/dev/null; then
          echo -e "${GREEN}  ✓ Recording works! (device: $DEV, rate: $RATE, channels: $CH)${NC}"
          rm -f "$TEST_FILE"
          echo ""
          echo -e "${GREEN}════════════════════════════════════════${NC}"
          echo -e "${GREEN}✓ HAT audio is working!${NC}"
          echo -e "${GREEN}════════════════════════════════════════${NC}"
          exit 0
        fi
      done
    done
  done

  echo -e "${RED}  ✗ Recording still failing${NC}"
  echo ""
  echo "  Relevant kernel messages:"
  dmesg | grep -i 'wm8960\|seeed\|i2s' | tail -10
  echo ""
  echo "  Available ALSA capture devices:"
  arecord -l 2>/dev/null
  echo ""
  echo "  Please share this output for further debugging."
  exit 1
fi

# ── Reboot needed ─────────────────────────────────────────
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${YELLOW}⚠ A reboot is required for changes to take effect.${NC}"
echo -e "${YELLOW}  After reboot, run this script again to verify.${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
read -p "Reboot now? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
  sudo reboot
else
  echo "Run 'sudo reboot' when ready, then re-run: bash fix-hat-audio.sh"
fi
