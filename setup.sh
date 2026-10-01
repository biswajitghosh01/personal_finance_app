#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
umask 077

PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python 3 was not found: $PYTHON_BIN" >&2
    echo "Install Python 3 or set PYTHON_BIN to its executable path." >&2
    exit 1
}
[[ -f requirements.txt && -f app.py ]] || {
    echo "setup.sh must be next to app.py and requirements.txt." >&2
    exit 1
}

if [[ -e .venv && ! -x .venv/bin/python ]]; then
    BACKUP_DIR=".venv.invalid-$(date +%Y%m%d%H%M%S)"
    mv -- .venv "$BACKUP_DIR"
    echo "Moved incomplete .venv to $BACKUP_DIR for inspection." >&2
fi

if [[ ! -x .venv/bin/python ]]; then
    "$PYTHON_BIN" -m venv .venv || {
        echo "Could not create .venv with $PYTHON_BIN." >&2
        echo "On Linux, install the python3-venv package and retry." >&2
        exit 1
    }
fi

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    "$VENV_PYTHON" -m ensurepip --upgrade
fi
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
    "$VENV_PYTHON" - .env <<'PY'
from pathlib import Path
from cryptography.fernet import Fernet
import secrets
import sys

target = Path(sys.argv[1])
temporary = target.with_name(target.name + '.tmp')
temporary.write_text(
    'SECRET_KEY=' + secrets.token_urlsafe(64) + '\n'
    'DATA_KEY=' + Fernet.generate_key().decode() + '\n'
    'DEFAULT_USER=admin\n'
    'DEFAULT_PASSWORD=ChangeMe-5555!\n', encoding='utf-8')
temporary.chmod(0o600)
temporary.replace(target)
PY
fi

chmod 600 .env
mkdir -p instance
chmod 700 instance
if [[ -f instance/finance.db ]]; then
    chmod 600 instance/finance.db
fi

exec "$VENV_PYTHON" app.py
