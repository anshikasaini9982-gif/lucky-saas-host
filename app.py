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
import telebot
from telebot import types

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = "LUCKY_SAINI_SUPER_SECRET_KEY_@2026"
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
tg_admin_bot = telebot.TeleBot(TG_ADMIN_TOKEN, parse_mode="HTML")

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

    c.execute("INSERT OR IGNORE INTO settings VALUES ('site_name', 'LUCKY SAINI HOSTING')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('upi_id', 'BHARATPE2U05011Z5J98004@unitype')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('notice', '🔥 Welcome to Lucky Saini Cloud! 5 Coins free on signup.')")
    
    # Pre-loaded Coupons
    c.execute("INSERT OR IGNORE INTO coupons VALUES ('LUCKY20', 20, 1000, 0)")
    c.execute("INSERT OR IGNORE INTO coupons VALUES ('VIP50', 50, 500, 0)")

    c.execute("SELECT id FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, email, password, coins, is_admin, created_at) VALUES (?, ?, ?, 9999, 1, ?)",
                  ('admin', 'admin@luckysaini.com', generate_password_hash('admin123'), datetime.now().strftime("%Y-%m-%d")))
    
    conn.commit()
    conn.close()

init_db()

def safe_render(template_name, **kwargs):
    try:
        return render_template(template_name, **kwargs)
    except Exception:
        root_tpl = os.path.join(BASE_DIR, template_name)
        if os.path.exists(root_tpl):
            with open(root_tpl, 'r', encoding='utf-8') as f:
                return f.read()
        return f"<div style='background:#070b14;color:#fff;padding:40px;text-align:center;'><h2>Template Error</h2></div>", 500

# 🛡️ 24x7 WATCHDOG (Auto-Revive + Auto VIP Expiry)
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
                # ⏰ Auto-Expire VIP Plan after 30 Days
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
                        new_proc = subprocess.Popen([sys.executable, file_path], cwd=user_folder)
                        running_processes[bot_id] = new_proc
            conn.close()
        except Exception:
            pass
        time.sleep(4)

threading.Thread(target=hosting_watchdog, daemon=True).start()

# ----------------- 🤖 TELEGRAM BOT CONTROLLER ----------------- #
def get_tg_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Live Stats", callback_data="tg_adm_stats"),
        types.InlineKeyboardButton("💳 Pending Orders", callback_data="tg_adm_pays")
    )
    markup.add(
        types.InlineKeyboardButton("🔍 Search User (Email/Name)", callback_data="tg_search_user"),
        types.InlineKeyboardButton("📂 Client Code Vault", callback_data="tg_adm_vault")
    )
    markup.add(
        types.InlineKeyboardButton("👥 User Directory", callback_data="tg_adm_users"),
        types.InlineKeyboardButton("⚙️ Change Settings/UPI", callback_data="tg_adm_settings")
    )
    return markup

def get_user_manage_keyboard(user_id, is_banned):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ 10 Coins", callback_data=f"tg_coins_{user_id}_10"),
        types.InlineKeyboardButton("➖ 10 Coins", callback_data=f"tg_coins_{user_id}_-10")
    )
    markup.add(
        types.InlineKeyboardButton("➕ 50 Coins", callback_data=f"tg_coins_{user_id}_50"),
        types.InlineKeyboardButton("➖ 50 Coins", callback_data=f"tg_coins_{user_id}_-50")
    )
    ban_btn = types.InlineKeyboardButton("🟢 Unban", callback_data=f"tg_ban_{user_id}_unban") if is_banned else types.InlineKeyboardButton("🔴 Ban User", callback_data=f"tg_ban_{user_id}_ban")
    markup.add(
        types.InlineKeyboardButton("👑 Give VIP (30D)", callback_data=f"tg_vip_{user_id}"),
        types.InlineKeyboardButton("🔑 Reset Pass: 123456", callback_data=f"tg_rst_{user_id}")
    )
    markup.add(ban_btn, types.InlineKeyboardButton("🔙 Back to Search", callback_data="tg_search_user"))
    return markup

@tg_admin_bot.message_handler(commands=['start', 'admin'])
def handle_tg_admin_start(message):
    if message.from_user.id != TG_ADMIN_ID:
        tg_admin_bot.reply_to(message, "❌ Unauthorized!")
        return

    text = (
        "👑 <b>MASTER ADMIN CONTROL HUB</b> ⚡\n\n"
        "Welcome Master Lucky Saini! Yahan se aap poore platform ko inline buttons ke sath live control kar sakte hain."
    )
    tg_admin_bot.send_message(TG_ADMIN_ID, text, reply_markup=get_tg_admin_keyboard())

