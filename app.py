import os, json, io, sqlite3, imaplib, email as email_lib
from datetime import datetime
from email.header import decode_header
from flask import Flask, render_template, request, jsonify, send_file
from openai import OpenAI
import pdfplumber
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
DB_PATH = os.getenv('DB_PATH', 'jobtracker.db')

# Grok uses OpenAI-compatible API — just swap the base_url
GROK_MODEL = os.getenv('GROK_MODEL', 'grok-3-mini')

def get_ai_client():
    key = os.getenv('XAI_API_KEY', '')
    if not key:
        return None
    return OpenAI(api_key=key, base_url='https://api.x.ai/v1')

def require_ai():
    c = get_ai_client()
    if not c:
        return None, (jsonify({'error': 'No XAI_API_KEY set in .env — get one free at console.x.ai'}), 400)
    return c, None

def grok(client, prompt, max_tokens=1500):
    """Single helper so every AI call is one line."""
    resp = client.chat.completions.create(
        model=GROK_MODEL,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content


# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
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
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id   INTEGER,
            action           TEXT,
            note             TEXT,
            timestamp        TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS interview_prep (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id   INTEGER UNIQUE,
            prep_json        TEXT,
            generated_at     TEXT DEFAULT (datetime('now'))
        );
    ''')
    conn.commit()
    conn.close()


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── Stats ──────────────────────────────────────────────────────────────────────

@app.route('/api/stats')
def get_stats():
    conn = get_db()
    stats = {}
    for status in ['Applied', 'Screening', 'Interview', 'Offer', 'Rejected', 'Withdrawn']:
        stats[status.lower()] = conn.execute(
            'SELECT COUNT(*) FROM applications WHERE status = ?', (status,)
        ).fetchone()[0]
    stats['total'] = conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0]

    recent = conn.execute('''
        SELECT al.action, al.note, al.timestamp, ap.company, ap.role
        FROM activity_log al
        LEFT JOIN applications ap ON al.application_id = ap.id
        ORDER BY al.timestamp DESC LIMIT 12
    ''').fetchall()
    stats['recent_activity'] = [dict(r) for r in recent]
    conn.close()
    return jsonify(stats)


# ── Applications ───────────────────────────────────────────────────────────────

@app.route('/api/applications', methods=['GET'])
def get_applications():
    conn = get_db()
    apps = conn.execute('''
        SELECT a.*, c.filename AS cv_filename
        FROM applications a
        LEFT JOIN cv_files c ON a.cv_id = c.id
        ORDER BY a.created_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(a) for a in apps])


