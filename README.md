# Secure Finance Vault

## Start

```bash
chmod +x setup.sh
./setup.sh
```

Open `http://localhost:5555`.

Initial credentials: `admin` / `ChangeMe-5555!`. The password must be changed after first login.

## Files excluded from version control

A fresh clone contains no secrets, no database, and no virtual environment. The application refuses to start until `.env` exists, and it exits immediately with:

```text
RuntimeError: Missing .env. Start the application with ./setup.sh
```

| Path                                                 | Contents                                                                                   | Created by                | Required before   |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------- | ----------------- |
| `.env`                                               | `SECRET_KEY`, `DATA_KEY`, `DEFAULT_USER`, `DEFAULT_PASSWORD`, optional deployment settings | `setup.sh` or `deploy.sh` | Application start |
| `instance/`                                          | SQLite database directory, mode `700`                                                      | `setup.sh`                | Application start |
| `instance/finance.db`                                | All financial records, mode `600`                                                          | `app.py` on first run     | First login       |
| `instance/finance.db-shm`, `instance/finance.db-wal` | SQLite write-ahead log sidecars                                                            | SQLite at runtime         | Automatic         |
| `.venv/`                                             | Virtual environment and dependencies                                                       | `setup.sh`                | Application start |
| `__pycache__/`, `*.pyc`                              | Byte-compiled Python                                                                       | Python                    | Automatic         |
| `*.log`                                              | Local log output                                                                           | Runtime                   | Automatic         |

`.env` and `instance/finance.db` are a matched pair. `DATA_KEY` encrypts account references inside the database, so a database restored alongside a different `DATA_KEY` cannot be decrypted. Always back up both together. Setup never replaces an existing `.env`; if its required settings are missing or invalid, preserve the file and repair it deliberately rather than generating a new key against an existing database.

## Recreating the ignored files

### Option 1: let setup.sh do everything

`setup.sh` is idempotent and performs every step below. It creates or validates `.venv`, installs requirements with that environment's Python, sets `umask 077`, writes `.env` atomically only if absent, protects `.env` and `instance/`, and starts the application with the same virtual-environment interpreter. An existing `.env` and database are preserved. An incomplete `.venv` is moved aside as `.venv.invalid-<timestamp>` before a new one is created.

```bash
chmod +x setup.sh
./setup.sh
```

An existing `.env` is never overwritten, so it is safe to re-run after a dependency change.

To select a particular Python installation, set `PYTHON_BIN` when starting setup:

```bash
PYTHON_BIN="$(command -v python3)" ./setup.sh
```

If the default port is already in use, choose another one without editing the app:

```bash
BIND_PORT=5556 ./setup.sh
```

Incomplete virtual environments are preserved under `.venv.invalid-<timestamp>`. These backups, virtual environments, secrets, databases, Python caches, and logs are excluded by `.gitignore`.

### Option 2: create each file manually

#### 1. Virtual environment and dependencies

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

#### 2. `.env`

Both keys must be newly generated; never reuse an example value. `DATA_KEY` must be a valid Fernet key, because `app.py` passes it straight to `Fernet()`.

```bash
umask 077
.venv/bin/python - <<'PY'
from pathlib import Path
from cryptography.fernet import Fernet
import secrets
Path('.env').write_text(
    'SECRET_KEY=' + secrets.token_urlsafe(64) + '\n'
    'DATA_KEY=' + Fernet.generate_key().decode() + '\n'
    'DEFAULT_USER=admin\n'
    'DEFAULT_PASSWORD=ChangeMe-5555!\n', encoding='utf-8')
PY
chmod 600 .env
```

The resulting file has this shape, with your own generated values:

```text
SECRET_KEY=<64-byte url-safe token>
DATA_KEY=<44-character Fernet key>
DEFAULT_USER=admin
DEFAULT_PASSWORD=ChangeMe-5555!
```

