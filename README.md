# Secure Finance Vault

A single-user personal finance dashboard: bank accounts, fixed and recurring
deposits, Indian and US stocks, mutual funds, metals, ESOPs, retirals,
liabilities, transactions, and monthly budgets — persisted to a local SQLite
file, with a per-currency net-worth dashboard, allocation charts, cashflow
trends, and a budget tracker.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

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
mkdir -p instance
chmod 700 instance

.venv/bin/python app.py
```

Then open `http://localhost:5555` and sign in with `admin` / `ChangeMe-5555!`.

On startup the app prints a banner with the resolved database path and
credentials:

```text
Finance Vault: http://127.0.0.1:5555
Database     : /path/to/project/instance/finance.db
============================================================
  DEFAULT SIGN-IN CREDENTIALS
============================================================
  Username         admin
  Password         ChangeMe-5555!
  Status           must be changed on first login
============================================================
```

The first user is created automatically when the database is initialized from
`DEFAULT_USER` and `DEFAULT_PASSWORD` in `.env`. The account is forced to
change its password on first login.

## Start

```bash
chmod +x setup.sh
./setup.sh
```

Open `http://localhost:5555`. Initial credentials: `admin` / `ChangeMe-5555!`.

## Files excluded from version control

A fresh clone contains no secrets, no database, and no virtual environment.
The application refuses to start until `.env` exists:

```text
RuntimeError: Missing .env. Start the application with ./setup.sh
```

| Path                    | Contents                                                                                   | Created by            |
| ----------------------- | ------------------------------------------------------------------------------------------ | --------------------- |
| `.env`                  | `SECRET_KEY`, `DATA_KEY`, `DEFAULT_USER`, `DEFAULT_PASSWORD`, optional deployment settings | `setup.sh`            |
| `instance/`             | SQLite database directory, mode `700`                                                      | `setup.sh`            |
| `instance/finance.db`   | All financial records, mode `600`                                                          | `app.py` on first run |
| `instance/finance.db-*` | SQLite WAL sidecars                                                                        | SQLite at runtime     |
| `.venv/`                | Virtual environment                                                                        | `setup.sh`            |
| `__pycache__/`, `*.pyc` | Byte-compiled Python                                                                       | Python                |
| `*.log`                 | Local log output                                                                           | Runtime               |

`.env` and `instance/finance.db` are a matched pair. `DATA_KEY` encrypts
account references inside the database, so a database restored alongside a
different `DATA_KEY` cannot be decrypted. Always back up both together.

## Recreating the ignored files

### Option 1: let setup.sh do everything

`setup.sh` is idempotent. It creates or validates `.venv`, installs
requirements, sets `umask 077`, writes `.env` atomically only if absent,
protects `.env` and `instance/`, and starts the application. An existing
`.env` and database are preserved.

```bash
chmod +x setup.sh
./setup.sh
```

To select a Python installation:

```bash
PYTHON_BIN="$(command -v python3)" ./setup.sh
```

To change the port:

```bash
BIND_PORT=5556 ./setup.sh
```

### Option 2: create each file manually

#### 1. Virtual environment and dependencies

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

#### 2. `.env`

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

All four settings are mandatory. Optional settings `ALLOWED_HOSTS`,
`SESSION_COOKIE_SECURE`, `TRUSTED_PROXY_COUNT`, `BIND_HOST`, and `BIND_PORT`
default to local-only values and are described in the deployment section.

#### 3. `instance/` directory and database

```bash
mkdir -p instance
chmod 700 instance
.venv/bin/python app.py
```

The database is created on first run. Open `http://localhost:5555` and sign
in with `DEFAULT_USER` and `DEFAULT_PASSWORD`. You are redirected to the
password-change page before any other route is reachable.

### Verify before first use

```bash
ls -l .env instance/finance.db
git status --short --ignored | grep -E '\.env|instance/|\.venv'
```

Expected: `-rw-------` for `.env` and `finance.db`, `drwx------` for
`instance`. All matches from `git status` must be marked `!!`, never `A`.

### Restoring from a backup

Restore `.env` and the database together, with the application stopped:

```bash
cp /secure/backup/.env .env
cp /secure/backup/finance.db instance/finance.db
chmod 600 .env instance/finance.db
```

## Features

- **Bank Accounts** — balances, rate, and per-currency totals.
- **Fixed Deposits** — principal, rate, tenure, interest earned, and an
  approximate maturity amount. Computed server-side with quarterly
  compounding, the Indian banking default.
