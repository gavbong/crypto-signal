#!/usr/bin/env bash
# deploy.sh — push latest code to server and restart services
# Usage: ./scripts/deploy.sh root@<server-ip>
set -euo pipefail

SERVER="${1:-root@46.62.219.155}"
INSTALL_DIR="/opt/mexc-signal-engine"
SSH_KEY="$HOME/.ssh/id_ed25519"

SSH="ssh -i $SSH_KEY"
SCP="scp -i $SSH_KEY"

echo "=== Deploying to $SERVER ==="

# Push local .env if it exists and the user wants to sync it
if [ -f ".env" ]; then
    read -rp "Sync local .env to server? [y/N]: " SYNC_ENV
    if [[ "$SYNC_ENV" =~ ^[Yy]$ ]]; then
        echo "  Uploading .env..."
        $SCP .env "$SERVER:$INSTALL_DIR/.env"
        $SSH "$SERVER" "chmod 600 $INSTALL_DIR/.env && chown mexc:mexc $INSTALL_DIR/.env"
    fi
fi

# Pull latest code and restart
$SSH "$SERVER" bash <<REMOTE
set -euo pipefail
echo "  Pulling latest code..."
git -C $INSTALL_DIR pull --ff-only

echo "  Updating dependencies (if requirements.txt changed)..."
$INSTALL_DIR/.venv/bin/pip install --quiet -r $INSTALL_DIR/requirements.txt

echo "  Restarting services..."
systemctl restart mexc-signal-engine mexc-dashboard mexc-paper-trader mexc-copy-trader mexc-poly-trader

sleep 3
echo ""
echo "Service status:"
systemctl is-active mexc-signal-engine mexc-dashboard mexc-paper-trader mexc-copy-trader mexc-poly-trader | \
    paste - - - - - | awk '{print "  signal-engine: "\$1"\\n  dashboard:     "\$2"\\n  paper-trader:  "\$3"\\n  copy-trader:   "\$4"\\n  poly-trader:   "\$5}'

# Health check
if curl -sf http://localhost:5000/api/health > /dev/null 2>&1; then
    echo "  Health: OK"
else
    echo "  Health: FAIL — check journalctl -fu mexc-dashboard"
    exit 1
fi
REMOTE

echo ""
echo "=== Deploy complete ==="
echo "To view dashboard: ssh -i $SSH_KEY -L 5000:localhost:5000 $SERVER"