All four settings are mandatory. A missing one aborts startup with `Missing required setting: <NAME>`. The optional settings `ALLOWED_HOSTS`, `SESSION_COOKIE_SECURE`, `TRUSTED_PROXY_COUNT`, `BIND_HOST`, and `BIND_PORT` default to local-only values and are described under [Deploying on a cloud Linux server](#deploying-on-a-cloud-linux-server). Parsing rules applied by `app.py`:

- One `KEY=value` pair per line; lines beginning with `#` are ignored.
- Values are used literally; do not wrap them in quotes.
- Variables already present in the process environment take precedence over the file.

Choose a different `DEFAULT_PASSWORD` if you prefer. The account is created with a forced-rotation flag, and the application rejects reusing the default value when you set the real password.

#### 3. `instance/` directory

```bash
mkdir -p instance
chmod 700 instance
```

#### 4. `instance/finance.db`

The database is created automatically on the first run. `app.py` executes its schema script, applies in-place column migrations for `liabilities` and `stocks`, inserts the default user with an Argon2id hash, and sets the file to mode `600`.

```bash
.venv/bin/python app.py
```

Then open `http://localhost:5555` and sign in with `DEFAULT_USER` and `DEFAULT_PASSWORD`. You are redirected to the password-change page before any other route is reachable.

### Verify before first use

```bash
ls -l .env instance/finance.db
stat -f '%Sp %N' .env instance instance/finance.db
```

Expected permissions: `-rw-------` for `.env` and `finance.db`, `drwx------` for `instance`.

Confirm no secret or database file is staged for commit:

```bash
git status --short --ignored | grep -E '\.env|instance/|\.venv'
```

Every match must be marked `!!` (ignored), never `A` or `M`.

### Restoring from a backup

Restore `.env` and the database together, with the application stopped:

```bash
cp /secure/backup/.env .env
cp /secure/backup/finance.db instance/finance.db
chmod 600 .env instance/finance.db
```

If the `instance/finance.db-wal` and `instance/finance.db-shm` sidecars exist in the backup, copy them too, or let SQLite recreate them from a cleanly closed database. Restoring a database without its matching `DATA_KEY` leaves encrypted account references unreadable.

## Deploying on a cloud Linux server

The application ships as a localhost-only development server. A public deployment puts Nginx in front of it as a TLS-terminating reverse proxy, runs the app as an unprivileged systemd service bound to `127.0.0.1`, and never exposes port 5555 to the internet.

```text
Browser ──HTTPS 443──> Nginx ──HTTP 127.0.0.1:5555──> Waitress (app.py)
```

Tested on Ubuntu 24.04 LTS. Adjust package commands for other distributions.

### Option 1: one-command provisioning with deploy.sh

`deploy.sh` updates Ubuntu packages and performs the host-side deployment: required system packages, service account, virtual environment, `.env` with freshly generated keys, the systemd unit, Nginx, the firewall, and a TLS certificate. It supports a domain name or a public IPv4 address. DNS (when using a domain) and the cloud provider's network security group must be configured beforehand.

Before running the script with a domain name, point its DNS A record at the server's public IPv4 address. Pass only the hostname to `--domain` (for example `finance.example.com`), not `https://` or a URL path. Also allow inbound SSH (22), HTTP (80), and HTTPS (443) in the cloud provider's network security group/security list. Port 80 is required for Let's Encrypt HTTP-01 issuance and renewal. The script configures UFW, but it cannot configure the provider firewall or subnet route table.

For local-folder deployment, create `/root/secure_finance_app` on the server and place the project files directly inside it. In particular, `app.py`, `requirements.txt`, and `deploy.sh` should be at `/root/secure_finance_app/`, not inside another nested project directory. The script copies that source folder to `/opt/finance/app` by default; use `--app-dir` to choose another runtime install location.

```bash
cd /root/secure_finance_app
sudo ./deploy.sh --domain finance.example.com --email you@example.com
```

This domain-name form uses Let's Encrypt domain validation. The script configures Nginx for the hostname and adds it to `ALLOWED_HOSTS`. If rerun on an existing IP deployment, it preserves `.env` secrets and credentials while adding the new hostname, and enables secure session cookies for TLS.

Alternatively, let the script clone a Git repository URL. The repository root must contain `app.py` and `requirements.txt`; `deploy.sh` itself does not need to come from that repository:

```bash
sudo ./deploy.sh \
    --domain finance.example.com \
    --repo-url https://github.com/your-account/your-repository.git \
    --branch main \
    --email you@example.com
```

Omit `--branch` to use the repository's default branch. For a private repository, configure a deploy key or other Git authentication for the root account running the script. Do not put access tokens or passwords in the repository URL or shell history.

For IP-only access with browser-trusted TLS, pass the server's public IPv4 address instead. Allow inbound ports 80 and 443 in the cloud security group; port 80 is needed for certificate issuance and renewal. IP certificates use a short-lived profile and Certbot renews them automatically, so do not disable its renewal timer.

```bash
sudo ./deploy.sh --domain 203.0.113.10 --email you@example.com
```

Options:

- `--domain <fqdn-or-ipv4>`: Required. Public hostname or IPv4 served over HTTPS.
- `--email <address>`: Contact address for Let's Encrypt registration.
- `--repo-url <url>`: Clone source from a Git repository instead of using files beside `deploy.sh`.
- `--branch <name>`: Branch to clone; requires `--repo-url`, otherwise the default branch is used.
- `--no-tls`: Skip certbot and serve plain HTTP on port 80.
- `--no-firewall`: Skip UFW configuration.
- `--port <number>`: Loopback port for the application, default 5555.
- `--app-dir <path>`: Install location, default `/opt/finance/app`.

On success the script prints the site URL and a randomly generated first-login password, shown once. Sign in as `admin` and change it immediately.

The script is idempotent. Re-running it upgrades dependencies and rewrites the service and Nginx configuration, but never overwrites an existing `.env` or database. To publish code changes, either copy updated project files directly into `/root/secure_finance_app` and rerun `sudo ./deploy.sh --domain <your-domain-or-public-ip>`, or rerun with `--repo-url <git-url>` and optionally `--branch <name>`. Both modes copy the source to `/opt/finance/app` and restart the service. The base template versions the stylesheet URL to avoid stale browser CSS; the template itself still requires redeployment.

### Deployment troubleshooting

#### IP-address TLS validation

For browser-trusted TLS using a public IPv4 address, use the one-command `deploy.sh` flow. It requests a short-lived IP certificate with Certbot's `shortlived` profile. Keep Certbot's renewal timer enabled and allow public inbound TCP 80 and 443 in the cloud firewall; TCP 22 is needed for SSH. A domain-based certificate requires the domain's A record to point at the server.

Test the challenge webroot locally and from a different machine before retrying Certbot:

```bash
sudo install -d -m 755 /var/www/letsencrypt/.well-known/acme-challenge
printf 'probe\n' | sudo tee /var/www/letsencrypt/.well-known/acme-challenge/probe >/dev/null
sudo chmod 644 /var/www/letsencrypt/.well-known/acme-challenge/probe
curl -i -H 'Host: 203.0.113.10' http://127.0.0.1/.well-known/acme-challenge/probe
curl -i http://203.0.113.10/.well-known/acme-challenge/probe
```

Replace `203.0.113.10` with the server's public IP. Both requests must return `200` and `probe`. A local `403` means Nginx cannot read or traverse the challenge path; the current `deploy.sh` sets those permissions and runs Certbot with a webroot-specific `umask 022`. If local access succeeds but external access cannot connect, inspect the cloud ingress rules, public subnet route to an Internet Gateway, and host packet-filter rules. `ufw status` alone may not show an earlier firewall rule that takes precedence.

On Ubuntu cloud images, inspect packet arrival and INPUT rule ordering with:

```bash
sudo tcpdump -nni any 'tcp port 80'
sudo iptables -nvL INPUT --line-numbers
```

If a catch-all `REJECT` appears before the UFW rules, UFW's later port-80 allow does not take effect. In the observed OCI image, the early reject followed the SSH allow; after confirming that same ordering, these temporary runtime rules allowed the ACME request and HTTPS traffic:

```bash
sudo iptables -I INPUT 5 -p tcp --dport 80 -m conntrack --ctstate NEW -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -m conntrack --ctstate NEW -j ACCEPT
```

These rules do not survive reboot. Correct the persistent firewall configuration that installs the early reject; do not save rules blindly if another firewall manager owns them. A TCP SYN visible in `tcpdump` without a SYN-ACK indicates the block is at the host firewall; no SYN indicates an upstream network rule or route problem.

### Configuration used by a public deployment

Four settings in `.env` switch the application from local-only to server mode. `deploy.sh` writes them for you; set them by hand if you deploy manually.

| Setting                  | Local default         | Server value | Purpose                                              |
| ------------------------ | --------------------- | ------------ | ---------------------------------------------------- |
| `ALLOWED_HOSTS`          | `localhost,127.0.0.1` | your domain  | `security_gate` returns HTTP 400 for any other host  |
| `SESSION_COOKIE_SECURE`  | `false`               | `true`       | Restricts the session cookie to HTTPS                |
| `TRUSTED_PROXY_COUNT`    | `0`                   | `1`          | Number of proxies whose `X-Forwarded-For` is trusted |
| `BIND_HOST`, `BIND_PORT` | `127.0.0.1`, `5555`   | unchanged    | Loopback bind address for Waitress                   |

`TRUSTED_PROXY_COUNT` matters for security. Login throttling, account lockout, and the audit log all record `request.remote_addr`. Behind Nginx, every request would otherwise appear to come from `127.0.0.1`, letting a single attacker exhaust the shared rate limit and making audit entries useless. Set it to the exact number of proxies you control; a larger value lets clients spoof their address through a forged header.

### Option 2: manual provisioning

#### 1. Provision and harden the server

Create a small VM (1 vCPU, 1 GB RAM is sufficient) and keep SSH key-only.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip nginx git ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Port 5555 is deliberately absent; the app is reachable only through Nginx. In your cloud provider's network security group, allow **22**, **80**, and **443**; port 80 is required by the HTTP-01 certificate challenge.

#### 2. Create a dedicated service account

Never run the application as root or as your login user.

```bash
sudo useradd --system --create-home --home-dir /opt/finance --shell /usr/sbin/nologin finance
sudo -u finance git clone <your-repository-url> /opt/finance/app
```

#### 3. Install dependencies

```bash
sudo -u finance python3 -m venv /opt/finance/app/.venv
sudo -u finance /opt/finance/app/.venv/bin/pip install --upgrade pip
sudo -u finance /opt/finance/app/.venv/bin/pip install -r /opt/finance/app/requirements.txt
```

#### 4. Create `.env` and the database

Generate fresh keys on the server. Do not copy development keys into production.

```bash
cd /opt/finance/app
sudo -u finance bash -c 'umask 077; .venv/bin/python - <<PY
from pathlib import Path
from cryptography.fernet import Fernet
import secrets
Path(".env").write_text(
    "SECRET_KEY=" + secrets.token_urlsafe(64) + "\n"
    "DATA_KEY=" + Fernet.generate_key().decode() + "\n"
    "DEFAULT_USER=admin\n"
    "DEFAULT_PASSWORD=" + secrets.token_urlsafe(18) + "\n"
    "ALLOWED_HOSTS=finance.example.com\n"
    "SESSION_COOKIE_SECURE=true\n"
    "TRUSTED_PROXY_COUNT=1\n", encoding="utf-8")
PY'
sudo -u finance mkdir -p instance
sudo chmod 700 /opt/finance/app/instance
sudo chmod 600 /opt/finance/app/.env
```

Read the generated default password once, then sign in and change it:

```bash
sudo grep DEFAULT_PASSWORD /opt/finance/app/.env
```

#### 5. Create the systemd service

```bash
sudo tee /etc/systemd/system/finance.service >/dev/null <<'EOF'
[Unit]
Description=Secure Finance Vault
After=network-online.target
Wants=network-online.target

[Service]
User=finance
Group=finance
WorkingDirectory=/opt/finance/app
ExecStart=/opt/finance/app/.venv/bin/python app.py
Restart=on-failure
RestartSec=5
UMask=0077

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/finance/app/instance
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

sudo systemctl daemon-reload
sudo systemctl enable --now finance
sudo systemctl status finance --no-pager
```

`ProtectSystem=strict` makes the whole filesystem read-only except `ReadWritePaths`, so the service can write only its SQLite database. The `app.py` entrypoint already calls `init_db()` and binds Waitress to `127.0.0.1:5555`.

#### 6. Configure Nginx

```bash
sudo tee /etc/nginx/sites-available/finance >/dev/null <<'EOF'
server {
    listen 80;
    server_name finance.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name finance.example.com;

    # Certificate paths are filled in by certbot.
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:5555;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/finance /etc/nginx/sites-enabled/finance
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

`proxy_set_header Host $host` is what makes the `ALLOWED_HOSTS` check see your real domain. `client_max_body_size 1m` complements the application's own `MAX_CONTENT_LENGTH` of 256 KB.

The application already sends its own CSP, `X-Frame-Options`, `Referrer-Policy`, and `Cache-Control: no-store` headers, so do not duplicate them in Nginx. HSTS is added here because it belongs at the TLS edge.

#### 7. Issue a TLS certificate

Point an A record at the server's public IP first, then:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d finance.example.com
sudo systemctl list-timers | grep certbot
```

Certbot rewrites the server block with the certificate paths and installs a renewal timer.

### 8. Verify the deployment

```bash
curl -I https://finance.example.com/login
sudo ss -tlnp | grep 5555
```

Expect a `302` or `200` from the first command, and the second must show `127.0.0.1:5555` only, never `0.0.0.0:5555`. Confirm the session cookie is hardened:

```bash
curl -sI https://finance.example.com/login | grep -i set-cookie
```

It must include `Secure`, `HttpOnly`, and `SameSite=Strict`. From another machine, `curl http://<server-ip>:5555` must fail to connect.

### 9. Operate

```bash
sudo systemctl restart finance
sudo journalctl -u finance -f
```

Back up `.env` and the database together, with the service stopped so SQLite's WAL is checkpointed:

```bash
sudo systemctl stop finance
sudo tar czf /root/finance-$(date +%F).tar.gz -C /opt/finance/app .env instance/finance.db
sudo systemctl start finance
```

Store backups off the server and encrypted. Anyone holding `.env` and the database has full access to your financial records.

To deploy updates:

```bash
cd /opt/finance/app
sudo -u finance git pull
sudo -u finance .venv/bin/pip install -r requirements.txt
sudo systemctl restart finance
```

Or re-run the provisioning script from an updated working copy, which keeps `.env` and the database intact:

```bash
sudo ./deploy.sh --domain finance.example.com
```

### Deployment limitations

- SQLite with a single Waitress process suits one user. Do not scale to multiple instances against the same database file.
- `Flask-Limiter` uses in-memory storage, so rate limits reset on restart and are not shared across processes.
- There is no built-in multi-tenancy; every account sees the same data set.
- Keep the server patched and restrict SSH to keys and known source addresses.

## Included

- Bank accounts with Account Number, Name of the Bank, Current Balance, and Last Updated Date
- Fixed and recurring deposits
- Indian and US stocks
- Mutual funds, metals, ESOPs, and other investments
- Liabilities
- Transactions
- Per-currency net worth dashboard
- Asset allocation and recent income-versus-expense charts
- Responsive colorful interface, hover effects, subtle gradient background, and favicon
- Separate HTML templates, CSS, and JavaScript files
- SQLite persistence

## Security

Argon2id password hashing, CSRF protection, login throttling and lockout, parameterized SQL, encrypted account references, forced default-password rotation, strict host validation, secure response headers, idle session expiration, request limits, audit logging, and localhost-only Waitress binding.

Back up `.env` together with `instance/finance.db`; neither is usable without the other. Existing databases from earlier prototypes should be backed up before copying them into this package. See [Files excluded from version control](#files-excluded-from-version-control) for what a fresh clone is missing and how to recreate it.
