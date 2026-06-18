import os, json, io, sqlite3, base64, re, secrets, hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_file, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from openai import OpenAI
import pdfplumber
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)

DB_PATH    = os.getenv('DB_PATH', 'jobtracker.db')
GROK_MODEL = os.getenv('GROK_MODEL', 'grok-3-mini')

GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
REDIRECT_URI = os.getenv('REDIRECT_URI', 'http://localhost:5001/auth/google/callback')
GMAIL_QUERY  = ('subject:(application OR interview OR "offer letter" OR position '
                'OR vacancy OR hiring OR recruitment OR shortlisted OR assessment)')

REJECTION_WORDS = [
    'unfortunately', 'regret to inform', 'not moving forward',
    'decided not to proceed', 'not selected', 'other candidates',
    'position has been filled', 'will not be moving forward',
    'not been selected', 'unsuccessful', 'not proceed with your application',
    'not be taking your application further', 'chosen not to proceed',
]


# ── AI ─────────────────────────────────────────────────────────────────────────

def get_ai_client():
    key      = os.getenv('XAI_API_KEY', '')
    base_url = os.getenv('AI_BASE_URL', 'https://api.x.ai/v1')
    if not key:
        return None
    return OpenAI(api_key=key, base_url=base_url)

def require_ai():
    c = get_ai_client()
    if not c:
        return None, (jsonify({'error': 'No XAI_API_KEY set in .env'}), 400)
    return c, None

def grok(client, prompt, max_tokens=1500):
    resp = client.chat.completions.create(
        model=GROK_MODEL, max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}], temperature=0.3,
    )
    return resp.choices[0].message.content


# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _run_migrations(conn):
    """Safe schema migrations — each check is idempotent."""
    # Add user_id to applications
    cols = {r[1] for r in conn.execute('PRAGMA table_info(applications)')}
    if 'user_id' not in cols:
        conn.execute('ALTER TABLE applications ADD COLUMN user_id INTEGER REFERENCES users(id)')

    # Add user_id to cv_files
    cols = {r[1] for r in conn.execute('PRAGMA table_info(cv_files)')}
    if 'user_id' not in cols:
        conn.execute('ALTER TABLE cv_files ADD COLUMN user_id INTEGER REFERENCES users(id)')

    # Recreate settings with per-user composite key
    cols = {r[1] for r in conn.execute('PRAGMA table_info(settings)')}
    if 'user_id' not in cols:
        conn.execute('ALTER TABLE settings RENAME TO _settings_bak')
        conn.execute('''CREATE TABLE settings (
            key TEXT NOT NULL, user_id INTEGER NOT NULL, value TEXT,
            UNIQUE(key, user_id)
        )''')
        conn.execute('DROP TABLE _settings_bak')

    # Recreate oauth_tokens with per-user composite key
    cols = {r[1] for r in conn.execute('PRAGMA table_info(oauth_tokens)')}
    if 'user_id' not in cols:
        conn.execute('ALTER TABLE oauth_tokens RENAME TO _oauth_bak')
        conn.execute('''CREATE TABLE oauth_tokens (
            provider TEXT NOT NULL, user_id INTEGER NOT NULL,
            token_json TEXT, email TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(provider, user_id)
        )''')
        conn.execute('DROP TABLE _oauth_bak')

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name          TEXT DEFAULT '',
            headline      TEXT DEFAULT '',
            location      TEXT DEFAULT '',
            linkedin_url  TEXT DEFAULT '',
            github_url    TEXT DEFAULT '',
            portfolio_url TEXT DEFAULT '',
            created_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cv_files (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT    NOT NULL,
            text_content TEXT,
            file_data    BLOB,
            is_active    INTEGER DEFAULT 0,
            uploaded_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS applications (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            company          TEXT NOT NULL,
            role             TEXT NOT NULL,
            job_description  TEXT,
            status           TEXT DEFAULT 'Applied',
            applied_date     TEXT,
            source           TEXT DEFAULT 'Manual',
            salary           TEXT,
            location         TEXT,
            job_url          TEXT,
            notes            TEXT,
            cv_id            INTEGER,
            created_at       TEXT DEFAULT (datetime('now')),
            updated_at       TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER,
            action         TEXT,
            note           TEXT,
            timestamp      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS interview_prep (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER UNIQUE,
            prep_json      TEXT,
            generated_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS oauth_tokens (
            provider   TEXT PRIMARY KEY,
            token_json TEXT,
            email      TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    ''')
    _run_migrations(conn)
    conn.commit()
    conn.close()


# ── Auth helpers ───────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/') or request.path.startswith('/auth/'):
                return jsonify({'error': 'Not authenticated'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def uid():
    return session['user_id']


# ── Google OAuth helpers ───────────────────────────────────────────────────────

def _oauth_client_config():
    return {
        "web": {
            "client_id":     os.getenv('GOOGLE_CLIENT_ID', ''),
            "client_secret": os.getenv('GOOGLE_CLIENT_SECRET', ''),
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }

def _get_gmail_service(user_id):
    conn = get_db()
    row  = conn.execute(
        "SELECT token_json FROM oauth_tokens WHERE provider='google' AND user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    creds = Credentials.from_authorized_user_info(json.loads(row['token_json']), GMAIL_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        conn = get_db()
        conn.execute(
            "UPDATE oauth_tokens SET token_json=?, updated_at=datetime('now') WHERE provider='google' AND user_id=?",
            (creds.to_json(), user_id)
        )
        conn.commit()
        conn.close()
    return build('gmail', 'v1', credentials=creds)

def _extract_body(payload):
    if payload.get('body', {}).get('data'):
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    for part in payload.get('parts', []):
        if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
            return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
    return ''

def _pkce_pair():
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return verifier, challenge


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect('/')
    conn = get_db()
    has_users = conn.execute('SELECT 1 FROM users LIMIT 1').fetchone()
    conn.close()

    if request.method == 'GET':
        return render_template('login.html', mode='login', can_register=not has_users)

    email    = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user['password_hash'], password):
        return render_template('login.html', mode='login',
                               error='Invalid email or password',
                               can_register=not has_users)
    session.permanent = True
    session['user_id'] = user['id']
    return redirect('/')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect('/')
    conn = get_db()
    has_users = conn.execute('SELECT 1 FROM users LIMIT 1').fetchone()
    conn.close()
    if has_users:
        return redirect('/login')

    if request.method == 'GET':
        return render_template('login.html', mode='register', can_register=True)

    name     = request.form.get('name', '').strip()
    email    = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    if not name or not email or not password:
        return render_template('login.html', mode='register', can_register=True,
                               error='All fields are required')
    if len(password) < 8:
        return render_template('login.html', mode='register', can_register=True,
                               error='Password must be at least 8 characters')

    conn = get_db()
    try:
        conn.execute('INSERT INTO users (email, password_hash, name) VALUES (?,?,?)',
                     (email, generate_password_hash(password), name))
        new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        # Assign any pre-auth data to this first user
        conn.execute('UPDATE applications SET user_id=? WHERE user_id IS NULL', (new_id,))
        conn.execute('UPDATE cv_files SET user_id=? WHERE user_id IS NULL', (new_id,))
        conn.commit()
        session.permanent = True
        session['user_id'] = new_id
        return redirect('/')
    except sqlite3.IntegrityError:
        return render_template('login.html', mode='register', can_register=True,
                               error='Email already registered')
    finally:
        conn.close()


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/api/me', methods=['GET'])
@login_required
def get_me():
    conn = get_db()
    user = conn.execute(
        'SELECT id, email, name, headline, location, linkedin_url, github_url, portfolio_url, created_at '
        'FROM users WHERE id=?', (uid(),)
    ).fetchone()
    conn.close()
    return jsonify(dict(user))


@app.route('/api/me', methods=['PUT'])
@login_required
def update_me():
    data = request.get_json() or {}
    allowed = ['name', 'headline', 'location', 'linkedin_url', 'github_url', 'portfolio_url']
    sets, vals = [], []
    for f in allowed:
        if f in data:
            sets.append(f'{f}=?')
            vals.append(data[f])
    if not sets:
        return jsonify({'error': 'Nothing to update'}), 400
    vals.append(uid())
    conn = get_db()
    conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/me/password', methods=['PUT'])
@login_required
def change_password():
    data    = request.get_json() or {}
    current = data.get('current_password', '')
    new_pw  = data.get('new_password', '')
    if not current or not new_pw:
        return jsonify({'error': 'Both fields required'}), 400
    if len(new_pw) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    conn = get_db()
    user = conn.execute('SELECT password_hash FROM users WHERE id=?', (uid(),)).fetchone()
    if not check_password_hash(user['password_hash'], current):
        conn.close()
        return jsonify({'error': 'Current password is incorrect'}), 400
    conn.execute('UPDATE users SET password_hash=? WHERE id=?',
                 (generate_password_hash(new_pw), uid()))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── Google OAuth routes ────────────────────────────────────────────────────────

@app.route('/auth/google')
@login_required
def google_auth():
    if not os.getenv('GOOGLE_CLIENT_ID') or not os.getenv('GOOGLE_CLIENT_SECRET'):
        return 'GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set in .env', 500
    verifier, challenge = _pkce_pair()
    flow = Flow.from_client_config(_oauth_client_config(), scopes=GMAIL_SCOPES)
    flow.redirect_uri = REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type='offline', prompt='consent',
        code_challenge=challenge, code_challenge_method='S256'
    )
    conn = get_db()
    user_id = uid()
    conn.execute("INSERT OR REPLACE INTO settings (key,user_id,value) VALUES ('oauth_state',?,?)",    (user_id, state))
    conn.execute("INSERT OR REPLACE INTO settings (key,user_id,value) VALUES ('pkce_verifier',?,?)", (user_id, verifier))
    conn.commit()
    conn.close()
    return redirect(auth_url)


@app.route('/auth/google/callback')
@login_required
def google_callback():
    if request.args.get('error'):
        return redirect('/')
    state   = request.args.get('state', '')
    user_id = uid()
    conn    = get_db()
    state_row    = conn.execute("SELECT value FROM settings WHERE key='oauth_state' AND user_id=?",    (user_id,)).fetchone()
    verifier_row = conn.execute("SELECT value FROM settings WHERE key='pkce_verifier' AND user_id=?", (user_id,)).fetchone()
    conn.close()
    if not state_row or state_row['value'] != state:
        return 'OAuth state mismatch — please try connecting again.', 400
    verifier = verifier_row['value'] if verifier_row else None
    flow = Flow.from_client_config(_oauth_client_config(), scopes=GMAIL_SCOPES, state=state)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=request.args.get('code', ''), code_verifier=verifier)
    creds = flow.credentials
    try:
        svc   = build('gmail', 'v1', credentials=creds)
        email = svc.users().getProfile(userId='me').execute().get('emailAddress', '')
    except Exception:
        email = ''
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO oauth_tokens (provider,user_id,token_json,email,updated_at) VALUES ('google',?,?,?,datetime('now'))",
        (user_id, creds.to_json(), email)
    )
    conn.commit()
    conn.close()
    return redirect('/')


@app.route('/api/gmail/status')
@login_required
def gmail_status():
    conn = get_db()
    row  = conn.execute(
        "SELECT email FROM oauth_tokens WHERE provider='google' AND user_id=?", (uid(),)
    ).fetchone()
    conn.close()
    return jsonify({'connected': bool(row), 'email': row['email'] if row else ''})


@app.route('/api/gmail/disconnect', methods=['POST'])
@login_required
def gmail_disconnect():
    conn = get_db()
    conn.execute("DELETE FROM oauth_tokens WHERE provider='google' AND user_id=?", (uid(),))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── Main page ──────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html')


# ── Stats ──────────────────────────────────────────────────────────────────────

@app.route('/api/stats')
@login_required
def get_stats():
    conn    = get_db()
    user_id = uid()
    stats   = {}
    for status in ['Applied', 'Screening', 'Interview', 'Offer', 'Rejected', 'Withdrawn']:
        stats[status.lower()] = conn.execute(
            'SELECT COUNT(*) FROM applications WHERE status=? AND user_id=?', (status, user_id)
        ).fetchone()[0]
    stats['total']  = conn.execute('SELECT COUNT(*) FROM applications WHERE user_id=?', (user_id,)).fetchone()[0]
    stats['active'] = stats['applied'] + stats['screening'] + stats['interview']

    followup_rows = conn.execute('''
        SELECT id, company, role, applied_date,
               CAST(julianday('now') - julianday(COALESCE(updated_at, created_at)) AS INTEGER) AS days_stale
        FROM applications
        WHERE user_id=? AND status IN ('Applied','Screening')
          AND julianday('now') - julianday(COALESCE(updated_at, created_at)) >= 7
        ORDER BY days_stale DESC LIMIT 8
    ''', (user_id,)).fetchall()
    stats['followup_needed'] = [dict(r) for r in followup_rows]

    sync_row = conn.execute(
        "SELECT value FROM settings WHERE key='last_gmail_sync' AND user_id=?", (user_id,)
    ).fetchone()
    stats['last_gmail_sync'] = sync_row['value'] if sync_row else None

    recent = conn.execute('''
        SELECT al.action, al.note, al.timestamp, ap.company, ap.role
        FROM activity_log al
        LEFT JOIN applications ap ON al.application_id = ap.id
        WHERE ap.user_id=?
        ORDER BY al.timestamp DESC LIMIT 12
    ''', (user_id,)).fetchall()
    stats['recent_activity'] = [dict(r) for r in recent]
    conn.close()
    return jsonify(stats)


# ── Applications ───────────────────────────────────────────────────────────────

@app.route('/api/applications', methods=['GET'])
@login_required
def get_applications():
    conn = get_db()
    apps = conn.execute('''
        SELECT a.*, c.filename AS cv_filename
        FROM applications a
        LEFT JOIN cv_files c ON a.cv_id = c.id
        WHERE a.user_id=?
        ORDER BY a.created_at DESC
    ''', (uid(),)).fetchall()
    conn.close()
    return jsonify([dict(a) for a in apps])


@app.route('/api/applications', methods=['POST'])
@login_required
def add_application():
    data = request.get_json()
    if not data.get('company') or not data.get('role'):
        return jsonify({'error': 'Company and role are required'}), 400

    conn    = get_db()
    user_id = uid()
    cv_id   = data.get('cv_id')
    if not cv_id:
        cv_row = conn.execute('SELECT id FROM cv_files WHERE is_active=1 AND user_id=?', (user_id,)).fetchone()
        cv_id  = cv_row['id'] if cv_row else None

    conn.execute('''
        INSERT INTO applications
          (user_id, company, role, job_description, status, applied_date, source, salary, location, job_url, notes, cv_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        user_id,
        data.get('company'), data.get('role'), data.get('job_description'),
        data.get('status', 'Applied'),
        data.get('applied_date', datetime.now().strftime('%Y-%m-%d')),
        data.get('source', 'Manual'), data.get('salary'),
        data.get('location'), data.get('job_url'), data.get('notes'), cv_id
    ))
    app_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?,?)',
                 (app_id, f"Added – {data.get('role')} at {data.get('company')}"))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': app_id})


@app.route('/api/applications/<int:app_id>', methods=['PUT'])
@login_required
def update_application(app_id):
    data = request.get_json()
    conn = get_db()
    # Verify ownership
    row = conn.execute('SELECT id FROM applications WHERE id=? AND user_id=?', (app_id, uid())).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    allowed = ['company', 'role', 'job_description', 'status',
               'applied_date', 'salary', 'location', 'job_url', 'notes']
    sets, vals = [], []
    for f in allowed:
        if f in data:
            sets.append(f'{f}=?')
            vals.append(data[f])
    sets.append("updated_at=datetime('now')")
    vals.append(app_id)
    conn.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id=?", vals)
    if 'status' in data:
        conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?,?)',
                     (app_id, f"Status → {data['status']}"))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/applications/<int:app_id>', methods=['DELETE'])
