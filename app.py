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
import telebot
from telebot import types

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

# 👑 TELEGRAM MASTER ADMIN BOT CONFIGURATION
TG_ADMIN_TOKEN = "8122282328:AAEw9VgaHcmmSmySsgXqKcw9sBv9hWiEDpE"
TG_ADMIN_ID = 1777177694
tg_admin_bot = telebot.TeleBot(TG_ADMIN_TOKEN, parse_mode="HTML", threaded=True)

def send_tg_alert(text, photo_path=None, reply_markup=None):
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as photo:
                tg_admin_bot.send_photo(TG_ADMIN_ID, photo, caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            tg_admin_bot.send_message(TG_ADMIN_ID, text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

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
    c.execute("INSERT OR IGNORE INTO settings VALUES ('merchant_name', 'LUKORA ADMIN')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('upi_id', 'anshxlucky@fam')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('notice', '🚀 Welcome to LUKORA Cloud! 5 Coins free on signup.')")
    
    c.execute("INSERT OR IGNORE INTO coupons VALUES ('LUCKY20', 20, 1000, 0)")
    c.execute("INSERT OR IGNORE INTO coupons VALUES ('VIP50', 50, 500, 0)")

    c.execute("SELECT id FROM users WHERE username = 'admin'")
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (username, email, password, coins, is_admin, created_at) VALUES (?, ?, ?, 9999, 1, ?)",
                  ('admin', 'admin@lukora.cloud', generate_password_hash('admin123'), datetime.now().strftime("%Y-%m-%d")))
    else:
        c.execute("UPDATE users SET password = ?, is_admin = 1 WHERE username = 'admin'", (generate_password_hash('admin123'),))
    
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
            c.execute("SELECT b.id, b.user_id, b.filename, b.real_filename, u.username, u.is_vip, u.vip_expires, u.is_banned FROM bots b JOIN users u ON b.user_id = u.id WHERE b.is_running = 1")
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
                log_path = os.path.join(user_folder, f"{filename}.log")

                if os.path.exists(file_path):
                    proc = running_processes.get(bot_id)
                    if proc is None or proc.poll() is not None:
                        cmd = get_runner_command(file_path)
                        log_file = open(log_path, 'a', encoding='utf-8')
                        new_proc = subprocess.Popen(cmd, cwd=user_folder, stdout=log_file, stderr=subprocess.STDOUT)
                        running_processes[bot_id] = new_proc
            conn.close()
        except Exception:
            pass
        time.sleep(4)

threading.Thread(target=hosting_watchdog, daemon=True).start()

# ----------------- 🤖 TELEGRAM ADMIN BOT (FAST ATOMIC HANDLER) ----------------- #
def get_tg_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Live Overview", callback_data="tg_adm_stats"),
        types.InlineKeyboardButton("💳 Pending Orders", callback_data="tg_adm_pays")
    )
    markup.add(
        types.InlineKeyboardButton("🔍 Search User", callback_data="tg_search_user"),
        types.InlineKeyboardButton("📂 Client Code Vault", callback_data="tg_adm_vault")
    )
    markup.add(
        types.InlineKeyboardButton("👥 User Directory", callback_data="tg_adm_users"),
        types.InlineKeyboardButton("⚙️ Branding & UPI", callback_data="tg_adm_settings")
    )
    return markup

@tg_admin_bot.message_handler(commands=['start', 'admin'])
def handle_tg_admin_start(message):
    if int(message.from_user.id) != int(TG_ADMIN_ID):
        tg_admin_bot.reply_to(message, "❌ Unauthorized.")
        return
    tg_admin_bot.send_message(TG_ADMIN_ID, "👑 <b>LUKORA ADMIN CONTROL HUB</b> ⚡", reply_markup=get_tg_admin_keyboard())

