#!/bin/bash

# ============================================================
# BARKOMATIC - Update Script
# ============================================================
# Pull latest changes and restart service
# Run with: bash update.sh

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🐕 BARKOMATIC - Update${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ────────────────────────────────────────────────────────────
# Step 1: Pull latest changes
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/2] Pulling latest changes...${NC}"
git pull origin main -q
echo -e "${GREEN}✓ Latest changes pulled${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 2: Restart service (if systemd is running)
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/2] Restarting Barkomatic service...${NC}"

sudo systemctl restart barkomatic
sleep 2
if systemctl is-active --quiet barkomatic; then
  echo -e "${GREEN}✓ Service restarted${NC}"
else
  echo -e "${RED}✗ Service failed to start - check: sudo journalctl -u barkomatic -n 20${NC}"
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ UPDATE COMPLETE!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo "Status:"
git log --oneline -1
echo ""
