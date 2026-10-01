import os, re, sqlite3
from datetime import date as today_date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix
from admin_routes import admin_bp, ensure_admin_schema

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
# Each hop must be a proxy you control; a larger count lets clients spoof X-Forwarded-For.
TRUSTED_PROXY_COUNT = max(0, int(os.environ.get('TRUSTED_PROXY_COUNT', '0')))
BIND_HOST = os.environ.get('BIND_HOST', '127.0.0.1').strip() or '127.0.0.1'
BIND_PORT = int(os.environ.get('BIND_PORT', '5555'))

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
limiter = Limiter(get_remote_address, app=app, default_limits=['300 per hour'], storage_uri='memory://')
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
cipher = Fernet(os.environ['DATA_KEY'].encode())
app.extensions['finance_cipher'] = cipher
app.register_blueprint(admin_bp)

CATEGORIES = {
    'BANK': 'Bank Accounts', 'FIXED_DEPOSIT': 'Fixed Deposits',
    'RECURRING_DEPOSIT': 'Recurring Deposits', 'SHARE': 'Stocks',
    'MUTUAL_FUND': 'Mutual Funds', 'METAL': 'Metals', 'ESOP': 'ESOPs',
    'LIABILITY': 'Liabilities', 'OTHER': 'Other investments'
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
    'AUD': 'A$'
}


def currency_symbol(code):
    return CURRENCY_SYMBOLS.get(code, code)
TRANSACTION_TYPES = ('INCOME', 'EXPENSE', 'TRANSFER', 'INVESTMENT', 'LIABILITY_PAYMENT')

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
 stock_name TEXT NOT NULL, market TEXT NOT NULL CHECK(market IN ('India','United States')),
 number_of_shares TEXT NOT NULL, buy_price TEXT NOT NULL,
 current_price TEXT NOT NULL, buy_transaction_date TEXT NOT NULL,
 currency TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT NOT NULL, entity_id INTEGER,
 event_time TEXT NOT NULL, remote_addr TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_user_category ON assets(user_id, category);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, transaction_date DESC);
