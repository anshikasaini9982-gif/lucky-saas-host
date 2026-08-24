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
import re

app = Flask(__name__)
app.secret_key = "LUCKY_SAINI_SUPER_SECRET_KEY_@2026"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        filename TEXT,
        real_filename TEXT,
        is_running INTEGER DEFAULT 0,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        item_type TEXT,
        coins_reward INTEGER DEFAULT 0,
        amount REAL,
        utr TEXT,
        screenshot TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    c.execute("INSERT OR IGNORE INTO settings VALUES ('site_name', 'LUCKY SAINI HOSTING')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('upi_id', 'BHARATPE2U05011Z5J98004@unitype')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('notice', '🔥 Welcome to Bot Cloud! 5 Coins free on signup.')")
    
    c.execute("SELECT id FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, email, password, coins, is_admin, created_at) VALUES (?, ?, ?, 9999, 1, ?)",
                  ('admin', 'admin@luckysaini.com', generate_password_hash('admin123'), datetime.now().strftime("%Y-%m-%d")))
    
    conn.commit()
    conn.close()

init_db()

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
                        new_proc = subprocess.Popen(
                            [sys.executable, filename],
                            cwd=user_folder,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        running_processes[bot_id] = new_proc
            conn.close()
        except Exception as e:
            print(f"Watchdog error: {e}")
        time.sleep(5)

threading.Thread(target=hosting_watchdog, daemon=True).start()

# ----------------- PAGE RENDERING ----------------- #
@app.route('/')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('dashboard.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/store')
def store_page():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('store.html')

@app.route('/admin')
def admin_page():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect('/login')
    return render_template('admin.html')

@app.route('/admin/bots')
def admin_bots_page():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect('/login')
    return render_template('admin_bots.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ----------------- REST APIs (100% JINJA FREE) ----------------- #
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
            return jsonify({'success': False, 'msg': '❌ Aapka account ban hai!'})
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = user['is_admin']
        return jsonify({'success': True, 'is_admin': bool(user['is_admin'])})
    return jsonify({'success': False, 'msg': '❌ Galat Username ya Password!'})

@app.route('/api/signup', methods=['POST'])
def api_signup():
    data = request.json or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if len(password) < 4:
        return jsonify({'success': False, 'msg': 'Password kam se kam 4 akshar ka hona chahiye!'})

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, email, password, coins, created_at) VALUES (?, ?, ?, 5, ?)",
                  (username, email, generate_password_hash(password), datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        return jsonify({'success': True, 'msg': '🎉 5 Coins free credit hue! Ab Login karein.'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'msg': '❌ Username ya Email pehle se maujood hai!'})
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

    c.execute("SELECT id, filename, is_running, created_at FROM bots WHERE user_id = ? ORDER BY id DESC", (user_id,))
    bots = [dict(b) for b in c.fetchall()]

    c.execute("SELECT value FROM settings WHERE key = 'site_name'")
    site_name = c.fetchone()['value']

    c.execute("SELECT value FROM settings WHERE key = 'notice'")
    notice = c.fetchone()['value']

    c.execute("SELECT value FROM settings WHERE key = 'upi_id'")
    upi_id = c.fetchone()['value']
    conn.close()

    return jsonify({'user': user, 'bots': bots, 'site_name': site_name, 'notice': notice, 'upi_id': upi_id})

@app.route('/api/upload_bot', methods=['POST'])
def upload_bot_api():
    if 'user_id' not in session:
        return jsonify({'success': False, 'msg': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    file = request.files.get('file')

    if file and file.filename.endswith('.py'):
        user_folder = os.path.join(UPLOAD_BASE, str(user_id))
        os.makedirs(user_folder, exist_ok=True)
        
        orig_name = secure_filename(file.filename)
        clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', orig_name)
        safe_name = f"bot_{int(time.time())}_{clean_name}"
        file.save(os.path.join(user_folder, safe_name))

        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO bots (user_id, filename, real_filename, created_at) VALUES (?, ?, ?, ?)",
                  (user_id, orig_name, safe_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    return jsonify({'success': False, 'msg': 'Kripya valid .py file select karein.'})

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

    if action == 'start':
        if not user['is_vip']:
            if user['coins'] < 5:
                conn.close()
                return jsonify({'success': False, 'msg': '❌ Launch karne ke liye 5 Coins chahiye!'})
            c.execute("UPDATE users SET coins = coins - 5 WHERE id = ?", (user_id,))

        c.execute("UPDATE bots SET is_running = 1 WHERE id = ?", (bot_id,))
        conn.commit()

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
        
        file_path = os.path.join(UPLOAD_BASE, str(user_id), bot['real_filename'])
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
    file = request.files.get('screenshot')

    plans = {
        'coins_15': {'amt': 80.0, 'coins': 15, 'name': '15 Coins Pack'},
        'coins_20': {'amt': 150.0, 'coins': 20, 'name': '20 Coins Pack'},
        'coins_100': {'amt': 600.0, 'coins': 100, 'name': '100 Coins Pack'},
        'coins_200': {'amt': 1100.0, 'coins': 200, 'name': '200 Coins Pack'},
        'vip_monthly': {'amt': 499.0, 'coins': 0, 'name': 'VIP Unlimited (1 Month)'}
    }

    if plan not in plans:
        return jsonify({'success': False, 'msg': 'Invalid Plan'})

    scr_filename = "no_screenshot.png"
    if file and file.filename != '':
        scr_filename = f"proof_{int(time.time())}_{secure_filename(file.filename)}"
        file.save(os.path.join(SCREENSHOT_DIR, scr_filename))

    p_info = plans[plan]
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO payments (user_id, username, item_type, coins_reward, amount, utr, screenshot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (user_id, session['username'], p_info['name'], p_info['coins'], p_info['amt'], utr, scr_filename, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'msg': '✅ Payment Submit ho gayi! Admin approve karte hi activate ho jayegi.'})

# ----------------- ADMIN CONTROLLER APIs ----------------- #
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

    c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 20")
    payments = [dict(p) for p in c.fetchall()]

    c.execute("SELECT id, username, email, coins, is_vip, is_banned, created_at FROM users WHERE is_admin = 0 ORDER BY id DESC")
    users = [dict(u) for u in c.fetchall()]

    c.execute("SELECT value FROM settings WHERE key = 'site_name'")
    site_name = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'upi_id'")
    upi_id = c.fetchone()['value']
    c.execute("SELECT value FROM settings WHERE key = 'notice'")
    notice = c.fetchone()['value']

    conn.close()
    return jsonify({
        'stats': {'total_users': total_users, 'active_bots': active_bots, 'total_rev': total_rev, 'pending_orders': pending_orders},
        'payments': payments,
        'users': users,
        'settings': {'site_name': site_name, 'upi_id': upi_id, 'notice': notice}
    })

@app.route('/api/admin/user/<int:user_id>/<action>', methods=['POST'])
def api_admin_user_action(user_id, action):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db()
    c = conn.cursor()

    if action == 'ban':
        c.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
        c.execute("UPDATE bots SET is_running = 0 WHERE user_id = ?", (user_id,))
    elif action == 'unban':
        c.execute("UPDATE users SET is_banned = 0 WHERE id = ?", (user_id,))
    elif action == 'add_coins':
        data = request.json or {}
        coins_to_add = int(data.get('coins', 10))
        c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (coins_to_add, user_id))

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/payment/<int:pay_id>/<action>', methods=['POST'])
def api_admin_payment_action(pay_id, action):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE id = ?", (pay_id,))
    pay = c.fetchone()

    if pay and pay['status'] == 'pending':
        if action == 'approve':
            c.execute("UPDATE payments SET status = 'approved' WHERE id = ?", (pay_id,))
            if "VIP" in pay['item_type']:
                exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, pay['user_id']))
            else:
                c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (pay['coins_reward'], pay['user_id']))
        else:
            c.execute("UPDATE payments SET status = 'rejected' WHERE id = ?", (pay_id,))
        conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/all_bots')
def api_admin_all_bots():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT b.id, b.user_id, b.filename, b.real_filename, b.is_running, b.created_at, u.username, u.email
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
            return jsonify({'filename': bot['filename'], 'code': code_content})
    return jsonify({'error': 'File not found'}), 404

@app.route('/admin/download_bot/<int:bot_id>')
def download_bot_file(bot_id):
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect('/login')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
    bot = c.fetchone()
    conn.close()

    if bot:
        file_path = os.path.join(UPLOAD_BASE, str(bot['user_id']), bot['real_filename'])
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=bot['filename'])
    return redirect('/admin/bots')

@app.route('/api/admin/update_settings', methods=['POST'])
def api_update_settings():
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_name', ?)", (data.get('site_name', 'LUCKY SAINI HOSTING'),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", (data.get('upi_id', ''),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('notice', ?)", (data.get('notice', ''),))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