@login_required
def delete_application(app_id):
    conn = get_db()
    row = conn.execute('SELECT id FROM applications WHERE id=? AND user_id=?', (app_id, uid())).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    conn.execute('DELETE FROM applications    WHERE id=?', (app_id,))
    conn.execute('DELETE FROM activity_log   WHERE application_id=?', (app_id,))
    conn.execute('DELETE FROM interview_prep WHERE application_id=?', (app_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── CV Management ──────────────────────────────────────────────────────────────

@app.route('/api/cv', methods=['GET'])
@login_required
def get_cvs():
    conn = get_db()
    rows = conn.execute(
        'SELECT id, filename, is_active, uploaded_at FROM cv_files WHERE user_id=? ORDER BY uploaded_at DESC',
        (uid(),)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/cv', methods=['POST'])
@login_required
def upload_cv():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are supported'}), 400

    raw  = f.read()
    text = ''
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or '') + '\n'
    except Exception as e:
        return jsonify({'error': f'PDF parse failed: {e}'}), 500

    conn    = get_db()
    user_id = uid()
    conn.execute('UPDATE cv_files SET is_active=0 WHERE user_id=?', (user_id,))
    conn.execute(
        'INSERT INTO cv_files (user_id, filename, text_content, file_data, is_active) VALUES (?,?,?,?,1)',
        (user_id, f.filename, text.strip(), raw)
    )
    cv_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': cv_id, 'preview': text[:600]})


@app.route('/api/cv/<int:cv_id>/activate', methods=['POST'])
@login_required
def activate_cv(cv_id):
    conn    = get_db()
    user_id = uid()
    row = conn.execute('SELECT id FROM cv_files WHERE id=? AND user_id=?', (cv_id, user_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    conn.execute('UPDATE cv_files SET is_active=0 WHERE user_id=?', (user_id,))
    conn.execute('UPDATE cv_files SET is_active=1 WHERE id=?', (cv_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/cv/<int:cv_id>/download')
@login_required
def download_cv(cv_id):
    conn = get_db()
    row  = conn.execute(
        'SELECT filename, file_data FROM cv_files WHERE id=? AND user_id=?', (cv_id, uid())
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return send_file(io.BytesIO(row['file_data']), download_name=row['filename'], as_attachment=True)


@app.route('/api/cv/active_text')
@login_required
def active_cv_text():
    conn = get_db()
    row  = conn.execute(
        'SELECT text_content FROM cv_files WHERE is_active=1 AND user_id=?', (uid(),)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'No active CV'}), 404
    return jsonify({'text': row['text_content']})


# ── AI: Extract job info ───────────────────────────────────────────────────────

EXTRACT_PROMPT = """Extract job application details from the text below.
Return ONLY valid JSON – no markdown, no explanation:
{{
  "company":         "company name or null",
  "role":            "job title or null",
  "location":        "city/remote or null",
  "salary":          "salary info or null",
  "job_url":         "URL if present or null",
  "job_description": "key requirements & responsibilities, max 250 words",
  "source":          "Email or WhatsApp or Other",
  "notes":           "any other important detail"
}}

TEXT:
{text}"""

def _ai_extract_job(client, text):
    try:
        raw = grok(client, EXTRACT_PROMPT.format(text=text[:3500]), max_tokens=900)
        raw = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        return json.loads(raw)
    except Exception:
        return {}


@app.route('/api/extract_job', methods=['POST'])
@login_required
def extract_job():
    client, err = require_ai()
    if err: return err
    text = (request.get_json() or {}).get('text', '')
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    result = _ai_extract_job(client, text)
    if not result:
        return jsonify({'error': 'AI could not parse the text'}), 500
    return jsonify(result)


# ── Gmail sync (OAuth) ─────────────────────────────────────────────────────────

@app.route('/api/gmail_scan', methods=['POST'])
@login_required
def gmail_scan():
    svc = _get_gmail_service(uid())
    if not svc:
        return jsonify({'error': 'Gmail not connected — click "Connect Gmail" on the Import page'}), 401
    try:
        results  = svc.users().messages().list(userId='me', q=GMAIL_QUERY, maxResults=25).execute()
        messages = results.get('messages', [])
        found    = []
        for meta in messages:
            msg     = svc.users().messages().get(userId='me', id=meta['id'], format='full').execute()
            headers = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}
            body    = _extract_body(msg['payload'])
            found.append({
                'subject': headers.get('Subject', ''),
                'sender':  headers.get('From', ''),
                'date':    headers.get('Date', ''),
                'body':    body[:2500],
            })
            if len(found) >= 20:
                break
        return jsonify({'emails': found, 'count': len(found)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gmail/sync', methods=['POST'])
@login_required
def gmail_sync():
    user_id = uid()
    svc     = _get_gmail_service(user_id)
    if not svc:
        return jsonify({'error': 'Gmail not connected — connect it in the Inbox tab'}), 401

    ai_client = get_ai_client()

    def _normalize(name):
        return re.sub(r'\b(inc|ltd|llc|corp|co|limited|plc|group|technologies|solutions)\b\.?',
                      '', name.lower()).strip()

    try:
        conn = get_db()
        apps = conn.execute(
            'SELECT id, company, role, status FROM applications WHERE user_id=?', (user_id,)
        ).fetchall()
        company_map   = {_normalize(a['company']): dict(a) for a in apps if a['company']}
        existing_keys = {(a['company'].lower(), (a['role'] or '').lower()) for a in apps if a['company']}

        results  = svc.users().messages().list(userId='me', q=GMAIL_QUERY, maxResults=50).execute()
        messages = results.get('messages', [])

        auto_rejected, auto_added, skipped = [], [], []

        for meta in messages:
            msg     = svc.users().messages().get(userId='me', id=meta['id'], format='full').execute()
            hdrs    = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}
            subject = hdrs.get('Subject', '')
            body    = _extract_body(msg['payload'])
            full    = (subject + ' ' + body[:1200]).lower()

            matched      = next((a for key, a in company_map.items() if key and key in full), None)
            is_rejection = any(kw in full for kw in REJECTION_WORDS)

            if is_rejection and matched and matched['status'] not in ('Rejected', 'Withdrawn', 'Offer'):
                conn.execute(
                    "UPDATE applications SET status='Rejected', updated_at=datetime('now') WHERE id=?",
                    (matched['id'],)
                )
                conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?,?)',
                             (matched['id'], 'Auto-rejected via Gmail sync'))
                auto_rejected.append({'company': matched['company'], 'subject': subject})

            elif not is_rejection and ai_client and not matched:
                extracted = _ai_extract_job(ai_client, subject + '\n' + body)
                company   = (extracted.get('company') or '').strip()
                role      = (extracted.get('role') or '').strip()
                if company and role:
                    dedup_key = (company.lower(), role.lower())
                    if dedup_key in existing_keys:
                        skipped.append({'company': company, 'role': role})
                    else:
                        cv_row = conn.execute(
                            'SELECT id FROM cv_files WHERE is_active=1 AND user_id=?', (user_id,)
                        ).fetchone()
                        conn.execute(
                            '''INSERT INTO applications
                               (user_id, company, role, job_description, status, applied_date,
                                source, salary, location, job_url, notes, cv_id)
                               VALUES (?,?,?,?,'Applied',?,'Email',?,?,?,?,?)''',
                            (user_id, company, role, extracted.get('job_description'),
                             datetime.now().strftime('%Y-%m-%d'),
                             extracted.get('salary'), extracted.get('location'),
                             extracted.get('job_url'), extracted.get('notes'),
                             cv_row['id'] if cv_row else None)
                        )
                        app_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                        conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?,?)',
                                     (app_id, 'Auto-added via Gmail sync'))
                        existing_keys.add(dedup_key)
                        auto_added.append({'company': company, 'role': role})

        conn.execute(
            "INSERT OR REPLACE INTO settings (key,user_id,value) VALUES ('last_gmail_sync',?,datetime('now'))",
            (user_id,)
        )
        conn.commit()
        conn.close()
        return jsonify({'auto_rejected': auto_rejected, 'auto_added': auto_added, 'skipped': skipped})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── AI: Interview Prep ─────────────────────────────────────────────────────────

@app.route('/api/interview_prep/<int:app_id>', methods=['GET'])
@login_required
def get_prep(app_id):
    conn = get_db()
    # Verify ownership
    own = conn.execute('SELECT id FROM applications WHERE id=? AND user_id=?', (app_id, uid())).fetchone()
    if not own:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    row = conn.execute('SELECT prep_json FROM interview_prep WHERE application_id=?', (app_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'No prep generated yet'}), 404
    return jsonify(json.loads(row['prep_json']))


@app.route('/api/interview_prep/<int:app_id>', methods=['POST'])
@login_required
def generate_prep(app_id):
    client, err = require_ai()
    if err: return err

    conn = get_db()
    user_id = uid()
    app_row = conn.execute('SELECT * FROM applications WHERE id=? AND user_id=?', (app_id, user_id)).fetchone()
    cv_row  = conn.execute('SELECT text_content FROM cv_files WHERE is_active=1 AND user_id=?', (user_id,)).fetchone()
    conn.close()
    if not app_row:
        return jsonify({'error': 'Application not found'}), 404

    cv_text = cv_row['text_content'] if cv_row else 'CV not provided'
    prompt  = f"""You are a world-class interview coach. Prepare this candidate for their interview.

ROLE: {app_row['role']} at {app_row['company']}
LOCATION: {app_row['location'] or 'Not specified'}
SALARY: {app_row['salary'] or 'Not specified'}

JOB DESCRIPTION:
{(app_row['job_description'] or 'Not provided')[:2000]}

CANDIDATE CV:
{cv_text[:2500]}

Return ONLY valid JSON – no markdown fences, no preamble, start directly with {{:
{{
  "technical_questions":    [{{"question":"...","ideal_answer":"...","tip":"..."}}],
  "behavioral_questions":   [{{"question":"...","ideal_answer":"...","tip":"..."}}],
  "company_research":       ["point 1","point 2","point 3"],
  "strengths_to_highlight": ["..."],
  "gaps_to_address":        [{{"gap":"...","how_to_handle":"..."}}],
  "questions_to_ask":       ["..."],
  "salary_negotiation":     "advice string",
  "dress_code_tip":         "...",
  "overall_tip":            "..."
}}

Generate exactly 5 technical questions and 5 behavioral questions."""

    try:
        raw    = grok(client, prompt, max_tokens=3500)
        raw    = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        result = json.loads(raw)
    except Exception as e:
        return jsonify({'error': f'AI parse error: {e}'}), 500

    conn = get_db()
    conn.execute(
        'INSERT OR REPLACE INTO interview_prep (application_id,prep_json,generated_at) VALUES (?,?,datetime("now"))',
        (app_id, json.dumps(result))
    )
    conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?,?)',
                 (app_id, 'Interview prep generated'))
    conn.commit()
    conn.close()
    return jsonify(result)


