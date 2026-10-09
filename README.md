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

   **Important:** the port belongs in the **Destination Port Range** field,
   not in the Source Port Range. Port 80 is required for Let's Encrypt
   HTTP-01 issuance and renewal. Port 443 serves the encrypted site.

4. Click **Add Ingress Rules**.

> **Warning — Oracle's hidden iptables firewall.** Opening ports in the
> Security List is **only half the job**. Oracle's Ubuntu images ship with a
> default `iptables` rule that rejects all inbound traffic except SSH,
> regardless of the Security List. If you skip Step 5.5 below, ports 80 and
> 443 will be blocked at the operating-system level even though the Security
> List shows them as open.

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
sudo apt install -y python3-venv python3-pip nginx git certbot python3-certbot-nginx fail2ban
```

This installs Python, Nginx, Certbot, and Fail2ban. **UFW is deliberately
omitted** from this list — see Step 5.5 for why.

### Step 5.5 — Fix Oracle's hidden iptables firewall

This step is mandatory on Oracle Cloud. Without it, the Certbot HTTP-01
challenge in Step 11 will fail with:

```text
Hint: The Certificate Authority failed to verify the temporary nginx
configuration changes made by Certbot. Ensure the listed domains point to
this nginx server and that it is accessible from the internet.
Some challenges have failed.
```

#### 5.5.1 — Confirm the block is at the host firewall

```bash
sudo iptables -L INPUT -n --line-numbers
```

Look for a `REJECT` rule that appears **before** any rule allowing port 80:

```
5    REJECT     all  --  0.0.0.0/0            0.0.0.0/0            reject-with icmp-host-prohibited
```

If that `REJECT` line appears earlier in the list than any `ACCEPT` rule for
port 80, ports 80 and 443 are being dropped at the OS level. This is what
blocks both web traffic and the Let's Encrypt challenge.

#### 5.5.2 — Insert accept rules above the reject

```bash
sudo iptables -I INPUT 5 -p tcp --dport 80 -m state --state NEW -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -m state --state NEW -j ACCEPT
```

The numbers `5` and `6` are rule positions. Adjust them so the two `ACCEPT`
rules end up **above** the `REJECT`. Re-run
`sudo iptables -L INPUT -n --line-numbers` to confirm the ordering:

```
1    ACCEPT     all  --  lo
2    ACCEPT     all  --  0.0.0.0/0  state RELATED,ESTABLISHED
3    ACCEPT     tcp  --  0.0.0.0/0  tcp dpt:22
4    ACCEPT     icmp --  0.0.0.0/0
5    ACCEPT     tcp  --  0.0.0.0/0  tcp dpt:80  state NEW   <-- added
6    ACCEPT     tcp  --  0.0.0.0/0  tcp dpt:443 state NEW   <-- added
7    REJECT     all  --  0.0.0.0/0  reject-with icmp-host-prohibited
```

#### 5.5.3 — Make the rules persistent across reboots

By default, `iptables` rules are lost on reboot. Save them:

```bash
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

The install prompts twice — answer **Yes** to both prompts (save current IPv4
rules and IPv6 rules).

#### 5.5.4 — Optional: skip UFW entirely

Oracle Cloud's Security List plus iptables is a complete two-layer firewall.
Installing UFW adds a third layer that can conflict with the pre-existing
iptables rules. The README deliberately does **not** install UFW, because:

- The `REJECT` rule is inserted by Oracle's image, not by UFW.
- Adding UFW rules does not remove the `REJECT`, so UFW appears to be
  misconfigured when it is actually iptables doing the blocking.
- Fewer moving parts mean fewer failure modes.

If UFW is not installed and you run `sudo ufw status verbose`, you will see:

```text
sudo: ufw: command not found
```

That is expected and harmless. Skip straight to the iptables fix above.

If you prefer UFW anyway, install it and then **verify iptables ordering
afterwards**:

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# Then check that iptables ACCEPT rules for 80/443 come before any REJECT
sudo iptables -L INPUT -n --line-numbers
```

If the `REJECT` still precedes UFW's rules, apply the manual iptables
insertion from 5.5.2 on top.

### Step 6 — Clone the repository and set up the app

Create the target directory and give the `ubuntu` user ownership:

```bash
sudo mkdir -p /opt/finance
sudo chown ubuntu:ubuntu /opt/finance
```

Then choose **one** of the two authentication methods below. GitHub
permanently removed password authentication for Git operations in August
2021, so the plain `git clone https://github.com/...` command will fail with
`remote: Invalid username or token. Password authentication is not supported
for Git operations.` unless you use a Personal Access Token or a Deploy Key.