# ⚡ INSTANT 1-CLICK BOT APPROVAL CALLBACK HANDLER
@tg_admin_bot.callback_query_handler(func=lambda call: True)
def handle_tg_callbacks(call):
    if int(call.from_user.id) != int(TG_ADMIN_ID):
        tg_admin_bot.answer_callback_query(call.id, "Unauthorized")
        return

    data = call.data
    conn = get_db()
    c = conn.cursor()

    # 1. Immediate Approve/Reject Handling
    if data.startswith("tg_pay_appr_") or data.startswith("tg_pay_rejc_") or data.startswith("tg_appr_") or data.startswith("tg_rejc_"):
        parts = data.split("_")
        action = "approve" if ("appr" in data) else "reject"
        pay_id = int(parts[-1])

        c.execute("SELECT * FROM payments WHERE id = ?", (pay_id,))
        pay = c.fetchone()

        if not pay:
            tg_admin_bot.answer_callback_query(call.id, "❌ Order not found!", show_alert=True)
            conn.close()
            return

        if pay['status'] != 'pending':
            tg_admin_bot.answer_callback_query(call.id, f"⚠️ Already {pay['status'].upper()}!", show_alert=True)
            conn.close()
            return

        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if action == "approve":
            c.execute("UPDATE payments SET status = 'approved', approved_by = 'Telegram Bot', approved_at = ? WHERE id = ?", (now_time, pay_id))
            
            coins_to_give = pay['coins_reward']
            if coins_to_give == 0 and "VIP" not in pay['item_type']:
                if pay['amount'] >= 1100: coins_to_give = 200
                elif pay['amount'] >= 600: coins_to_give = 100
                elif pay['amount'] >= 150: coins_to_give = 20
                else: coins_to_give = 15

            if "VIP" in pay['item_type']:
                exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, pay['user_id']))
                success_text = "👑 VIP 30-Days Activated!"
            else:
                c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (coins_to_give, pay['user_id']))
                success_text = f"🪙 {coins_to_give} Coins Credited!"

            txn_code = f"TXN-{random.randint(100000, 999999)}"
            c.execute("""
                INSERT INTO transactions (txn_id, user_id, username, type, amount, coins, plan_name, ref_id, admin_ref, created_at)
                VALUES (?, ?, ?, 'Payment Approved', ?, ?, ?, ?, 'Telegram Bot', ?)
            """, (txn_code, pay['user_id'], pay['username'], pay['amount'], coins_to_give, pay['item_type'], pay['request_id'], now_time))
            
            conn.commit()
            record_audit("Telegram Bot", "Payment Approved", pay['request_id'], f"Credited ₹{pay['amount']}")
            tg_admin_bot.answer_callback_query(call.id, f"✅ Order #{pay['request_id']} Approved! {success_text}", show_alert=True)
            
            try:
                tg_admin_bot.edit_message_caption(f"✅ <b>ORDER #{pay['request_id']} APPROVED!</b>\n\n👤 Client: {pay['username']}\n💵 Amount: ₹{pay['amount']}\n📦 Credited: {pay['item_type']}", TG_ADMIN_ID, call.message.message_id)
            except:
                pass

        else:
            c.execute("UPDATE payments SET status = 'rejected', reject_reason = 'Declined via Telegram Admin Bot', approved_by = 'Telegram Bot', approved_at = ? WHERE id = ?", (now_time, pay_id))
            conn.commit()
            record_audit("Telegram Bot", "Payment Rejected", pay['request_id'], "Declined by Admin")
            tg_admin_bot.answer_callback_query(call.id, f"❌ Order #{pay['request_id']} Rejected.", show_alert=True)
            try:
                tg_admin_bot.edit_message_caption(f"❌ <b>ORDER #{pay['request_id']} REJECTED</b>\n\n👤 Client: {pay['username']}\n💵 Amount: ₹{pay['amount']}", TG_ADMIN_ID, call.message.message_id)
            except:
                pass

    elif data == "tg_adm_stats":
        c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0")
        t_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bots WHERE is_running = 1")
        a_bots = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM payments WHERE status = 'approved'")
        rev = c.fetchone()[0] or 0.0
        c.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
        p_orders = c.fetchone()[0]
        tg_admin_bot.answer_callback_query(call.id)
        tg_admin_bot.send_message(TG_ADMIN_ID, f"📊 <b>LUKORA STATS</b>\n\n👤 Users: {t_users}\n⚡ Running Bots: {a_bots}\n💳 Pending: {p_orders}\n💰 Revenue: ₹{rev}", reply_markup=get_tg_admin_keyboard())

    elif data == "tg_adm_pays":
        c.execute("SELECT * FROM payments WHERE status = 'pending' ORDER BY id DESC LIMIT 5")
        pays = c.fetchall()
        tg_admin_bot.answer_callback_query(call.id)
        if not pays:
            tg_admin_bot.send_message(TG_ADMIN_ID, "✅ No pending payment requests!", reply_markup=get_tg_admin_keyboard())
        else:
            for p in pays:
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton(f"✅ Approve (₹{p['amount']})", callback_data=f"tg_pay_appr_{p['id']}"),
                    types.InlineKeyboardButton("❌ Reject", callback_data=f"tg_pay_rejc_{p['id']}")
                )
                tg_admin_bot.send_message(TG_ADMIN_ID, f"💳 <b>Order #{p['request_id']}</b>\n👤 Client: {p['username']}\n📦 Plan: {p['item_type']}\n💵 Amount: ₹{p['amount']}\n📌 UTR: <code>{p['utr']}</code>", reply_markup=markup)

    conn.close()