- **Recurring Deposits** — monthly contribution, tenure, interest, and
  approximate maturity using the ordinary-annuity-due future value with
  monthly compounding.
- **Stocks** — split into US and Indian sections with market-specific
  fields:
  - **US positions** track Name, Ticker, Total Amount Invested (USD),
    Current Value (USD), and derived Investment Returns (USD and %).
  - **Indian positions** track Stock Symbol, Company Name, ISIN Code, Qty,
    Average Cost Price, Current Market Price, Value At Cost, Value At Market
    Price, Realized P&L, Unrealized P&L, and Unrealized P&L %.
  - Both markets support sale tracking, GST, brokerage, STT, exchange fees,
    and optional partial sales. Every underlying lot is editable from the
    Transaction Lots table.
- **Mutual Funds** — fund house, category, SIP or lump-sum mode, invested vs.
  current value, per-currency summary.
- **Metals** — gold, silver, and others with weight, purity, mint, and
  invested vs. current value.
- **ESOPs** — grants with vesting dates, current price, unrealised P&L, and
  per-grant editing.
- **Retirals** — EPF, PPF, NPS, Superannuation, and other retirement pots.
- **Liabilities** — lender, type, status, EMI, repayment schedule, and
  outstanding percentage.
- **Transactions** — income, expense, transfer, investment, and
  liability-payment entries, feeding the cashflow chart.
- **Budgets** — monthly spending limits per category with progress bars, a
  month selector, and a dashboard Budget Status panel.
- **Dashboard** — per-currency net worth, separate Bank Balance cards, asset
  allocation, assets vs. liabilities, liability breakdown, metals breakdown,
  budget usage, and quick-access tiles.
- **Administration** — user CRUD and an application-health page showing
  database size, record counts, audit log, and server log.
- **Profile** — username, role, status, creation date, last login, and a
  change-password entry point.

### Fixed and recurring deposit maturity math

Both listings compute tenure, interest, and approximate maturity server-side
in `app.py` via `_fd_metrics()` and `_rd_metrics()`.

**Fixed deposits** use quarterly compounding:

```
A = P × (1 + r/4)^(4·t)
```

**Recurring deposits** use the ordinary-annuity-due future value with monthly
compounding:

```
M = P × (((1+i)^n − 1) / i) × (1+i)
```

Both values are labelled **approx.** — actual bank figures can differ by
0.5–2 % depending on the institution's day-count convention. The edit forms
show a live preview that mirrors the server-side formula exactly.

## Deploying on Oracle Cloud

Oracle Cloud Infrastructure (OCI) offers an **Always Free** tier that
includes the `VM.Standard.E2.1.Micro` shape (1/8 OCPU, 1 GB RAM) running
Ubuntu, and the ARM-based `VM.Standard.A1.Flex` shape (up to 4 OCPUs, 24 GB
RAM). Either is more than enough for this single-user app.

### Overview

```text
Browser ──HTTPS 443──> Nginx ──HTTP 127.0.0.1:5555──> Waitress (app.py)
```

Nginx terminates TLS on the public side. The Flask app binds to loopback only
and is never reachable directly from the internet.

### Step 1 — Create the Oracle Cloud account and a compartment

1. Sign up at `https://cloud.oracle.com`. A credit card is required for
   identity verification, but Always Free resources will not be charged.
2. In the OCI Console, navigate to
   **Identity & Security → Identity → Compartments**.
3. Click **Create Compartment**. Name it e.g. `finance`, set parent to your
   root tenancy, and click **Create Compartment**.

### Step 2 — Create the Ubuntu VM

1. Go to **Compute → Instances → Create instance**.
2. **Name:** e.g. `finance-server`.
3. **Compartment:** the one you just created.
4. **Image:** click **Change image** and select **Canonical Ubuntu 22.04** or
   **24.04**. Confirm the **Always Free** badge.
5. **Shape:** select `VM.Standard.E2.1.Micro` (Always Free AMD) or
   `VM.Standard.A1.Flex` (Always Free ARM) if available in your region.
6. **Networking:** leave the default "Create new virtual cloud network" — OCI
   provisions a VCN, public subnet, internet gateway, and route table for
   you.
7. **Add SSH keys:** select **Generate a key pair for me** and download the
   private key. You will need it to connect.
8. Click **Create**. Wait for the instance state to read **Running**.
9. On the instance page, copy the **Public IP address** under
   **Instance access**.

### Step 3 — Open the required ports in the Security List

By default, OCI allows only SSH inbound. HTTP and HTTPS must be opened
explicitly.