# ── AI: Skills Gap ─────────────────────────────────────────────────────────────

@app.route('/api/skills_gap', methods=['POST'])
@login_required
def skills_gap():
    client, err = require_ai()
    if err: return err

    conn    = get_db()
    user_id = uid()
    cv_row  = conn.execute('SELECT text_content FROM cv_files WHERE is_active=1 AND user_id=?', (user_id,)).fetchone()
    app_rows = conn.execute(
        'SELECT role, job_description FROM applications WHERE user_id=? AND job_description IS NOT NULL LIMIT 10',
        (user_id,)
    ).fetchall()
    conn.close()

    if not cv_row:
        return jsonify({'error': 'Please upload your CV first'}), 400

    jd_ctx = '\n'.join([f"- {r['role']}: {(r['job_description'] or '')[:200]}" for r in app_rows])
    prompt = f"""You are a top career coach with deep knowledge of the 2025 global job market.

CANDIDATE CV:
{cv_row['text_content'][:3000]}

JOBS THEY HAVE APPLIED FOR:
{jd_ctx or '(none recorded)'}

Analyse their profile against the CURRENT 2025 market. Return ONLY valid JSON, no markdown fences:
{{
  "profile_summary":        "2-3 sentence honest summary",
  "current_strengths":      ["strength 1","strength 2","strength 3"],
  "skill_gaps": [
    {{"skill":"...","why_important":"...","demand":"High/Medium"}}
  ],
  "courses": [
    {{
      "title":    "exact course name",
      "platform": "Coursera/Udemy/YouTube/LinkedIn Learning/freeCodeCamp/etc",
      "url":      "real URL or null",
      "duration": "e.g. 10 hours",
      "why":      "why this helps",
      "priority": "High/Medium/Low",
      "free":     true
    }}
  ],
  "projects_to_build": [
    {{
      "title":         "project name",
      "description":   "what to build",
      "technologies":  ["tech1","tech2"],
      "resume_impact": "how to write it on CV",
      "difficulty":    "Beginner/Intermediate/Advanced",
      "time_estimate": "e.g. 2 weekends"
    }}
  ],
  "certifications": [
    {{"name":"...","provider":"...","cost":"...","why":"..."}}
  ],
  "market_insights":      ["2025 trend 1","trend 2","trend 3"],
  "job_titles_to_target": ["title 1","title 2","title 3"]
}}

Be specific to 2025. Give exactly 5 courses, 3 projects, 2 certifications, 4 skill gaps."""

    try:
        raw = grok(client, prompt, max_tokens=3500)
        raw = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({'error': f'AI parse error: {e}'}), 500


