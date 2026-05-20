#!/usr/bin/env bash
# setup_domain.sh — configure nginx reverse proxy + Let's Encrypt TLS for the dashboard
# Run as root on the server.
# Usage: bash scripts/setup_domain.sh <your-domain.com> <your-email@example.com>
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Usage: $0 <domain> <email>"
    echo "  domain  — the domain pointing to this server (e.g. signal.example.com)"
    echo "  email   — contact email for Let's Encrypt expiry notices"
    exit 1
fi

INSTALL_DIR="/opt/mexc-signal-engine"
NGINX_CONF="/etc/nginx/sites-available/mexc-dashboard"

echo "=== Domain setup: $DOMAIN ==="

# ── 1. Install nginx + certbot ───────────────────────────────────────────────
echo "[1/5] Installing nginx and certbot..."
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx

# ── 2. Write initial nginx config (HTTP only, needed for certbot challenge) ──
echo "[2/5] Writing nginx config..."
cat > "$NGINX_CONF" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ { root /var/www/certbot; }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
        proxy_buffering off;
    }
}
NGINX

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/mexc-dashboard
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ── 3. Open firewall for HTTP/HTTPS ─────────────────────────────────────────
echo "[3/5] Opening firewall ports 80 and 443..."
ufw allow 80/tcp  comment "HTTP (nginx)"
ufw allow 443/tcp comment "HTTPS (nginx)"

# ── 4. Obtain TLS certificate ────────────────────────────────────────────────
echo "[4/5] Obtaining Let's Encrypt certificate for $DOMAIN..."
certbot --nginx -n --agree-tos --email "$EMAIL" -d "$DOMAIN"

# ── 5. Verify nginx config has TLS, reload ───────────────────────────────────
echo "[5/5] Reloading nginx with TLS config..."
nginx -t && systemctl reload nginx

echo ""
echo "=== Setup complete ==="
echo ""
echo "Dashboard is now available at: https://$DOMAIN"
echo ""
echo "Next steps:"
echo "  1. Ensure DASHBOARD_TOKEN is set in $INSTALL_DIR/.env"
echo "  2. Ensure SECRET_KEY is set in $INSTALL_DIR/.env"
echo "     Generate: python3 -c \"import secrets; print(secrets.token_hex(32))\""
echo "  3. Restart the dashboard service:"
echo "     systemctl restart mexc-dashboard"
echo ""
echo "To renew the certificate automatically, certbot installs a systemd timer."
echo "Verify: systemctl status certbot.timer"