1. Go to **Networking → Virtual Cloud Networks** and click the VCN created
   with your instance.
2. Under **Resources**, click **Security Lists**, then the default security
   list.
3. Click **Add Ingress Rules** and add three rules with **Source Type: CIDR**
   and **Source CIDR: `0.0.0.0/0`**:

   | Stateless | IP Protocol | Destination Port | Description |
   | --------- | ----------- | ---------------- | ----------- |
   | No        | TCP         | `22`             | SSH         |
   | No        | TCP         | `80`             | HTTP        |
   | No        | TCP         | `443`            | HTTPS       |

   Port 80 is required for Let's Encrypt HTTP-01 issuance and renewal. Port
   443 serves the encrypted site.

4. Click **Add Ingress Rules**.

### Step 4 — Connect to the instance

From your local machine:

```bash
chmod 400 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<YOUR_INSTANCE_PUBLIC_IP>
```

The default user on an Ubuntu OCI image is `ubuntu`.

### Step 5 — Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip nginx git certbot python3-certbot-nginx ufw fail2ban
```

This installs Python, Nginx, Certbot, UFW, and Fail2ban.

### Step 6 — Clone the repository and set up the app

```bash
sudo mkdir -p /opt/finance
sudo chown ubuntu:ubuntu /opt/finance
git clone <YOUR_GITHUB_REPO_URL> /opt/finance/app
cd /opt/finance/app

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Generate the `.env` with fresh secrets. **Do not copy development keys into
production:**

```bash
python3 - <<'PY'
from pathlib import Path
from cryptography.fernet import Fernet
import secrets
Path('.env').write_text(
    'SECRET_KEY=' + secrets.token_urlsafe(64) + '\n'
    'DATA_KEY=' + Fernet.generate_key().decode() + '\n'
    'DEFAULT_USER=admin\n'
    'DEFAULT_PASSWORD=' + secrets.token_urlsafe(18) + '\n'
    'ALLOWED_HOSTS=yourdomain.duckdns.org\n'
    'SESSION_COOKIE_SECURE=true\n'
    'TRUSTED_PROXY_COUNT=1\n'
    'BIND_HOST=127.0.0.1\n'
    'BIND_PORT=5555\n', encoding='utf-8')
PY
chmod 600 .env
```

Replace `yourdomain.duckdns.org` with your actual domain (from Step 10). If
you want to test with the IP first, set `ALLOWED_HOSTS=<PUBLIC_IP>` and
`SESSION_COOKIE_SECURE=false` temporarily.

Read the generated password once:

```bash
grep '^DEFAULT_PASSWORD=' .env
```

### Step 7 — Create the systemd service

```bash
sudo tee /etc/systemd/system/finance.service >/dev/null <<'EOF'
[Unit]
Description=Secure Finance Vault
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
Group=ubuntu
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

Check the startup banner for credentials and DB path:

```bash
sudo journalctl -u finance -n 40 --no-pager
```

### Step 8 — Configure Nginx as a reverse proxy

```bash
sudo tee /etc/nginx/sites-available/finance >/dev/null <<'EOF'
server {
    listen 80;
    server_name yourdomain.duckdns.org;

    client_max_body_size 1m;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

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
sudo mkdir -p /var/www/letsencrypt
sudo nginx -t && sudo systemctl reload nginx
```

### Step 9 — Configure the host firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
sudo ufw status verbose
```

Do not open port 5555. The app is reachable only through Nginx on loopback.

### Step 10 — Point a free domain at the server

Let's Encrypt only issues certificates for domain names (IP certificates use
a separate 6-day profile that is fragile for production). The simplest free
option is **DuckDNS**.

1. Go to `https://www.duckdns.org` and sign in with Google, GitHub, or X.
2. In the **sub domain** field, enter a unique name (e.g. `myfinance`). Your
   domain becomes `myfinance.duckdns.org`.
3. In the **current ip** field, paste your OCI instance's public IP.
4. Click **update ip**.
5. Copy your **token** from the DuckDNS dashboard in case you want automatic
   IP updates later.
6. Verify from your local machine:

   ```bash
   nslookup myfinance.duckdns.org
   ```

   It should return your OCI public IP.

7. Update `.env` on the server so `ALLOWED_HOSTS` matches:

   ```bash
   sed -i 's/^ALLOWED_HOSTS=.*/ALLOWED_HOSTS=myfinance.duckdns.org/' /opt/finance/app/.env
   sudo systemctl restart finance
   ```