@tg_admin_bot.message_handler(commands=['search'])
def handle_tg_search_cmd(message):
    if message.from_user.id != TG_ADMIN_ID:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        tg_admin_bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/search username_ya_email</code>")
        return
    search_and_display_user(parts[1].strip())

def search_and_display_user(query):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username LIKE ? OR email LIKE ? OR id = ?", (f"%{query}%", f"%{query}%", query))
    users = c.fetchall()
    conn.close()

    if not users:
        tg_admin_bot.send_message(TG_ADMIN_ID, f"❌ Koi user nahi mila query: <b>{query}</b> ke liye!", reply_markup=get_tg_admin_keyboard())
        return

    for u in users:
        vip_status = f"👑 VIP Active (Till {u['vip_expires']})" if u['is_vip'] else "Standard Free"
        ban_status = "🔴 BANNED" if u['is_banned'] else "🟢 Active"
        card = (
            f"👤 <b>CLIENT PROFILE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>User ID:</b> <code>{u['id']}</code>\n"
            f"👤 <b>Username:</b> <b>{u['username']}</b>\n"
            f"📧 <b>Email:</b> <code>{u['email']}</code>\n"
            f"🪙 <b>Coin Balance:</b> <b>{u['coins']} Coins</b>\n"
            f"💎 <b>Plan:</b> {vip_status}\n"
            f"🛡️ <b>Status:</b> {ban_status}\n"
            f"📅 <b>Joined:</b> {u['created_at']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👇 <i>Neeche buttons se Coins ya Settings change karein:</i>"
        )
        tg_admin_bot.send_message(TG_ADMIN_ID, card, reply_markup=get_user_manage_keyboard(u['id'], u['is_banned']))