def run_tg_bot():
    try:
        tg_admin_bot.delete_webhook(drop_pending_updates=True)
    except:
        pass
    while True:
        try:
            tg_admin_bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception:
            time.sleep(3)

threading.Thread(target=run_tg_bot, daemon=True).start()

# ----------------- WEB ROUTES ----------------- #
@app.route('/')
def home():
    if 'user_id' in session:
        return safe_render('dashboard.html')
    return safe_render('landing.html')

@app.route('/dashboard')
def dashboard_view():
    if 'user_id' not in session:
        return redirect('/login')
    return safe_render('dashboard.html')

@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect('/dashboard')
    return safe_render('login.html')

@app.route('/register')
def register_page():
    return redirect('/login#register')

@app.route('/forgot-password')
def forgot_password_page():
    return redirect('/login#forgot')

@app.route('/store')
def store_page():
    if 'user_id' not in session:
        return redirect('/login')
    return safe_render('store.html')

@app.route('/payment')
def payment_page():
    if 'user_id' not in session:
        return redirect('/login')
    return safe_render('payment.html')

@app.route('/payment-history')
def payment_history_page():
    if 'user_id' not in session:
        return redirect('/login')
    return safe_render('payment_history.html')

# 👑 MASTER ADMIN PAGE (Guaranteed Direct Unlock)
@app.route('/admin', methods=['GET', 'POST'])
def admin_page():
    if request.method == 'POST':
        u = request.form.get('username', '').strip().lower()
        p = request.form.get('password', '').strip()
        
        # 100% Guaranteed Master Password Check
        if u == 'admin' and (p == 'admin123' or p == 'admin'):
            session.permanent = True
            session['user_id'] = 1
            session['username'] = 'admin'
            session['is_admin'] = 1
            return safe_render('admin.html')
        
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
            return safe_render('admin.html')
        else:
            return "<script>alert('Invalid Admin Credentials!'); window.location.href='/admin';</script>"

    if session.get('is_admin') == 1:
        return safe_render('admin.html')

    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>LUKORA Admin Portal</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background: #060913; color: #fff; font-family: sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
            .admin-box { background: #0c1222; border: 1px solid #1e293b; border-radius: 18px; padding: 30px; width: 100%; max-width: 380px; box-shadow: 0 20px 50px rgba(0,0,0,0.8); }
        </style>
    </head>
    <body>
        <div class="admin-box">
            <h4 class="text-center fw-bold text-info mb-3">👑 LUKORA ADMIN PORTAL</h4>
            <form action="/admin" method="POST">
                <div class="mb-3">
                    <label class="small text-secondary">Admin Username</label>
                    <input type="text" name="username" class="form-control bg-dark text-white border-secondary" required value="admin">
                </div>
                <div class="mb-3">
                    <label class="small text-secondary">Admin Password</label>
                    <input type="password" name="password" class="form-control bg-dark text-white border-secondary" required placeholder="••••••••">
                </div>
                <button type="submit" class="btn btn-info w-100 fw-bold py-2">Unlock Admin Hub</button>
            </form>
        </div>
    </body>
    </html>
    '''

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
            return jsonify({'success': False, 'msg': '❌ Account Banned!'})
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
        send_tg_alert(f"👤 <b>NEW USER REGISTERED:</b> {username} ({email})")
        return jsonify({'success': True, 'msg': '🎉 5 Coins credited! Login now.'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'msg': '❌ Username or Email already exists!'})
    finally:
        conn.close()

@app.route('/api/forgot_password', methods=['POST'])
def api_forgot_password():
    data = request.json or {}
    email = data.get('email', '').strip()
    new_password = data.get('new_password', '')

    if len(new_password) < 4:
        return jsonify({'success': False, 'msg': 'Password must be at least 4 characters!'})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE email = ?", (email,))
    user = c.fetchone()

    if user:
        c.execute("UPDATE users SET password = ? WHERE id = ?", (generate_password_hash(new_password), user['id']))
        conn.commit()
        conn.close()
        send_tg_alert(f"🔑 <b>Password Reset:</b> {user['username']}")
        return jsonify({'success': True, 'msg': '✅ Password updated! Please Sign In.'})
    
    conn.close()
    return jsonify({'success': False, 'msg': '❌ Email is not registered!'})

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

@app.route('/api/payment_history_details')
def get_payment_history_details():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE id = ?", (user_id,))
    u_row = c.fetchone()
    coins = u_row['coins'] if u_row else 0

    c.execute("SELECT value FROM settings WHERE key = 'site_name'")
    site_name = c.fetchone()['value']

    c.execute("SELECT id, request_id, item_type, amount, utr, screenshot, status, reject_reason, created_at FROM payments WHERE user_id = ? ORDER BY id DESC", (user_id,))
    history = [dict(r) for r in c.fetchall()]
    conn.close()

    return jsonify({'coins': coins, 'site_name': site_name, 'history': history})

@app.route('/api/bot_logs/<int:bot_id>')
def get_bot_logs(bot_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'logs': 'Unauthorized'}), 401
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM bots WHERE id = ? AND user_id = ?", (bot_id, session['user_id']))
    bot = c.fetchone()
    conn.close()

    if not bot:
        return jsonify({'success': False, 'logs': 'Bot not found'}), 404

    user_folder = os.path.join(UPLOAD_BASE, str(session['user_id']))
    log_path = os.path.join(user_folder, f"{bot['real_filename']}.log")

    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            logs = "".join(lines[-150:])
        return jsonify({'success': True, 'filename': bot['filename'], 'logs': logs or 'Bot active. No errors.'})
    
    return jsonify({'success': True, 'filename': bot['filename'], 'logs': 'No execution logs available.'})

@app.route('/api/install_package', methods=['POST'])
def install_package_api():
    if 'user_id' not in session:
        return jsonify({'success': False, 'output': 'Unauthorized'}), 401
    
    data = request.json or {}
    packages_input = data.get('packages', '').strip()
    clean_pkgs = [p.strip() for p in re.split(r'[,\s\n]+', packages_input) if p.strip()]
    safe_pkgs = [p for p in clean_pkgs if re.match(r'^[a-zA-Z0-9_\-\.\=\>\<]+$', p)]

    if not safe_pkgs:
        return jsonify({'success': False, 'output': '❌ Invalid package format.'})

    try:
        cmd = [sys.executable, "-m", "pip", "install"] + safe_pkgs
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return jsonify({'success': res.returncode == 0, 'output': res.stdout + "\n" + res.stderr})
    except Exception as e:
        return jsonify({'success': False, 'output': f'❌ Error: {e}'})

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
    log_path = os.path.join(user_folder, f"{bot['real_filename']}.log")

    if action == 'start':
        if not user['is_vip']:
            if user['coins'] < 5:
                conn.close()
                return jsonify({'success': False, 'msg': '❌ Minimum 5 Coins required!'})
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
            log_file = open(log_path, 'a', encoding='utf-8')
            proc = subprocess.Popen(cmd, cwd=user_folder, stdout=log_file, stderr=subprocess.STDOUT)
            running_processes[bot_id] = proc
            send_tg_alert(f"🚀 <b>Bot Launched 24x7:</b> {bot['filename']} by {user['username']}")

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
    photo_saved_path = None
    if file and file.filename != '':
        scr_filename = f"proof_{int(time.time())}_{secure_filename(file.filename)}"
        photo_saved_path = os.path.join(SCREENSHOT_DIR, scr_filename)
        file.save(photo_saved_path)

    p_info = plans[plan]
    req_id = f"LKR-{random.randint(100000, 999999)}"
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO payments (request_id, user_id, username, item_type, coins_reward, amount, utr, screenshot, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
    """, (req_id, user_id, session['username'], p_info['name'], p_info['coins'], final_charge, utr, scr_filename, datetime.now().strftime("%Y-%m-%d %H:%M")))
    pay_id = c.lastrowid
    conn.commit()
    conn.close()

    try:
        tg_markup = types.InlineKeyboardMarkup(row_width=2)
        tg_markup.add(
            types.InlineKeyboardButton(f"✅ Approve (₹{final_charge})", callback_data=f"tg_pay_appr_{pay_id}"),
            types.InlineKeyboardButton("❌ Reject", callback_data=f"tg_pay_rejc_{pay_id}")
        )
        caption_text = (
            f"🔔 <b>NEW PAYMENT RECEIVED!</b> 💳\n\n"
            f"🆔 <b>Request ID:</b> <code>#{req_id}</code>\n"
            f"👤 <b>Client:</b> {session['username']} (ID: {user_id})\n"
            f"📦 <b>Package:</b> {p_info['name']}\n"
            f"💵 <b>Amount Paid:</b> ₹{final_charge}\n"
            f"📌 <b>UTR / Ref:</b> <code>{utr}</code>"
        )
        send_tg_alert(caption_text, photo_saved_path, tg_markup)
    except Exception as e:
        print(f"Alert Error: {e}")

    return jsonify({'success': True, 'request_id': req_id, 'msg': f"✅ Payment request #{req_id} submitted for verification."})

# ⚡ LIVE 1-CLICK ATOMIC APPROVE / REJECT API
@app.route('/api/admin/payment/<int:pay_id>/<action>', methods=['POST', 'GET'])
def api_admin_payment_action(pay_id, action):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE id = ?", (pay_id,))
    pay = c.fetchone()

    if not pay:
        conn.close()
        return jsonify({'success': False, 'msg': '❌ Payment request not found!'})

    if pay['status'] != 'pending':
        conn.close()
        return jsonify({'success': False, 'msg': f"⚠️ This order was already {pay['status'].upper()}!"})

    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    admin_name = session.get('username', 'Admin')

    if action == 'approve':
        c.execute("UPDATE payments SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?", (admin_name, now_time, pay_id))
        
        coins_to_give = pay['coins_reward']
        if coins_to_give == 0 and "VIP" not in pay['item_type']:
            if pay['amount'] >= 1100: coins_to_give = 200
            elif pay['amount'] >= 600: coins_to_give = 100
            elif pay['amount'] >= 150: coins_to_give = 20
            else: coins_to_give = 15

        if "VIP" in pay['item_type']:
            exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, pay['user_id']))
            success_msg = f"👑 VIP 30-Days Activated for {pay['username']}!"
        else:
            c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (coins_to_give, pay['user_id']))
            success_msg = f"🪙 {coins_to_give} Coins Credited to {pay['username']}!"

        txn_code = f"TXN-{random.randint(100000, 999999)}"
        c.execute("""
            INSERT INTO transactions (txn_id, user_id, username, type, amount, coins, plan_name, ref_id, admin_ref, created_at)
            VALUES (?, ?, ?, 'Payment Approved', ?, ?, ?, ?, ?, ?)
        """, (txn_code, pay['user_id'], pay['username'], pay['amount'], coins_to_give, pay['item_type'], pay['request_id'], admin_name, now_time))
        
        conn.commit()
        record_audit(admin_name, "Approved Payment", pay['request_id'], f"Credited ₹{pay['amount']}")
        conn.close()

        send_tg_alert(f"✅ <b>ORDER #{pay['request_id']} APPROVED!</b>\n👤 Client: {pay['username']}\n💵 Amount: ₹{pay['amount']}")
        return jsonify({'success': True, 'msg': f"✅ Payment #{pay['request_id']} Approved! {success_msg}"})

    elif action == 'reject':
        data = request.get_json(silent=True) or {}
        reject_reason = data.get('reason', 'Payment evidence could not be verified')
        c.execute("UPDATE payments SET status = 'rejected', reject_reason = ?, approved_by = ?, approved_at = ? WHERE id = ?", (reject_reason, admin_name, now_time, pay_id))
        conn.commit()
        record_audit(admin_name, "Rejected Payment", pay['request_id'], f"Reason: {reject_reason}")
        conn.close()

        send_tg_alert(f"❌ <b>ORDER #{pay['request_id']} REJECTED</b>\n👤 Client: {pay['username']}")
        return jsonify({'success': True, 'msg': f"❌ Payment #{pay['request_id']} Rejected."})

    conn.close()
    return jsonify({'success': False, 'msg': 'Invalid action'})

# ----------------- ADMIN DATA APIs ----------------- #
@app.route('/api/admin/data')
def get_admin_data():
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
        'settings': {'site_name': site_name, 'merchant_name': merchant_name, 'upi_id': upi_id, 'notice': notice}
    })

@app.route('/api/admin/user/<int:user_id>/<action>', methods=['POST'])
def api_admin_user_action(user_id, action):
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()

    if action == 'add_coins':
        coins_amt = int(data.get('coins', 10))
        c.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE id = ?", (coins_amt, user_id))
        conn.commit()
    elif action == 'ban':
        c.execute("UPDATE users SET is_banned = 1, ban_reason = ? WHERE id = ?", (data.get('reason', 'Violation'), user_id))
        c.execute("UPDATE bots SET is_running = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
    elif action == 'unban':
        c.execute("UPDATE users SET is_banned = 0, ban_reason = NULL WHERE id = ?", (user_id,))
        conn.commit()
    elif action == 'make_vip':
        exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, user_id))
        conn.commit()
    elif action == 'reset_password':
        c.execute("UPDATE users SET password = ? WHERE id = ?", (generate_password_hash("123456"), user_id))
        conn.commit()

    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/all_bots')
def api_admin_all_bots():
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
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
    bot = c.fetchone()
    conn.close()

    if bot:
        file_path = os.path.join(UPLOAD_BASE, str(bot['user_id']), bot['real_filename'])
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=bot['filename'])
    return redirect('/admin')

@app.route('/api/admin/update_settings', methods=['POST'])
def api_update_settings():
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_name', ?)", (data.get('site_name', 'LUKORA'),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('merchant_name', ?)", (data.get('merchant_name', 'LUKORA ADMIN'),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", (data.get('upi_id', 'anshxlucky@fam'),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('notice', ?)", (data.get('notice', ''),))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)