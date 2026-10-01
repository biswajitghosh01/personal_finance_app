#!/usr/bin/env bash
# Provision Secure Finance Vault on a cloud Linux server and bring the site live.
# Run as root on a fresh Debian/Ubuntu host:  sudo ./deploy.sh --domain 203.0.113.10
set -Eeuo pipefail
umask 077

SERVICE_NAME="finance"
SERVICE_USER="finance"
APP_ROOT="/opt/finance"
APP_DIR="$APP_ROOT/app"
BIND_HOST="127.0.0.1"
BIND_PORT="5555"
DOMAIN=""
EMAIL=""
ENABLE_TLS="yes"
CONFIGURE_FIREWALL="yes"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

fail() { echo "ERROR: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

usage() {
    cat <<USAGE
Usage: sudo ./deploy.sh --domain <fqdn-or-ipv4> [--email <address>] [options]

Required:
    --domain <fqdn-or-ipv4>  Public hostname or public IPv4 served over HTTPS.

Options:
  --email <address>      Contact address for Let's Encrypt registration.
    --no-tls               Skip certificate setup; serve plain HTTP on port 80 only.
  --no-firewall          Skip UFW configuration.
  --port <number>        Loopback port for the application (default 5555).
  --app-dir <path>       Install location (default /opt/finance/app).
  -h, --help             Show this message.

IP certificates are short-lived and renewed automatically by Certbot.
The script is idempotent. An existing .env and database are never overwritten.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain) DOMAIN="${2:-}"; shift 2 ;;
        --email) EMAIL="${2:-}"; shift 2 ;;
        --no-tls) ENABLE_TLS="no"; shift ;;
        --no-firewall) CONFIGURE_FIREWALL="no"; shift ;;
        --port) BIND_PORT="${2:-}"; shift 2 ;;
        --app-dir) APP_DIR="${2:-}"; APP_ROOT="$(dirname "$APP_DIR")"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; fail "Unknown argument: $1" ;;
    esac
done