#### Method A — Personal Access Token (quickest)

Generate a token on GitHub:

1. Sign in at `https://github.com`.
2. Go to **Settings → Developer settings → Personal access tokens →
   Tokens (classic)**.
3. Click **Generate new token (classic)**.
4. Give it a name, e.g. `oracle-server-deploy`, and set an expiration
   (90 days is a reasonable balance).
5. Under **Scopes**, check **`repo`** (required for private repositories).
6. Click **Generate token** and copy the value — it is shown only once.

Clone using the token embedded in the URL:

```bash
git clone https://<GITHUB_USERNAME>:<YOUR_PAT>@github.com/biswajitghosh01/personal_finance_app.git /opt/finance/app
```

To avoid embedding the token in every future `git pull`, store it in
`~/.netrc`:

```bash
cat > ~/.netrc <<'EOF'
machine github.com
login <GITHUB_USERNAME>
password <YOUR_PAT>
EOF
chmod 600 ~/.netrc
```

Then clone normally:

```bash
git clone https://github.com/biswajitghosh01/personal_finance_app.git /opt/finance/app
```

#### Method B — SSH Deploy Key (recommended for production)

A deploy key is scoped to a single repository and can be read-only, so a
compromised server cannot modify your code.

Generate the key pair on the server:

```bash
ssh-keygen -t ed25519 -C "oracle-finance-server" -f ~/.ssh/github_deploy_key -N ""
```

Print the public key and copy the whole line (it starts with `ssh-ed25519`):

```bash
cat ~/.ssh/github_deploy_key.pub
```

On GitHub, go to your repository:

1. **Settings → Deploy keys → Add deploy key**.
2. Give it a title, e.g. `oracle-server`.
3. Paste the public key.
4. Leave **Allow write access** unchecked.
5. Click **Add key**.

Configure SSH so Git uses this key for GitHub:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_deploy_key
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

Clone using the SSH URL (note the `git@` prefix):

```bash
git clone git@github.com:biswajitghosh01/personal_finance_app.git /opt/finance/app
```

Verify the connection any time with:

```bash
ssh -T git@github.com
```

A successful result prints something like
`Hi biswajitghosh01! You've successfully authenticated...`.

#### After cloning

```bash
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

Replace `yourdomain.duckdns.org` with the actual domain from Step 10. If you
want to test with the IP first, set `ALLOWED_HOSTS=<PUBLIC_IP>` and
`SESSION_COOKIE_SECURE=false` temporarily.

Pre-create the `instance/` directory that systemd's `ReadWritePaths=`
directive requires to exist before the service starts:

```bash
mkdir -p /opt/finance/app/instance
chmod 700 /opt/finance/app/instance
```

Read the generated password once:

```bash
grep '^DEFAULT_PASSWORD=' .env
```

#### Troubleshooting the clone

| Symptom                                                                                   | Fix                                                                                                                               |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `Invalid username or token. Password authentication is not supported for Git operations.` | You used your GitHub password. Switch to a PAT (Method A) or a Deploy Key (Method B).                                             |
| `Permission denied (publickey)`                                                           | The SSH key is not added to GitHub, or `~/.ssh/config` is missing the `Host github.com` entry. Test with `ssh -T git@github.com`. |
| `Repository not found`                                                                    | The PAT lacks the `repo` scope, or the Deploy Key was added to a different repository.                                            |
| `Host key verification failed`                                                            | Run `ssh-keyscan github.com >> ~/.ssh/known_hosts` once on the server.                                                            |
| Prompts for username/password on every `git pull`                                         | Configure `~/.netrc` (Method A) or switch to SSH (Method B).                                                                      |
| `fatal: could not read Username for 'https://github.com'`                                 | No credentials are configured. Follow Method A or B from the start.                                                               |

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

#### Troubleshooting the systemd unit

If the service fails with this error:

```text
finance.service: Failed to set up mount namespacing: /opt/finance/app/instance: No such file or directory
finance.service: Main process exited, code=exited, status=226/NAMESPACE
```

it means the `instance/` directory that `ReadWritePaths=` expects does not
exist. systemd refuses to start a service with `ProtectSystem=strict` unless
every path listed under `ReadWritePaths=` already exists on disk. Fix it by
creating the directory once:

```bash
sudo mkdir -p /opt/finance/app/instance
sudo chown ubuntu:ubuntu /opt/finance/app/instance
sudo chmod 700 /opt/finance/app/instance
sudo systemctl restart finance
sudo systemctl status finance --no-pager
```

If the restart still fails, confirm the app actually cloned correctly:

```bash
ls -la /opt/finance/app/           # app.py, requirements.txt, templates/, static/, .env, .venv, instance/
ls -la /opt/finance/app/.venv/bin/python
ls -la /opt/finance/app/.env
```

Any missing item indicates the clone or the `.env` creation step did not
complete. Re-run the corresponding step.

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

### Step 9 — (Optional) Install UFW

Skip this step if you have already applied the iptables fix in Step 5.5.
The iptables rules plus the Oracle Security List are a complete firewall for
a single-user deployment.

If you want UFW as an additional layer:

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status verbose
```