@app.route('/api/applications', methods=['POST'])
def add_application():
    data = request.get_json()
    if not data.get('company') or not data.get('role'):
        return jsonify({'error': 'Company and role are required'}), 400

    conn = get_db()
    cv_id = data.get('cv_id')
    if not cv_id:
        cv_row = conn.execute('SELECT id FROM cv_files WHERE is_active = 1').fetchone()
        cv_id = cv_row['id'] if cv_row else None

    conn.execute('''
        INSERT INTO applications
          (company, role, job_description, status, applied_date, source, salary, location, job_url, notes, cv_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.get('company'), data.get('role'), data.get('job_description'),
        data.get('status', 'Applied'),
        data.get('applied_date', datetime.now().strftime('%Y-%m-%d')),
        data.get('source', 'Manual'), data.get('salary'),
        data.get('location'), data.get('job_url'), data.get('notes'), cv_id
    ))
    app_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?, ?)',
                 (app_id, f"Added – {data.get('role')} at {data.get('company')}"))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': app_id})


@app.route('/api/applications/<int:app_id>', methods=['PUT'])
def update_application(app_id):
    data = request.get_json()
    conn = get_db()
    allowed = ['company', 'role', 'job_description', 'status',
               'applied_date', 'salary', 'location', 'job_url', 'notes']
    sets, vals = [], []
    for f in allowed:
        if f in data:
            sets.append(f'{f} = ?')
            vals.append(data[f])
    sets.append("updated_at = datetime('now')")
    vals.append(app_id)
    conn.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id = ?", vals)

    if 'status' in data:
        conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?, ?)',
                     (app_id, f"Status → {data['status']}"))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/applications/<int:app_id>', methods=['DELETE'])
def delete_application(app_id):
    conn = get_db()
    conn.execute('DELETE FROM applications    WHERE id = ?', (app_id,))
    conn.execute('DELETE FROM activity_log   WHERE application_id = ?', (app_id,))
    conn.execute('DELETE FROM interview_prep WHERE application_id = ?', (app_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── CV Management ──────────────────────────────────────────────────────────────

@app.route('/api/cv', methods=['GET'])
def get_cvs():
    conn = get_db()
    rows = conn.execute(
        'SELECT id, filename, is_active, uploaded_at FROM cv_files ORDER BY uploaded_at DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/cv', methods=['POST'])
def upload_cv():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are supported'}), 400

    raw = f.read()
    text = ''
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or '') + '\n'
    except Exception as e:
        return jsonify({'error': f'PDF parse failed: {e}'}), 500

    conn = get_db()
    conn.execute('UPDATE cv_files SET is_active = 0')
    conn.execute(
        'INSERT INTO cv_files (filename, text_content, file_data, is_active) VALUES (?, ?, ?, 1)',
        (f.filename, text.strip(), raw)
    )
    cv_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': cv_id, 'preview': text[:600]})


@app.route('/api/cv/<int:cv_id>/activate', methods=['POST'])
def activate_cv(cv_id):
    conn = get_db()
    conn.execute('UPDATE cv_files SET is_active = 0')
    conn.execute('UPDATE cv_files SET is_active = 1 WHERE id = ?', (cv_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/cv/<int:cv_id>/download')
def download_cv(cv_id):
    conn = get_db()
    row = conn.execute('SELECT filename, file_data FROM cv_files WHERE id = ?', (cv_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return send_file(io.BytesIO(row['file_data']),
                     download_name=row['filename'], as_attachment=True)


@app.route('/api/cv/active_text')
def active_cv_text():
    conn = get_db()
    row = conn.execute('SELECT text_content FROM cv_files WHERE is_active = 1').fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'No active CV'}), 404
    return jsonify({'text': row['text_content']})


# ── AI: Extract job info from pasted text ──────────────────────────────────────

@app.route('/api/extract_job', methods=['POST'])
def extract_job():
    client, err = require_ai()
    if err: return err

    text = (request.get_json() or {}).get('text', '')
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    prompt = f"""Extract job application details from the text below.
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
{text[:3500]}"""

    try:
        raw = grok(client, prompt, max_tokens=900)
        # Strip markdown code fences if Grok wraps the JSON
        raw = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({'error': f'AI parse error: {e}'}), 500


# ── Gmail IMAP scan ────────────────────────────────────────────────────────────

@app.route('/api/gmail_scan', methods=['POST'])
def gmail_scan():
    data = request.get_json() or {}
    email_addr = data.get('email', '').strip()
    password   = data.get('password', '').strip()
    if not email_addr or not password:
        return jsonify({'error': 'Email and App Password required'}), 400

    job_keywords = ['application', 'interview', 'offer letter', 'position', 'role',
                    'vacancy', 'hiring', 'recruitment', 'job opportunity', 'shortlisted',
                    'congratulations', 'next steps', 'assessment']
    found = []
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(email_addr, password)
        mail.select('inbox')

        _, data_ids = mail.search(None, 'ALL')
        ids = data_ids[0].split()[-100:]

        for eid in reversed(ids):
            _, msg_data = mail.fetch(eid, '(RFC822)')
            raw_msg = email_lib.message_from_bytes(msg_data[0][1])

            raw_subj = raw_msg.get('Subject', '')
            decoded  = decode_header(raw_subj)[0]
            subject  = decoded[0].decode(decoded[1] or 'utf-8', errors='ignore') \
                       if isinstance(decoded[0], bytes) else (decoded[0] or '')

            if not any(kw in subject.lower() for kw in job_keywords):
                continue

            body = ''
            if raw_msg.is_multipart():
                for part in raw_msg.walk():
                    if part.get_content_type() == 'text/plain':
                        body = (part.get_payload(decode=True) or b'').decode('utf-8', errors='ignore')[:2500]
                        break
            else:
                body = (raw_msg.get_payload(decode=True) or b'').decode('utf-8', errors='ignore')[:2500]

            found.append({'subject': subject, 'sender': raw_msg.get('From', ''),
                          'date': raw_msg.get('Date', ''), 'body': body})
            if len(found) >= 20:
                break

        mail.logout()
        return jsonify({'emails': found, 'count': len(found)})
    except imaplib.IMAP4.error as e:
        return jsonify({'error': f'Login failed – check your App Password: {e}'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── AI: Interview Prep ─────────────────────────────────────────────────────────

@app.route('/api/interview_prep/<int:app_id>', methods=['GET'])
def get_prep(app_id):
    conn = get_db()
    row = conn.execute('SELECT prep_json FROM interview_prep WHERE application_id = ?', (app_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'No prep generated yet'}), 404
    return jsonify(json.loads(row['prep_json']))


@app.route('/api/interview_prep/<int:app_id>', methods=['POST'])
def generate_prep(app_id):
    client, err = require_ai()
    if err: return err

    conn = get_db()
    app_row = conn.execute('SELECT * FROM applications WHERE id = ?', (app_id,)).fetchone()
    cv_row  = conn.execute('SELECT text_content FROM cv_files WHERE is_active = 1').fetchone()
    conn.close()

    if not app_row:
        return jsonify({'error': 'Application not found'}), 404

    cv_text = cv_row['text_content'] if cv_row else 'CV not provided'

    prompt = f"""You are a world-class interview coach. Prepare this candidate for their interview.

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
        raw = grok(client, prompt, max_tokens=3500)
        raw = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        result = json.loads(raw)
    except Exception as e:
        return jsonify({'error': f'AI parse error: {e}'}), 500

    conn = get_db()
    conn.execute('''
        INSERT OR REPLACE INTO interview_prep (application_id, prep_json, generated_at)
        VALUES (?, ?, datetime('now'))
    ''', (app_id, json.dumps(result)))
    conn.execute('INSERT INTO activity_log (application_id, action) VALUES (?, ?)',
                 (app_id, 'Interview prep generated'))
    conn.commit()
    conn.close()
    return jsonify(result)


# ── AI: Skills Gap & Course Suggestions ───────────────────────────────────────

@app.route('/api/skills_gap', methods=['POST'])
def skills_gap():
    client, err = require_ai()
    if err: return err

    conn = get_db()
    cv_row   = conn.execute('SELECT text_content FROM cv_files WHERE is_active = 1').fetchone()
    app_rows = conn.execute(
        'SELECT role, job_description FROM applications WHERE job_description IS NOT NULL LIMIT 10'
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
def job_recommendations():
    client, err = require_ai()
    if err: return err

    conn = get_db()
    cv_row = conn.execute('SELECT text_content FROM cv_files WHERE is_active = 1').fetchone()
    conn.close()
    if not cv_row:
        return jsonify({'error': 'Please upload your CV first'}), 400

    kw_prompt = f"""Based on this CV give 3 job-search keywords (job titles) that best match the
profile for the 2025 market. Return ONLY a JSON array: ["keyword1","keyword2","keyword3"]

CV:
{cv_row['text_content'][:2000]}"""

    try:
        raw = grok(client, kw_prompt, max_tokens=80)
        raw = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        keywords = json.loads(raw)
    except:
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
        except:
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