[[ $EUID -eq 0 ]] || fail "Run this script as root: sudo ./deploy.sh --domain <fqdn>"
[[ -n "$DOMAIN" ]] || { usage; fail "--domain is required"; }
HOST_IS_IP="no"
if [[ "$DOMAIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    HOST_IS_IP="yes"
    python3 - "$DOMAIN" <<'PY' || fail "Invalid IPv4 address: $DOMAIN"
import ipaddress, sys
ipaddress.IPv4Address(sys.argv[1])
PY
else
    [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || fail "Invalid hostname: $DOMAIN"
fi
[[ "$BIND_PORT" =~ ^[0-9]+$ ]] || fail "Invalid port: $BIND_PORT"
command -v apt-get >/dev/null 2>&1 || fail "This script supports Debian/Ubuntu (apt-get) only."
[[ -f "$SOURCE_DIR/app.py" && -f "$SOURCE_DIR/requirements.txt" ]] \
    || fail "Run this script from the application directory; app.py was not found."

step "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq python3-venv python3-pip nginx rsync ca-certificates curl iproute2 sudo
if [[ "$CONFIGURE_FIREWALL" == "yes" ]]; then
    apt-get install -y -qq ufw
fi

step "Creating service account $SERVICE_USER"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$APP_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

step "Copying application to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' \
    --exclude 'instance/' --exclude '.env' \
    "$SOURCE_DIR"/ "$APP_DIR"/
mkdir -p "$APP_DIR/instance"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_ROOT"
chmod 700 "$APP_DIR/instance"

step "Creating virtual environment"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade --quiet pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

GENERATED_PASSWORD=""
if [[ -f "$APP_DIR/.env" ]]; then
    step "Keeping existing .env"
else
    step "Generating .env with fresh keys"
    sudo -u "$SERVICE_USER" env DOMAIN="$DOMAIN" TLS="$ENABLE_TLS" PORT="$BIND_PORT" \
        "$APP_DIR/.venv/bin/python" - "$APP_DIR/.env" <<'PY'
import os, secrets, sys
from pathlib import Path
from cryptography.fernet import Fernet

target = Path(sys.argv[1])
password = secrets.token_urlsafe(18)
secure = 'true' if os.environ['TLS'] == 'yes' else 'false'
target.write_text(
    'SECRET_KEY=' + secrets.token_urlsafe(64) + '\n'
    'DATA_KEY=' + Fernet.generate_key().decode() + '\n'
    'DEFAULT_USER=admin\n'
    'DEFAULT_PASSWORD=' + password + '\n'
    'ALLOWED_HOSTS=' + os.environ['DOMAIN'] + '\n'
    'SESSION_COOKIE_SECURE=' + secure + '\n'
    'TRUSTED_PROXY_COUNT=1\n'
    'BIND_HOST=127.0.0.1\n'
    'BIND_PORT=' + os.environ['PORT'] + '\n',
    encoding='utf-8')
PY
    GENERATED_PASSWORD="$(grep '^DEFAULT_PASSWORD=' "$APP_DIR/.env" | cut -d= -f2-)"
fi
chown "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

# Keep an existing deployment reachable if it was provisioned for another domain.
if ! grep -q "^ALLOWED_HOSTS=.*\b${DOMAIN}\b" "$APP_DIR/.env"; then
    echo "WARNING: $APP_DIR/.env does not list $DOMAIN in ALLOWED_HOSTS; requests will return HTTP 400." >&2
fi

step "Installing systemd unit $SERVICE_NAME.service"
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Secure Finance Vault
After=network-online.target
Wants=network-online.target

[Service]
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python app.py
Restart=on-failure
RestartSec=5
UMask=0077

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/instance
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --quiet "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

step "Waiting for the application to answer on $BIND_HOST:$BIND_PORT"
APP_READY="no"
for _ in $(seq 1 30); do
    if curl -sS -o /dev/null --max-time 2 -H "Host: $DOMAIN" "http://$BIND_HOST:$BIND_PORT/login"; then
        APP_READY="yes"
        break
    fi
    sleep 1
done
systemctl is-active --quiet "$SERVICE_NAME" \
    || { journalctl -u "$SERVICE_NAME" -n 30 --no-pager >&2; fail "Service failed to start."; }
[[ "$APP_READY" == "yes" ]] \
    || { journalctl -u "$SERVICE_NAME" -n 30 --no-pager >&2; fail "Application did not become ready on $BIND_HOST:$BIND_PORT."; }

step "Configuring Nginx for $DOMAIN"
cat > "/etc/nginx/sites-available/$SERVICE_NAME" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    client_max_body_size 1m;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        proxy_pass http://$BIND_HOST:$BIND_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
    }
}
EOF

ln -sf "/etc/nginx/sites-available/$SERVICE_NAME" "/etc/nginx/sites-enabled/$SERVICE_NAME"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if [[ "$CONFIGURE_FIREWALL" == "yes" ]]; then
    step "Configuring the firewall"
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw allow OpenSSH >/dev/null
    ufw allow 'Nginx Full' >/dev/null
    ufw --force enable >/dev/null
    ufw status verbose | sed 's/^/    /'
fi

if [[ "$ENABLE_TLS" == "yes" ]]; then
    step "Requesting a TLS certificate for $DOMAIN"
    apt-get install -y -qq snapd
    systemctl enable --now snapd.socket
    if snap list core >/dev/null 2>&1; then
        snap refresh core
    else
        snap install core
    fi
    if snap list certbot >/dev/null 2>&1; then
        snap refresh certbot
    else
        snap install certbot --classic
    fi
    certbot_args=(certonly --webroot -w /var/www/letsencrypt --cert-name "$SERVICE_NAME"
        --non-interactive --agree-tos)
    if [[ "$HOST_IS_IP" == "yes" ]]; then
        certbot_args+=(--ip-address "$DOMAIN" --required-profile shortlived)
    else
        certbot_args+=(-d "$DOMAIN")
    fi
    if [[ -n "$EMAIL" ]]; then
        certbot_args+=(--email "$EMAIL")
    else
        certbot_args+=(--register-unsafely-without-email)
    fi
    mkdir -p /var/www/letsencrypt/.well-known/acme-challenge
    chmod 755 /var/www/letsencrypt \
        /var/www/letsencrypt/.well-known \
        /var/www/letsencrypt/.well-known/acme-challenge
    (
        umask 022
        /snap/bin/certbot "${certbot_args[@]}"
    )

    cat > "/etc/nginx/sites-available/$SERVICE_NAME" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$SERVICE_NAME/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$SERVICE_NAME/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 1m;

    location / {
        proxy_pass http://$BIND_HOST:$BIND_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_redirect off;
    }
}
EOF
    mkdir -p /etc/letsencrypt/renewal-hooks/deploy
    printf '#!/bin/sh\nsystemctl reload nginx\n' \
        > "/etc/letsencrypt/renewal-hooks/deploy/$SERVICE_NAME-nginx-reload"
    chmod 755 "/etc/letsencrypt/renewal-hooks/deploy/$SERVICE_NAME-nginx-reload"
    nginx -t && systemctl reload nginx
    SITE_URL="https://$DOMAIN"
else
    SITE_URL="http://$DOMAIN"
fi

step "Verifying"
LISTENERS="$(ss -H -ltn "sport = :$BIND_PORT" | awk '{print $4}')"
[[ -n "$LISTENERS" ]] || fail "Nothing is listening on port $BIND_PORT."
while IFS= read -r listener; do
    [[ "$listener" =~ ^127\.0\.0\.1: || "$listener" =~ ^\[::1\]: ]] \
        || fail "Port $BIND_PORT is exposed on $listener instead of loopback only."
done <<< "$LISTENERS"
echo "    loopback listener(s): $LISTENERS"
curl -fsS -o /dev/null -w '    local check: HTTP %{http_code}\n' --max-time 5 \
    -H "Host: $DOMAIN" "http://$BIND_HOST:$BIND_PORT/login" \
    || fail "Local application check failed."
curl -fsS -o /dev/null -w '    public check: HTTP %{http_code}\n' --max-time 10 "$SITE_URL/login" \
    || fail "Public site check failed at $SITE_URL/login. Check DNS and firewall rules."

cat <<SUMMARY

============================================================
Secure Finance Vault is live.

  URL              $SITE_URL
  Service          systemctl status $SERVICE_NAME
  Logs             journalctl -u $SERVICE_NAME -f
  Application      $APP_DIR
  Configuration    $APP_DIR/.env
  Database         $APP_DIR/instance/finance.db
============================================================
SUMMARY

if [[ -n "$GENERATED_PASSWORD" ]]; then
    cat <<CREDS
First sign-in credentials, shown once:

  Username         admin
  Password         $GENERATED_PASSWORD

Change this password immediately after signing in.
CREDS
else
    echo "Existing .env retained; previous credentials still apply."
fi

cat <<'NEXT'

Back up .env and instance/finance.db together. The database cannot be
decrypted without the DATA_KEY stored in .env.
NEXT