**After enabling UFW, re-check iptables ordering** — UFW inserts its rules
but does not necessarily place them before Oracle's `REJECT`:

```bash
sudo iptables -L INPUT -n --line-numbers
```

If a `REJECT` line still precedes the UFW rules, apply the manual
insertion from Step 5.5.2. Do not open port 5555 in either UFW or iptables;
the app is reachable only through Nginx on loopback.

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

   It should return your OCI public IP. If it doesn't, wait 1–2 minutes for
   DNS propagation and try again.

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

With the domain resolving to your server and ports 80/443 open in both the
Security List and iptables, Certbot can complete the HTTP-01 challenge.

#### 11.1 — Pre-flight verification

Before running Certbot, confirm every layer is correct:

```bash
# From your local machine:
dig +short myfinance.duckdns.org
# Must return your OCI public IP.

# On the server:
sudo iptables -L INPUT -n --line-numbers | head -20
# ACCEPT rules for ports 80 and 443 must come before any REJECT.

sudo ss -tlnp | grep ':80'
# Nginx must be LISTENing on 0.0.0.0:80 or *:80.

sudo nginx -t
# Configuration syntax must be OK.
```

Test the challenge path end-to-end:

```bash
# On the server:
sudo mkdir -p /var/www/letsencrypt/.well-known/acme-challenge
printf 'probe\n' | sudo tee /var/www/letsencrypt/.well-known/acme-challenge/probe
sudo chmod -R 755 /var/www/letsencrypt

# From your local machine:
curl http://myfinance.duckdns.org/.well-known/acme-challenge/probe
# Expected output: probe
```

If you see `probe`, the entire network path is clear and Certbot will
succeed. If you see a timeout or `Connection refused`, return to Step 5.5.

#### 11.2 — Run Certbot

```bash
sudo certbot --nginx -d myfinance.duckdns.org \
    --non-interactive --agree-tos -m you@example.com --redirect \
    --nginx-sleep-seconds 5
```

The `--nginx-sleep-seconds 5` gives Nginx five seconds to reload after
Certbot's temporary configuration change. On smaller Always Free shapes,
the default one-second wait is sometimes not enough.

Certbot rewrites the Nginx server block with the certificate paths and adds
an HTTPS redirect. Verify the renewal timer:

```bash
systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

#### 11.3 — Troubleshooting the Certbot failure

If Certbot fails with:

```text
Hint: The Certificate Authority failed to verify the temporary nginx
configuration changes made by Certbot. Ensure the listed domains point to
this nginx server and that it is accessible from the internet.
Some challenges have failed.
```

work through these causes in order:

**Cause 1 — Oracle's iptables firewall (most common).** Re-check the INPUT
chain ordering as shown in Step 5.5.1. If a `REJECT` precedes port 80,
re-apply the fix in Step 5.5.2 and re-run Certbot.

**Cause 2 — DNS mismatch.** Confirm the domain resolves to the server's
public IP:

```bash
dig +short myfinance.duckdns.org
```

Compare against the IP shown in the OCI Console. If they differ, update
DuckDNS with the correct IP.

**Cause 3 — Nginx not listening on port 80.** Verify:

```bash
sudo ss -tlnp | grep ':80'
```

The output must include `0.0.0.0:80` or `*:80`. If it only shows
`127.0.0.1:80`, the server block has the wrong `listen` directive.

**Cause 4 — Stale redirect intercepting the challenge.** If your port-80
server block has a `return 301 https://$host$request_uri` that runs before
the `location ^~ /.well-known/acme-challenge/` block, the HTTP-01 challenge
is redirected to HTTPS and fails. Ensure the challenge location is the
first `location` block in the port-80 server, and add an explicit `allow
all`:

```nginx
location ^~ /.well-known/acme-challenge/ {
    allow all;
    root /var/www/letsencrypt;
}
```

**Cause 5 — Nginx reload timing.** Re-run Certbot with
`--nginx-sleep-seconds 5`. If you already have a certificate config file,
edit `/etc/letsencrypt/renewal/myfinance.duckdns.org.conf` and add:

```
nginx_sleep_seconds = 5
```

under the `[renewalparams]` section.

**Read the detailed log.** Certbot records the exact HTTP status and the
challenge URL:

```bash
sudo cat /var/log/letsencrypt/letsencrypt.log | tail -100
```

Look for the `"detail"` field in the JSON error response. Common values:

| Detail message                    | Cause                                                       |
| --------------------------------- | ----------------------------------------------------------- |
| `Invalid response from ...: 404`  | Nginx isn't serving the challenge path (Cause 4)            |
| `Invalid response from ...: 403`  | Nginx is denying access to the challenge path (permissions) |
| `Timeout` or `Connection refused` | Port 80 blocked at network layer (Cause 1 or 2)             |
| `DNS problem: NXDOMAIN`           | Domain doesn't resolve (Cause 2)                            |

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

**`sudo: ufw: command not found`.** UFW is not installed on Oracle's Ubuntu
images by default, and the deployment guide deliberately does not install it.
This is expected and harmless — the OCI Security List plus iptables is a
complete firewall. Skip the UFW steps and apply the iptables fix in Step 5.5.

**Certbot says the CA cannot verify the temporary Nginx configuration.** The
Let's Encrypt servers couldn't reach the challenge file. Work through the
five causes in Step 11.3. On Oracle Cloud, the hidden iptables firewall
(Step 5.5) is almost always the culprit.

**Site unreachable after opening ports.** Confirm iptables ordering first:

```bash
sudo iptables -L INPUT -n --line-numbers | head -20
```

Then confirm Nginx is listening:

```bash
sudo ss -tlnp | grep ':80'
```

If the app is not listening on `127.0.0.1:5555`, check:

```bash
sudo journalctl -u finance -n 60 --no-pager
```

**`Failed to set up mount namespacing: /opt/finance/app/instance: No such
file or directory`.** The systemd unit's `ReadWritePaths=` requires the
directory to exist before the service starts. Create it once:

```bash
sudo mkdir -p /opt/finance/app/instance
sudo chown ubuntu:ubuntu /opt/finance/app/instance
sudo chmod 700 /opt/finance/app/instance
sudo systemctl restart finance
```

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

**Git authentication failures during clone or pull.** GitHub removed
password authentication in August 2021. If `git clone` or `git pull` fails
with `Invalid username or token` or `Password authentication is not
supported for Git operations`, switch to a Personal Access Token or an SSH
Deploy Key — see the troubleshooting table in Step 6.

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

- OCI Security List ingress restricted to TCP 22, 80, and 443 only.
- Explicit iptables `ACCEPT` rules for ports 80 and 443, inserted before
  Oracle's default `REJECT` rule, and persisted with `netfilter-persistent`.
- systemd hardening (`NoNewPrivileges`, `ProtectSystem=strict`,
  `PrivateTmp`, `MemoryDenyWriteExecute`).
- Fail2ban for SSH brute-force protection.
- Let's Encrypt TLS with automatic renewal.

Back up `.env` together with `instance/finance.db`; neither is usable without
the other.

## License

This project is provided as-is for personal use.