'''

def now(): return datetime.now(timezone.utc).isoformat()
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
    if connection: connection.close()
def init_db():
    DB_PATH.parent.mkdir(exist_ok=True, mode=0o700)
    connection = sqlite3.connect(DB_PATH)
    connection.executescript(SCHEMA)
    liability_columns={row[1] for row in connection.execute('PRAGMA table_info(liabilities)').fetchall()}
    if 'emi_date' not in liability_columns:
        connection.execute("ALTER TABLE liabilities ADD COLUMN emi_date TEXT")
    stock_columns={row[1] for row in connection.execute('PRAGMA table_info(stocks)').fetchall()}
    for column,definition in {
        'sale_date':'TEXT', 'sale_units':"TEXT NOT NULL DEFAULT '0'", 'sell_price':"TEXT NOT NULL DEFAULT '0'",
        'gst':"TEXT NOT NULL DEFAULT '0'", 'brokerage':"TEXT NOT NULL DEFAULT '0'",
        'stt':"TEXT NOT NULL DEFAULT '0'", 'exchange_fees':"TEXT NOT NULL DEFAULT '0'"
    }.items():
        if column not in stock_columns:
            connection.execute(f'ALTER TABLE stocks ADD COLUMN {column} {definition}')
    connection.execute('INSERT OR IGNORE INTO users(username,password_hash,must_change,created_at) VALUES(?,?,1,?)',
                       (os.environ['DEFAULT_USER'], password_hasher.hash(os.environ['DEFAULT_PASSWORD']), now()))
    connection.commit(); connection.close(); os.chmod(DB_PATH, 0o600)
def audit(action, entity_id=None):
    get_db().execute('INSERT INTO audit_log(user_id,action,entity_id,event_time,remote_addr) VALUES(?,?,?,?,?)',
                     (session.get('uid'), action, entity_id, now(), request.remote_addr or 'unknown'))
    get_db().commit()
def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get('uid'): return redirect(url_for('login', next=request.path))
        if session.get('must_change') and request.endpoint != 'change_password': return redirect(url_for('change_password'))
        return function(*args, **kwargs)
    return wrapper
def clean_text(value, length, required=False):
    value = (value or '').strip()
    if required and not value: raise ValueError('Please complete all required fields.')
    if len(value) > length or any(ord(c) < 32 and c not in '\n\r\t' for c in value): raise ValueError('Invalid text value.')
    return value
def clean_number(value):
    try: number = Decimal((value or '0').strip())
    except InvalidOperation: raise ValueError('Enter a valid number.')
    if not number.is_finite() or number < 0 or number > Decimal('1000000000000000'): raise ValueError('Number is outside the allowed range.')
    return format(number, 'f')
def clean_date(value):
    value = (value or '').strip()
    if value:
        try: datetime.strptime(value, '%Y-%m-%d')
        except ValueError: raise ValueError('Enter a valid date.')
    return value or None
def decrypt_mask(blob):
    if not blob: return ''
    try:
        value = cipher.decrypt(blob).decode()
        return '•••• ' + value[-4:]
    except (InvalidToken, UnicodeDecodeError): return 'Unavailable'
app.jinja_env.globals['decrypt_mask'] = decrypt_mask
app.jinja_env.globals['currency_symbol'] = currency_symbol

def parse_asset(form):
    category = form.get('category', '')
    currency = form.get('currency', '').upper()
    if category in {'BANK', 'FIXED_DEPOSIT', 'SHARE', 'ESOP', 'MUTUAL_FUND', 'METAL', 'LIABILITY'}: raise ValueError('Use the dedicated page for this category.')
    if category not in CATEGORIES or currency not in CURRENCIES: raise ValueError('Invalid category or currency.')
    country = clean_text(form.get('country'), 60)
    if category == 'SHARE' and country not in ('India', 'United States'): raise ValueError('Stocks must use India or United States as the market.')
    reference = clean_text(form.get('account_ref'), 80)
    return (category, clean_text(form.get('name'), 120, True), clean_text(form.get('institution'), 120), country,
            currency, clean_number(form.get('quantity')), clean_number(form.get('current_price')),
            clean_number(form.get('principal')), clean_number(form.get('interest_rate')),
            clean_date(form.get('start_date')), clean_date(form.get('maturity_date')),
            cipher.encrypt(reference.encode()) if reference else None, clean_text(form.get('notes'), 1000))

@app.before_request
def security_gate():
    if request.host.split(':')[0].lower() not in ALLOWED_HOSTS: abort(400)
    if session.get('uid'):
        last_seen = session.get('last_seen')
        if last_seen and datetime.now(timezone.utc) - datetime.fromisoformat(last_seen) > timedelta(minutes=30):
            session.clear(); flash('Your session expired. Please sign in again.', 'warning'); return redirect(url_for('login'))
        session['last_seen'] = now(); session.permanent = True
@app.after_request
def security_headers(response):
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    response.headers['X-Content-Type-Options'] = 'nosniff'; response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'; response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cache-Control'] = 'no-store'; return response

@app.route('/login', methods=['GET','POST'])
@limiter.limit('5 per minute; 20 per hour')
def login():
    if request.method == 'POST':
        username = clean_text(request.form.get('username'), 80)
        user = get_db().execute('SELECT * FROM users WHERE username=?', (username,)).fetchone(); valid = False
        if user and (not user['locked_until'] or datetime.fromisoformat(user['locked_until']) <= datetime.now(timezone.utc)):
            try: valid = password_hasher.verify(user['password_hash'], request.form.get('password',''))
            except (VerifyMismatchError, VerificationError): pass
        if not valid:
            if user:
                failures = user['failed'] + 1
                locked = (datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat() if failures >= 5 else None
                get_db().execute('UPDATE users SET failed=?,locked_until=? WHERE id=?', (0 if locked else failures, locked, user['id'])); get_db().commit()
            flash('Invalid username or password.', 'error')
        else:
            ensure_admin_schema(); get_db().execute('UPDATE users SET failed=0,locked_until=NULL,last_login=? WHERE id=?', (now(),user['id'])); get_db().commit()
            session.clear(); session.update(uid=user['id'], username=user['username'], must_change=bool(user['must_change']), last_seen=now())
            audit('LOGIN', user['id']); return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/change-password', methods=['GET','POST'])
@login_required
def change_password():
    if request.method == 'POST':
        password = request.form.get('password','')
        good = len(password) >= 14 and all((re.search('[A-Z]',password),re.search('[a-z]',password),re.search(r'\d',password),re.search('[^A-Za-z0-9]',password)))
        if password != request.form.get('confirm') or not good: flash('Use matching passwords with 14+ characters, upper, lower, number, and symbol.', 'error')
        elif password == os.environ['DEFAULT_PASSWORD']: flash('Choose a password different from the default.', 'error')
        else:
            get_db().execute('UPDATE users SET password_hash=?,must_change=0 WHERE id=?',(password_hasher.hash(password),session['uid']));get_db().commit();session['must_change']=False;audit('PASSWORD_CHANGED');return redirect(url_for('dashboard'))
    return render_template('change_password.html')
@app.post('/logout')
@login_required
def logout(): audit('LOGOUT'); session.clear(); return redirect(url_for('login'))

@app.route('/', methods=['GET'])
@app.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    db = get_db()
    uid = session['uid']
    assets = {}
    liabilities = {}
    allocation = {}

    def add(target, currency, value):
        amount = Decimal(str(value or '0'))
        target[currency] = target.get(currency, Decimal(0)) + amount
        return amount

    for row in db.execute(
        'SELECT currency, current_balance FROM bank_accounts WHERE user_id=?',
        (uid,),
    ):
        value = add(assets, row['currency'], row['current_balance'])
        allocation['BANK'] = allocation.get('BANK', Decimal(0)) + value

    for row in db.execute(
        'SELECT currency, initial_deposit FROM fixed_deposits WHERE user_id=?',
        (uid,),
    ):
        value = add(assets, row['currency'], row['initial_deposit'])
        allocation['FIXED_DEPOSIT'] = (
            allocation.get('FIXED_DEPOSIT', Decimal(0)) + value
        )

    for row in db.execute('SELECT currency,current_value FROM recurring_deposits WHERE user_id=?',(uid,)):
        value=add(assets,row['currency'],row['current_value'])
        allocation['RECURRING_DEPOSIT']=allocation.get('RECURRING_DEPOSIT',Decimal(0))+value
    for row in db.execute(
        """
        SELECT
            currency,
            MAX(
                0,
                CAST(number_of_shares AS REAL)
                - CAST(COALESCE(sale_units, '0') AS REAL)
            ) AS remaining_units,
            current_price
        FROM stocks
        WHERE user_id=?
        """,
        (uid,),
    ):
        value = (
            Decimal(str(row['remaining_units']))
            * Decimal(str(row['current_price']))
        )
        add(assets, row['currency'], value)
        allocation['SHARE'] = allocation.get('SHARE', Decimal(0)) + value

    for row in db.execute(
        'SELECT currency, current_value FROM mutual_funds WHERE user_id=?',
        (uid,),
    ):
        value = add(assets, row['currency'], row['current_value'])
        allocation['MUTUAL_FUND'] = (
            allocation.get('MUTUAL_FUND', Decimal(0)) + value
        )

    for row in db.execute(
        'SELECT currency, current_value FROM retirals WHERE user_id=?',
        (uid,),
    ):
        value = add(assets, row['currency'], row['current_value'])
        allocation['RETIRAL'] = allocation.get('RETIRAL', Decimal(0)) + value

    metal_breakdown = {}
    for row in db.execute(
        'SELECT metal_type, currency, current_value FROM metals WHERE user_id=?',
        (uid,),
    ):
        value = add(assets, row['currency'], row['current_value'])
        allocation['METAL'] = allocation.get('METAL', Decimal(0)) + value
        metal_breakdown[row['metal_type']] = (
            metal_breakdown.get(row['metal_type'], Decimal(0)) + value
        )

    liability_breakdown = {}
    for row in db.execute(
        """
        SELECT liability_type, currency, current_balance
        FROM liabilities
        WHERE user_id=? AND status!='Paid Off'
        """,
        (uid,),
    ):
        value = add(liabilities, row['currency'], row['current_balance'])
        liability_breakdown[row['liability_type']] = (
            liability_breakdown.get(row['liability_type'], Decimal(0)) + value
        )

    dedicated_categories = {
        'BANK',
        'FIXED_DEPOSIT',
        'RECURRING_DEPOSIT',
        'SHARE',
        'MUTUAL_FUND',
        'METAL',
        'LIABILITY',
    }
    for row in db.execute('SELECT * FROM assets WHERE user_id=?', (uid,)):
        if row['category'] in dedicated_categories:
            continue
        if row['category'] == 'RECURRING_DEPOSIT':
            value = Decimal(row['principal'])
        else:
            value = Decimal(row['quantity']) * Decimal(row['current_price'])
        add(assets, row['currency'], value)
        allocation[row['category']] = (
            allocation.get(row['category'], Decimal(0)) + value
        )

    currencies = sorted(set(assets) | set(liabilities))
    net = {
        currency: assets.get(currency, Decimal(0))
        - liabilities.get(currency, Decimal(0))
        for currency in currencies
    }

    cash_rows = db.execute(
        """
        SELECT
            substr(transaction_date, 1, 7) AS month,
            transaction_type,
            SUM(CAST(amount AS REAL)) AS total
        FROM transactions
        WHERE user_id=? AND transaction_type IN ('INCOME', 'EXPENSE')
        GROUP BY month, transaction_type
        ORDER BY month DESC
        LIMIT 24
        """,
        (uid,),
    ).fetchall()
    months = sorted({row['month'] for row in cash_rows if row['month']})[-12:]
    cash_map = {
        (row['month'], row['transaction_type']): float(row['total'] or 0)
        for row in cash_rows
    }

    chart_data = {
        'allocation': {
            'labels': [CATEGORIES.get(key, 'Retirals') for key in allocation],
            'values': [float(value) for value in allocation.values()],
        },
        'balance': {
            'labels': currencies,
            'assets': [float(assets.get(currency, 0)) for currency in currencies],
            'liabilities': [
                float(liabilities.get(currency, 0)) for currency in currencies
            ],
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
            'url': url_for(dedicated_routes[code])
            if code in dedicated_routes
            else url_for('section', category=code),
        }
        for code, label in CATEGORIES.items()
    ]
    if 'RETIRAL' not in CATEGORIES:
        section_links.append({'label': 'Retirals', 'url': url_for('retirals')})

    return render_template(
        'dashboard.html',
        net=net,
        assets=assets,
        liabilities=liabilities,
        allocation_chart=chart_data['allocation'],
        liability_chart=chart_data['liabilities'],
        chart_data=chart_data,
        section_links=section_links,
    )

@app.route('/section/<category>')
@login_required
def section(category):
    if category == 'BANK': return redirect(url_for('bank_accounts'))
    if category == 'FIXED_DEPOSIT': return redirect(url_for('fixed_deposits'))
    if category == 'RECURRING_DEPOSIT': return redirect(url_for('recurring_deposits'))
    if category == 'SHARE': return redirect(url_for('stocks'))
    if category == 'ESOP': return redirect(url_for('esops'))
    if category == 'MUTUAL_FUND': return redirect(url_for('mutual_funds'))
    if category == 'METAL': return redirect(url_for('metals'))
    if category == 'LIABILITY': return redirect(url_for('liabilities'))
    if category == 'RETIRAL': return redirect(url_for('retirals'))
    if category not in CATEGORIES: abort(404)
    rows=get_db().execute('SELECT * FROM assets WHERE user_id=? AND category=? ORDER BY institution,name',(session['uid'],category)).fetchall()
    return render_template('section.html',rows=rows,category=category,title=CATEGORIES[category])
@app.route('/assets/new',methods=['GET','POST'])
@login_required
def asset_new():
    category=request.values.get('category','RECURRING_DEPOSIT')
    if category == 'BANK': return redirect(url_for('bank_account_new'))
    if category == 'FIXED_DEPOSIT': return redirect(url_for('fixed_deposit_new'))
    if category == 'RECURRING_DEPOSIT': return redirect(url_for('recurring_deposit_new'))
    if category == 'SHARE': return redirect(url_for('stock_new'))
    if category == 'ESOP': return redirect(url_for('esop_new'))
    if category == 'MUTUAL_FUND': return redirect(url_for('mutual_fund_new'))
    if category == 'METAL': return redirect(url_for('metal_new'))
    if category == 'LIABILITY': return redirect(url_for('liability_new'))
    if category == 'RETIRAL': return redirect(url_for('retiral_new'))
    if category not in CATEGORIES: category='RECURRING_DEPOSIT'
    if request.method=='POST':
        try: values=parse_asset(request.form)
        except ValueError as exc: flash(str(exc),'error'); return render_template('asset_form.html',current=category,categories={k:v for k,v in CATEGORIES.items() if k not in {'BANK','FIXED_DEPOSIT','RECURRING_DEPOSIT','SHARE','ESOP','MUTUAL_FUND','METAL','LIABILITY','RETIRAL'}},currencies=CURRENCIES,asset=request.form)
        cursor=get_db().execute('INSERT INTO assets(user_id,category,name,institution,country,currency,quantity,current_price,principal,interest_rate,start_date,maturity_date,account_ref,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(session['uid'],*values,now(),now()));get_db().commit();audit('ASSET_CREATE',cursor.lastrowid);return redirect(url_for('section',category=category))
    return render_template('asset_form.html',current=category,categories={k:v for k,v in CATEGORIES.items() if k not in {'BANK','FIXED_DEPOSIT','RECURRING_DEPOSIT','SHARE','ESOP','MUTUAL_FUND','METAL','LIABILITY','RETIRAL'}},currencies=CURRENCIES,asset={})
@app.post('/assets/<int:asset_id>/delete')
@login_required
def asset_delete(asset_id):
    cursor=get_db().execute('DELETE FROM assets WHERE id=? AND user_id=?',(asset_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit();audit('ASSET_DELETE',asset_id);return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for('dashboard'))

@app.route('/bank-accounts')
@login_required
def bank_accounts():
    rows = get_db().execute('SELECT * FROM bank_accounts WHERE user_id=? ORDER BY bank_name,id',(session['uid'],)).fetchall()
    display_rows=[]
    for index,row in enumerate(rows, start=1):
        item=dict(row); item['display_id']=index; display_rows.append(item)
    return render_template('bank_accounts.html', rows=display_rows)

@app.route('/bank-accounts/new', methods=['GET','POST'])
@login_required
def bank_account_new():
    account_types = ('Savings','Current','Salary','NRE','NRO','FCNR','Other')
    if request.method == 'POST':
        try:
            bank_name = clean_text(request.form.get('bank_name'), 120, True)
            account_number = clean_text(request.form.get('account_number'), 80, True)
            ifsc_code = clean_text(request.form.get('ifsc_code'), 20).upper()
            micr_code = clean_text(request.form.get('micr_code'), 20)
            bank_address = clean_text(request.form.get('bank_address'), 500)
            account_type = request.form.get('account_type','')
            if account_type not in account_types: raise ValueError('Invalid account type.')
            current_balance = clean_number(request.form.get('current_balance'))
            interest_rate = clean_number(request.form.get('interest_rate'))
            if Decimal(interest_rate) > Decimal('100'):
                raise ValueError('Interest rate must be between 0 and 100.')
            currency = request.form.get('currency', '').upper()
            if currency not in CURRENCIES:
                raise ValueError('Invalid currency.')
            notes = clean_text(request.form.get('notes'), 1000)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'bank_account_edit.html',
                account=request.form,
                account_types=account_types,
                currencies=CURRENCIES,
                is_edit=False,
            )
        cursor = get_db().execute(
            '''INSERT INTO bank_accounts(user_id,bank_name,account_number,ifsc_code,micr_code,bank_address,account_type,current_balance,interest_rate,currency,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (session['uid'], bank_name, cipher.encrypt(account_number.encode()), ifsc_code, micr_code,
             bank_address, account_type, current_balance, interest_rate, currency, notes, now(), now()),
        )
        get_db().commit()
        audit('BANK_ACCOUNT_CREATE', cursor.lastrowid)
        flash('Bank account saved.', 'success')
        return redirect(url_for('bank_accounts'))
    return render_template(
        'bank_account_edit.html',
        account={},
        account_types=account_types,
        currencies=CURRENCIES,
        is_edit=False,
    )

