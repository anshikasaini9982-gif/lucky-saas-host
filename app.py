from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import sqlite3
import os
import sys
import subprocess
import threading
import time
import random
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = "LUKORA_ENTERPRISE_SUPER_KEY_@2026"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

UPLOAD_BASE = os.path.join(BASE_DIR, 'user_bots')
SCREENSHOT_DIR = os.path.join(BASE_DIR, 'static', 'proofs')
os.makedirs(UPLOAD_BASE, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, 'hosting_saas.db')
running_processes = {}

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        email TEXT UNIQUE,
        password TEXT,
        coins INTEGER DEFAULT 5,
        is_vip INTEGER DEFAULT 0,
        vip_expires TEXT,
        is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        ban_reason TEXT,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        filename TEXT,
        real_filename TEXT,
        lang_type TEXT DEFAULT 'Python',
        is_running INTEGER DEFAULT 0,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT UNIQUE,
        user_id INTEGER,
        username TEXT,
        item_type TEXT,
        coins_reward INTEGER DEFAULT 0,
        amount REAL,
        utr TEXT,
        screenshot TEXT,
        status TEXT DEFAULT 'pending',
        reject_reason TEXT,
        approved_by TEXT,
        approved_at TEXT,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txn_id TEXT UNIQUE,
        user_id INTEGER,
        username TEXT,
        type TEXT,
        amount REAL DEFAULT 0,
        coins INTEGER DEFAULT 0,
        details TEXT,
        admin_ref TEXT,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_user TEXT,
        action TEXT,
        target TEXT,
        details TEXT,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS coupons (
        code TEXT PRIMARY KEY,
        discount_percent INTEGER,
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    c.execute("INSERT OR IGNORE INTO settings VALUES ('site_name', 'LUKORA')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('merchant_name', 'LUCKY BHAI HOSTING')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('upi_id', 'BHARATPE2U05011Z5J98004@unitype')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('notice', '🚀 Welcome to LUKORA Cloud! 5 Coins free on signup.')")
    
    c.execute("INSERT OR IGNORE INTO coupons VALUES ('LUCKY20', 20, 1000, 0)")
    c.execute("INSERT OR IGNORE INTO coupons VALUES ('VIP50', 50, 500, 0)")

    c.execute("SELECT id FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, email, password, coins, is_admin, created_at) VALUES (?, ?, ?, 9999, 1, ?)",
                  ('admin', 'admin@lukora.cloud', generate_password_hash('admin123'), datetime.now().strftime("%Y-%m-%d")))
    
    conn.commit()
    conn.close()

init_db()

def record_audit(admin, action, target, details=""):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO audit_logs (admin_user, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)",
                  (admin, action, str(target), str(details), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_runner_command(file_path):
    ext = file_path.split('.')[-1].lower()
    if ext == 'py':
        return [sys.executable, file_path]
    elif ext == 'js':
        return ['node', file_path]
    elif ext == 'php':
        return ['php', file_path]
    elif ext == 'sh':
        return ['bash', file_path]
    return [sys.executable, file_path]

def detect_language(filename):
    ext = filename.split('.')[-1].lower()
    mapping = {'py': 'Python', 'js': 'Node.js', 'php': 'PHP', 'sh': 'Bash'}
    return mapping.get(ext, 'Script')

def safe_render(template_name, **kwargs):
    try:
        return render_template(template_name, **kwargs)
    except Exception:
        root_tpl = os.path.join(BASE_DIR, template_name)
        if os.path.exists(root_tpl):
            with open(root_tpl, 'r', encoding='utf-8') as f:
                return f.read()
        return "<div style='background:#070b14;color:#fff;padding:40px;text-align:center;'><h2>Template Error</h2></div>", 500

# 🛡️ 24x7 WATCHDOG
def hosting_watchdog():
    while True:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT b.id, b.user_id, b.real_filename, u.is_vip, u.vip_expires, u.is_banned FROM bots b JOIN users u ON b.user_id = u.id WHERE b.is_running = 1")
            active_bots = c.fetchall()

            for b in active_bots:
                bot_id = b['id']
                user_id = b['user_id']
                filename = b['real_filename']
                is_vip = b['is_vip']
                vip_exp = b['vip_expires']
                is_banned = b['is_banned']

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if is_banned or (is_vip and vip_exp and vip_exp < now_str):
                    if is_vip and vip_exp < now_str:
                        c.execute("UPDATE users SET is_vip = 0 WHERE id = ?", (user_id,))
                    c.execute("UPDATE bots SET is_running = 0 WHERE id = ?", (bot_id,))
                    conn.commit()
                    if bot_id in running_processes:
                        running_processes[bot_id].terminate()
                        del running_processes[bot_id]
                    continue

                user_folder = os.path.join(UPLOAD_BASE, str(user_id))
                file_path = os.path.join(user_folder, filename)

                if os.path.exists(file_path):
                    proc = running_processes.get(bot_id)
                    if proc is None or proc.poll() is not None:
                        cmd = get_runner_command(file_path)
                        new_proc = subprocess.Popen(cmd, cwd=user_folder)
                        running_processes[bot_id] = new_proc
            conn.close()
        except Exception:
            pass
        time.sleep(4)

threading.Thread(target=hosting_watchdog, daemon=True).start()

# ----------------- WEB ROUTES ----------------- #
@app.route('/')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    return safe_render('dashboard.html')

@app.route('/login')
def login_page():
    return safe_render('login.html')

@app.route('/store')
def store_page():
    if 'user_id' not in session:
        return redirect('/login')
    return safe_render('store.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin_page():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? AND is_admin = 1", (u,))
        adm = c.fetchone()
        conn.close()

        if adm and check_password_hash(adm['password'], p):
            session.permanent = True
            session['user_id'] = adm['id']
            session['username'] = adm['username']
            session['is_admin'] = 1
            record_audit(adm['username'], "Admin Login", "Web Portal")
            return redirect('/admin')
        else:
            return "<script>alert('Invalid Admin Key!'); window.location.href='/admin';</script>"

    if 'user_id' not in session or not session.get('is_admin'):
        return '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>LUKORA Admin Portal</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { background: #060913; color: #fff; font-family: sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
                .admin-box { background: #0c1222; border: 1px solid #1e293b; border-radius: 18px; padding: 30px; width: 100%; max-width: 380px; }
            </style>
        </head>
        <body>
            <div class="admin-box">
                <h4 class="text-center fw-bold text-info mb-3">👑 LUKORA ADMIN PORTAL</h4>
                <form action="/admin" method="POST">
                    <div class="mb-3">
                        <label class="small text-secondary">Admin Username</label>
                        <input type="text" name="username" class="form-control bg-dark text-white border-secondary" required placeholder="admin">
                    </div>
                    <div class="mb-3">
                        <label class="small text-secondary">Admin Password</label>
                        <input type="password" name="password" class="form-control bg-dark text-white border-secondary" required placeholder="••••••••">
                    </div>
                    <button type="submit" class="btn btn-info w-100 fw-bold">Unlock Admin Hub</button>
                </form>
            </div>
        </body>
        </html>
        '''
    return safe_render('admin.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ----------------- APIs ----------------- #
@app.route('/api/site_info')
def get_site_info():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'site_name'")
    site_name = c.fetchone()['value']
    conn.close()
    return jsonify({'site_name': site_name})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, username))
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        if user['is_banned']:
            return jsonify({'success': False, 'msg': f"❌ Account Banned! Reason: {user['ban_reason'] or 'Violation of terms'}"})
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = user['is_admin']
        return jsonify({'success': True, 'is_admin': bool(user['is_admin'])})
    return jsonify({'success': False, 'msg': '❌ Invalid Username or Password!'})

@app.route('/api/signup', methods=['POST'])
def api_signup():
    data = request.json or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if len(password) < 4:
        return jsonify({'success': False, 'msg': 'Password must be at least 4 characters!'})

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, email, password, coins, created_at) VALUES (?, ?, ?, 5, ?)",
                  (username, email, generate_password_hash(password), datetime.now().strftime("%Y-%m-%d")))
        uid = c.lastrowid
        txn_code = f"TXN-{random.randint(100000, 999999)}"
        c.execute("INSERT INTO transactions (txn_id, user_id, username, type, coins, details, created_at) VALUES (?, ?, ?, 'Welcome Bonus', 5, 'Free Signup Bonus', ?)",
                  (txn_code, uid, username, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        return jsonify({'success': True, 'msg': '🎉 5 Coins credited! Login now.'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'msg': '❌ Username or Email already exists!'})
    finally:
        conn.close()

@app.route('/api/user_data')
def get_user_data():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, email, coins, is_vip, vip_expires, is_admin FROM users WHERE id = ?", (user_id,))
    user = dict(c.fetchone())

    c.execute("SELECT id, filename, lang_type, is_running, created_at FROM bots WHERE user_id = ? ORDER BY id DESC", (user_id,))
    bots = [dict(b) for b in c.fetchall()]

    c.execute("SELECT value FROM settings WHERE key = 'site_name'")
    site_name = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'merchant_name'")
    merchant_name = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'notice'")
    notice = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'upi_id'")
    upi_id = c.fetchone()['value']
    conn.close()

    return jsonify({'user': user, 'bots': bots, 'site_name': site_name, 'merchant_name': merchant_name, 'notice': notice, 'upi_id': upi_id})

@app.route('/api/my_payments')
def get_my_payments():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT request_id, item_type, amount, utr, status, reject_reason, created_at FROM payments WHERE user_id = ? ORDER BY id DESC LIMIT 10", (session['user_id'],))
    history = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({'history': history})

@app.route('/api/check_coupon', methods=['POST'])
def check_coupon():
    data = request.json or {}
    code = data.get('code', '').strip().upper()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM coupons WHERE code = ? AND used_count < max_uses", (code,))
    coup = c.fetchone()
    conn.close()

    if coup:
        return jsonify({'valid': True, 'discount': coup['discount_percent'], 'msg': f"🎉 {coup['discount_percent']}% Discount Applied!"})
    return jsonify({'valid': False, 'msg': '❌ Invalid or Expired Coupon!'})

@app.route('/api/upload_bot', methods=['POST'])
def upload_bot_api():
    if 'user_id' not in session:
        return jsonify({'success': False, 'msg': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    file = request.files.get('file')

    allowed_exts = ['py', 'js', 'php', 'sh']
    if file and any(file.filename.endswith('.' + ext) for ext in allowed_exts):
        user_folder = os.path.join(UPLOAD_BASE, str(user_id))
        os.makedirs(user_folder, exist_ok=True)
        
        orig_name = secure_filename(file.filename)
        clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', orig_name)
        safe_name = f"bot_{int(time.time())}_{clean_name}"
        file.save(os.path.join(user_folder, safe_name))

        lang = detect_language(orig_name)
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO bots (user_id, filename, real_filename, lang_type, created_at) VALUES (?, ?, ?, ?, ?)",
                  (user_id, orig_name, safe_name, lang, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    return jsonify({'success': False, 'msg': 'Supported: .py, .js, .php, .sh files only!'})

@app.route('/api/bot_action/<int:bot_id>/<action>')
def bot_action_api(bot_id, action):
    if 'user_id' not in session:
        return jsonify({'success': False, 'msg': 'Unauthorized'})
    
    user_id = session['user_id']
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM bots WHERE id = ? AND user_id = ?", (bot_id, user_id))
    bot = c.fetchone()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()

    if not bot:
        conn.close()
        return jsonify({'success': False, 'msg': 'Bot not found'})

    user_folder = os.path.join(UPLOAD_BASE, str(user_id))
    file_path = os.path.join(user_folder, bot['real_filename'])

    if action == 'start':
        if not user['is_vip']:
            if user['coins'] < 5:
                conn.close()
                return jsonify({'success': False, 'msg': '❌ Minimum 5 Coins required to Launch!'})
            c.execute("UPDATE users SET coins = coins - 5 WHERE id = ?", (user_id,))
            txn_code = f"TXN-{random.randint(100000, 999999)}"
            c.execute("INSERT INTO transactions (txn_id, user_id, username, type, coins, details, created_at) VALUES (?, ?, ?, 'Bot Launch', -5, ?, ?)",
                      (txn_code, user_id, user['username'], f"Launched {bot['filename']}", datetime.now().strftime("%Y-%m-%d %H:%M")))

        c.execute("UPDATE bots SET is_running = 1 WHERE id = ?", (bot_id,))
        conn.commit()

        if os.path.exists(file_path):
            if bot_id in running_processes and running_processes[bot_id].poll() is None:
                running_processes[bot_id].terminate()
            cmd = get_runner_command(file_path)
            proc = subprocess.Popen(cmd, cwd=user_folder)
            running_processes[bot_id] = proc

    elif action == 'stop':
        c.execute("UPDATE bots SET is_running = 0 WHERE id = ?", (bot_id,))
        conn.commit()
        if bot_id in running_processes:
            running_processes[bot_id].terminate()
            del running_processes[bot_id]

    elif action == 'delete':
        if bot_id in running_processes:
            running_processes[bot_id].terminate()
            del running_processes[bot_id]
        c.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        conn.commit()
        if os.path.exists(file_path):
            os.remove(file_path)

    conn.close()
    return jsonify({'success': True})

@app.route('/api/buy_plan', methods=['POST'])
def buy_plan_api():
    if 'user_id' not in session:
        return jsonify({'success': False, 'msg': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    plan = request.form.get('plan')
    utr = request.form.get('utr', '').strip()
    paid_amt = float(request.form.get('final_amount', 0))
    file = request.files.get('screenshot')

    plans = {
        'coins_15': {'amt': 80.0, 'coins': 15, 'name': '15 Coins Pack'},
        'coins_20': {'amt': 150.0, 'coins': 20, 'name': '20 Coins Pack'},
        'coins_100': {'amt': 600.0, 'coins': 100, 'name': '100 Coins Pack'},
        'coins_200': {'amt': 1100.0, 'coins': 200, 'name': '200 Coins Pack'},
        'vip_monthly': {'amt': 499.0, 'coins': 0, 'name': 'LUKORA VIP — 30 Days'}
    }

    if plan not in plans:
        return jsonify({'success': False, 'msg': 'Invalid Plan Selected'})

    final_charge = paid_amt if paid_amt > 0 else plans[plan]['amt']

    scr_filename = "no_screenshot.png"
    if file and file.filename != '':
        scr_filename = f"proof_{int(time.time())}_{secure_filename(file.filename)}"
        file.save(os.path.join(SCREENSHOT_DIR, scr_filename))

    p_info = plans[plan]
    req_id = f"LKR-{random.randint(100000, 999999)}"
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO payments (request_id, user_id, username, item_type, coins_reward, amount, utr, screenshot, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
    """, (req_id, user_id, session['username'], p_info['name'], p_info['coins'], final_charge, utr, scr_filename, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'request_id': req_id, 'msg': f"✅ Payment request #{req_id} submitted for manual verification."})

# ----------------- ADMIN APIs ----------------- #
@app.route('/api/admin/data')
def get_admin_data():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM bots WHERE is_running = 1")
    active_bots = c.fetchone()[0]
    c.execute("SELECT SUM(amount) FROM payments WHERE status = 'approved'")
    total_rev = c.fetchone()[0] or 0.0
    c.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
    pending_orders = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
    vip_users = c.fetchone()[0]
    c.execute("SELECT SUM(coins) FROM users WHERE is_admin = 0")
    coins_in_circ = c.fetchone()[0] or 0

    c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 50")
    payments = [dict(p) for p in c.fetchall()]

    c.execute("SELECT id, username, email, coins, is_vip, vip_expires, is_banned, ban_reason, created_at FROM users WHERE is_admin = 0 ORDER BY id DESC")
    users = [dict(u) for u in c.fetchall()]

    c.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 30")
    audit_logs = [dict(a) for a in c.fetchall()]

    c.execute("SELECT * FROM coupons ORDER BY used_count DESC")
    coupons = [dict(co) for co in c.fetchall()]

    c.execute("SELECT value FROM settings WHERE key = 'site_name'")
    site_name = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'merchant_name'")
    merchant_name = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'upi_id'")
    upi_id = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'notice'")
    notice = c.fetchone()['value']
    conn.close()

    return jsonify({
        'stats': {
            'total_users': total_users, 'active_bots': active_bots, 'total_rev': total_rev,
            'pending_orders': pending_orders, 'vip_users': vip_users, 'coins_in_circ': coins_in_circ
        },
        'payments': payments,
        'users': users,
        'audit_logs': audit_logs,
        'coupons': coupons,
        'settings': {'site_name': site_name, 'merchant_name': merchant_name, 'upi_id': upi_id, 'notice': notice}
    })

@app.route('/api/admin/payment/<int:pay_id>/<action>', methods=['POST'])
def api_admin_payment_action(pay_id, action):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json or {}
    reject_reason = data.get('reason', 'Payment evidence could not be verified')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE id = ?", (pay_id,))
    pay = c.fetchone()

    if not pay or pay['status'] != 'pending':
        conn.close()
        return jsonify({'success': False, 'msg': 'Invalid or already processed request'})

    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    admin_name = session.get('username', 'Admin')

    if action == 'approve':
        c.execute("UPDATE payments SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ? AND status = 'pending'",
                  (admin_name, now_time, pay_id))
        
        if "VIP" in pay['item_type']:
            exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, pay['user_id']))
        else:
            c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (pay['coins_reward'], pay['user_id']))

        txn_code = f"TXN-{random.randint(100000, 999999)}"
        c.execute("INSERT INTO transactions (txn_id, user_id, username, type, amount, coins, plan_name, ref_id, admin_ref, created_at) VALUES (?, ?, ?, 'Payment Approved', ?, ?, ?, ?, ?, ?)",
                  (txn_code, pay['user_id'], pay['username'], pay['amount'], pay['coins_reward'], pay['item_type'], pay['request_id'], admin_name, now_time))
        conn.commit()
        record_audit(admin_name, "Approved Payment", pay['request_id'], f"Credited ₹{pay['amount']}")

    elif action == 'reject':
        c.execute("UPDATE payments SET status = 'rejected', reject_reason = ?, approved_by = ?, approved_at = ? WHERE id = ? AND status = 'pending'",
                  (reject_reason, admin_name, now_time, pay_id))
        conn.commit()
        record_audit(admin_name, "Rejected Payment", pay['request_id'], f"Reason: {reject_reason}")

    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/user/<int:user_id>/<action>', methods=['POST'])
def api_admin_user_action(user_id, action):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json or {}
    admin_name = session.get('username', 'Admin')

    conn = get_db()
    c = conn.cursor()

    if action == 'add_coins':
        coins_amt = int(data.get('coins', 10))
        reason = data.get('reason', 'Admin balance adjustment')
        c.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE id = ?", (coins_amt, user_id))
        txn_code = f"TXN-{random.randint(100000, 999999)}"
        c.execute("INSERT INTO transactions (txn_id, user_id, username, type, coins, details, admin_ref, created_at) VALUES (?, ?, (SELECT username FROM users WHERE id=?), 'Coin Adjustment', ?, ?, ?, ?)",
                  (txn_code, user_id, user_id, coins_amt, reason, admin_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        record_audit(admin_name, "Coin Adjustment", user_id, f"{coins_amt} Coins")

    elif action == 'ban':
        reason = data.get('reason', 'Terms violation')
        c.execute("UPDATE users SET is_banned = 1, ban_reason = ? WHERE id = ?", (reason, user_id))
        c.execute("UPDATE bots SET is_running = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        record_audit(admin_name, "Banned User", user_id, f"Reason: {reason}")

    elif action == 'unban':
        c.execute("UPDATE users SET is_banned = 0, ban_reason = NULL WHERE id = ?", (user_id,))
        conn.commit()
        record_audit(admin_name, "Unbanned User", user_id)

    elif action == 'make_vip':
        exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, user_id))
        conn.commit()
        record_audit(admin_name, "Activated 30D VIP", user_id)

    elif action == 'reset_password':
        new_pwd = data.get('password', '123456')
        c.execute("UPDATE users SET password = ? WHERE id = ?", (generate_password_hash(new_pwd), user_id))
        conn.commit()
        record_audit(admin_name, "Reset User Password", user_id)

    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/all_bots')
def api_admin_all_bots():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT b.id, b.user_id, b.filename, b.real_filename, b.lang_type, b.is_running, b.created_at, u.username, u.email
        FROM bots b
        JOIN users u ON b.user_id = u.id
        ORDER BY b.id DESC
    """)
    bots = [dict(b) for b in c.fetchall()]
    conn.close()
    return jsonify({'bots': bots})

@app.route('/api/admin/view_code/<int:bot_id>')
def api_view_code(bot_id):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
    bot = c.fetchone()
    conn.close()

    if bot:
        file_path = os.path.join(UPLOAD_BASE, str(bot['user_id']), bot['real_filename'])
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                code_content = f.read()
            record_audit(session.get('username', 'Admin'), "Viewed Code", bot['filename'])
            return jsonify({'filename': bot['filename'], 'code': code_content})
    return jsonify({'error': 'File not found'}), 404

@app.route('/admin/download_bot/<int:bot_id>')
def download_bot_file(bot_id):
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect('/admin')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
    bot = c.fetchone()
    conn.close()

    if bot:
        file_path = os.path.join(UPLOAD_BASE, str(bot['user_id']), bot['real_filename'])
        if os.path.exists(file_path):
            record_audit(session.get('username', 'Admin'), "Downloaded File", bot['filename'])
            return send_file(file_path, as_attachment=True, download_name=bot['filename'])
    return redirect('/admin')

@app.route('/api/admin/update_settings', methods=['POST'])
def api_update_settings():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_name', ?)", (data.get('site_name', 'LUKORA'),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('merchant_name', ?)", (data.get('merchant_name', 'LUCKY BHAI HOSTING'),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", (data.get('upi_id', ''),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('notice', ?)", (data.get('notice', ''),))
    conn.commit()
    conn.close()
    record_audit(session.get('username', 'Admin'), "Updated Settings", "Branding & UPI")
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
            
