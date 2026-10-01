#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "Python 3 is required." >&2; exit 1; }
[ -d .venv ] || "$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
umask 077
if [ ! -f .env ]; then
python3 - <<'PY'
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
fi
mkdir -p instance
chmod 700 instance
exec python3 app.py
