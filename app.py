import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

import click
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from flask import (
    Flask, abort, flash, g, redirect, render_template, request, session, url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from admin_routes import admin_bp, ensure_admin_schema

# ---------------------------------------------------------------- environment
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / 'instance' / 'finance.db'
ENV_PATH = BASE / '.env'

if not ENV_PATH.exists():
    raise RuntimeError('Missing .env. Start the application with ./setup.sh')

for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())

for key in ('SECRET_KEY', 'DATA_KEY', 'DEFAULT_USER', 'DEFAULT_PASSWORD'):
    if not os.getenv(key):
        raise RuntimeError(f'Missing required setting: {key}')


def flag(name, default='false'):
    return os.environ.get(name, default).strip().lower() in {'1', 'true', 'yes'}


ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
}
TRUSTED_PROXY_COUNT = max(0, int(os.environ.get('TRUSTED_PROXY_COUNT', '0')))
BIND_HOST = os.environ.get('BIND_HOST', '127.0.0.1').strip() or '127.0.0.1'
BIND_PORT = int(os.environ.get('BIND_PORT', '5555'))

# ---------------------------------------------------------------- flask setup
app = Flask(__name__, template_folder='templates', static_folder='static')

if TRUSTED_PROXY_COUNT:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_COUNT,
        x_proto=TRUSTED_PROXY_COUNT,
        x_host=TRUSTED_PROXY_COUNT,
    )

app.config.update(
    SECRET_KEY=os.environ['SECRET_KEY'],
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict',
    SESSION_COOKIE_SECURE=flag('SESSION_COOKIE_SECURE'),
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    MAX_CONTENT_LENGTH=256 * 1024,
    WTF_CSRF_TIME_LIMIT=3600,
)

CSRFProtect(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=['300 per hour'],
    storage_uri='memory://',
)
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
cipher = Fernet(os.environ['DATA_KEY'].encode())
app.extensions['finance_cipher'] = cipher
app.register_blueprint(admin_bp)

# ---------------------------------------------------------------- constants
CATEGORIES = {
    'BANK': 'Bank Accounts',
    'FIXED_DEPOSIT': 'Fixed Deposits',
    'RECURRING_DEPOSIT': 'Recurring Deposits',
    'SHARE': 'Stocks',
    'MUTUAL_FUND': 'Mutual Funds',
    'METAL': 'Metals',
    'ESOP': 'ESOPs',
    'LIABILITY': 'Liabilities',
    'OTHER': 'Other investments',
}

CURRENCIES = ('INR', 'USD', 'EUR', 'GBP', 'SGD', 'AED', 'JPY', 'CAD', 'AUD')
CURRENCY_SYMBOLS = {
    'INR': '₹',
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'SGD': 'S$',
    'AED': 'AED',
    'JPY': '¥',
    'CAD': 'C$',
    'AUD': 'A$',
}

TRANSACTION_TYPES = (
    'INCOME', 'EXPENSE', 'TRANSFER', 'INVESTMENT', 'LIABILITY_PAYMENT',
)
LIABILITY_TYPES = ('Personal Loan', 'Home Loan', 'Auto Loan', 'Other')
LIABILITY_STATUSES = ('Active', 'Paid Off', 'In Dispute', 'Deferred')
PAYMENT_FREQUENCIES = (
    'Monthly', 'Quarterly', 'Bi-weekly', 'Weekly',
    'Semi-annual', 'Annual', 'On Demand',
)
PAYMENT_METHODS = (
    'Auto-pay', 'ACH Transfer', 'Wire', 'Check',
    'Cash', 'Standing Instruction', 'Other',
)
ACCOUNT_TYPES = ('Savings', 'Current', 'Salary', 'NRE', 'NRO', 'FCNR', 'Other')
RETIRAL_FUND_TYPES = (
    'EPF', 'PPF', 'NPS', 'Superannuation',
    'Pension Fund', 'Gratuity', '401(k)', 'Other',
)
METAL_TYPES = ('Gold', 'Silver', 'Platinum', 'Palladium', 'Other')
METAL_PRODUCT_FORMS = (
    'Coin', 'Bar', 'Round', 'ETF', 'Digital Gold', 'Jewellery', 'Other',
)