@tg_admin_bot.callback_query_handler(func=lambda call: True)
def handle_tg_callbacks(call):
    if call.from_user.id != TG_ADMIN_ID:
        return

    data = call.data
    conn = get_db()
    c = conn.cursor()

    if data == "tg_search_user":
        msg = tg_admin_bot.send_message(TG_ADMIN_ID, "🔍 <b>Search Client:</b>\n\nJis user ko dhoondna hai uska <b>Username</b> ya <b>Email Address</b> type karke bhejein:")
        tg_admin_bot.register_next_step_handler(msg, lambda m: search_and_display_user(m.text.strip()))

    elif data.startswith("tg_coins_"):
        parts = data.split("_")
        user_id = int(parts[2])
        amt = int(parts[3])
        c.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE id = ?", (amt, user_id))
        conn.commit()
        c.execute("SELECT username, coins, is_banned FROM users WHERE id = ?", (user_id,))
        u = c.fetchone()
        tg_admin_bot.answer_callback_query(call.id, f"✅ Balance Updated! New Coins: {u['coins']}", show_alert=True)
        tg_admin_bot.edit_message_reply_markup(TG_ADMIN_ID, call.message.message_id, reply_markup=get_user_manage_keyboard(user_id, u['is_banned']))

    elif data.startswith("tg_ban_"):
        parts = data.split("_")
        user_id = int(parts[2])
        action = parts[3]
        new_ban = 1 if action == "ban" else 0
        c.execute("UPDATE users SET is_banned = ? WHERE id = ?", (new_ban, user_id))
        if new_ban == 1:
            c.execute("UPDATE bots SET is_running = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        tg_admin_bot.answer_callback_query(call.id, f"✅ User {action.upper()} Successful!", show_alert=True)
        tg_admin_bot.edit_message_reply_markup(TG_ADMIN_ID, call.message.message_id, reply_markup=get_user_manage_keyboard(user_id, new_ban))

    elif data.startswith("tg_vip_"):
        user_id = int(data.replace("tg_vip_", ""))
        exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, user_id))
        conn.commit()
        tg_admin_bot.answer_callback_query(call.id, "👑 30 Days VIP Plan Activated for User!", show_alert=True)

    elif data.startswith("tg_rst_"):
        user_id = int(data.replace("tg_rst_", ""))
        c.execute("UPDATE users SET password = ? WHERE id = ?", (generate_password_hash("123456"), user_id))
        conn.commit()
        tg_admin_bot.answer_callback_query(call.id, "🔑 Password Reset to: 123456", show_alert=True)

    elif data == "tg_adm_stats":
        c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0")
        t_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bots WHERE is_running = 1")
        a_bots = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM payments WHERE status = 'approved'")
        rev = c.fetchone()[0] or 0.0
        c.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
        p_orders = c.fetchone()[0]

        stats_text = (
            "📊 <b>LIVE PLATFORM OVERVIEW</b>\n\n"
            f"👤 <b>Total Clients:</b> <code>{t_users}</code>\n"
            f"⚡ <b>Live Bots (24x7):</b> <code>{a_bots}</code>\n"
            f"💳 <b>Pending Payments:</b> <code>{p_orders}</code>\n"
            f"💰 <b>Total Revenue:</b> ₹<code>{rev}</code>\n"
        )
        tg_admin_bot.send_message(TG_ADMIN_ID, stats_text, reply_markup=get_tg_admin_keyboard())

    elif data == "tg_adm_pays":
        c.execute("SELECT * FROM payments WHERE status = 'pending' ORDER BY id DESC LIMIT 5")
        pays = c.fetchall()
        if not pays:
            tg_admin_bot.answer_callback_query(call.id, "Koi pending payment nahi hai!", show_alert=True)
        else:
            for p in pays:
                p_text = (
                    f"💳 <b>Pending Payment Request #{p['id']}</b>\n\n"
                    f"👤 <b>User:</b> {p['username']} (ID: {p['user_id']})\n"
                    f"📦 <b>Plan:</b> {p['item_type']}\n"
                    f"💵 <b>Amount:</b> ₹{p['amount']}\n"
                    f"📌 <b>UTR:</b> <code>{p['utr']}</code>\n"
                    f"📅 <b>Date:</b> {p['created_at']}"
                )
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("✅ Approve", callback_data=f"tg_pay_appr_{p['id']}"),
                    types.InlineKeyboardButton("❌ Reject", callback_data=f"tg_pay_rejc_{p['id']}")
                )
                tg_admin_bot.send_message(TG_ADMIN_ID, p_text, reply_markup=markup)

    elif data.startswith("tg_pay_appr_") or data.startswith("tg_pay_rejc_"):
        parts = data.split("_")
        action = parts[2]
        pay_id = int(parts[3])

        c.execute("SELECT * FROM payments WHERE id = ?", (pay_id,))
        pay = c.fetchone()
        if pay and pay['status'] == 'pending':
            if action == 'appr':
                c.execute("UPDATE payments SET status = 'approved' WHERE id = ?", (pay_id,))
                if "VIP" in pay['item_type']:
                    exp_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                    c.execute("UPDATE users SET is_vip = 1, vip_expires = ? WHERE id = ?", (exp_date, pay['user_id']))
                else:
                    c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (pay['coins_reward'], pay['user_id']))
                conn.commit()
                tg_admin_bot.answer_callback_query(call.id, f"✅ Payment #{pay_id} Approved! Coins Credited.", show_alert=True)
                try:
                    tg_admin_bot.edit_message_caption(f"✅ <b>PAYMENT #{pay_id} APPROVED! (+{pay['item_type']})</b>\n\n👤 User: {pay['username']}\n💵 Amount: ₹{pay['amount']}\n📌 UTR: {pay['utr']}", TG_ADMIN_ID, call.message.message_id)
                except:
                    tg_admin_bot.edit_message_text(f"✅ <b>PAYMENT #{pay_id} APPROVED! (+{pay['item_type']})</b>\n\n👤 User: {pay['username']}\n💵 Amount: ₹{pay['amount']}\n📌 UTR: {pay['utr']}", TG_ADMIN_ID, call.message.message_id)
            else:
                c.execute("UPDATE payments SET status = 'rejected' WHERE id = ?", (pay_id,))
                conn.commit()
                tg_admin_bot.answer_callback_query(call.id, f"❌ Payment #{pay_id} Rejected.", show_alert=True)
                try:
                    tg_admin_bot.edit_message_caption(f"❌ <b>PAYMENT #{pay_id} REJECTED</b>\n\n👤 User: {pay['username']}\n💵 Amount: ₹{pay['amount']}\n📌 UTR: {pay['utr']}", TG_ADMIN_ID, call.message.message_id)
                except:
                    tg_admin_bot.edit_message_text(f"❌ <b>PAYMENT #{pay_id} REJECTED</b>\n\n👤 User: {pay['username']}\n💵 Amount: ₹{pay['amount']}\n📌 UTR: {pay['utr']}", TG_ADMIN_ID, call.message.message_id)

    elif data == "tg_adm_vault":
        c.execute("SELECT b.id, b.user_id, b.filename, b.real_filename, u.username FROM bots b JOIN users u ON b.user_id = u.id ORDER BY b.id DESC LIMIT 10")
        all_b = c.fetchall()
        if not all_b:
            tg_admin_bot.answer_callback_query(call.id, "Abhi koi bot uploaded nahi hai!", show_alert=True)
        else:
            for b in all_b:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(f"⬇️ Download {b['filename']}", callback_data=f"tg_dl_{b['id']}"))
                tg_admin_bot.send_message(TG_ADMIN_ID, f"📄 <b>Script:</b> <code>{b['filename']}</code>\n👤 <b>By User:</b> {b['username']}", reply_markup=markup)

    elif data.startswith("tg_dl_"):
        bot_id = int(data.replace("tg_dl_", ""))
        c.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
        b = c.fetchone()
        if b:
            file_path = os.path.join(UPLOAD_BASE, str(b['user_id']), b['real_filename'])
            if os.path.exists(file_path):
                with open(file_path, 'rb') as doc:
                    tg_admin_bot.send_document(TG_ADMIN_ID, doc, caption=f"📁 <b>{b['filename']}</b>")
            else:
                tg_admin_bot.answer_callback_query(call.id, "File server par nahi mili!", show_alert=True)

    elif data == "tg_adm_users":
        c.execute("SELECT id, username, email, coins, is_banned, is_vip FROM users WHERE is_admin = 0 ORDER BY id DESC LIMIT 8")
        users = c.fetchall()
        u_text = "👥 <b>RECENT REGISTERED CLIENTS:</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for u in users:
            b_status = "🔴 BANNED" if u['is_banned'] else ("👑 VIP" if u['is_vip'] else "🟢 Active")
            u_text += f"• <b>{u['username']}</b> (<code>{u['email']}</code>)\n  🪙 {u['coins']} Coins | {b_status}\n\n"
        u_text += "💡 <i>Kisi specific user ko manage karne ke liye <b>🔍 Search User</b> button dabayein!</i>"
        tg_admin_bot.send_message(TG_ADMIN_ID, u_text, reply_markup=get_tg_admin_keyboard())

    elif data == "tg_adm_settings":
        c.execute("SELECT value FROM settings WHERE key = 'site_name'")
        site = c.fetchone()['value']
        c.execute("SELECT value FROM settings WHERE key = 'upi_id'")
        upi = c.fetchone()['value']
        s_text = f"⚙️ <b>CURRENT SYSTEM SETTINGS</b>\n\n🏢 <b>Brand Name:</b> {site}\n💳 <b>UPI ID:</b> <code>{upi}</code>\n\n👇 <i>Kya badalna chahte hain?</i>"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✏️ Change Brand Name", callback_data="tg_set_brand"),
            types.InlineKeyboardButton("💳 Change UPI ID", callback_data="tg_set_upi")
        )
        markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="tg_back_main"))
        tg_admin_bot.send_message(TG_ADMIN_ID, s_text, reply_markup=markup)

    elif data == "tg_set_brand":
        msg = tg_admin_bot.send_message(TG_ADMIN_ID, "✍️ <b>Naya Website / Brand Name bhejein:</b>")
        tg_admin_bot.register_next_step_handler(msg, process_tg_new_brand)

    elif data == "tg_set_upi":
        msg = tg_admin_bot.send_message(TG_ADMIN_ID, "💳 <b>Nayi UPI ID bhejein:</b>")
        tg_admin_bot.register_next_step_handler(msg, process_tg_new_upi)

    elif data == "tg_back_main":
        handle_tg_admin_start(call.message)

    conn.close()

