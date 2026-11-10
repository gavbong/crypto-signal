#!/usr/bin/env bash
# Install (or reinstall) the premarket-gappers systemd timer on Hetzner.
# Run this once after deploying. Safe to re-run.
#
# Usage: bash scripts/install_premarket_timer.sh

set -euo pipefail

SERVER="root@<YOUR_SERVER_IP>"
SSH_OPTS="-i $HOME/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new"
INSTALL_DIR="/opt/mexc-signal-engine"

echo "Installing premarket-gappers timer on $SERVER ..."

ssh $SSH_OPTS "$SERVER" bash -s << REMOTE
set -euo pipefail

# Copy unit files from the repo into systemd
cp $INSTALL_DIR/scripts/premarket-gappers.service /etc/systemd/system/
cp $INSTALL_DIR/scripts/premarket-gappers.timer   /etc/systemd/system/

# Ensure tzdata is present for TZ=America/New_York to work
if ! timedatectl list-timezones 2>/dev/null | grep -q America/New_York; then
    apt-get install -y tzdata
fi

systemctl daemon-reload
systemctl enable --now premarket-gappers.timer

echo ""
echo "=== Timer status ==="
systemctl status premarket-gappers.timer --no-pager

echo ""
echo "=== Next fire time ==="
systemctl list-timers premarket-gappers.timer --no-pager
REMOTE

echo ""
echo "Done. Logs: ssh $SERVER journalctl -u premarket-gappers"