# ── Job Recommendations ────────────────────────────────────────────────────────

@app.route('/api/job_recommendations', methods=['POST'])
@login_required
def job_recommendations():
    client, err = require_ai()
    if err: return err

    conn    = get_db()
    user_id = uid()
    cv_row  = conn.execute('SELECT text_content FROM cv_files WHERE is_active=1 AND user_id=?', (user_id,)).fetchone()
    conn.close()
    if not cv_row:
        return jsonify({'error': 'Please upload your CV first'}), 400

    kw_prompt = f"""Based on this CV give 3 job-search keywords (job titles) that best match the
profile for the 2025 market. Return ONLY a JSON array: ["keyword1","keyword2","keyword3"]

CV:
{cv_row['text_content'][:2000]}"""

    try:
        raw      = grok(client, kw_prompt, max_tokens=80)
        raw      = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        keywords = json.loads(raw)
    except Exception:
        keywords = ['software developer', 'engineer', 'developer']

    jobs = []
    for kw in keywords[:2]:
        try:
            resp = requests.get(
                'https://remotive.com/api/remote-jobs',
                params={'search': kw, 'limit': 8},
                headers={'User-Agent': 'JobTrackerAI/1.0'},
                timeout=10
            )
            if resp.ok:
                for j in resp.json().get('jobs', []):
                    jobs.append({
                        'title':    j.get('title'),
                        'company':  j.get('company_name'),
                        'location': j.get('candidate_required_location', 'Remote'),
                        'salary':   j.get('salary', ''),
                        'url':      j.get('url'),
                        'tags':     j.get('tags', [])[:6],
                        'posted':   (j.get('publication_date') or '')[:10],
                        'logo':     j.get('company_logo', ''),
                    })
        except Exception:
            pass

    seen, unique = set(), []
    for j in jobs:
        key = f"{j['title']}|{j['company']}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    return jsonify({'keywords': keywords, 'jobs': unique[:18]})


# ── Boot ───────────────────────────────────────────────────────────────────────

init_db()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(debug=False, host='0.0.0.0', port=port)