@app.post('/bank-accounts/<int:account_id>/delete')
@login_required
def bank_account_delete(account_id):
    cursor=get_db().execute('DELETE FROM bank_accounts WHERE id=? AND user_id=?',(account_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit(); audit('BANK_ACCOUNT_DELETE',account_id); flash('Bank account deleted.','success')
    return redirect(url_for('bank_accounts'))

@app.route('/fixed-deposits')
@login_required
def fixed_deposits():
    rows = get_db().execute(
        'SELECT * FROM fixed_deposits WHERE user_id=? ORDER BY maturity_date,bank_name,id',
        (session['uid'],)
    ).fetchall()
    display_rows = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item['display_id'] = index
        display_rows.append(item)
    return render_template('fixed_deposits.html', rows=display_rows)

@app.route('/fixed-deposits/new', methods=['GET', 'POST'])
@login_required
def fixed_deposit_new():
    if request.method == 'POST':
        try:
            bank_name = clean_text(request.form.get('bank_name'), 120, True)
            account_number = clean_text(request.form.get('account_number'), 80, True)
            ifsc_code = clean_text(request.form.get('ifsc_code'), 11, True).upper()
            micr_code = clean_text(request.form.get('micr_code'), 9, True)
            bank_address = clean_text(request.form.get('bank_address'), 1000, True)
            initial_deposit = clean_number(request.form.get('initial_deposit'))
            investment_date = clean_date(request.form.get('investment_date'))
            maturity_date = clean_date(request.form.get('maturity_date'))
            interest_rate = clean_number(request.form.get('interest_rate'))
            currency = request.form.get('currency', '').upper()
            notes = clean_text(request.form.get('notes'), 1000)
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
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('fixed_deposit_edit.html', deposit=request.form, currencies=CURRENCIES)
        cursor = get_db().execute(
            'INSERT INTO fixed_deposits(user_id,bank_name,account_number,ifsc_code,micr_code,bank_address,initial_deposit,investment_date,maturity_date,interest_rate,currency,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (session['uid'], bank_name, cipher.encrypt(account_number.encode()), ifsc_code, micr_code,
             bank_address, initial_deposit, investment_date, maturity_date, interest_rate,
             currency, notes, now(), now())
        )
        get_db().commit()
        audit('FIXED_DEPOSIT_CREATE', cursor.lastrowid)
        flash('Fixed deposit saved.', 'success')
        return redirect(url_for('fixed_deposits'))
    return render_template('fixed_deposit_edit.html', deposit={}, currencies=CURRENCIES)

@app.post('/fixed-deposits/<int:deposit_id>/delete')
@login_required
def fixed_deposit_delete(deposit_id):
    cursor = get_db().execute(
        'DELETE FROM fixed_deposits WHERE id=? AND user_id=?',
        (deposit_id, session['uid'])
    )
    if not cursor.rowcount:
        abort(404)
    get_db().commit()
    audit('FIXED_DEPOSIT_DELETE', deposit_id)
    flash('Fixed deposit deleted.', 'success')
    return redirect(url_for('fixed_deposits'))

@app.route('/recurring-deposits')
@login_required
def recurring_deposits():
 rows=get_db().execute('SELECT * FROM recurring_deposits WHERE user_id=? ORDER BY maturity_date,bank_name,id',(session['uid'],)).fetchall(); display_rows=[]; 
 for index,row in enumerate(rows, start=1):
  item=dict(row); item['display_id']=index; display_rows.append(item)
 return render_template('recurring_deposits.html',rows=display_rows)
def parse_recurring_deposit(f):
 bank=clean_text(f.get('bank_name'),120,True); account=clean_text(f.get('account_number'),80,True); monthly=clean_number(f.get('monthly_deposit')); invested=clean_number(f.get('amount_invested')); current=clean_number(f.get('current_value'))
 try: day=int(f.get('deposit_day','0'))
 except ValueError: raise ValueError('Deposit Day must be between 1 and 31.')
 if not 1<=day<=31 or Decimal(monthly)<=0: raise ValueError('Enter a valid Deposit Day and Monthly Deposit.')
 start=clean_date(f.get('start_date')); maturity=clean_date(f.get('maturity_date'))
 if not start or not maturity or maturity<=start: raise ValueError('Maturity Date must be later than Start Date.')
 rate=clean_number(f.get('interest_rate')); currency=f.get('currency','').upper()
 if currency not in CURRENCIES: raise ValueError('Invalid currency.')
 return bank,account,monthly,day,invested,current,start,maturity,rate,currency,clean_text(f.get('notes'),1000)
@app.route('/recurring-deposits/new',methods=['GET','POST'])
@login_required
def recurring_deposit_new():
 if request.method=='POST':
  try: v=parse_recurring_deposit(request.form)
  except ValueError as e: flash(str(e),'error'); return render_template('recurring_deposit_edit.html',deposit=request.form,currencies=CURRENCIES)
  bank,account,*rest=v; cur=get_db().execute('INSERT INTO recurring_deposits(user_id,bank_name,account_number,monthly_deposit,deposit_day,amount_invested,current_value,start_date,maturity_date,interest_rate,currency,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(session['uid'],bank,cipher.encrypt(account.encode()),*rest,now(),now())); get_db().commit(); audit('RECURRING_DEPOSIT_CREATE',cur.lastrowid); return redirect(url_for('recurring_deposits'))
 return render_template('recurring_deposit_edit.html',deposit={},currencies=CURRENCIES)
@app.route('/recurring-deposits/<int:deposit_id>/edit',methods=['GET','POST'])
@login_required
def recurring_deposit_edit(deposit_id):
 db=get_db(); row=db.execute('SELECT * FROM recurring_deposits WHERE id=? AND user_id=?',(deposit_id,session['uid'])).fetchone()
 if not row: abort(404)
 if request.method=='POST':
  try: v=parse_recurring_deposit(request.form)
  except ValueError as e: flash(str(e),'error'); return render_template('recurring_deposit_edit.html',deposit=request.form,deposit_id=deposit_id,currencies=CURRENCIES)
  bank,account,*rest=v; db.execute('UPDATE recurring_deposits SET bank_name=?,account_number=?,monthly_deposit=?,deposit_day=?,amount_invested=?,current_value=?,start_date=?,maturity_date=?,interest_rate=?,currency=?,notes=?,updated_at=? WHERE id=? AND user_id=?',(bank,cipher.encrypt(account.encode()),*rest,now(),deposit_id,session['uid'])); db.commit(); audit('RECURRING_DEPOSIT_UPDATE',deposit_id); return redirect(url_for('recurring_deposits'))
 d=dict(row)
 try: d['account_number']=cipher.decrypt(row['account_number']).decode()
 except (InvalidToken,UnicodeDecodeError): d['account_number']=''
 return render_template('recurring_deposit_edit.html',deposit=d,deposit_id=deposit_id,currencies=CURRENCIES)
@app.post('/recurring-deposits/<int:deposit_id>/delete')
@login_required
def recurring_deposit_delete(deposit_id):
 cur=get_db().execute('DELETE FROM recurring_deposits WHERE id=? AND user_id=?',(deposit_id,session['uid']))
 if not cur.rowcount: abort(404)
 get_db().commit(); audit('RECURRING_DEPOSIT_DELETE',deposit_id); return redirect(url_for('recurring_deposits'))
@app.route('/stocks')
@login_required
def stocks():
    db=get_db(); uid=session['uid']
    lots=db.execute("SELECT *,COALESCE(sale_units,'0') AS sale_units,COALESCE(sell_price,'0') AS sell_price,COALESCE(gst,'0') AS gst,COALESCE(brokerage,'0') AS brokerage,COALESCE(stt,'0') AS stt,COALESCE(exchange_fees,'0') AS exchange_fees FROM stocks WHERE user_id=? ORDER BY UPPER(TRIM(stock_name)),buy_transaction_date,id",(uid,)).fetchall()
    rows=db.execute('''SELECT MIN(id) AS first_id, MIN(stock_name) AS stock_name, market, currency, COUNT(*) AS lot_count,
        SUM(CAST(number_of_shares AS REAL)) AS total_purchased_units,
        SUM(CAST(COALESCE(sale_units,'0') AS REAL)) AS total_sold_units,
        SUM(MAX(0,CAST(number_of_shares AS REAL)-CAST(COALESCE(sale_units,'0') AS REAL))) AS balance_units,
        SUM((CAST(number_of_shares AS REAL)*CAST(buy_price AS REAL)+CAST(COALESCE(gst,'0') AS REAL)+CAST(COALESCE(brokerage,'0') AS REAL)+CAST(COALESCE(stt,'0') AS REAL)+CAST(COALESCE(exchange_fees,'0') AS REAL)) * MAX(0,CAST(number_of_shares AS REAL)-CAST(COALESCE(sale_units,'0') AS REAL))/CAST(number_of_shares AS REAL)) AS total_cost_price,
        SUM(MAX(0,CAST(number_of_shares AS REAL)-CAST(COALESCE(sale_units,'0') AS REAL))*CAST(current_price AS REAL)) AS current_holding_value
        FROM stocks WHERE user_id=? GROUP BY UPPER(TRIM(stock_name)),market,currency ORDER BY UPPER(TRIM(stock_name))''',(uid,)).fetchall()
    holdings=[]
    for row in rows:
        item=dict(row); item['profit_loss']=item['current_holding_value']-item['total_cost_price']; item['return_percentage']=(item['profit_loss']/item['total_cost_price']*100) if item['total_cost_price'] else 0; holdings.append(item)
    return render_template('stocks.html',rows=holdings,lots=lots)


def parse_stock_form(form):
    stock_name=clean_text(form.get('stock_name'),120,True)
    market=form.get('market','')
    if market not in ('India','United States'): raise ValueError('Invalid stock market.')
    units=clean_number(form.get('number_of_shares'))
    if Decimal(units)<=0: raise ValueError('Purchased Units must be greater than zero.')
    buy_price=clean_number(form.get('buy_price')); current_price=clean_number(form.get('current_price'))
    buy_date=clean_date(form.get('buy_transaction_date'))
    if not buy_date: raise ValueError('Buy Transaction Date is required.')
    currency=form.get('currency','').upper()
    if currency not in CURRENCIES: raise ValueError('Invalid currency.')
    if market=='India' and currency!='INR': raise ValueError('Indian stocks must use INR.')
    if market=='United States' and currency!='USD': raise ValueError('US stocks must use USD.')
    sale_date=clean_date(form.get('sale_date')); sale_units=clean_number(form.get('sale_units')); sell_price=clean_number(form.get('sell_price'))
    if Decimal(sale_units)>Decimal(units): raise ValueError('Sale Units cannot exceed Purchased Units.')
    if Decimal(sale_units)>0 and (not sale_date or Decimal(sell_price)<=0): raise ValueError('Sale Date and Sell Price are required when Sale Units are entered.')
    if sale_date and sale_date<buy_date: raise ValueError('Sale Date cannot be before Buy Transaction Date.')
    fees=(clean_number(form.get('gst')),clean_number(form.get('brokerage')),clean_number(form.get('stt')),clean_number(form.get('exchange_fees')))
    notes=clean_text(form.get('notes'),1000)
    return (stock_name,market,units,buy_price,current_price,buy_date,currency,sale_date,sale_units,sell_price,*fees,notes)

@app.route('/stocks/new',methods=['GET','POST'])
@login_required
def stock_new():
    if request.method=='POST':
        try: values=parse_stock_form(request.form)
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('stock_edit.html',stock=request.form,currencies=CURRENCIES)
        cursor=get_db().execute('''INSERT INTO stocks(user_id,stock_name,market,number_of_shares,buy_price,current_price,buy_transaction_date,currency,sale_date,sale_units,sell_price,gst,brokerage,stt,exchange_fees,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(session['uid'],*values,now(),now()))
        get_db().commit();audit('STOCK_CREATE',cursor.lastrowid);flash('Stock transaction saved.','success');return redirect(url_for('stocks'))
    return render_template('stock_edit.html',stock={},currencies=CURRENCIES)

@app.post('/stocks/<int:stock_id>/delete')
@login_required
def stock_delete(stock_id):
    cursor=get_db().execute('DELETE FROM stocks WHERE id=? AND user_id=?',(stock_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit();audit('STOCK_DELETE',stock_id);flash('Stock record deleted.','success');return redirect(url_for('stocks'))

@app.route('/esops')
@login_required
def esops():
    db=get_db(); uid=session['uid']
    lots=db.execute('SELECT * FROM esops WHERE user_id=? ORDER BY UPPER(TRIM(company_name)),grant_date,id',(uid,)).fetchall()
    rows=db.execute('''SELECT MIN(id) AS first_id, MIN(company_name) AS company_name, currency, COUNT(*) AS lot_count,
        SUM(CAST(number_of_units AS REAL)) AS total_units,
        SUM(CAST(number_of_units AS REAL) * CAST(grant_price AS REAL)) AS total_cost_price,
        SUM(CAST(number_of_units AS REAL) * CAST(current_price AS REAL)) AS current_holding_value
        FROM esops WHERE user_id=? GROUP BY UPPER(TRIM(company_name)),currency ORDER BY UPPER(TRIM(company_name))''',(uid,)).fetchall()
    holdings=[]
    for index,row in enumerate(rows, start=1):
        item=dict(row); item['display_id']=index; item['profit_loss']=item['current_holding_value']-item['total_cost_price']; item['return_percentage']=(item['profit_loss']/item['total_cost_price']*100) if item['total_cost_price'] else 0; holdings.append(item)
    detail_rows=[]
    for index,row in enumerate(lots, start=1):
        item=dict(row); item['display_id']=index; detail_rows.append(item)
    return render_template('esops.html',rows=holdings,lots=detail_rows)


def parse_esop_form(form):
    company_name=clean_text(form.get('company_name'),120,True)
    units=clean_number(form.get('number_of_units'))
    if Decimal(units)<=0: raise ValueError('Units must be greater than zero.')
    grant_price=clean_number(form.get('grant_price')); current_price=clean_number(form.get('current_price'))
    grant_date=clean_date(form.get('grant_date'))
    if not grant_date: raise ValueError('Grant Date is required.')
    vesting_date=clean_date(form.get('vesting_date'))
    if vesting_date and vesting_date<grant_date: raise ValueError('Vesting Date cannot be before Grant Date.')
    currency=form.get('currency','').upper()
    if currency not in CURRENCIES: raise ValueError('Invalid currency.')
    notes=clean_text(form.get('notes'),1000)
    return (company_name,grant_date,vesting_date,units,grant_price,current_price,currency,notes)

@app.route('/esops/new',methods=['GET','POST'])
@login_required
def esop_new():
    if request.method=='POST':
        try: values=parse_esop_form(request.form)
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('esop_edit.html',esop=request.form,currencies=CURRENCIES)
        cursor=get_db().execute('''INSERT INTO esops(user_id,company_name,grant_date,vesting_date,number_of_units,grant_price,current_price,currency,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(session['uid'],*values,now(),now()))
        get_db().commit();audit('ESOP_CREATE',cursor.lastrowid);flash('ESOP record saved.','success');return redirect(url_for('esops'))
    return render_template('esop_edit.html',esop={},currencies=CURRENCIES)

@app.route('/esops/<int:esop_id>/edit',methods=['GET','POST'])
@login_required
def esop_edit(esop_id):
    db=get_db(); row=db.execute('SELECT * FROM esops WHERE id=? AND user_id=?',(esop_id,session['uid'])).fetchone()
    if not row: abort(404)
    if request.method=='POST':
        try: values=parse_esop_form(request.form)
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('esop_edit.html',esop=request.form,esop_id=esop_id,currencies=CURRENCIES)
        db.execute('''UPDATE esops SET company_name=?,grant_date=?,vesting_date=?,number_of_units=?,grant_price=?,current_price=?,currency=?,notes=?,updated_at=? WHERE id=? AND user_id=?''',(*values,now(),esop_id,session['uid']))
        db.commit();audit('ESOP_UPDATE',esop_id);flash('ESOP record updated.','success');return redirect(url_for('esops'))
    return render_template('esop_edit.html',esop=row,esop_id=esop_id,currencies=CURRENCIES)

@app.post('/esops/<int:esop_id>/delete')
@login_required
def esop_delete(esop_id):
    cursor=get_db().execute('DELETE FROM esops WHERE id=? AND user_id=?',(esop_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit();audit('ESOP_DELETE',esop_id);flash('ESOP record deleted.','success');return redirect(url_for('esops'))

@app.route('/mutual-funds')
@login_required
def mutual_funds():
    rows=get_db().execute('SELECT * FROM mutual_funds WHERE user_id=? ORDER BY fund_house,fund_name,investment_date',(session['uid'],)).fetchall()
    display_rows=[]
    for index,row in enumerate(rows, start=1):
        item=dict(row); item['display_id']=index; display_rows.append(item)
    return render_template('mutual_funds.html',rows=display_rows)

@app.route('/mutual-funds/new',methods=['GET','POST'])
@login_required
def mutual_fund_new():
    if request.method=='POST':
        try:
            fund_house=clean_text(request.form.get('fund_house'),120,True)
            fund_name=clean_text(request.form.get('fund_name'),160,True)
            fund_category=clean_text(request.form.get('fund_category'),100,True)
            invested_amount=clean_number(request.form.get('invested_amount'))
            if Decimal(invested_amount)<=0: raise ValueError('Invested Amount must be greater than zero.')
            current_value=clean_number(request.form.get('current_value'))
            investment_mode=request.form.get('investment_mode','')
            if investment_mode not in {'SIP','LUMPSUM'}: raise ValueError('Select SIP or Lumpsum.')
            investment_date=clean_date(request.form.get('investment_date'))
            if not investment_date: raise ValueError('Date of SIP / Investment is required.')
            currency=request.form.get('currency','').upper()
            if currency not in CURRENCIES: raise ValueError('Invalid currency.')
        except ValueError as exc:
            flash(str(exc),'error')
            return render_template('mutual_fund_edit.html',fund=request.form,currencies=CURRENCIES)
        cursor=get_db().execute('INSERT INTO mutual_funds(user_id,fund_house,fund_name,fund_category,invested_amount,current_value,investment_mode,investment_date,currency,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(session['uid'],fund_house,fund_name,fund_category,invested_amount,current_value,investment_mode,investment_date,currency,now(),now()))
        get_db().commit();audit('MUTUAL_FUND_CREATE',cursor.lastrowid);flash('Mutual fund saved.','success')
        return redirect(url_for('mutual_funds'))
    return render_template('mutual_fund_edit.html',fund={},currencies=CURRENCIES)

@app.post('/mutual-funds/<int:fund_id>/delete')
@login_required
def mutual_fund_delete(fund_id):
    cursor=get_db().execute('DELETE FROM mutual_funds WHERE id=? AND user_id=?',(fund_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit();audit('MUTUAL_FUND_DELETE',fund_id);flash('Mutual fund deleted.','success')
    return redirect(url_for('mutual_funds'))

@app.route('/metals')
@login_required
def metals():
    rows=get_db().execute('SELECT * FROM metals WHERE user_id=? ORDER BY metal_type,product_form,mint_brand',(session['uid'],)).fetchall()
    display_rows=[]
    for index,row in enumerate(rows, start=1):
        item=dict(row); item['display_id']=index; display_rows.append(item)
    return render_template('metals.html',rows=display_rows)

@app.route('/metals/new',methods=['GET','POST'])
@login_required
def metal_new():
    metal_types=('Gold','Silver','Platinum','Palladium','Other')
    product_forms=('Coin','Bar','Round','ETF','Digital Gold','Jewellery','Other')
    if request.method=='POST':
        try:
            metal_type=request.form.get('metal_type','')
            product_form=request.form.get('product_form','')
            if metal_type not in metal_types: raise ValueError('Select a valid Type of Metal.')
            if product_form not in product_forms: raise ValueError('Select a valid Form / Product.')
            weight=clean_number(request.form.get('weight'))
            if Decimal(weight)<=0: raise ValueError('Weight must be greater than zero.')
            weight_unit=request.form.get('weight_unit','')
            if weight_unit not in {'GRAM','TROY_OUNCE'}: raise ValueError('Select Grams or Troy Ounces.')
            purity=clean_text(request.form.get('purity'),30,True)
            mint_brand=clean_text(request.form.get('mint_brand'),120,True)
            investment_amount=clean_number(request.form.get('investment_amount'))
            if Decimal(investment_amount)<=0: raise ValueError('Investment Amount must be greater than zero.')
            current_value=clean_number(request.form.get('current_value'))
            currency=request.form.get('currency','').upper()
            if currency not in CURRENCIES: raise ValueError('Invalid currency.')
        except ValueError as exc:
            flash(str(exc),'error')
            return render_template('metal_edit.html',metal=request.form,currencies=CURRENCIES,metal_types=metal_types,product_forms=product_forms)
        cursor=get_db().execute('INSERT INTO metals(user_id,metal_type,product_form,weight,weight_unit,purity,mint_brand,investment_amount,current_value,currency,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(session['uid'],metal_type,product_form,weight,weight_unit,purity,mint_brand,investment_amount,current_value,currency,now(),now()))
        get_db().commit();audit('METAL_CREATE',cursor.lastrowid);flash('Metal investment saved.','success')
        return redirect(url_for('metals'))
    return render_template('metal_edit.html',metal={},currencies=CURRENCIES,metal_types=metal_types,product_forms=product_forms)

@app.post('/metals/<int:metal_id>/delete')
@login_required
def metal_delete(metal_id):
    cursor=get_db().execute('DELETE FROM metals WHERE id=? AND user_id=?',(metal_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit();audit('METAL_DELETE',metal_id);flash('Metal investment deleted.','success')
    return redirect(url_for('metals'))

@app.route('/liabilities')
@login_required
def liabilities():
    rows=get_db().execute('SELECT * FROM liabilities WHERE user_id=? ORDER BY status,lender_name,maturity_date',(session['uid'],)).fetchall()
    display_rows=[]
    for index,row in enumerate(rows, start=1):
        item=dict(row); item['display_id']=index; display_rows.append(item)
    return render_template('liabilities.html',rows=display_rows)

@app.route('/liabilities/new',methods=['GET','POST'])
@login_required
def liability_new():
    liability_types=('Personal Loan','Home Loan','Auto Loan','Other')
    statuses=('Active','Paid Off','In Dispute','Deferred')
    payment_frequencies=('Monthly','Quarterly','Bi-weekly','Weekly','Semi-annual','Annual','On Demand')
    payment_methods=('Auto-pay','ACH Transfer','Wire','Check','Cash','Standing Instruction','Other')
    if request.method=='POST':
        try:
            lender_name=clean_text(request.form.get('lender_name'),160,True)
            account_number=clean_text(request.form.get('account_number'),100,True)
            liability_type=request.form.get('liability_type','')
            status=request.form.get('status','')
            if liability_type not in liability_types: raise ValueError('Select a valid Liability Type.')
            if status not in statuses: raise ValueError('Select a valid liability Status.')
            original_principal=clean_number(request.form.get('original_principal'))
            if Decimal(original_principal)<=0: raise ValueError('Original Principal Amount must be greater than zero.')
            current_balance=clean_number(request.form.get('current_balance'))
            currency=request.form.get('currency','').upper()
            if currency not in CURRENCIES: raise ValueError('Invalid currency.')
            origination_date=clean_date(request.form.get('origination_date'))
            maturity_date=clean_date(request.form.get('maturity_date'))
            if not origination_date or not maturity_date: raise ValueError('Origination and Maturity dates are required.')
            if maturity_date < origination_date: raise ValueError('Maturity / End Date cannot be before Origination Date.')
            interest_rate=clean_number(request.form.get('interest_rate'))
            rate_type=request.form.get('rate_type','')
            if rate_type not in {'FIXED','VARIABLE'}: raise ValueError('Select Fixed or Variable interest.')
            payment_frequency=request.form.get('payment_frequency','')
            payment_method=request.form.get('payment_method','')
            if payment_frequency not in payment_frequencies: raise ValueError('Select a valid Payment Frequency.')
            if payment_method not in payment_methods: raise ValueError('Select a valid Payment Method.')
            regular_payment=clean_number(request.form.get('regular_payment'))
            emi_date=clean_date(request.form.get('emi_date'))
            if not emi_date: raise ValueError('EMI Date is required.')
            notes=clean_text(request.form.get('notes'),1000)
        except ValueError as exc:
            flash(str(exc),'error')
            return render_template('liability_edit.html',liability=request.form,currencies=CURRENCIES,liability_types=liability_types,statuses=statuses,payment_frequencies=payment_frequencies,payment_methods=payment_methods)
        cursor=get_db().execute('INSERT INTO liabilities(user_id,lender_name,account_number,liability_type,status,original_principal,current_balance,currency,origination_date,maturity_date,interest_rate,rate_type,payment_frequency,regular_payment,payment_method,emi_date,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(session['uid'],lender_name,cipher.encrypt(account_number.encode()),liability_type,status,original_principal,current_balance,currency,origination_date,maturity_date,interest_rate,rate_type,payment_frequency,regular_payment,payment_method,emi_date,notes,now(),now()))
        get_db().commit();audit('LIABILITY_CREATE',cursor.lastrowid);flash('Liability saved.','success')
        return redirect(url_for('liabilities'))
    return render_template('liability_edit.html',liability={},currencies=CURRENCIES,liability_types=liability_types,statuses=statuses,payment_frequencies=payment_frequencies,payment_methods=payment_methods)

@app.post('/liabilities/<int:liability_id>/delete')
@login_required
def liability_delete(liability_id):
    cursor=get_db().execute('DELETE FROM liabilities WHERE id=? AND user_id=?',(liability_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit();audit('LIABILITY_DELETE',liability_id);flash('Liability deleted.','success')
    return redirect(url_for('liabilities'))

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

    account_types = ('Savings', 'Current', 'Salary', 'NRE', 'NRO', 'FCNR', 'Other')

    if request.method == 'POST':
        try:
            bank_name = clean_text(request.form.get('bank_name'), 120, True)
            account_number = clean_text(request.form.get('account_number'), 80, True)
            ifsc_code = clean_text(request.form.get('ifsc_code'), 20).upper()
            micr_code = clean_text(request.form.get('micr_code'), 20)
            bank_address = clean_text(request.form.get('bank_address'), 500)
            account_type = request.form.get('account_type', '')
            if account_type not in account_types:
                raise ValueError('Invalid account type.')
            current_balance = clean_number(request.form.get('current_balance'))
            interest_rate = clean_number(request.form.get('interest_rate'))
            if Decimal(interest_rate) > Decimal('100'):
                raise ValueError('Interest rate must be between 0 and 100.')
            currency = request.form.get('currency', '').upper()
            if currency not in CURRENCIES:
                raise ValueError('Invalid currency.')
            notes = clean_text(request.form.get('notes'), 1000)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template(
                'bank_account_edit.html',
                account=request.form,
                account_id=account_id,
                account_types=account_types,
                currencies=CURRENCIES,
                is_edit=True,
            )

        encrypted_account_number = cipher.encrypt(account_number.encode())
        db.execute(
            '''UPDATE bank_accounts
               SET bank_name=?, account_number=?, ifsc_code=?, micr_code=?, bank_address=?, account_type=?,
                   current_balance=?, interest_rate=?, currency=?, notes=?, updated_at=?
               WHERE id=? AND user_id=?''',
            (bank_name, encrypted_account_number, ifsc_code, micr_code, bank_address, account_type,
             current_balance, interest_rate, currency, notes, now(), account_id, session['uid']),
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
        account_types=account_types,
        currencies=CURRENCIES,
        is_edit=True,
    )

@app.route('/fixed-deposits/<int:deposit_id>/edit', methods=['GET','POST'])
@login_required
def fixed_deposit_edit(deposit_id):
    db=get_db()
    row=db.execute('SELECT * FROM fixed_deposits WHERE id=? AND user_id=?',(deposit_id,session['uid'])).fetchone()
    if not row: abort(404)
    if request.method=='POST':
        try:
            bank_name=clean_text(request.form.get('bank_name'),120,True)
            account_number=clean_text(request.form.get('account_number'),80,True)
            ifsc_code=clean_text(request.form.get('ifsc_code'),11,True).upper()
            micr_code=clean_text(request.form.get('micr_code'),9,True)
            bank_address=clean_text(request.form.get('bank_address'),1000,True)
            initial_deposit=clean_number(request.form.get('initial_deposit'))
            investment_date=clean_date(request.form.get('investment_date'))
            maturity_date=clean_date(request.form.get('maturity_date'))
            interest_rate=clean_number(request.form.get('interest_rate'))
            currency=request.form.get('currency','').upper()
            notes=clean_text(request.form.get('notes'),1000)
            if not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}',ifsc_code): raise ValueError('Enter a valid 11-character IFSC code.')
            if not re.fullmatch(r'\d{9}',micr_code): raise ValueError('Enter a valid 9-digit MICR code.')
            if not investment_date or not maturity_date or maturity_date<=investment_date: raise ValueError('Maturity date must be later than investment date.')
            if currency not in CURRENCIES: raise ValueError('Invalid currency.')
        except ValueError as exc:
            flash(str(exc),'error')
            return render_template('fixed_deposit_edit.html',deposit=request.form,deposit_id=deposit_id,currencies=CURRENCIES)
        encrypted_account_number=cipher.encrypt(account_number.encode())
        db.execute('UPDATE fixed_deposits SET bank_name=?,account_number=?,ifsc_code=?,micr_code=?,bank_address=?,initial_deposit=?,investment_date=?,maturity_date=?,interest_rate=?,currency=?,notes=?,updated_at=? WHERE id=? AND user_id=?',(bank_name,encrypted_account_number,ifsc_code,micr_code,bank_address,initial_deposit,investment_date,maturity_date,interest_rate,currency,notes,now(),deposit_id,session['uid']))
        db.commit(); audit('FIXED_DEPOSIT_UPDATE',deposit_id); flash('Fixed deposit updated.','success'); return redirect(url_for('fixed_deposits'))
    deposit=dict(row)
    try:
        deposit['account_number']=cipher.decrypt(row['account_number']).decode()
    except (InvalidToken,UnicodeDecodeError):
        deposit['account_number']=''
        flash('The stored account number could not be decrypted. Enter it again before saving.','warning')
    return render_template('fixed_deposit_edit.html',deposit=deposit,deposit_id=deposit_id,currencies=CURRENCIES)

@app.route('/stocks/<int:stock_id>/edit',methods=['GET','POST'])
@login_required
def stock_edit(stock_id):
    db=get_db(); row=db.execute('SELECT * FROM stocks WHERE id=? AND user_id=?',(stock_id,session['uid'])).fetchone()
    if not row: abort(404)
    if request.method=='POST':
        try: values=parse_stock_form(request.form)
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('stock_edit.html',stock=request.form,stock_id=stock_id,currencies=CURRENCIES)
        db.execute('''UPDATE stocks SET stock_name=?,market=?,number_of_shares=?,buy_price=?,current_price=?,buy_transaction_date=?,currency=?,sale_date=?,sale_units=?,sell_price=?,gst=?,brokerage=?,stt=?,exchange_fees=?,notes=?,updated_at=? WHERE id=? AND user_id=?''',(*values,now(),stock_id,session['uid']))
        db.commit();audit('STOCK_UPDATE',stock_id);flash('Stock transaction updated.','success');return redirect(url_for('stocks'))
    return render_template('stock_edit.html',stock=row,stock_id=stock_id,currencies=CURRENCIES)

@app.route('/mutual-funds/<int:fund_id>/edit', methods=['GET','POST'])
@login_required
def mutual_fund_edit(fund_id):
    db=get_db(); row=db.execute('SELECT * FROM mutual_funds WHERE id=? AND user_id=?',(fund_id,session['uid'])).fetchone()
    if not row: abort(404)
    if request.method=='POST':
        try:
            fund_house=clean_text(request.form.get('fund_house'),120,True); fund_name=clean_text(request.form.get('fund_name'),160,True); fund_category=clean_text(request.form.get('fund_category'),100,True); invested_amount=clean_number(request.form.get('invested_amount')); current_value=clean_number(request.form.get('current_value')); investment_mode=request.form.get('investment_mode',''); investment_date=clean_date(request.form.get('investment_date')); currency=request.form.get('currency','').upper()
            if Decimal(invested_amount)<=0: raise ValueError('Invested Amount must be greater than zero.')
            if investment_mode not in {'SIP','LUMPSUM'}: raise ValueError('Select SIP or Lumpsum.')
            if not investment_date: raise ValueError('Date of SIP / Investment is required.')
            if currency not in CURRENCIES: raise ValueError('Invalid currency.')
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('mutual_fund_edit.html',fund=request.form,fund_id=fund_id,currencies=CURRENCIES)
        db.execute('UPDATE mutual_funds SET fund_house=?,fund_name=?,fund_category=?,invested_amount=?,current_value=?,investment_mode=?,investment_date=?,currency=?,updated_at=? WHERE id=? AND user_id=?',(fund_house,fund_name,fund_category,invested_amount,current_value,investment_mode,investment_date,currency,now(),fund_id,session['uid']))
        db.commit(); audit('MUTUAL_FUND_UPDATE',fund_id); flash('Mutual fund updated.','success'); return redirect(url_for('mutual_funds'))
    return render_template('mutual_fund_edit.html',fund=row,fund_id=fund_id,currencies=CURRENCIES)

@app.route('/metals/<int:metal_id>/edit', methods=['GET','POST'])
@login_required
def metal_edit(metal_id):
    db=get_db(); row=db.execute('SELECT * FROM metals WHERE id=? AND user_id=?',(metal_id,session['uid'])).fetchone()
    if not row: abort(404)
    metal_types=('Gold','Silver','Platinum','Palladium','Other'); product_forms=('Coin','Bar','Round','ETF','Digital Gold','Jewellery','Other')
    if request.method=='POST':
        try:
            metal_type=request.form.get('metal_type',''); product_form=request.form.get('product_form',''); weight=clean_number(request.form.get('weight')); weight_unit=request.form.get('weight_unit',''); purity=clean_text(request.form.get('purity'),30,True); mint_brand=clean_text(request.form.get('mint_brand'),120,True); investment_amount=clean_number(request.form.get('investment_amount')); current_value=clean_number(request.form.get('current_value')); currency=request.form.get('currency','').upper()
            if metal_type not in metal_types or product_form not in product_forms: raise ValueError('Select valid metal and product values.')
            if Decimal(weight)<=0 or Decimal(investment_amount)<=0: raise ValueError('Weight and Investment Amount must be greater than zero.')
            if weight_unit not in {'GRAM','TROY_OUNCE'}: raise ValueError('Select a valid weight unit.')
            if currency not in CURRENCIES: raise ValueError('Invalid currency.')
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('metal_edit.html',metal=request.form,metal_id=metal_id,currencies=CURRENCIES,metal_types=metal_types,product_forms=product_forms)
        db.execute('UPDATE metals SET metal_type=?,product_form=?,weight=?,weight_unit=?,purity=?,mint_brand=?,investment_amount=?,current_value=?,currency=?,updated_at=? WHERE id=? AND user_id=?',(metal_type,product_form,weight,weight_unit,purity,mint_brand,investment_amount,current_value,currency,now(),metal_id,session['uid']))
        db.commit(); audit('METAL_UPDATE',metal_id); flash('Metal investment updated.','success'); return redirect(url_for('metals'))
    return render_template('metal_edit.html',metal=row,metal_id=metal_id,currencies=CURRENCIES,metal_types=metal_types,product_forms=product_forms)

@app.route('/liabilities/<int:liability_id>/edit', methods=['GET','POST'])
@login_required
def liability_edit(liability_id):
    db=get_db(); row=db.execute('SELECT * FROM liabilities WHERE id=? AND user_id=?',(liability_id,session['uid'])).fetchone()
    if not row: abort(404)
    liability_types=('Personal Loan','Home Loan','Auto Loan','Other'); statuses=('Active','Paid Off','In Dispute','Deferred'); payment_frequencies=('Monthly','Quarterly','Bi-weekly','Weekly','Semi-annual','Annual','On Demand'); payment_methods=('Auto-pay','ACH Transfer','Wire','Check','Cash','Standing Instruction','Other')
    if request.method=='POST':
        try:
            lender_name=clean_text(request.form.get('lender_name'),160,True); liability_type=request.form.get('liability_type',''); status=request.form.get('status',''); original_principal=clean_number(request.form.get('original_principal')); current_balance=clean_number(request.form.get('current_balance')); currency=request.form.get('currency','').upper(); origination_date=clean_date(request.form.get('origination_date')); maturity_date=clean_date(request.form.get('maturity_date')); interest_rate=clean_number(request.form.get('interest_rate')); rate_type=request.form.get('rate_type',''); payment_frequency=request.form.get('payment_frequency',''); regular_payment=clean_number(request.form.get('regular_payment')); payment_method=request.form.get('payment_method',''); emi_date=clean_date(request.form.get('emi_date')); notes=clean_text(request.form.get('notes'),1000)
            if liability_type not in liability_types or status not in statuses: raise ValueError('Select valid liability type and status.')
            if Decimal(original_principal)<=0: raise ValueError('Original Principal must be greater than zero.')
            if currency not in CURRENCIES or rate_type not in {'FIXED','VARIABLE'}: raise ValueError('Invalid currency or rate type.')
            if not origination_date or not maturity_date or maturity_date<origination_date: raise ValueError('Enter valid origination and maturity dates.')
            if payment_frequency not in payment_frequencies or payment_method not in payment_methods: raise ValueError('Select valid payment details.')
            if not emi_date: raise ValueError('EMI Date is required.')
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('liability_edit.html',liability=request.form,liability_id=liability_id,currencies=CURRENCIES,liability_types=liability_types,statuses=statuses,payment_frequencies=payment_frequencies,payment_methods=payment_methods)
        db.execute('UPDATE liabilities SET lender_name=?,liability_type=?,status=?,original_principal=?,current_balance=?,currency=?,origination_date=?,maturity_date=?,interest_rate=?,rate_type=?,payment_frequency=?,regular_payment=?,payment_method=?,emi_date=?,notes=?,updated_at=? WHERE id=? AND user_id=?',(lender_name,liability_type,status,original_principal,current_balance,currency,origination_date,maturity_date,interest_rate,rate_type,payment_frequency,regular_payment,payment_method,emi_date,notes,now(),liability_id,session['uid']))
        db.commit(); audit('LIABILITY_UPDATE',liability_id); flash('Liability updated.','success'); return redirect(url_for('liabilities'))
    return render_template('liability_edit.html',liability=row,liability_id=liability_id,currencies=CURRENCIES,liability_types=liability_types,statuses=statuses,payment_frequencies=payment_frequencies,payment_methods=payment_methods)

@app.route('/retirals')
@login_required
def retirals():
    rows=get_db().execute(
        'SELECT * FROM retirals WHERE user_id=? ORDER BY fund_type,id',
        (session['uid'],),
    ).fetchall()
    display_rows=[]
    for index,row in enumerate(rows, start=1):
        item=dict(row); item['display_id']=index; display_rows.append(item)
    return render_template('retirals.html',rows=display_rows)


def parse_retiral_form(form):
    fund_types=('EPF','PPF','NPS','Superannuation','Pension Fund','Gratuity','401(k)','Other')
    fund_type=form.get('fund_type','')
    if fund_type not in fund_types: raise ValueError('Select a valid Retiral Fund type.')
    amount_invested=clean_number(form.get('amount_invested'))
    current_value=clean_number(form.get('current_value'))
    currency=form.get('currency','').upper()
    if currency not in CURRENCIES: raise ValueError('Invalid currency.')
    notes=clean_text(form.get('notes'),1000)
    return fund_types,(fund_type,amount_invested,current_value,currency,notes)

@app.route('/retirals/new',methods=['GET','POST'])
@login_required
def retiral_new():
    fund_types=('EPF','PPF','NPS','Superannuation','Pension Fund','Gratuity','401(k)','Other')
    if request.method=='POST':
        try: fund_types,values=parse_retiral_form(request.form)
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('retiral_edit.html',retiral=request.form,fund_types=fund_types,currencies=CURRENCIES)
        cursor=get_db().execute(
            'INSERT INTO retirals(user_id,fund_type,amount_invested,current_value,currency,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (session['uid'],*values,now(),now()),
        )
        get_db().commit(); audit('RETIRAL_CREATE',cursor.lastrowid); flash('Retiral fund saved.','success'); return redirect(url_for('retirals'))
    return render_template('retiral_edit.html',retiral={},fund_types=fund_types,currencies=CURRENCIES)

@app.route('/retirals/<int:retiral_id>/edit',methods=['GET','POST'])
@login_required
def retiral_edit(retiral_id):
    db=get_db(); row=db.execute('SELECT * FROM retirals WHERE id=? AND user_id=?',(retiral_id,session['uid'])).fetchone()
    if not row: abort(404)
    fund_types=('EPF','PPF','NPS','Superannuation','Pension Fund','Gratuity','401(k)','Other')
    if request.method=='POST':
        try: fund_types,values=parse_retiral_form(request.form)
        except ValueError as exc:
            flash(str(exc),'error'); return render_template('retiral_edit.html',retiral=request.form,retiral_id=retiral_id,fund_types=fund_types,currencies=CURRENCIES)
        db.execute('UPDATE retirals SET fund_type=?,amount_invested=?,current_value=?,currency=?,notes=?,updated_at=? WHERE id=? AND user_id=?',(*values,now(),retiral_id,session['uid']))
        db.commit(); audit('RETIRAL_UPDATE',retiral_id); flash('Retiral fund updated.','success'); return redirect(url_for('retirals'))
    return render_template('retiral_edit.html',retiral=row,retiral_id=retiral_id,fund_types=fund_types,currencies=CURRENCIES)

@app.post('/retirals/<int:retiral_id>/delete')
@login_required
def retiral_delete(retiral_id):
    cursor=get_db().execute('DELETE FROM retirals WHERE id=? AND user_id=?',(retiral_id,session['uid']))
    if not cursor.rowcount: abort(404)
    get_db().commit(); audit('RETIRAL_DELETE',retiral_id); flash('Retiral fund deleted.','success'); return redirect(url_for('retirals'))

@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(429)
@app.errorhandler(500)
def error_page(error): return render_template('error.html',code=getattr(error,'code',500)),getattr(error,'code',500)

if __name__=='__main__':
    init_db(); ensure_admin_schema(); print(f'Finance Vault: http://{BIND_HOST}:{BIND_PORT}'); print('Portal is now Live. Press Ctrl+C to stop the server.');
    serve(app,host=BIND_HOST,port=BIND_PORT,threads=8,trusted_proxy='127.0.0.1',trusted_proxy_headers=['x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'])
