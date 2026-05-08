#!/usr/bin/env bash
# server-setup.sh — run as root on a fresh Hetzner CX22 (Ubuntu 24.04)
# Usage: bash server-setup.sh
set -euo pipefail

REPO_URL="https://github.com/gavbong/crypto-signal.git"
INSTALL_DIR="/opt/mexc-signal-engine"
SERVICE_USER="mexc"

echo "=== MEXC Signal Engine — Server Setup ==="
echo "Repo:    $REPO_URL"
echo "Install: $INSTALL_DIR"
echo "User:    $SERVICE_USER"
echo ""

# ── 1. System packages ───────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git ufw curl

# ── 2. Service user ───────────────────────────────────────────────────────────
echo "[2/7] Creating service user '$SERVICE_USER'..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$SERVICE_USER"
fi

# ── 3. Clone repo ─────────────────────────────────────────────────────────────
echo "[3/7] Cloning repository..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Repo already exists — pulling latest..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 4. Python venv + dependencies ─────────────────────────────────────────────
echo "[4/7] Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.venv"

# ── 5. .env file ──────────────────────────────────────────────────────────────
echo "[5/7] Configuring environment variables..."
ENV_FILE="$INSTALL_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo "  .env already exists — skipping (edit manually at $ENV_FILE)"
else
    echo "  Enter your credentials (leave blank to skip and fill in later):"
    echo ""

    read -rp "  MEXC_API_KEY: " MEXC_API_KEY
    read -rp "  MEXC_SECRET: " MEXC_SECRET
    read -rp "  ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY
    read -rp "  TELEGRAM_BOT_TOKEN (signal alerts): " TELEGRAM_BOT_TOKEN
    read -rp "  TELEGRAM_CHAT_ID: " TELEGRAM_CHAT_ID
    read -rp "  COPY_TELEGRAM_BOT_TOKEN (copy trader alerts, separate bot): " COPY_TELEGRAM_BOT_TOKEN
    read -rp "  COPY_TELEGRAM_CHAT_ID (leave blank to use same chat): " COPY_TELEGRAM_CHAT_ID
    COPY_TELEGRAM_CHAT_ID="${COPY_TELEGRAM_CHAT_ID:-$TELEGRAM_CHAT_ID}"

    cat > "$ENV_FILE" <<EOF
MEXC_API_KEY=${MEXC_API_KEY}
MEXC_SECRET=${MEXC_SECRET}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
COPY_TELEGRAM_BOT_TOKEN=${COPY_TELEGRAM_BOT_TOKEN}
COPY_TELEGRAM_CHAT_ID=${COPY_TELEGRAM_CHAT_ID}
EOF
    chmod 600 "$ENV_FILE"
    chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
    echo "  .env written to $ENV_FILE"
fi

# ── 6. systemd services ────────────────────────────────────────────────────────
echo "[6/7] Installing systemd services..."
cp "$INSTALL_DIR/deploy/signal-engine.service"  /etc/systemd/system/mexc-signal-engine.service
cp "$INSTALL_DIR/deploy/dashboard.service"      /etc/systemd/system/mexc-dashboard.service
cp "$INSTALL_DIR/deploy/paper-trader.service"   /etc/systemd/system/mexc-paper-trader.service
cp "$INSTALL_DIR/deploy/copy-trader.service"    /etc/systemd/system/mexc-copy-trader.service

systemctl daemon-reload
systemctl enable mexc-signal-engine mexc-dashboard mexc-paper-trader mexc-copy-trader
systemctl restart mexc-signal-engine mexc-dashboard mexc-paper-trader mexc-copy-trader

# ── 7. Firewall ────────────────────────────────────────────────────────────────
echo "[7/7] Configuring firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
# Port 5000 intentionally NOT opened — access via SSH tunnel only
ufw --force enable

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Service status:"
systemctl is-active mexc-signal-engine mexc-dashboard mexc-paper-trader mexc-copy-trader | paste - - - - | \
    awk '{print "  signal-engine: "$1"\n  dashboard:     "$2"\n  paper-trader:  "$3"\n  copy-trader:   "$4}'
echo ""
echo "View logs:"
echo "  journalctl -fu mexc-signal-engine"
echo "  journalctl -fu mexc-dashboard"
echo "  journalctl -fu mexc-paper-trader"
echo "  journalctl -fu mexc-copy-trader"
echo ""
echo "Access dashboard (from your local machine):"
echo "  ssh -L 5000:localhost:5000 root@$(hostname -I | awk '{print $1}')"
echo "  Then open: http://localhost:5000"
echo ""
echo "If you have a signals.db to restore, upload it with:"
echo "  scp signals.db root@$(hostname -I | awk '{print $1}'):$INSTALL_DIR/signals.db"
echo "  ssh root@$(hostname -I | awk '{print $1}') chown $SERVICE_USER:$SERVICE_USER $INSTALL_DIR/signals.db"
echo "  ssh root@$(hostname -I | awk '{print $1}') systemctl restart mexc-signal-engine mexc-dashboard mexc-paper-trader"