8. Update the Nginx config:

   ```bash
   sudo sed -i 's/yourdomain.duckdns.org/myfinance.duckdns.org/g' /etc/nginx/sites-available/finance
   sudo nginx -t && sudo systemctl reload nginx
   ```

**Optional — automatic IP updates.** OCI instances keep their public IP for
the lifetime of the instance unless released, so frequent updates are rarely
needed. If you want one anyway, add a cron job on the server:

```bash
(crontab -l 2>/dev/null; echo '*/5 * * * * curl -s "https://www.duckdns.org/update?domains=myfinance&token=YOUR-TOKEN&ip=" > /dev/null') | crontab -
```

**Other free domain options:**

- **sslip.io** or **nip.io** — zero configuration. If your IP is
  `203.0.113.10`, you can immediately access the site at
  `https://203.0.113.10.sslip.io` without any signup or DNS records.
- **DigitalPlat** — free domains with TLDs like `.dpdns.org` or `.qzz.io`.
  Register the domain, point it at Cloudflare for DNS management, and get a
  free SSL certificate through Cloudflare's free plan.
- **Cloudflare + any registrar** — if you own a domain (from Namecheap,
  Porkbun, etc.), move its nameservers to Cloudflare, then create an **A
  record** pointing the subdomain at your OCI public IP. Cloudflare's free
  plan includes DNS management, DDoS protection, and a free SSL certificate.

### Step 11 — Obtain a free TLS certificate

With the domain resolving to your server, Certbot can complete the HTTP-01
challenge:

```bash
sudo certbot --nginx -d myfinance.duckdns.org \
    --non-interactive --agree-tos -m you@example.com --redirect
```

Certbot rewrites the Nginx server block with the certificate paths and adds
an HTTPS redirect. Verify the renewal timer:

```bash
systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

### Step 12 — Verify the deployment

```bash
# Public site should return 200 or 302
curl -I https://myfinance.duckdns.org/login

# App should only be listening on loopback
sudo ss -tlnp | grep 5555

# Session cookie must be hardened
curl -sI https://myfinance.duckdns.org/login | grep -i set-cookie
```

The `set-cookie` line must include `Secure`, `HttpOnly`, and
`SameSite=Strict`. From another machine, `curl http://<public-ip>:5555` must
fail to connect.

Visit `https://myfinance.duckdns.org` and sign in with the password from
Step 6. You will be prompted to change it on first login.

### Operating the deployment

```bash
# Restart the app
sudo systemctl restart finance

# Follow the application log
sudo journalctl -u finance -f

# Reload Nginx after config changes
sudo nginx -t && sudo systemctl reload nginx

# Deploy code updates
cd /opt/finance/app
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart finance
```

### Backing up

Back up `.env` and the database together, with the service stopped so SQLite
checkpoints its WAL:

```bash
sudo systemctl stop finance
sudo tar czf ~/finance-$(date +%F).tar.gz -C /opt/finance/app .env instance/finance.db
sudo systemctl start finance
```

Store backups off the server and encrypted. Anyone holding `.env` and the
database has full access to your financial records.

### Deployment troubleshooting

**Site unreachable after opening ports.** OCI's Security List is only half
the firewall. Confirm UFW is not blocking:

```bash
sudo ufw status verbose
```

If the app is not listening on `127.0.0.1:5555`, check
`sudo journalctl -u finance -n 60 --no-pager`.

**Certbot fails the HTTP-01 challenge.** Test the webroot locally and from
another machine:

```bash
sudo mkdir -p /var/www/letsencrypt/.well-known/acme-challenge
printf 'probe\n' | sudo tee /var/www/letsencrypt/.well-known/acme-challenge/probe
sudo chmod -R 755 /var/www/letsencrypt

curl -i -H 'Host: myfinance.duckdns.org' http://127.0.0.1/.well-known/acme-challenge/probe
curl -i http://myfinance.duckdns.org/.well-known/acme-challenge/probe
```

Both must return `200` and `probe`. A local `403` means Nginx cannot read the
challenge directory — verify permissions. A remote timeout means the Security
List or UFW is still blocking port 80.

**`ALLOWED_HOSTS` errors (HTTP 400).** Confirm the domain in `.env` matches
what the browser is sending:

```bash
grep '^ALLOWED_HOSTS=' /opt/finance/app/.env
```

If you changed the domain, update `.env`, restart the service, and reload
Nginx.

**"Account is locked" or "Invalid username or password".** Five failed login
attempts lock the account for 15 minutes. Clear the lock directly:

```bash
sqlite3 /opt/finance/app/instance/finance.db \
  "UPDATE users SET failed=0, locked_until=NULL WHERE username='admin';"
```

**Stale browser cache after CSS changes.** The `base.html` template links
the stylesheet with a version query parameter. Bump it in the template and
push the update.

**IP-address certificates.** Let's Encrypt now issues certificates for bare
IP addresses using the `shortlived` profile (valid for 160 hours).
Use `--preferred-profile shortlived` combined with `--ip-address <ip>` in
Certbot. This is useful for testing without a domain, but for a persistent
deployment a real domain is strongly preferred.

### Configuration used by a public deployment

Four settings in `.env` switch the application from local-only to server
mode.

| Setting                  | Local default         | Server value | Purpose                                              |
| ------------------------ | --------------------- | ------------ | ---------------------------------------------------- |
| `ALLOWED_HOSTS`          | `localhost,127.0.0.1` | your domain  | `security_gate` returns HTTP 400 for any other host  |
| `SESSION_COOKIE_SECURE`  | `false`               | `true`       | Restricts the session cookie to HTTPS                |
| `TRUSTED_PROXY_COUNT`    | `0`                   | `1`          | Number of proxies whose `X-Forwarded-For` is trusted |
| `BIND_HOST`, `BIND_PORT` | `127.0.0.1`, `5555`   | unchanged    | Loopback bind address for Waitress                   |

`TRUSTED_PROXY_COUNT` matters for security. Login throttling, account
lockout, and the audit log all record `request.remote_addr`. Behind Nginx,
every request would otherwise appear to come from `127.0.0.1`. Set it to the
exact number of proxies you control.

### Deployment limitations

- SQLite with a single Waitress process suits one user. Do not scale to
  multiple instances against the same database file.
- `Flask-Limiter` uses in-memory storage, so rate limits reset on restart.
- There is no built-in multi-tenancy; every account sees the same data set.
- Keep the server patched and restrict SSH to keys and known source
  addresses.

## Project layout

```text
.
├── app.py                       Application entry point, all routes
├── admin_routes.py              Admin blueprint (user CRUD, health page)
├── requirements.txt
├── setup.sh                     Local dev bootstrap
├── deploy.sh                    Ubuntu host-side provisioning
├── templates/
│   ├── base.html                Shared shell (sidebar, topbar, footer)
│   ├── _summary_card.html       Shared macro for section summary cards
│   ├── dashboard.html
│   ├── bank_accounts.html / bank_account_edit.html
│   ├── fixed_deposits.html / fixed_deposit_edit.html
│   ├── recurring_deposits.html / recurring_deposit_edit.html
│   ├── stocks.html / stock_edit.html
│   ├── esops.html / esop_edit.html
│   ├── mutual_funds.html / mutual_fund_edit.html
│   ├── metals.html / metal_edit.html
│   ├── liabilities.html / liability_edit.html
│   ├── retirals.html / retiral_edit.html
│   ├── budgets.html / budget_edit.html
│   ├── admin.html / admin_health.html
│   ├── user_profile.html
│   ├── login.html / change_password.html
│   └── error.html
└── static/
    ├── style.css                Global theme and layout
    ├── admin.css                Admin + health page styles
    ├── portfolio_summary.css    Section summary cards and tables
    ├── record_actions.css       Edit/Delete button styles
    ├── budgets.css              Budget tracker styles
    ├── liabilities.css / metals.css / profile.css
    ├── dashboard_charts.css / fixed_deposit.css
    ├── app.js / admin.js / charts.js
    ├── stock_edit.js            Market toggle + live stock calculations
    ├── form.js / esops.js / mutual_funds.js
    ├── metals.js / recurring_deposits.js / retirals.js
    ├── liabilities.js
    └── favicon.svg
```

## Security

Argon2id password hashing, CSRF protection, login throttling and lockout,
parameterized SQL, encrypted account references, forced default-password
rotation, strict host validation, secure response headers, idle session
expiration, request limits, audit logging, and localhost-only Waitress
binding.

On the server side, the deployment guide configures:

- Security List ingress restricted to TCP 22, 80, and 443 only.
- UFW denying all inbound except SSH and Nginx Full.
- systemd hardening (`NoNewPrivileges`, `ProtectSystem=strict`,
  `PrivateTmp`, `MemoryDenyWriteExecute`).
- Fail2ban for SSH brute-force protection.
- Let's Encrypt TLS with automatic renewal.

Back up `.env` together with `instance/finance.db`; neither is usable without
the other.

## License

This project is provided as-is for personal use.