def currency_symbol(code):
    return CURRENCY_SYMBOLS.get(code, code)


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 must_change INTEGER NOT NULL DEFAULT 1, failed INTEGER NOT NULL DEFAULT 0,
 locked_until TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 category TEXT NOT NULL CHECK(category IN ('BANK','FIXED_DEPOSIT','RECURRING_DEPOSIT','SHARE','MUTUAL_FUND','METAL','ESOP','LIABILITY','OTHER')),
 name TEXT NOT NULL, institution TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '',
 currency TEXT NOT NULL, quantity TEXT NOT NULL DEFAULT '0', current_price TEXT NOT NULL DEFAULT '0',
 principal TEXT NOT NULL DEFAULT '0', interest_rate TEXT NOT NULL DEFAULT '0',
 start_date TEXT, maturity_date TEXT, account_ref BLOB, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS bank_accounts (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 bank_name TEXT NOT NULL, account_number BLOB NOT NULL,
 ifsc_code TEXT NOT NULL DEFAULT '', micr_code TEXT NOT NULL DEFAULT '',
 bank_address TEXT NOT NULL DEFAULT '', account_type TEXT NOT NULL,
 current_balance TEXT NOT NULL DEFAULT '0', interest_rate TEXT NOT NULL DEFAULT '0',
 currency TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bank_accounts_user ON bank_accounts(user_id);
CREATE TABLE IF NOT EXISTS fixed_deposits (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 bank_name TEXT NOT NULL, account_number BLOB NOT NULL,
 ifsc_code TEXT NOT NULL, micr_code TEXT NOT NULL,
 bank_address TEXT NOT NULL, initial_deposit TEXT NOT NULL DEFAULT '0',
 investment_date TEXT NOT NULL, maturity_date TEXT NOT NULL,
 interest_rate TEXT NOT NULL DEFAULT '0', currency TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fixed_deposits_user_maturity ON fixed_deposits(user_id,maturity_date);
CREATE TABLE IF NOT EXISTS recurring_deposits (
 id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,bank_name TEXT NOT NULL,account_number BLOB NOT NULL,
 monthly_deposit TEXT NOT NULL,deposit_day INTEGER NOT NULL,amount_invested TEXT NOT NULL DEFAULT '0',
 current_value TEXT NOT NULL DEFAULT '0',start_date TEXT NOT NULL,maturity_date TEXT NOT NULL,
 interest_rate TEXT NOT NULL DEFAULT '0',currency TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_recurring_deposits_user_maturity ON recurring_deposits(user_id,maturity_date);
CREATE TABLE IF NOT EXISTS stocks (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 stock_name TEXT NOT NULL,
 ticker TEXT, stock_symbol TEXT, company_name TEXT, isin_code TEXT,
 market TEXT NOT NULL CHECK(market IN ('India','United States')),
 number_of_shares TEXT NOT NULL, buy_price TEXT NOT NULL,
 current_price TEXT NOT NULL, previous_close TEXT NOT NULL DEFAULT '0',
 buy_transaction_date TEXT NOT NULL,
 currency TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 sale_date TEXT, sale_units TEXT NOT NULL DEFAULT '0', sell_price TEXT NOT NULL DEFAULT '0',
 gst TEXT NOT NULL DEFAULT '0', brokerage TEXT NOT NULL DEFAULT '0',
 stt TEXT NOT NULL DEFAULT '0', exchange_fees TEXT NOT NULL DEFAULT '0',
 realized_profit_loss TEXT NOT NULL DEFAULT '0',
 us_total_invested TEXT NOT NULL DEFAULT '0',
 us_current_value TEXT NOT NULL DEFAULT '0',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_stocks_user_market ON stocks(user_id,market);
CREATE TABLE IF NOT EXISTS esops (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 company_name TEXT NOT NULL, grant_date TEXT NOT NULL,
 vesting_date TEXT, number_of_units TEXT NOT NULL,
 grant_price TEXT NOT NULL, current_price TEXT NOT NULL,
 currency TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_esops_user_company ON esops(user_id,company_name);
CREATE TABLE IF NOT EXISTS mutual_funds (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 fund_house TEXT NOT NULL, fund_name TEXT NOT NULL,
 fund_category TEXT NOT NULL, invested_amount TEXT NOT NULL,
 current_value TEXT NOT NULL, investment_mode TEXT NOT NULL CHECK(investment_mode IN ('SIP','LUMPSUM')),
 investment_date TEXT NOT NULL, currency TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mutual_funds_user_house ON mutual_funds(user_id,fund_house);
CREATE TABLE IF NOT EXISTS metals (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 metal_type TEXT NOT NULL, product_form TEXT NOT NULL,
 weight TEXT NOT NULL, weight_unit TEXT NOT NULL CHECK(weight_unit IN ('GRAM','TROY_OUNCE')),
 purity TEXT NOT NULL, mint_brand TEXT NOT NULL,
 investment_amount TEXT NOT NULL, current_value TEXT NOT NULL,
 currency TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_metals_user_type ON metals(user_id,metal_type);
CREATE TABLE IF NOT EXISTS liabilities (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 lender_name TEXT NOT NULL, account_number BLOB NOT NULL,
 liability_type TEXT NOT NULL, status TEXT NOT NULL,
 original_principal TEXT NOT NULL, current_balance TEXT NOT NULL,
 currency TEXT NOT NULL, origination_date TEXT NOT NULL,
 maturity_date TEXT NOT NULL, interest_rate TEXT NOT NULL,
 rate_type TEXT NOT NULL CHECK(rate_type IN ('FIXED','VARIABLE')),
 payment_frequency TEXT NOT NULL, regular_payment TEXT NOT NULL,
 payment_method TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_liabilities_user_status ON liabilities(user_id,status);
CREATE TABLE IF NOT EXISTS retirals (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 fund_type TEXT NOT NULL, amount_invested TEXT NOT NULL DEFAULT '0',
 current_value TEXT NOT NULL DEFAULT '0', currency TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_retirals_user_type ON retirals(user_id,fund_type);
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, transaction_date TEXT NOT NULL,
 transaction_type TEXT NOT NULL CHECK(transaction_type IN ('INCOME','EXPENSE','TRANSFER','INVESTMENT','LIABILITY_PAYMENT')),
 category TEXT NOT NULL, description TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
 account_name TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS budgets (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 category TEXT NOT NULL, monthly_limit TEXT NOT NULL DEFAULT '0',
 currency TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_budgets_user_category ON budgets(user_id, category);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT NOT NULL, entity_id INTEGER,
 event_time TEXT NOT NULL, remote_addr TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_user_category ON assets(user_id, category);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, transaction_date DESC);
'''


# ---------------------------------------------------------------- helpers
def now():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA journal_mode=WAL')
    return g.db


@app.teardown_appcontext
def close_db(_=None):
    connection = g.pop('db', None)
    if connection:
        connection.close()


def _run_schema_migrations(connection):
    connection.executescript(SCHEMA)

    liability_columns = {
        row[1] for row in connection.execute('PRAGMA table_info(liabilities)').fetchall()
    }
    if 'emi_date' not in liability_columns:
        connection.execute('ALTER TABLE liabilities ADD COLUMN emi_date TEXT')

    stock_columns = {
        row[1] for row in connection.execute('PRAGMA table_info(stocks)').fetchall()
    }
    for column, definition in {
        'sale_date': 'TEXT',
        'sale_units': "TEXT NOT NULL DEFAULT '0'",
        'sell_price': "TEXT NOT NULL DEFAULT '0'",
        'gst': "TEXT NOT NULL DEFAULT '0'",
        'brokerage': "TEXT NOT NULL DEFAULT '0'",
        'stt': "TEXT NOT NULL DEFAULT '0'",
        'exchange_fees': "TEXT NOT NULL DEFAULT '0'",
        'ticker': 'TEXT',
        'stock_symbol': 'TEXT',
        'company_name': 'TEXT',
        'isin_code': 'TEXT',
        'previous_close': "TEXT NOT NULL DEFAULT '0'",
        'realized_profit_loss': "TEXT NOT NULL DEFAULT '0'",
        'us_total_invested': "TEXT NOT NULL DEFAULT '0'",
        'us_current_value': "TEXT NOT NULL DEFAULT '0'",
    }.items():
        if column not in stock_columns:
            connection.execute(f'ALTER TABLE stocks ADD COLUMN {column} {definition}')

    connection.commit()


def ensure_default_user(connection=None):
    username = os.environ['DEFAULT_USER']
    password = os.environ['DEFAULT_PASSWORD']

    own_connection = connection is None
    if own_connection:
        DB_PATH.parent.mkdir(exist_ok=True, mode=0o700)
        connection = sqlite3.connect(DB_PATH)
        connection.execute('PRAGMA foreign_keys=ON')

    previous_row_factory = connection.row_factory
    if previous_row_factory is not sqlite3.Row:
        connection.row_factory = sqlite3.Row

    try:
        connection.executescript(SCHEMA)

        existing = connection.execute(
            'SELECT id, password_hash FROM users WHERE username=?',
            (username,),
        ).fetchone()

        if existing is None:
            connection.execute(
                'INSERT INTO users(username,password_hash,must_change,failed,created_at) '
                'VALUES(?,?,1,0,?)',
                (username, password_hasher.hash(password), now()),
            )
            connection.commit()
            return username

        stored_hash = (
            existing['password_hash'] if isinstance(existing, sqlite3.Row)
            else existing[1]
        ) or ''
        user_id = existing['id'] if isinstance(existing, sqlite3.Row) else existing[0]

        if len(stored_hash) < 40 or not stored_hash.startswith('$argon2'):
            connection.execute(
                'UPDATE users SET password_hash=?, must_change=1 WHERE id=?',
                (password_hasher.hash(password), user_id),
            )
            connection.commit()
            return username
        return None
    finally:
        if own_connection:
            connection.close()
        else:
            connection.row_factory = previous_row_factory


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True, mode=0o700)
    connection = sqlite3.connect(DB_PATH)
    try:
        _run_schema_migrations(connection)
        ensure_default_user(connection)
    finally:
        connection.close()
    os.chmod(DB_PATH, 0o600)


def _print_startup_credentials():
    user = (os.environ.get('DEFAULT_USER') or '').strip()
    password = (os.environ.get('DEFAULT_PASSWORD') or '').strip()
    if not user or not password:
        return

    must_change = None
    try:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            'SELECT must_change FROM users WHERE username=?',
            (user,),
        ).fetchone()
        if row is not None:
            must_change = bool(row['must_change'])
        connection.close()
    except sqlite3.Error:
        pass

    bar = '=' * 60
    print(bar)
    print('  DEFAULT SIGN-IN CREDENTIALS')
    print(bar)
    print(f'  Username         {user}')
    print(f'  Password         {password}')
    if must_change is True:
        print('  Status           must be changed on first login')
    elif must_change is False:
        print('  Status           password already changed by the user')
    else:
        print('  Status           user not found in database')
    print(bar)
    print('  Change this password immediately after signing in.')
    print(bar)


def audit(action, entity_id=None):
    get_db().execute(
        'INSERT INTO audit_log(user_id,action,entity_id,event_time,remote_addr) '
        'VALUES(?,?,?,?,?)',
        (session.get('uid'), action, entity_id, now(), request.remote_addr or 'unknown'),
    )
    get_db().commit()


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get('uid'):
            return redirect(url_for('login', next=request.path))
        if session.get('must_change') and request.endpoint != 'change_password':
            return redirect(url_for('change_password'))
        return function(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- validators
def clean_text(value, length, required=False):
    value = (value or '').strip()
    if required and not value:
        raise ValueError('Please complete all required fields.')
    if len(value) > length or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ValueError('Invalid text value.')
    return value


def clean_number(value):
    try:
        number = Decimal((value or '0').strip())
    except InvalidOperation:
        raise ValueError('Enter a valid number.')
    if not number.is_finite() or number < 0 or number > Decimal('1000000000000000'):
        raise ValueError('Number is outside the allowed range.')
    return format(number, 'f')


def clean_signed_number(value):
    """Like clean_number but permits negatives — used for realized P&L."""
    try:
        number = Decimal((value or '0').strip())
    except InvalidOperation:
        raise ValueError('Enter a valid number.')
    if not number.is_finite() or abs(number) > Decimal('1000000000000000'):
        raise ValueError('Number is outside the allowed range.')
    return format(number, 'f')


def clean_date(value):
    value = (value or '').strip()
    if value:
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            raise ValueError('Enter a valid date.')
    return value or None


def decrypt_mask(blob):
    if not blob:
        return ''
    try:
        value = cipher.decrypt(blob).decode()
        return '•••• ' + value[-4:]
    except (InvalidToken, UnicodeDecodeError):
        return 'Unavailable'


app.jinja_env.globals['decrypt_mask'] = decrypt_mask
app.jinja_env.globals['currency_symbol'] = currency_symbol


# ---------------------------------------------------------------- request hooks
@app.before_request
def security_gate():
    if request.host.split(':')[0].lower() not in ALLOWED_HOSTS:
        abort(400)
    if session.get('uid'):
        last_seen = session.get('last_seen')
        if last_seen and datetime.now(timezone.utc) - datetime.fromisoformat(last_seen) > timedelta(minutes=30):
            session.clear()
            flash('Your session expired. Please sign in again.', 'warning')
            return redirect(url_for('login'))
        session['last_seen'] = now()
        session.permanent = True


@app.before_request
def ensure_default_user_once():
    if app.extensions.get('_default_user_ready'):
        return
    try:
        created = ensure_default_user()
        if created:
            app.logger.info('Seeded default user: %s', created)
    except Exception:
        app.logger.exception('Failed to ensure default user.')
    finally:
        app.extensions['_default_user_ready'] = True


@app.after_request
def security_headers(response):
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cache-Control'] = 'no-store'
    return response


# ---------------------------------------------------------------- auth routes
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour')
def login():
    if request.method == 'POST':
        username = clean_text(request.form.get('username'), 80)
        user = get_db().execute(
            'SELECT * FROM users WHERE username=?', (username,),
        ).fetchone()

        valid = False
        if user and (
            not user['locked_until']
            or datetime.fromisoformat(user['locked_until']) <= datetime.now(timezone.utc)
        ):
            try:
                valid = password_hasher.verify(
                    user['password_hash'], request.form.get('password', ''),
                )
            except (VerifyMismatchError, VerificationError):
                pass

        if not valid:
            if user:
                failures = user['failed'] + 1
                locked = (
                    (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
                    if failures >= 5 else None
                )
                get_db().execute(
                    'UPDATE users SET failed=?,locked_until=? WHERE id=?',
                    (0 if locked else failures, locked, user['id']),
                )
                get_db().commit()
            flash('Invalid username or password.', 'error')
        else:
            ensure_admin_schema()
            get_db().execute(
                'UPDATE users SET failed=0,locked_until=NULL,last_login=? WHERE id=?',
                (now(), user['id']),
            )
            get_db().commit()
            session.clear()
            session.update(
                uid=user['id'],
                username=user['username'],
                must_change=bool(user['must_change']),
                last_seen=now(),
            )
            audit('LOGIN', user['id'])
            return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        password = request.form.get('password', '')
        good = len(password) >= 14 and all((
            re.search('[A-Z]', password),
            re.search('[a-z]', password),
            re.search(r'\d', password),
            re.search('[^A-Za-z0-9]', password),
        ))
        if password != request.form.get('confirm') or not good:
            flash('Use matching passwords with 14+ characters, upper, lower, number, and symbol.', 'error')
        elif password == os.environ['DEFAULT_PASSWORD']:
            flash('Choose a password different from the default.', 'error')
        else:
            get_db().execute(
                'UPDATE users SET password_hash=?,must_change=0 WHERE id=?',
                (password_hasher.hash(password), session['uid']),
            )
            get_db().commit()
            session['must_change'] = False
            audit('PASSWORD_CHANGED')
            return redirect(url_for('dashboard'))
    return render_template('change_password.html')


@app.post('/logout')
@login_required
def logout():
    audit('LOGOUT')
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------- dashboard
@app.route('/', methods=['GET'])
@app.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    db = get_db()
    uid = session['uid']
    assets = {}
    liabilities = {}
    bank_balances = {}
    allocation = {}

    def add(target, currency, value):
        amount = Decimal(str(value or '0'))
        target[currency] = target.get(currency, Decimal(0)) + amount
        return amount

    for row in db.execute('SELECT currency, current_balance FROM bank_accounts WHERE user_id=?', (uid,)):
        value = add(assets, row['currency'], row['current_balance'])
        add(bank_balances, row['currency'], row['current_balance'])
        allocation['BANK'] = allocation.get('BANK', Decimal(0)) + value

    for row in db.execute('SELECT currency, initial_deposit FROM fixed_deposits WHERE user_id=?', (uid,)):
        value = add(assets, row['currency'], row['initial_deposit'])
        allocation['FIXED_DEPOSIT'] = allocation.get('FIXED_DEPOSIT', Decimal(0)) + value

    for row in db.execute('SELECT currency, current_value FROM recurring_deposits WHERE user_id=?', (uid,)):
        value = add(assets, row['currency'], row['current_value'])
        allocation['RECURRING_DEPOSIT'] = allocation.get('RECURRING_DEPOSIT', Decimal(0)) + value

    # Stocks — use explicit USD values when present, otherwise fall back to
    # units × current_price for Indian positions (remaining after any sales).
    for row in db.execute(
        'SELECT market, currency, number_of_shares, current_price, sale_units, '
        'us_total_invested, us_current_value FROM stocks WHERE user_id=?',
        (uid,),
    ):
        keys = row.keys()
        us_invested = float(row['us_total_invested'] or 0) if 'us_total_invested' in keys else 0.0
        us_value = float(row['us_current_value'] or 0) if 'us_current_value' in keys else 0.0
        if row['market'] == 'United States' and (us_invested > 0 or us_value > 0):
            value = Decimal(str(us_value))
        else:
            units = Decimal(str(row['number_of_shares'] or '0'))
            sold = Decimal(str(row['sale_units'] or '0'))
            price = Decimal(str(row['current_price'] or '0'))
            value = max(units - sold, Decimal(0)) * price
        add(assets, row['currency'], value)
        allocation['SHARE'] = allocation.get('SHARE', Decimal(0)) + value

    for row in db.execute('SELECT currency, current_value FROM mutual_funds WHERE user_id=?', (uid,)):
        value = add(assets, row['currency'], row['current_value'])
        allocation['MUTUAL_FUND'] = allocation.get('MUTUAL_FUND', Decimal(0)) + value

    for row in db.execute('SELECT currency, current_value FROM retirals WHERE user_id=?', (uid,)):
        value = add(assets, row['currency'], row['current_value'])
        allocation['RETIRAL'] = allocation.get('RETIRAL', Decimal(0)) + value

    metal_breakdown = {}
    for row in db.execute('SELECT metal_type, currency, current_value FROM metals WHERE user_id=?', (uid,)):
        value = add(assets, row['currency'], row['current_value'])
        allocation['METAL'] = allocation.get('METAL', Decimal(0)) + value
        metal_breakdown[row['metal_type']] = metal_breakdown.get(row['metal_type'], Decimal(0)) + value

    liability_breakdown = {}
    for row in db.execute(
        "SELECT liability_type, currency, current_balance FROM liabilities WHERE user_id=? AND status!='Paid Off'",
        (uid,),
    ):
        value = add(liabilities, row['currency'], row['current_balance'])
        liability_breakdown[row['liability_type']] = liability_breakdown.get(row['liability_type'], Decimal(0)) + value

    dedicated = {'BANK', 'FIXED_DEPOSIT', 'RECURRING_DEPOSIT', 'SHARE', 'MUTUAL_FUND', 'METAL', 'LIABILITY'}
    for row in db.execute('SELECT * FROM assets WHERE user_id=?', (uid,)):
        if row['category'] in dedicated:
            continue
        value = (
            Decimal(row['principal']) if row['category'] == 'RECURRING_DEPOSIT'
            else Decimal(row['quantity']) * Decimal(row['current_price'])
        )
        add(assets, row['currency'], value)
        allocation[row['category']] = allocation.get(row['category'], Decimal(0)) + value

    currencies = sorted(set(assets) | set(liabilities))
    net = {
        currency: assets.get(currency, Decimal(0)) - liabilities.get(currency, Decimal(0))
        for currency in currencies
    }

    cash_rows = db.execute(
        '''
        SELECT substr(transaction_date,1,7) AS month, transaction_type, SUM(CAST(amount AS REAL)) AS total
        FROM transactions
        WHERE user_id=? AND transaction_type IN ('INCOME','EXPENSE')
        GROUP BY month, transaction_type ORDER BY month DESC LIMIT 24
        ''',
        (uid,),
    ).fetchall()
    months = sorted({row['month'] for row in cash_rows if row['month']})[-12:]
    cash_map = {(row['month'], row['transaction_type']): float(row['total'] or 0) for row in cash_rows}

    chart_data = {
        'allocation': {
            'labels': [CATEGORIES.get(key, 'Retirals') for key in allocation],
            'values': [float(value) for value in allocation.values()],
        },
        'balance': {
            'labels': currencies,
            'assets': [float(assets.get(currency, 0)) for currency in currencies],
            'liabilities': [float(liabilities.get(currency, 0)) for currency in currencies],
        },
        'cashflow': {
            'labels': months,
            'income': [cash_map.get((month, 'INCOME'), 0) for month in months],
            'expense': [cash_map.get((month, 'EXPENSE'), 0) for month in months],
        },
        'liabilities': {
            'labels': list(liability_breakdown),
            'values': [float(value) for value in liability_breakdown.values()],
        },
        'metals': {
            'labels': list(metal_breakdown),
            'values': [float(value) for value in metal_breakdown.values()],
        },
    }

    today = datetime.now(timezone.utc).date()
    current_month = f'{today.year}-{today.month:02d}'
    _, budget_summary = _budget_summary_for_month(db, uid, current_month)

    dedicated_routes = {
        'BANK': 'bank_accounts',
        'FIXED_DEPOSIT': 'fixed_deposits',
        'RECURRING_DEPOSIT': 'recurring_deposits',
        'SHARE': 'stocks',
        'ESOP': 'esops',
        'MUTUAL_FUND': 'mutual_funds',
        'METAL': 'metals',
        'LIABILITY': 'liabilities',
        'RETIRAL': 'retirals',
    }
    section_links = [
        {
            'label': label,
            'url': url_for(dedicated_routes[code]) if code in dedicated_routes else url_for('section', category=code),
        }
        for code, label in CATEGORIES.items()
    ]
    section_links.append({'label': 'Retirals', 'url': url_for('retirals')})

    return render_template(
        'dashboard.html',
        net=net,
        assets=assets,
        liabilities=liabilities,
        bank_balances=bank_balances,
        budget_summary=budget_summary,
        allocation_chart=chart_data['allocation'],
        liability_chart=chart_data['liabilities'],
        chart_data=chart_data,
        section_links=section_links,
    )


# ---------------------------------------------------------------- sections
@app.route('/section/<category>')
@login_required
def section(category):
    redirects = {
        'BANK': 'bank_accounts',
        'FIXED_DEPOSIT': 'fixed_deposits',
        'RECURRING_DEPOSIT': 'recurring_deposits',
        'SHARE': 'stocks',
        'ESOP': 'esops',
        'MUTUAL_FUND': 'mutual_funds',
        'METAL': 'metals',
        'LIABILITY': 'liabilities',
        'RETIRAL': 'retirals',
    }
    if category in redirects:
        return redirect(url_for(redirects[category]))
    if category not in CATEGORIES:
        abort(404)
    rows = get_db().execute(
        'SELECT * FROM assets WHERE user_id=? AND category=? ORDER BY institution,name',
        (session['uid'], category),
    ).fetchall()
    return render_template('section.html', rows=rows, category=category, title=CATEGORIES[category])


@app.route('/assets/new', methods=['GET', 'POST'])
@login_required
def asset_new():
    category = request.values.get('category', 'RECURRING_DEPOSIT')
    redirects = {
        'BANK': 'bank_account_new',
        'FIXED_DEPOSIT': 'fixed_deposit_new',
        'RECURRING_DEPOSIT': 'recurring_deposit_new',
        'SHARE': 'stock_new',
        'ESOP': 'esop_new',
        'MUTUAL_FUND': 'mutual_fund_new',
        'METAL': 'metal_new',
        'LIABILITY': 'liability_new',
        'RETIRAL': 'retiral_new',
    }
    if category in redirects:
        return redirect(url_for(redirects[category]))
    if category not in CATEGORIES:
        category = 'RECURRING_DEPOSIT'

    other_categories = {
        k: v for k, v in CATEGORIES.items()
        if k not in {
            'BANK', 'FIXED_DEPOSIT', 'RECURRING_DEPOSIT', 'SHARE', 'ESOP',
            'MUTUAL_FUND', 'METAL', 'LIABILITY', 'RETIRAL',
        }
    }

    if request.method == 'POST':
        try:
            category_value = request.form.get('category', '')
            currency = request.form.get('currency', '').upper()
            if category_value in {
                'BANK', 'FIXED_DEPOSIT', 'SHARE', 'ESOP',
                'MUTUAL_FUND', 'METAL', 'LIABILITY',
            }:
                raise ValueError('Use the dedicated page for this category.')
            if category_value not in CATEGORIES or currency not in CURRENCIES:
                raise ValueError('Invalid category or currency.')
            country = clean_text(request.form.get('country'), 60)
            reference = clean_text(request.form.get('account_ref'), 80)
            values = (
                category_value,
                clean_text(request.form.get('name'), 120, True),
                clean_text(request.form.get('institution'), 120),
                country,
                currency,
                clean_number(request.form.get('quantity')),
                clean_number(request.form.get('current_price')),
                clean_number(request.form.get('principal')),
                clean_number(request.form.get('interest_rate')),
                clean_date(request.form.get('start_date')),
                clean_date(request.form.get('maturity_date')),
                cipher.encrypt(reference.encode()) if reference else None,
                clean_text(request.form.get('notes'), 1000),
            )
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'asset_form.html',
                current=category,
                categories=other_categories,
                currencies=CURRENCIES,
                asset=request.form,
            )
        cursor = get_db().execute(
            'INSERT INTO assets(user_id,category,name,institution,country,currency,'
            'quantity,current_price,principal,interest_rate,start_date,maturity_date,'
            'account_ref,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('ASSET_CREATE', cursor.lastrowid)
        return redirect(url_for('section', category=category))

    return render_template(
        'asset_form.html',
        current=category,
        categories=other_categories,
        currencies=CURRENCIES,
        asset={},
    )


@app.post('/assets/<int:asset_id>/delete')
@login_required
def asset_delete(asset_id):
    cursor = get_db().execute(
        'DELETE FROM assets WHERE id=? AND user_id=?', (asset_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('ASSET_DELETE', asset_id)
    referrer = request.referrer
    return redirect(referrer if referrer and referrer.startswith(request.host_url) else url_for('dashboard'))


# ---------------------------------------------------------------- bank accounts
def _parse_bank_account(form):
    bank_name = clean_text(form.get('bank_name'), 120, True)
    account_number = clean_text(form.get('account_number'), 80, True)
    ifsc_code = clean_text(form.get('ifsc_code'), 20).upper()
    micr_code = clean_text(form.get('micr_code'), 20)
    bank_address = clean_text(form.get('bank_address'), 500)
    account_type = form.get('account_type', '')
    if account_type not in ACCOUNT_TYPES:
        raise ValueError('Invalid account type.')
    current_balance = clean_number(form.get('current_balance'))
    interest_rate = clean_number(form.get('interest_rate'))
    if Decimal(interest_rate) > Decimal('100'):
        raise ValueError('Interest rate must be between 0 and 100.')
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')
    notes = clean_text(form.get('notes'), 1000)
    return (
        bank_name, cipher.encrypt(account_number.encode()), ifsc_code, micr_code,
        bank_address, account_type, current_balance, interest_rate, currency, notes,
    )


@app.route('/bank-accounts')
@login_required
def bank_accounts():
    rows = get_db().execute(
        'SELECT * FROM bank_accounts WHERE user_id=? ORDER BY bank_name,id',
        (session['uid'],),
    ).fetchall()
    return render_template('bank_accounts.html', rows=[
        {**dict(row), 'display_id': i + 1} for i, row in enumerate(rows)
    ])


@app.route('/bank-accounts/new', methods=['GET', 'POST'])
@login_required
def bank_account_new():
    if request.method == 'POST':
        try:
            values = _parse_bank_account(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'bank_account_edit.html',
                account=request.form,
                account_types=ACCOUNT_TYPES,
                currencies=CURRENCIES,
                is_edit=False,
            )
        cursor = get_db().execute(
            'INSERT INTO bank_accounts(user_id,bank_name,account_number,ifsc_code,micr_code,'
            'bank_address,account_type,current_balance,interest_rate,currency,notes,'
            'created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('BANK_ACCOUNT_CREATE', cursor.lastrowid)
        flash('Bank account saved.', 'success')
        return redirect(url_for('bank_accounts'))
    return render_template(
        'bank_account_edit.html',
        account={},
        account_types=ACCOUNT_TYPES,
        currencies=CURRENCIES,
        is_edit=False,
    )


@app.route('/bank-accounts/<int:account_id>/edit', methods=['GET', 'POST'])
@login_required
def bank_account_edit(account_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM bank_accounts WHERE id=? AND user_id=?',
        (account_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        try:
            values = _parse_bank_account(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'bank_account_edit.html',
                account=request.form,
                account_id=account_id,
                account_types=ACCOUNT_TYPES,
                currencies=CURRENCIES,
                is_edit=True,
            )
        db.execute(
            'UPDATE bank_accounts SET bank_name=?, account_number=?, ifsc_code=?, micr_code=?, '
            'bank_address=?, account_type=?, current_balance=?, interest_rate=?, currency=?, '
            'notes=?, updated_at=? WHERE id=? AND user_id=?',
            (*values, now(), account_id, session['uid']),
        )
        db.commit()
        audit('BANK_ACCOUNT_UPDATE', account_id)
        flash('Bank account updated.', 'success')
        return redirect(url_for('bank_accounts'))

    account = dict(row)
    try:
        account['account_number'] = cipher.decrypt(row['account_number']).decode()
    except (InvalidToken, UnicodeDecodeError):
        account['account_number'] = ''
        flash('The stored account number could not be decrypted. Enter it again before saving.', 'warning')

    return render_template(
        'bank_account_edit.html',
        account=account,
        account_id=account_id,
        account_types=ACCOUNT_TYPES,
        currencies=CURRENCIES,
        is_edit=True,
    )


@app.post('/bank-accounts/<int:account_id>/delete')
@login_required
def bank_account_delete(account_id):
    cursor = get_db().execute(
        'DELETE FROM bank_accounts WHERE id=? AND user_id=?',
        (account_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('BANK_ACCOUNT_DELETE', account_id)
    flash('Bank account deleted.', 'success')
    return redirect(url_for('bank_accounts'))


# ---------------------------------------------------------------- fixed deposits
def _fd_metrics(row):
    principal = Decimal(str(row['initial_deposit'] or '0'))
    rate_pct = Decimal(str(row['interest_rate'] or '0'))

    try:
        start = datetime.strptime(row['investment_date'], '%Y-%m-%d').date()
        end = datetime.strptime(row['maturity_date'], '%Y-%m-%d').date()
        days = max((end - start).days, 0)
    except (TypeError, ValueError):
        days = 0

    years = Decimal(days) / Decimal('365')
    months = round(days / 30.4375)

    if principal <= 0 or rate_pct <= 0 or years <= 0:
        maturity = principal
        interest = Decimal('0')
    else:
        r = rate_pct / Decimal('100')
        n = Decimal('4')
        base = Decimal('1') + (r / n)
        maturity = principal * Decimal(str(float(base) ** float(n * years)))
        interest = maturity - principal

    return {
        'principal': float(principal),
        'interest': float(interest),
        'maturity': float(maturity),
        'tenure_days': days,
        'tenure_months': months,
        'tenure_years': float(years),
    }


def _parse_fixed_deposit(form):
    bank_name = clean_text(form.get('bank_name'), 120, True)
    account_number = clean_text(form.get('account_number'), 80, True)
    ifsc_code = clean_text(form.get('ifsc_code'), 11, True).upper()
    micr_code = clean_text(form.get('micr_code'), 9, True)
    bank_address = clean_text(form.get('bank_address'), 1000, True)
    initial_deposit = clean_number(form.get('initial_deposit'))
    investment_date = clean_date(form.get('investment_date'))
    maturity_date = clean_date(form.get('maturity_date'))
    interest_rate = clean_number(form.get('interest_rate'))
    currency = form.get('currency', '').upper()
    notes = clean_text(form.get('notes'), 1000)

    if not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', ifsc_code):
        raise ValueError('Enter a valid 11-character IFSC code.')
    if not re.fullmatch(r'\d{9}', micr_code):
        raise ValueError('Enter a valid 9-digit MICR code.')
    if not investment_date or not maturity_date:
        raise ValueError('Investment and maturity dates are required.')
    if maturity_date <= investment_date:
        raise ValueError('Maturity date must be later than investment date.')
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')

    return (
        bank_name, cipher.encrypt(account_number.encode()), ifsc_code, micr_code,
        bank_address, initial_deposit, investment_date, maturity_date,
        interest_rate, currency, notes,
    )


@app.route('/fixed-deposits')
@login_required
def fixed_deposits():
    rows = get_db().execute(
        'SELECT * FROM fixed_deposits WHERE user_id=? ORDER BY maturity_date,bank_name,id',
        (session['uid'],),
    ).fetchall()
    display_rows = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item['display_id'] = index
        item.update(_fd_metrics(row))
        display_rows.append(item)
    return render_template('fixed_deposits.html', rows=display_rows)


@app.route('/fixed-deposits/new', methods=['GET', 'POST'])
@login_required
def fixed_deposit_new():
    if request.method == 'POST':
        try:
            values = _parse_fixed_deposit(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('fixed_deposit_edit.html', deposit=request.form, currencies=CURRENCIES)
        cursor = get_db().execute(
            'INSERT INTO fixed_deposits(user_id,bank_name,account_number,ifsc_code,micr_code,'
            'bank_address,initial_deposit,investment_date,maturity_date,interest_rate,currency,'
            'notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('FIXED_DEPOSIT_CREATE', cursor.lastrowid)
        flash('Fixed deposit saved.', 'success')
        return redirect(url_for('fixed_deposits'))
    return render_template('fixed_deposit_edit.html', deposit={}, currencies=CURRENCIES)


@app.route('/fixed-deposits/<int:deposit_id>/edit', methods=['GET', 'POST'])
@login_required
def fixed_deposit_edit(deposit_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM fixed_deposits WHERE id=? AND user_id=?',
        (deposit_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        try:
            values = _parse_fixed_deposit(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'fixed_deposit_edit.html',
                deposit=request.form,
                deposit_id=deposit_id,
                currencies=CURRENCIES,
            )
        db.execute(
            'UPDATE fixed_deposits SET bank_name=?, account_number=?, ifsc_code=?, micr_code=?, '
            'bank_address=?, initial_deposit=?, investment_date=?, maturity_date=?, interest_rate=?, '
            'currency=?, notes=?, updated_at=? WHERE id=? AND user_id=?',
            (*values, now(), deposit_id, session['uid']),
        )
        db.commit()
        audit('FIXED_DEPOSIT_UPDATE', deposit_id)
        flash('Fixed deposit updated.', 'success')
        return redirect(url_for('fixed_deposits'))

    deposit = dict(row)
    try:
        deposit['account_number'] = cipher.decrypt(row['account_number']).decode()
    except (InvalidToken, UnicodeDecodeError):
        deposit['account_number'] = ''
        flash('The stored account number could not be decrypted. Enter it again before saving.', 'warning')
    return render_template(
        'fixed_deposit_edit.html',
        deposit=deposit,
        deposit_id=deposit_id,
        currencies=CURRENCIES,
    )


@app.post('/fixed-deposits/<int:deposit_id>/delete')
@login_required
def fixed_deposit_delete(deposit_id):
    cursor = get_db().execute(
        'DELETE FROM fixed_deposits WHERE id=? AND user_id=?',
        (deposit_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('FIXED_DEPOSIT_DELETE', deposit_id)
    flash('Fixed deposit deleted.', 'success')
    return redirect(url_for('fixed_deposits'))


# ---------------------------------------------------------------- recurring deposits
def _rd_metrics(row):
    monthly = Decimal(str(row['monthly_deposit'] or '0'))
    rate_pct = Decimal(str(row['interest_rate'] or '0'))

    try:
        start = datetime.strptime(row['start_date'], '%Y-%m-%d').date()
        end = datetime.strptime(row['maturity_date'], '%Y-%m-%d').date()
        days = max((end - start).days, 0)
    except (TypeError, ValueError):
        days = 0

    months = max(round(days / 30.4375), 0)
    invested = Decimal(str(row['amount_invested'] or '0'))

    if monthly <= 0 or rate_pct <= 0 or months <= 0:
        maturity = invested
        gain = Decimal('0')
    else:
        i = rate_pct / Decimal('100') / Decimal('12')
        n = Decimal(months)
        base = Decimal('1') + i
        growth = Decimal(str(float(base) ** float(n)))
        maturity = monthly * ((growth - Decimal('1')) / i) * base
        gain = maturity - invested

    return {
        'monthly': float(monthly),
        'invested': float(invested),
        'gain': float(gain),
        'maturity': float(maturity),
        'tenure_days': days,
        'tenure_months': months,
        'tenure_years': float(Decimal(days) / Decimal('365')),
    }


def _parse_recurring_deposit(form):
    bank = clean_text(form.get('bank_name'), 120, True)
    account = clean_text(form.get('account_number'), 80, True)
    monthly = clean_number(form.get('monthly_deposit'))
    invested = clean_number(form.get('amount_invested'))
    current = clean_number(form.get('current_value'))

    try:
        day = int(form.get('deposit_day', '0'))
    except ValueError:
        raise ValueError('Deposit Day must be between 1 and 31.')
    if not 1 <= day <= 31 or Decimal(monthly) <= 0:
        raise ValueError('Enter a valid Deposit Day and Monthly Deposit.')

    start = clean_date(form.get('start_date'))
    maturity = clean_date(form.get('maturity_date'))
    if not start or not maturity or maturity <= start:
        raise ValueError('Maturity Date must be later than Start Date.')

    rate = clean_number(form.get('interest_rate'))
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')

    notes = clean_text(form.get('notes'), 1000)
    return (
        bank, cipher.encrypt(account.encode()), monthly, day, invested,
        current, start, maturity, rate, currency, notes,
    )


@app.route('/recurring-deposits')
@login_required
def recurring_deposits():
    rows = get_db().execute(
        'SELECT * FROM recurring_deposits WHERE user_id=? ORDER BY maturity_date,bank_name,id',
        (session['uid'],),
    ).fetchall()
    display_rows = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item['display_id'] = index
        item.update(_rd_metrics(row))
        display_rows.append(item)
    return render_template('recurring_deposits.html', rows=display_rows)


@app.route('/recurring-deposits/new', methods=['GET', 'POST'])
@login_required
def recurring_deposit_new():
    if request.method == 'POST':
        try:
            values = _parse_recurring_deposit(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('recurring_deposit_edit.html', deposit=request.form, currencies=CURRENCIES)
        cursor = get_db().execute(
            'INSERT INTO recurring_deposits(user_id,bank_name,account_number,monthly_deposit,'
            'deposit_day,amount_invested,current_value,start_date,maturity_date,interest_rate,'
            'currency,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('RECURRING_DEPOSIT_CREATE', cursor.lastrowid)
        flash('Recurring deposit saved.', 'success')
        return redirect(url_for('recurring_deposits'))
    return render_template('recurring_deposit_edit.html', deposit={}, currencies=CURRENCIES)


@app.route('/recurring-deposits/<int:deposit_id>/edit', methods=['GET', 'POST'])
@login_required
def recurring_deposit_edit(deposit_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM recurring_deposits WHERE id=? AND user_id=?',
        (deposit_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        try:
            values = _parse_recurring_deposit(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'recurring_deposit_edit.html',
                deposit=request.form,
                deposit_id=deposit_id,
                currencies=CURRENCIES,
            )
        db.execute(
            'UPDATE recurring_deposits SET bank_name=?, account_number=?, monthly_deposit=?, '
            'deposit_day=?, amount_invested=?, current_value=?, start_date=?, maturity_date=?, '
            'interest_rate=?, currency=?, notes=?, updated_at=? WHERE id=? AND user_id=?',
            (*values, now(), deposit_id, session['uid']),
        )
        db.commit()
        audit('RECURRING_DEPOSIT_UPDATE', deposit_id)
        flash('Recurring deposit updated.', 'success')
        return redirect(url_for('recurring_deposits'))

    deposit = dict(row)
    try:
        deposit['account_number'] = cipher.decrypt(row['account_number']).decode()
    except (InvalidToken, UnicodeDecodeError):
        deposit['account_number'] = ''
    return render_template(
        'recurring_deposit_edit.html',
        deposit=deposit,
        deposit_id=deposit_id,
        currencies=CURRENCIES,
    )


@app.post('/recurring-deposits/<int:deposit_id>/delete')
@login_required
def recurring_deposit_delete(deposit_id):
    cursor = get_db().execute(
        'DELETE FROM recurring_deposits WHERE id=? AND user_id=?',
        (deposit_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('RECURRING_DEPOSIT_DELETE', deposit_id)
    flash('Recurring deposit deleted.', 'success')
    return redirect(url_for('recurring_deposits'))


# ---------------------------------------------------------------- stocks
def _stock_form_values(form):
    market = form.get('market', '')
    if market not in ('India', 'United States'):
        raise ValueError('Invalid stock market.')

    if market == 'United States':
        ticker = clean_text(form.get('ticker'), 20, True).upper()
        stock_symbol = None
        company_name = clean_text(form.get('company_name'), 120, True)
        stock_name = company_name
        isin_code = None
        currency = 'USD'

        us_total_invested = clean_number(form.get('us_total_invested'))
        us_current_value = clean_number(form.get('us_current_value'))

        # The stocks table still requires these columns; store neutral values.
        units = '1'
        buy_price = '0'
        current_price = '0'
    else:
        stock_symbol = clean_text(form.get('stock_symbol'), 20, True).upper()
        company_name = clean_text(form.get('company_name'), 120, True)
        stock_name = company_name
        ticker = None
        isin_code = clean_text(form.get('isin_code'), 12, True).upper()
        if not re.fullmatch(r'IN[A-Z0-9]{10}', isin_code):
            raise ValueError('ISIN must be 12 characters starting with IN.')
        currency = 'INR'

        us_total_invested = '0'
        us_current_value = '0'

        units = clean_number(form.get('number_of_shares'))
        if Decimal(units) <= 0:
            raise ValueError('Quantity must be greater than zero.')
        buy_price = clean_number(form.get('buy_price'))
        current_price = clean_number(form.get('current_price'))

    buy_date = clean_date(form.get('buy_transaction_date'))
    if not buy_date:
        raise ValueError('Buy Transaction Date is required.')

    sale_date = clean_date(form.get('sale_date'))
    sale_units = clean_number(form.get('sale_units'))
    sell_price = clean_number(form.get('sell_price'))
    if sale_date and sale_date < buy_date:
        raise ValueError('Sale Date cannot be before Buy Transaction Date.')

    realized_pnl = clean_signed_number(form.get('realized_profit_loss'))

    fees = (
        clean_number(form.get('gst')),
        clean_number(form.get('brokerage')),
        clean_number(form.get('stt')),
        clean_number(form.get('exchange_fees')),
    )
    notes = clean_text(form.get('notes'), 1000)

    # previous_close is retained in the schema but no longer collected from the form.
    return (
        stock_name, ticker, stock_symbol, company_name, isin_code, market,
        units, buy_price, current_price, '0', buy_date, currency,
        sale_date, sale_units, sell_price, *fees, realized_pnl,
        us_total_invested, us_current_value, notes,
    )


@app.route('/stocks')
@login_required
def stocks():
    db = get_db()
    uid = session['uid']

    rows = db.execute(
        'SELECT * FROM stocks WHERE user_id=? '
        'ORDER BY market, UPPER(TRIM(stock_name)), buy_transaction_date, id',
        (uid,),
    ).fetchall()

    def build_row(row):
        keys = row.keys()
        sale_units = float(row['sale_units'] or 0)
        sell_price = float(row['sell_price'] or 0)

        fees_total = sum(
            float(row[k] or 0) for k in ('gst', 'brokerage', 'stt', 'exchange_fees')
            if k in keys
        )

        us_invested = float(row['us_total_invested'] or 0) if 'us_total_invested' in keys else 0.0
        us_value = float(row['us_current_value'] or 0) if 'us_current_value' in keys else 0.0
        use_us_values = row['market'] == 'United States' and (us_invested > 0 or us_value > 0)

        if use_us_values:
            units = 0.0
            buy_price = 0.0
            current_price = 0.0
            previous_close = 0.0
            remaining = 0.0
            original_cost = us_invested
            total_invested = us_invested
            current_value = us_value
        else:
            units = float(row['number_of_shares'] or 0)
            buy_price = float(row['buy_price'] or 0)
            current_price = float(row['current_price'] or 0)
            previous_close = float(row['previous_close'] or 0)
            remaining = max(units - sale_units, 0)
            original_cost = (units * buy_price) + fees_total
            total_invested = (remaining * buy_price) + fees_total
            current_value = remaining * current_price

        unrealized = current_value - total_invested
        unrealized_pct = (unrealized / total_invested * 100) if total_invested else 0

        realized = float(row['realized_profit_loss'] or 0) if 'realized_profit_loss' in keys else 0.0
        if realized == 0 and sale_units > 0 and not use_us_values:
            realized = sale_units * (sell_price - buy_price)

        change_pct = ((current_price - previous_close) / previous_close * 100) if previous_close else 0

        item = dict(row)
        item.update({
            'units': units,
            'remaining_units': remaining,
            'buy_price': buy_price,
            'current_price': current_price,
            'previous_close': previous_close,
            'original_cost': original_cost,
            'total_invested': total_invested,
            'current_value': current_value,
            'unrealized': unrealized,
            'unrealized_pct': unrealized_pct,
            'realized': realized,
            'change_pct': change_pct,
            'use_us_values': use_us_values,
        })
        return item

    us_rows = [build_row(r) for r in rows if r['market'] == 'United States']
    india_rows = [build_row(r) for r in rows if r['market'] == 'India']

    summary = {}
    for item in us_rows + india_rows:
        code = item['currency']
        bucket = summary.setdefault(code, {'invested': 0.0, 'current': 0.0, 'count': 0})
        bucket['invested'] += item['total_invested']
        bucket['current'] += item['current_value']
        bucket['count'] += 1

    return render_template(
        'stocks.html',
        us_rows=us_rows,
        india_rows=india_rows,
        summary=summary,
    )


@app.route('/stocks/new', methods=['GET', 'POST'])
@login_required
def stock_new():
    if request.method == 'POST':
        try:
            values = _stock_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('stock_edit.html', stock=request.form, is_edit=False)
        cursor = get_db().execute(
            '''INSERT INTO stocks(user_id,stock_name,ticker,stock_symbol,company_name,isin_code,
               market,number_of_shares,buy_price,current_price,previous_close,buy_transaction_date,
               currency,sale_date,sale_units,sell_price,gst,brokerage,stt,exchange_fees,
               realized_profit_loss,us_total_invested,us_current_value,notes,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('STOCK_CREATE', cursor.lastrowid)
        flash('Stock transaction saved.', 'success')
        return redirect(url_for('stocks'))
    return render_template('stock_edit.html', stock={}, is_edit=False)


@app.route('/stocks/<int:stock_id>/edit', methods=['GET', 'POST'])
@login_required
def stock_edit(stock_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM stocks WHERE id=? AND user_id=?',
        (stock_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        try:
            values = _stock_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'stock_edit.html',
                stock=request.form,
                stock_id=stock_id,
                is_edit=True,
            )
        db.execute(
            '''UPDATE stocks SET stock_name=?, ticker=?, stock_symbol=?, company_name=?, isin_code=?,
               market=?, number_of_shares=?, buy_price=?, current_price=?, previous_close=?,
               buy_transaction_date=?, currency=?, sale_date=?, sale_units=?, sell_price=?,
               gst=?, brokerage=?, stt=?, exchange_fees=?, realized_profit_loss=?,
               us_total_invested=?, us_current_value=?, notes=?,
               updated_at=? WHERE id=? AND user_id=?''',
            (*values, now(), stock_id, session['uid']),
        )
        db.commit()
        audit('STOCK_UPDATE', stock_id)
        flash('Stock transaction updated.', 'success')
        return redirect(url_for('stocks'))

    return render_template(
        'stock_edit.html',
        stock=row,
        stock_id=stock_id,
        is_edit=True,
    )


@app.post('/stocks/<int:stock_id>/delete')
@login_required
def stock_delete(stock_id):
    """Delete every lot belonging to the same (stock_name, market, currency) group."""
    db = get_db()
    row = db.execute(
        'SELECT stock_name, market, currency FROM stocks WHERE id=? AND user_id=?',
        (stock_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)
    cursor = db.execute(
        'DELETE FROM stocks WHERE user_id=? '
        'AND UPPER(TRIM(stock_name))=UPPER(TRIM(?)) AND market=? AND currency=?',
        (session['uid'], row['stock_name'], row['market'], row['currency']),
    )
    db.commit()
    audit('STOCK_DELETE_GROUP', stock_id)
    removed = cursor.rowcount
    flash(f"Deleted {removed} stock {'lot' if removed == 1 else 'lots'} for {row['stock_name']}.", 'success')
    return redirect(url_for('stocks'))


@app.post('/stocks/<int:stock_id>/delete-lot')
@login_required
def stock_delete_lot(stock_id):
    """Delete a single stock lot."""
    cursor = get_db().execute(
        'DELETE FROM stocks WHERE id=? AND user_id=?', (stock_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('STOCK_DELETE_LOT', stock_id)
    flash('Stock lot deleted.', 'success')
    return redirect(url_for('stocks'))


# ---------------------------------------------------------------- ESOPs
def _esop_form_values(form):
    company_name = clean_text(form.get('company_name'), 120, True)
    units = clean_number(form.get('number_of_units'))
    if Decimal(units) <= 0:
        raise ValueError('Units must be greater than zero.')
    grant_price = clean_number(form.get('grant_price'))
    current_price = clean_number(form.get('current_price'))
    grant_date = clean_date(form.get('grant_date'))
    if not grant_date:
        raise ValueError('Grant Date is required.')
    vesting_date = clean_date(form.get('vesting_date'))
    if vesting_date and vesting_date < grant_date:
        raise ValueError('Vesting Date cannot be before Grant Date.')
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')
    notes = clean_text(form.get('notes'), 1000)
    return (company_name, grant_date, vesting_date, units, grant_price, current_price, currency, notes)


@app.route('/esops')
@login_required
def esops():
    db = get_db()
    uid = session['uid']

    lots = db.execute(
        'SELECT * FROM esops WHERE user_id=? ORDER BY UPPER(TRIM(company_name)), grant_date, id',
        (uid,),
    ).fetchall()

    rows = db.execute(
        '''
        SELECT MIN(id) AS first_id, MIN(company_name) AS company_name, currency,
        COUNT(*) AS lot_count,
        SUM(CAST(number_of_units AS REAL)) AS total_units,
        SUM(CAST(number_of_units AS REAL) * CAST(grant_price AS REAL)) AS total_cost_price,
        SUM(CAST(number_of_units AS REAL) * CAST(current_price AS REAL)) AS current_holding_value
        FROM esops WHERE user_id=?
        GROUP BY UPPER(TRIM(company_name)), currency
        ORDER BY UPPER(TRIM(company_name))
        ''',
        (uid,),
    ).fetchall()

    holdings = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item['display_id'] = index
        item['profit_loss'] = item['current_holding_value'] - item['total_cost_price']
        item['return_percentage'] = (
            item['profit_loss'] / item['total_cost_price'] * 100
        ) if item['total_cost_price'] else 0
        holdings.append(item)

    detail_rows = []
    for index, row in enumerate(lots, start=1):
        item = dict(row)
        item['display_id'] = index
        detail_rows.append(item)

    return render_template('esops.html', rows=holdings, lots=detail_rows)


@app.route('/esops/new', methods=['GET', 'POST'])
@login_required
def esop_new():
    if request.method == 'POST':
        try:
            values = _esop_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('esop_edit.html', esop=request.form, currencies=CURRENCIES)
        cursor = get_db().execute(
            '''INSERT INTO esops(user_id,company_name,grant_date,vesting_date,number_of_units,
               grant_price,current_price,currency,notes,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('ESOP_CREATE', cursor.lastrowid)
        flash('ESOP record saved.', 'success')
        return redirect(url_for('esops'))
    return render_template('esop_edit.html', esop={}, currencies=CURRENCIES)


@app.route('/esops/<int:esop_id>/edit', methods=['GET', 'POST'])
@login_required
def esop_edit(esop_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM esops WHERE id=? AND user_id=?', (esop_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)
    if request.method == 'POST':
        try:
            values = _esop_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('esop_edit.html', esop=request.form, esop_id=esop_id, currencies=CURRENCIES)
        db.execute(
            '''UPDATE esops SET company_name=?,grant_date=?,vesting_date=?,number_of_units=?,
               grant_price=?,current_price=?,currency=?,notes=?,updated_at=?
               WHERE id=? AND user_id=?''',
            (*values, now(), esop_id, session['uid']),
        )
        db.commit()
        audit('ESOP_UPDATE', esop_id)
        flash('ESOP record updated.', 'success')
        return redirect(url_for('esops'))
    return render_template('esop_edit.html', esop=row, esop_id=esop_id, currencies=CURRENCIES)


@app.post('/esops/<int:esop_id>/delete')
@login_required
def esop_delete(esop_id):
    """Delete every grant belonging to the same (company_name, currency) group."""
    db = get_db()
    row = db.execute(
        'SELECT company_name, currency FROM esops WHERE id=? AND user_id=?',
        (esop_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)
    cursor = db.execute(
        'DELETE FROM esops WHERE user_id=? '
        'AND UPPER(TRIM(company_name))=UPPER(TRIM(?)) AND currency=?',
        (session['uid'], row['company_name'], row['currency']),
    )
    db.commit()
    audit('ESOP_DELETE_GROUP', esop_id)
    removed = cursor.rowcount
    flash(f"Deleted {removed} ESOP {'grant' if removed == 1 else 'grants'} for {row['company_name']}.", 'success')
    return redirect(url_for('esops'))


@app.post('/esops/<int:esop_id>/delete-lot')
@login_required
def esop_delete_lot(esop_id):
    """Delete a single ESOP grant."""
    cursor = get_db().execute(
        'DELETE FROM esops WHERE id=? AND user_id=?', (esop_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('ESOP_DELETE_LOT', esop_id)
    flash('ESOP grant deleted.', 'success')
    return redirect(url_for('esops'))


# ---------------------------------------------------------------- mutual funds
def _mutual_fund_form_values(form):
    fund_house = clean_text(form.get('fund_house'), 120, True)
    fund_name = clean_text(form.get('fund_name'), 160, True)
    fund_category = clean_text(form.get('fund_category'), 100, True)
    invested_amount = clean_number(form.get('invested_amount'))
    if Decimal(invested_amount) <= 0:
        raise ValueError('Invested Amount must be greater than zero.')
    current_value = clean_number(form.get('current_value'))
    investment_mode = form.get('investment_mode', '')
    if investment_mode not in {'SIP', 'LUMPSUM'}:
        raise ValueError('Select SIP or Lumpsum.')
    investment_date = clean_date(form.get('investment_date'))
    if not investment_date:
        raise ValueError('Date of SIP / Investment is required.')
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')
    return (
        fund_house, fund_name, fund_category, invested_amount,
        current_value, investment_mode, investment_date, currency,
    )


@app.route('/mutual-funds')
@login_required
def mutual_funds():
    rows = get_db().execute(
        'SELECT * FROM mutual_funds WHERE user_id=? ORDER BY fund_house,fund_name,investment_date',
        (session['uid'],),
    ).fetchall()
    return render_template('mutual_funds.html', rows=[
        {**dict(row), 'display_id': i + 1} for i, row in enumerate(rows)
    ])


@app.route('/mutual-funds/new', methods=['GET', 'POST'])
@login_required
def mutual_fund_new():
    if request.method == 'POST':
        try:
            values = _mutual_fund_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('mutual_fund_edit.html', fund=request.form, currencies=CURRENCIES)
        cursor = get_db().execute(
            '''INSERT INTO mutual_funds(user_id,fund_house,fund_name,fund_category,invested_amount,
               current_value,investment_mode,investment_date,currency,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('MUTUAL_FUND_CREATE', cursor.lastrowid)
        flash('Mutual fund saved.', 'success')
        return redirect(url_for('mutual_funds'))
    return render_template('mutual_fund_edit.html', fund={}, currencies=CURRENCIES)


@app.route('/mutual-funds/<int:fund_id>/edit', methods=['GET', 'POST'])
@login_required
def mutual_fund_edit(fund_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM mutual_funds WHERE id=? AND user_id=?', (fund_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)
    if request.method == 'POST':
        try:
            values = _mutual_fund_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('mutual_fund_edit.html', fund=request.form, fund_id=fund_id, currencies=CURRENCIES)
        db.execute(
            '''UPDATE mutual_funds SET fund_house=?,fund_name=?,fund_category=?,invested_amount=?,
               current_value=?,investment_mode=?,investment_date=?,currency=?,updated_at=?
               WHERE id=? AND user_id=?''',
            (*values, now(), fund_id, session['uid']),
        )
        db.commit()
        audit('MUTUAL_FUND_UPDATE', fund_id)
        flash('Mutual fund updated.', 'success')
        return redirect(url_for('mutual_funds'))
    return render_template('mutual_fund_edit.html', fund=row, fund_id=fund_id, currencies=CURRENCIES)


@app.post('/mutual-funds/<int:fund_id>/delete')
@login_required
def mutual_fund_delete(fund_id):
    cursor = get_db().execute(
        'DELETE FROM mutual_funds WHERE id=? AND user_id=?', (fund_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('MUTUAL_FUND_DELETE', fund_id)
    flash('Mutual fund deleted.', 'success')
    return redirect(url_for('mutual_funds'))


# ---------------------------------------------------------------- metals
def _metal_form_values(form):
    metal_type = form.get('metal_type', '')
    product_form = form.get('product_form', '')
    if metal_type not in METAL_TYPES:
        raise ValueError('Select a valid Type of Metal.')
    if product_form not in METAL_PRODUCT_FORMS:
        raise ValueError('Select a valid Form / Product.')
    weight = clean_number(form.get('weight'))
    if Decimal(weight) <= 0:
        raise ValueError('Weight must be greater than zero.')
    weight_unit = form.get('weight_unit', '')
    if weight_unit not in {'GRAM', 'TROY_OUNCE'}:
        raise ValueError('Select Grams or Troy Ounces.')
    purity = clean_text(form.get('purity'), 30, True)
    mint_brand = clean_text(form.get('mint_brand'), 120, True)
    investment_amount = clean_number(form.get('investment_amount'))
    if Decimal(investment_amount) <= 0:
        raise ValueError('Investment Amount must be greater than zero.')
    current_value = clean_number(form.get('current_value'))
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')
    return (
        metal_type, product_form, weight, weight_unit, purity,
        mint_brand, investment_amount, current_value, currency,
    )


@app.route('/metals')
@login_required
def metals():
    rows = get_db().execute(
        'SELECT * FROM metals WHERE user_id=? ORDER BY metal_type,product_form,mint_brand',
        (session['uid'],),
    ).fetchall()
    return render_template('metals.html', rows=[
        {**dict(row), 'display_id': i + 1} for i, row in enumerate(rows)
    ])


@app.route('/metals/new', methods=['GET', 'POST'])
@login_required
def metal_new():
    if request.method == 'POST':
        try:
            values = _metal_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'metal_edit.html', metal=request.form, currencies=CURRENCIES,
                metal_types=METAL_TYPES, product_forms=METAL_PRODUCT_FORMS,
            )
        cursor = get_db().execute(
            '''INSERT INTO metals(user_id,metal_type,product_form,weight,weight_unit,purity,
               mint_brand,investment_amount,current_value,currency,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('METAL_CREATE', cursor.lastrowid)
        flash('Metal investment saved.', 'success')
        return redirect(url_for('metals'))
    return render_template(
        'metal_edit.html', metal={}, currencies=CURRENCIES,
        metal_types=METAL_TYPES, product_forms=METAL_PRODUCT_FORMS,
    )


@app.route('/metals/<int:metal_id>/edit', methods=['GET', 'POST'])
@login_required
def metal_edit(metal_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM metals WHERE id=? AND user_id=?', (metal_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)
    if request.method == 'POST':
        try:
            values = _metal_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'metal_edit.html', metal=request.form, metal_id=metal_id,
                currencies=CURRENCIES, metal_types=METAL_TYPES,
                product_forms=METAL_PRODUCT_FORMS,
            )
        db.execute(
            '''UPDATE metals SET metal_type=?,product_form=?,weight=?,weight_unit=?,purity=?,
               mint_brand=?,investment_amount=?,current_value=?,currency=?,updated_at=?
               WHERE id=? AND user_id=?''',
            (*values, now(), metal_id, session['uid']),
        )
        db.commit()
        audit('METAL_UPDATE', metal_id)
        flash('Metal investment updated.', 'success')
        return redirect(url_for('metals'))
    return render_template(
        'metal_edit.html', metal=row, metal_id=metal_id,
        currencies=CURRENCIES, metal_types=METAL_TYPES,
        product_forms=METAL_PRODUCT_FORMS,
    )


@app.post('/metals/<int:metal_id>/delete')
@login_required
def metal_delete(metal_id):
    cursor = get_db().execute(
        'DELETE FROM metals WHERE id=? AND user_id=?', (metal_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('METAL_DELETE', metal_id)
    flash('Metal investment deleted.', 'success')
    return redirect(url_for('metals'))


# ---------------------------------------------------------------- liabilities
def _liability_form_values(form, include_account=True):
    lender_name = clean_text(form.get('lender_name'), 160, True)
    liability_type = form.get('liability_type', '')
    status = form.get('status', '')
    if liability_type not in LIABILITY_TYPES:
        raise ValueError('Select a valid Liability Type.')
    if status not in LIABILITY_STATUSES:
        raise ValueError('Select a valid liability Status.')

    original_principal = clean_number(form.get('original_principal'))
    if Decimal(original_principal) <= 0:
        raise ValueError('Original Principal Amount must be greater than zero.')
    current_balance = clean_number(form.get('current_balance'))
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')

    origination_date = clean_date(form.get('origination_date'))
    maturity_date = clean_date(form.get('maturity_date'))
    if not origination_date or not maturity_date:
        raise ValueError('Origination and Maturity dates are required.')
    if maturity_date < origination_date:
        raise ValueError('Maturity / End Date cannot be before Origination Date.')

    interest_rate = clean_number(form.get('interest_rate'))
    rate_type = form.get('rate_type', '')
    if rate_type not in {'FIXED', 'VARIABLE'}:
        raise ValueError('Select Fixed or Variable interest.')

    payment_frequency = form.get('payment_frequency', '')
    payment_method = form.get('payment_method', '')
    if payment_frequency not in PAYMENT_FREQUENCIES:
        raise ValueError('Select a valid Payment Frequency.')
    if payment_method not in PAYMENT_METHODS:
        raise ValueError('Select a valid Payment Method.')

    regular_payment = clean_number(form.get('regular_payment'))
    emi_date = clean_date(form.get('emi_date'))
    if not emi_date:
        raise ValueError('EMI Date is required.')

    notes = clean_text(form.get('notes'), 1000)

    if include_account:
        account_number = clean_text(form.get('account_number'), 100, True)
        return (
            lender_name, cipher.encrypt(account_number.encode()), liability_type,
            status, original_principal, current_balance, currency,
            origination_date, maturity_date, interest_rate, rate_type,
            payment_frequency, regular_payment, payment_method, emi_date, notes,
        )

    return (
        lender_name, liability_type, status, original_principal, current_balance,
        currency, origination_date, maturity_date, interest_rate, rate_type,
        payment_frequency, regular_payment, payment_method, emi_date, notes,
    )


@app.route('/liabilities')
@login_required
def liabilities():
    rows = get_db().execute(
        'SELECT * FROM liabilities WHERE user_id=? ORDER BY status,lender_name,maturity_date',
        (session['uid'],),
    ).fetchall()
    return render_template('liabilities.html', rows=[
        {**dict(row), 'display_id': i + 1} for i, row in enumerate(rows)
    ])


@app.route('/liabilities/new', methods=['GET', 'POST'])
@login_required
def liability_new():
    if request.method == 'POST':
        try:
            values = _liability_form_values(request.form, include_account=True)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'liability_edit.html', liability=request.form, currencies=CURRENCIES,
                liability_types=LIABILITY_TYPES, statuses=LIABILITY_STATUSES,
                payment_frequencies=PAYMENT_FREQUENCIES, payment_methods=PAYMENT_METHODS,
            )
        cursor = get_db().execute(
            '''INSERT INTO liabilities(user_id,lender_name,account_number,liability_type,status,
               original_principal,current_balance,currency,origination_date,maturity_date,
               interest_rate,rate_type,payment_frequency,regular_payment,payment_method,
               emi_date,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('LIABILITY_CREATE', cursor.lastrowid)
        flash('Liability saved.', 'success')
        return redirect(url_for('liabilities'))
    return render_template(
        'liability_edit.html', liability={}, currencies=CURRENCIES,
        liability_types=LIABILITY_TYPES, statuses=LIABILITY_STATUSES,
        payment_frequencies=PAYMENT_FREQUENCIES, payment_methods=PAYMENT_METHODS,
    )


@app.route('/liabilities/<int:liability_id>/edit', methods=['GET', 'POST'])
@login_required
def liability_edit(liability_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM liabilities WHERE id=? AND user_id=?',
        (liability_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)
    if request.method == 'POST':
        try:
            values = _liability_form_values(request.form, include_account=False)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'liability_edit.html', liability=request.form, liability_id=liability_id,
                currencies=CURRENCIES, liability_types=LIABILITY_TYPES,
                statuses=LIABILITY_STATUSES, payment_frequencies=PAYMENT_FREQUENCIES,
                payment_methods=PAYMENT_METHODS,
            )
        db.execute(
            '''UPDATE liabilities SET lender_name=?,liability_type=?,status=?,original_principal=?,
               current_balance=?,currency=?,origination_date=?,maturity_date=?,interest_rate=?,
               rate_type=?,payment_frequency=?,regular_payment=?,payment_method=?,emi_date=?,
               notes=?,updated_at=? WHERE id=? AND user_id=?''',
            (*values, now(), liability_id, session['uid']),
        )
        db.commit()
        audit('LIABILITY_UPDATE', liability_id)
        flash('Liability updated.', 'success')
        return redirect(url_for('liabilities'))
    return render_template(
        'liability_edit.html', liability=row, liability_id=liability_id,
        currencies=CURRENCIES, liability_types=LIABILITY_TYPES,
        statuses=LIABILITY_STATUSES, payment_frequencies=PAYMENT_FREQUENCIES,
        payment_methods=PAYMENT_METHODS,
    )


@app.post('/liabilities/<int:liability_id>/delete')
@login_required
def liability_delete(liability_id):
    cursor = get_db().execute(
        'DELETE FROM liabilities WHERE id=? AND user_id=?',
        (liability_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('LIABILITY_DELETE', liability_id)
    flash('Liability deleted.', 'success')
    return redirect(url_for('liabilities'))


# ---------------------------------------------------------------- retirals
def _retiral_form_values(form):
    fund_type = form.get('fund_type', '')
    if fund_type not in RETIRAL_FUND_TYPES:
        raise ValueError('Select a valid Retiral Fund type.')
    amount_invested = clean_number(form.get('amount_invested'))
    current_value = clean_number(form.get('current_value'))
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')
    notes = clean_text(form.get('notes'), 1000)
    return (fund_type, amount_invested, current_value, currency, notes)


@app.route('/retirals')
@login_required
def retirals():
    rows = get_db().execute(
        'SELECT * FROM retirals WHERE user_id=? ORDER BY fund_type,id',
        (session['uid'],),
    ).fetchall()
    return render_template('retirals.html', rows=[
        {**dict(row), 'display_id': i + 1} for i, row in enumerate(rows)
    ])


@app.route('/retirals/new', methods=['GET', 'POST'])
@login_required
def retiral_new():
    if request.method == 'POST':
        try:
            values = _retiral_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'retiral_edit.html', retiral=request.form,
                fund_types=RETIRAL_FUND_TYPES, currencies=CURRENCIES,
            )
        cursor = get_db().execute(
            'INSERT INTO retirals(user_id,fund_type,amount_invested,current_value,currency,'
            'notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (session['uid'], *values, now(), now()),
        )
        get_db().commit()
        audit('RETIRAL_CREATE', cursor.lastrowid)
        flash('Retiral fund saved.', 'success')
        return redirect(url_for('retirals'))
    return render_template(
        'retiral_edit.html', retiral={},
        fund_types=RETIRAL_FUND_TYPES, currencies=CURRENCIES,
    )


@app.route('/retirals/<int:retiral_id>/edit', methods=['GET', 'POST'])
@login_required
def retiral_edit(retiral_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM retirals WHERE id=? AND user_id=?',
        (retiral_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)
    if request.method == 'POST':
        try:
            values = _retiral_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'retiral_edit.html', retiral=request.form, retiral_id=retiral_id,
                fund_types=RETIRAL_FUND_TYPES, currencies=CURRENCIES,
            )
        db.execute(
            'UPDATE retirals SET fund_type=?,amount_invested=?,current_value=?,currency=?,'
            'notes=?,updated_at=? WHERE id=? AND user_id=?',
            (*values, now(), retiral_id, session['uid']),
        )
        db.commit()
        audit('RETIRAL_UPDATE', retiral_id)
        flash('Retiral fund updated.', 'success')
        return redirect(url_for('retirals'))
    return render_template(
        'retiral_edit.html', retiral=row, retiral_id=retiral_id,
        fund_types=RETIRAL_FUND_TYPES, currencies=CURRENCIES,
    )


@app.post('/retirals/<int:retiral_id>/delete')
@login_required
def retiral_delete(retiral_id):
    cursor = get_db().execute(
        'DELETE FROM retirals WHERE id=? AND user_id=?',
        (retiral_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('RETIRAL_DELETE', retiral_id)
    flash('Retiral fund deleted.', 'success')
    return redirect(url_for('retirals'))


# ---------------------------------------------------------------- budgets
def _budget_form_values(form):
    category = clean_text(form.get('category'), 100, True)
    monthly_limit = clean_number(form.get('monthly_limit'))
    if Decimal(monthly_limit) <= 0:
        raise ValueError('Monthly limit must be greater than zero.')
    currency = form.get('currency', '').upper()
    if currency not in CURRENCIES:
        raise ValueError('Invalid currency.')
    notes = clean_text(form.get('notes'), 500)
    return (category, monthly_limit, currency, notes)


def _budget_summary_for_month(db, uid, month):
    budget_rows = db.execute(
        'SELECT * FROM budgets WHERE user_id=? ORDER BY currency, category',
        (uid,),
    ).fetchall()

    spend_rows = db.execute(
        '''
        SELECT category, currency, SUM(CAST(amount AS REAL)) AS spent
        FROM transactions
        WHERE user_id=? AND transaction_type='EXPENSE' AND substr(transaction_date,1,7)=?
        GROUP BY category, currency
        ''',
        (uid, month),
    ).fetchall()
    spend_map = {
        (r['category'].strip().lower(), r['currency']): float(r['spent'] or 0)
        for r in spend_rows
    }

    rows = []
    for row in budget_rows:
        item = dict(row)
        limit = float(row['monthly_limit'] or 0)
        spent = spend_map.get((row['category'].strip().lower(), row['currency']), 0.0)
        item['limit'] = limit
        item['spent'] = spent
        item['remaining'] = limit - spent
        item['percent'] = (spent / limit * 100) if limit else 0
        item['over'] = spent > limit
        rows.append(item)

    summary = {}
    for row in rows:
        code = row['currency']
        if code not in summary:
            summary[code] = {'limit': 0.0, 'spent': 0.0, 'over_count': 0, 'count': 0}
        summary[code]['limit'] += row['limit']
        summary[code]['spent'] += row['spent']
        summary[code]['count'] += 1
        if row['over']:
            summary[code]['over_count'] += 1

    return rows, summary


def _used_categories(db, uid):
    return [
        r['category'] for r in db.execute(
            'SELECT DISTINCT category FROM transactions WHERE user_id=? ORDER BY category',
            (uid,),
        ).fetchall()
    ]


@app.route('/budgets')
@login_required
def budgets():
    db = get_db()
    uid = session['uid']

    today = datetime.now(timezone.utc).date()
    default_month = f'{today.year}-{today.month:02d}'
    selected_month = request.args.get('month', default_month)
    if not re.fullmatch(r'\d{4}-\d{2}', selected_month):
        selected_month = default_month

    rows, summary = _budget_summary_for_month(db, uid, selected_month)

    year, month = map(int, selected_month.split('-'))
    first = today.replace(year=year, month=month, day=1)
    prev_month = (first - timedelta(days=1)).strftime('%Y-%m')
    next_month = f'{year + 1}-01' if month == 12 else f'{year}-{month + 1:02d}'

    return render_template(
        'budgets.html',
        rows=rows,
        summary=summary,
        selected_month=selected_month,
        prev_month=prev_month,
        next_month=next_month,
        used_categories=_used_categories(db, uid),
    )


@app.route('/budgets/new', methods=['GET', 'POST'])
@login_required
def budget_new():
    db = get_db()
    if request.method == 'POST':
        try:
            values = _budget_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'budget_edit.html', budget=request.form,
                currencies=CURRENCIES, used_categories=[],
            )
        cursor = db.execute(
            'INSERT INTO budgets(user_id,category,monthly_limit,currency,notes,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?)',
            (session['uid'], *values, now(), now()),
        )
        db.commit()
        audit('BUDGET_CREATE', cursor.lastrowid)
        flash('Budget saved.', 'success')
        return redirect(url_for('budgets'))
    return render_template(
        'budget_edit.html', budget={}, currencies=CURRENCIES,
        used_categories=_used_categories(db, session['uid']),
    )


@app.route('/budgets/<int:budget_id>/edit', methods=['GET', 'POST'])
@login_required
def budget_edit(budget_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM budgets WHERE id=? AND user_id=?',
        (budget_id, session['uid']),
    ).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        try:
            values = _budget_form_values(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'budget_edit.html', budget=request.form, budget_id=budget_id,
                currencies=CURRENCIES, used_categories=[],
            )
        db.execute(
            'UPDATE budgets SET category=?,monthly_limit=?,currency=?,notes=?,updated_at=? '
            'WHERE id=? AND user_id=?',
            (*values, now(), budget_id, session['uid']),
        )
        db.commit()
        audit('BUDGET_UPDATE', budget_id)
        flash('Budget updated.', 'success')
        return redirect(url_for('budgets'))

    return render_template(
        'budget_edit.html', budget=row, budget_id=budget_id,
        currencies=CURRENCIES, used_categories=_used_categories(db, session['uid']),
    )


@app.post('/budgets/<int:budget_id>/delete')
@login_required
def budget_delete(budget_id):
    cursor = get_db().execute(
        'DELETE FROM budgets WHERE id=? AND user_id=?',
        (budget_id, session['uid']),
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('BUDGET_DELETE', budget_id)
    flash('Budget deleted.', 'success')
    return redirect(url_for('budgets'))


# ---------------------------------------------------------------- errors & CLI
@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(429)
@app.errorhandler(500)
def error_page(error):
    return render_template('error.html', code=getattr(error, 'code', 500)), getattr(error, 'code', 500)


@app.cli.command('ensure-default-user')
def ensure_default_user_command():
    created = ensure_default_user()
    if created:
        click.echo(f'Created default user: {created}')
    else:
        click.echo('Default user already exists.')


@app.cli.command('init-db')
def init_db_command():
    init_db()
    click.echo('Database initialised.')


if __name__ == '__main__':
    init_db()
    ensure_admin_schema()

    print(f'Finance Vault: http://{BIND_HOST}:{BIND_PORT}')
    print(f'Database     : {DB_PATH}')
    _print_startup_credentials()
    print('Portal is now Live. Press Ctrl+C to stop the server.')

    serve(app, host=BIND_HOST, port=BIND_PORT, threads=8)