def process_tg_new_brand(message):
    if message.from_user.id != TG_ADMIN_ID:
        return
    new_name = message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_name', ?)", (new_name,))
    conn.commit()
    conn.close()
    tg_admin_bot.send_message(TG_ADMIN_ID, f"✅ <b>Brand Name updated to '{new_name}'!</b>", reply_markup=get_tg_admin_keyboard())

def process_tg_new_upi(message):
    if message.from_user.id != TG_ADMIN_ID:
        return
    new_upi = message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", (new_upi,))
    conn.commit()
    conn.close()
    tg_admin_bot.send_message(TG_ADMIN_ID, f"✅ <b>UPI ID updated to '<code>{new_upi}</code>'!</b>", reply_markup=get_tg_admin_keyboard())

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

# ----------------- WEB ROUTES & STORE COUPONS ----------------- #
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
            return redirect('/admin')
        else:
            return "<script>alert('Galat Admin Password!'); window.location.href='/admin';</script>"

    if 'user_id' not in session or not session.get('is_admin'):
        return '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Master Admin Login</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { background: #070b14; color: #fff; font-family: sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
                .admin-box { background: #0f172a; border: 1px solid #1e293b; border-radius: 16px; padding: 30px; width: 100%; max-width: 380px; }
            </style>
        </head>
        <body>
            <div class="admin-box">
                <h4 class="text-center fw-bold text-info mb-3">👑 MASTER ADMIN PORTAL</h4>
                <form action="/admin" method="POST">
                    <div class="mb-3">
                        <label class="small text-secondary">Admin Username</label>
                        <input type="text" name="username" class="form-control bg-dark text-white border-secondary" required placeholder="admin">
                    </div>
                    <div class="mb-3">
                        <label class="small text-secondary">Admin Password</label>
                        <input type="password" name="password" class="form-control bg-dark text-white border-secondary" required placeholder="••••••••">
                    </div>
                    <button type="submit" class="btn btn-info w-100 fw-bold">Login to Admin Hub</button>
                </form>
            </div>
        </body>
        </html>
        '''
    return safe_render('admin.html')

@app.route('/admin/bots')
def admin_bots_page():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect('/admin')
    return safe_render('admin_bots.html')

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
            return jsonify({'success': False, 'msg': '❌ Aapka account ban hai!'})
        session.permanent = True
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
    return jsonify({'valid': False, 'msg': '❌ Invalid ya Expired Coupon Code!'})

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
    return jsonify({'success': False, 'msg': 'Valid .py file select karein.'})

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
                return jsonify({'success': False, 'msg': '❌ Launch karne ke liye 5 Coins chahiye!'})
            c.execute("UPDATE users SET coins = coins - 5 WHERE id = ?", (user_id,))

        c.execute("UPDATE bots SET is_running = 1 WHERE id = ?", (bot_id,))
        conn.commit()

        if os.path.exists(file_path):
            if bot_id in running_processes and running_processes[bot_id].poll() is None:
                running_processes[bot_id].terminate()
            proc = subprocess.Popen([sys.executable, file_path], cwd=user_folder)
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
        'vip_monthly': {'amt': 499.0, 'coins': 0, 'name': 'VIP Unlimited (1 Month)'}
    }

    if plan not in plans:
        return jsonify({'success': False, 'msg': 'Invalid Plan'})

    final_charge = paid_amt if paid_amt > 0 else plans[plan]['amt']

    scr_filename = "no_screenshot.png"
    photo_saved_path = None
    if file and file.filename != '':
        scr_filename = f"proof_{int(time.time())}_{secure_filename(file.filename)}"
        photo_saved_path = os.path.join(SCREENSHOT_DIR, scr_filename)
        file.save(photo_saved_path)

    p_info = plans[plan]
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO payments (user_id, username, item_type, coins_reward, amount, utr, screenshot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (user_id, session['username'], p_info['name'], p_info['coins'], final_charge, utr, scr_filename, datetime.now().strftime("%Y-%m-%d %H:%M")))
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
            f"🔔 <b>NEW PAYMENT REQUEST!</b> 💳\n\n"
            f"👤 <b>Client:</b> {session['username']} (ID: {user_id})\n"
            f"📦 <b>Plan:</b> {p_info['name']}\n"
            f"💵 <b>Amount Paid:</b> ₹{final_charge}\n"
            f"📌 <b>UTR:</b> <code>{utr}</code>\n"
            f"⚡ <i>Approve or Reject directly below:</i>"
        )
        if photo_saved_path and os.path.exists(photo_saved_path):
            with open(photo_saved_path, 'rb') as photo:
                tg_admin_bot.send_photo(TG_ADMIN_ID, photo, caption=caption_text, reply_markup=tg_markup)
        else:
            tg_admin_bot.send_message(TG_ADMIN_ID, caption_text, reply_markup=tg_markup)
    except Exception:
        pass

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
        return redirect('/admin')

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
