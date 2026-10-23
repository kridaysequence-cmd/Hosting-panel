# -*- coding: utf-8 -*-
import subprocess
import sys
import os
import importlib

# Auto-install missing modules
def auto_install(package):
    try:
        importlib.import_module(package)
    except ModuleNotFoundError:
        print(f"Installing missing package: {package} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"Installed: {package}")

for mod in ["telebot", "psutil", "requests", "flask"]:
    auto_install(mod)

import telebot
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import atexit
import requests
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'M SHAURYA'S HOSTING BOT"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")

TOKEN = os.environ['BOT_TOKEN']
OWNER_ID = int(os.environ.get('OWNER_ID', '8747368604'))
ADMIN_ID = int(os.environ.get('ADMIN_ID', str(OWNER_ID)))
YOUR_USERNAME = '@REDEYESIR'
UPDATE_CHANNEL = 'https://t.me/ALLTYPEBOTMAKING'

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

FREE_USER_LIMIT = 3
SUBSCRIBED_USER_LIMIT = 15
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot_locked = False
approval_required = False
active_users = set()
user_subscriptions = {}
admin_ids = set()
user_files = {}
pending_files = {}
bot_scripts = {}
DB_LOCK = threading.Lock()

bot = telebot.TeleBot(TOKEN, parse_mode='Markdown')

# ================= DATABASE SETUP =================
def init_db():
    os.makedirs(IROTECH_DIR, exist_ok=True)
    os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT, PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS file_approval (user_id INTEGER, file_name TEXT, file_type TEXT, status TEXT DEFAULT 'pending', uploaded_by INTEGER, upload_date TEXT, PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)

def load_data():
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except ValueError:
                logger.warning(f"Invalid expiry format for user {user_id}: {expiry}. Skipping.")
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))
        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())
        c.execute('SELECT user_id, file_name, file_type, status FROM file_approval')
        for uid, fname, ftype, status in c.fetchall():
            key = f"{uid}_{fname}"
            if uid not in user_files or not any(f[0] == fname for f in user_files.get(uid, [])):
                continue
            file_path = os.path.join(get_user_folder(uid), fname)
            pending_files[key] = {
                'user_id': uid, 'file_name': fname, 'file_type': ftype,
                'status': status, 'upload_msg_id': None, 'upload_chat_id': None,
                'file_path': file_path
            }
        c.execute('SELECT key, value FROM bot_settings WHERE key = ?', ('approval_required',))
        row = c.fetchone()
        if row:
            global approval_required
            approval_required = row[1].lower() == 'true'
        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(user_subscriptions)} subscriptions, {len(admin_ids)} admins, {len(pending_files)} pending files.")
    except Exception as e:
        logger.error(f"Error loading data: {e}", exc_info=True)

init_db()
load_data()

# ================= HELPER FUNCTIONS =================
def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_limit(user_id):
    if user_id == OWNER_ID:
        return OWNER_LIMIT
    if user_id in admin_ids:
        return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try: script_info['log_file'].close()
                    except: pass
                if script_key in bot_scripts: del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try: script_info['log_file'].close()
                except: pass
            if script_key in bot_scripts: del bot_scripts[script_key]
            return False
        except Exception:
            return False
    return False

def kill_process_tree(process_info):
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A')
    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
            except Exception as log_e:
                logger.error(f"Error closing log file during kill for {script_key}: {log_e}")
        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
        if pid:
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    try: child.terminate()
                    except psutil.NoSuchProcess: pass
                    except Exception: 
                        try: child.kill()
                        except: pass
                gone, alive = psutil.wait_procs(children, timeout=1)
                for p in alive:
                    try: p.kill()
                    except: pass
                try: parent.terminate()
                except Exception: 
                    try: parent.kill()
                    except: pass
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                logger.error(f"Error killing process tree: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error killing tree: {e}", exc_info=True)

# ================= TELEGRAM MODULES =================
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'telethon.sync': 'telethon',
    'telepot': 'telepot',
    'tgcrypto': 'tgcrypto',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'asyncio': None, 'json': None, 'datetime': None, 'os': None, 'sys': None, 
    're': None, 'time': None, 'math': None, 'random': None, 'logging': None,
    'threading': None, 'subprocess': None, 'zipfile': None, 'tempfile': None,
    'shutil': None, 'sqlite3': None, 'psutil': 'psutil', 'atexit': None
}

# ================= DATABASE OPERATIONS =================
def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)', (user_id, file_name, file_type))
            c.execute('INSERT OR REPLACE INTO file_approval (user_id, file_name, file_type, status, uploaded_by, upload_date) VALUES (?, ?, ?, ?, ?, ?)',
                      (user_id, file_name, file_type, 'pending', user_id, datetime.now().isoformat()))
            conn.commit()
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
            key = f"{user_id}_{file_name}"
            pending_files[key] = {
                'user_id': user_id, 'file_name': file_name, 'file_type': file_type,
                'status': 'pending', 'upload_msg_id': None, 'upload_chat_id': None,
                'file_path': os.path.join(get_user_folder(user_id), file_name)
            }
        except sqlite3.Error as e:
            logger.error(f"SQLite error saving file: {e}")
        finally:
            conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            c.execute('DELETE FROM file_approval WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
            key = f"{user_id}_{file_name}"
            if key in pending_files:
                del pending_files[key]
        except sqlite3.Error as e:
            logger.error(f"SQLite error removing file: {e}")
        finally:
            conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"SQLite error adding active user: {e}")
        finally:
            conn.close()

def save_subscription(user_id, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (user_id, expiry_str))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry}
        except sqlite3.Error as e:
            logger.error(f"SQLite error saving subscription: {e}")
        finally:
            conn.close()

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions:
                del user_subscriptions[user_id]
        except sqlite3.Error as e:
            logger.error(f"SQLite error removing subscription: {e}")
        finally:
            conn.close()

def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id)
        except sqlite3.Error as e:
            logger.error(f"SQLite error adding admin: {e}")
        finally:
            conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        removed = False
        try:
            c.execute('SELECT 1 FROM admins WHERE user_id = ?', (admin_id,))
            if c.fetchone():
                c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
                conn.commit()
                removed = c.rowcount > 0
                if removed:
                    admin_ids.discard(admin_id)
            return removed
        except sqlite3.Error as e:
            logger.error(f"SQLite error removing admin: {e}")
            return False
        finally:
            conn.close()

# ================= MENUS =================
def _styled_inline(text, callback_data=None, url=None, style=None):
    btn = types.InlineKeyboardButton(text, callback_data=callback_data, url=url)
    if style:
        btn.style = style
    return btn

def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if user_id in admin_ids:
        markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
        markup.add(
            types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
            types.InlineKeyboardButton('📁 Check Files', callback_data='check_files')
        )
        markup.add(
            types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats')
        )
        markup.add(
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('📢 Broadcast', callback_data='broadcast')
        )
        markup.add(
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot', callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('▶️ Run All User Scripts', callback_data='run_all_scripts')
        )
        markup.add(types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'))
    else:
        markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
        markup.add(
            types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
            types.InlineKeyboardButton('📁 Check Files', callback_data='check_files')
        )
        markup.add(types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'))
        markup.add(types.InlineKeyboardButton('📊 Statistics', callback_data='stats'))
    markup.add(types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    return markup

def create_control_buttons(script_owner_id, file_name, is_running):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.add(
            _styled_inline("⏹ Stop", callback_data=f'stop_{script_owner_id}_{file_name}', style='danger'),
            _styled_inline("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}', style='primary')
        )
    else:
        markup.add(
            _styled_inline("▶️ Start", callback_data=f'start_{script_owner_id}_{file_name}', style='success'),
            _styled_inline("🗑 Delete", callback_data=f'delete_{script_owner_id}_{file_name}', style='danger')
        )
    markup.add(_styled_inline("📜 View Logs", callback_data=f'logs_{script_owner_id}_{file_name}', style='primary'))
    markup.add(_styled_inline("📥 Get This File", callback_data=f'getfile_{script_owner_id}_{file_name}', style='primary'))
    markup.add(_styled_inline("🔙 Back to Files", callback_data='check_files', style='primary'))
    return markup

def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('👤 Add Admin', callback_data='add_admin'),
        types.InlineKeyboardButton('❌ Remove Admin', callback_data='remove_admin')
    )
    markup.add(
        types.InlineKeyboardButton('📋 List Admins', callback_data='list_admins'),
        types.InlineKeyboardButton('🔐 Toggle Approval', callback_data='toggle_approval')
    )
    markup.add(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('➕ Add Subscription', callback_data='add_subscription'),
        types.InlineKeyboardButton('➖ Remove Subscription', callback_data='remove_subscription')
    )
    markup.add(types.InlineKeyboardButton('🔍 Check Subscription', callback_data='check_subscription'))
    markup.add(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

# ================= AUTO INSTALL & RUN SCRIPT =================
def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None:
        return False
    try:
        bot.reply_to(message, f"📦 Module '{module_name}' not found. Installing '{package_name}'...")
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Package '{package_name}' installed.")
            return True
        else:
            error_msg = f"❌ Failed to install '{package_name}'.\nLog:\n{result.stderr or result.stdout}"
            bot.reply_to(message, error_msg[:4000])
            return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing '{package_name}': {str(e)}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"📦 Node package '{module_name}' not found. Installing locally...")
        command = ['npm', 'install', module_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Node package '{module_name}' installed locally.")
            return True
        else:
            error_msg = f"❌ Failed to install Node package '{module_name}'.\nLog:\n{result.stderr or result.stdout}"
            bot.reply_to(message, error_msg[:4000])
            return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ Error: 'npm' not found. Ensure Node.js/npm are installed.")
        return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing Node package: {str(e)}")
        return False

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"Failed to run '{file_name}' after {max_attempts} attempts.")
        return
    script_key = f"{script_owner_id}_{file_name}"
    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Error: Script '{file_name}' not found!")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return
        if attempt == 1:
            check_command = [sys.executable, script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("\\")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"❌ Install failed. Cannot run '{file_name}'.")
                            return
                    else:
                        bot.reply_to(message_obj_for_reply, f"❌ Error in pre-check:\n{stderr[:500]}")
                        return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, f"❌ Python interpreter not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"❌ Unexpected pre-check error: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
        
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file: {e}")
            return
        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                [sys.executable, script_path], cwd=user_folder,
                stdout=log_file, stderr=log_file, stdin=subprocess.PIPE,
                startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id, 'start_time': datetime.now(),
                'user_folder': user_folder, 'type': 'py', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ Python script '{file_name}' started! (PID: {process.pid})")
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            bot.reply_to(message_obj_for_reply, f"❌ Error starting Python script: {str(e)}")
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        logger.error(f"Unexpected error in run_script: {e}", exc_info=True)

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"Failed to run '{file_name}' after {max_attempts} attempts.")
        return
    script_key = f"{script_owner_id}_{file_name}"
    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Error: Script '{file_name}' not found!")
            return
        if attempt == 1:
            check_command = ['node', script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                time.sleep(2)
                                threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                return
                            else:
                                bot.reply_to(message_obj_for_reply, f"❌ NPM Install failed.")
                                return
                    else:
                        bot.reply_to(message_obj_for_reply, f"❌ Error in JS pre-check:\n{stderr[:500]}")
                        return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, "❌ Error: 'node' not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"❌ Unexpected JS pre-check error: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
        
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file: {e}")
            return
        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                ['node', script_path], cwd=user_folder,
                stdout=log_file, stderr=log_file, stdin=subprocess.PIPE,
                startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id, 'start_time': datetime.now(),
                'user_folder': user_folder, 'type': 'js', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ JS script '{file_name}' started! (PID: {process.pid})")
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            bot.reply_to(message_obj_for_reply, f"❌ Error starting JS script: {str(e)}")
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        logger.error(f"Unexpected error in run_js_script: {e}", exc_info=True)

# ================= FILE HANDLERS =================
def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        if approval_required:
            bot.reply_to(message, f"File uploaded: '{file_name}'. Waiting for admin approval...")
            approval_markup = types.InlineKeyboardMarkup(row_width=2)
            approval_markup.add(
                types.InlineKeyboardButton("Approve", callback_data=f'approve_{script_owner_id}_{file_name}'),
                types.InlineKeyboardButton("❌ Reject", callback_data=f'reject_{script_owner_id}_{file_name}')
            )
            bot.send_message(OWNER_ID, f"New file by {script_owner_id} ({message.from_user.first_name})\nFile: {file_name} (js)", reply_markup=approval_markup)
        else:
            bot.reply_to(message, f"✅ File uploaded: '{file_name}'. Auto-starting...")
            key = f"{script_owner_id}_{file_name}"
            if key in pending_files:
                pending_files[key]['status'] = 'approved'
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"Error processing JS file: {e}", exc_info=True)

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        if approval_required:
            bot.reply_to(message, f"File uploaded: '{file_name}'. Waiting for admin approval...")
            approval_markup = types.InlineKeyboardMarkup(row_width=2)
            approval_markup.add(
                types.InlineKeyboardButton("Approve", callback_data=f'approve_{script_owner_id}_{file_name}'),
                types.InlineKeyboardButton("❌ Reject", callback_data=f'reject_{script_owner_id}_{file_name}')
            )
            bot.send_message(OWNER_ID, f"New file by {script_owner_id} ({message.from_user.first_name})\nFile: {file_name} (py)", reply_markup=approval_markup)
        else:
            bot.reply_to(message, f"✅ File uploaded: '{file_name}'. Auto-starting...")
            key = f"{script_owner_id}_{file_name}"
            if key in pending_files:
                pending_files[key]['status'] = 'approved'
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"Error processing PY file: {e}", exc_info=True)

# ================= LOGIC FUNCTIONS =================
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    add_active_user(user_id)
    bot.send_message(chat_id, f"👋 Welcome {user_name}!\n\nI'm a bot hosting service. Use the buttons below.", reply_markup=create_main_menu_inline(user_id))

def _logic_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📁 Your files:\n\n(No files uploaded yet)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
    bot.reply_to(message, "📁 Your files:\nClick to manage.", reply_markup=markup)

def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "⏳ Testing speed...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "👤 Free User"
        bot.edit_message_text(f"⚡ Bot Speed: {response_time} ms\nStatus: {status}\nLevel: {user_level}", chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Error in speed: {e}")

def _logic_statistics(message):
    user_id = message.from_user.id
    total_users = len(active_users)
    total_files_records = sum(len(files) for files in user_files.values())
    running_bots_count = 0
    for script_key_iter, script_info_iter in list(bot_scripts.items()):
        s_owner_id = script_key_iter.split('_', 1)[0]
        if is_bot_running(int(s_owner_id), script_info_iter['file_name']):
            running_bots_count += 1
    stats_msg = f"📊 Bot Statistics:\n\n👥 Total Users: {total_users}\n📁 Total Files: {total_files_records}\n🟢 Running Bots: {running_bots_count}"
    bot.reply_to(message, stats_msg)

def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin permissions required.")
        return
    bot.reply_to(message, "👑 Admin Panel:", reply_markup=create_admin_panel())

def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(message_or_call.message.chat.id, text, **kwargs)
    else:
        return
    if admin_user_id not in admin_ids:
        reply_func("Admin permissions required.")
        return
    started_count = 0
    for uid, files in user_files.items():
        for fname, ftype in files:
            if not is_bot_running(uid, fname):
                user_folder = get_user_folder(uid)
                file_path = os.path.join(user_folder, fname)
                if os.path.exists(file_path):
                    dummy_msg = type('DummyMsg', (), {'chat': type('DummyChat', (), {'id': uid}), 'from_user': type('DummyUser', (), {'id': uid, 'first_name': 'Admin'})})()
                    if ftype == 'py':
                        threading.Thread(target=run_script, args=(file_path, uid, user_folder, fname, dummy_msg)).start()
                    elif ftype == 'js':
                        threading.Thread(target=run_js_script, args=(file_path, uid, user_folder, fname, dummy_msg)).start()
                    started_count += 1
    reply_func(f"✅ Started {started_count} scripts.")

# ================= COMMAND HANDLERS =================
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message):
    _logic_send_welcome(message)

@bot.message_handler(commands=['status'])
def command_show_status(message):
    _logic_statistics(message)

@bot.message_handler(commands=['adminpanel'])
def command_admin_panel(message):
    _logic_admin_panel(message)

@bot.message_handler(commands=['runningallcode'])
def command_run_all_code(message):
    _logic_run_all_scripts(message)

@bot.message_handler(commands=['ping'])
def ping(message):
    start_ping_time = time.time()
    msg = bot.reply_to(message, "Pong!")
    latency = round((time.time() - start_ping_time) * 1000, 2)
    bot.edit_message_text(f"Pong! Latency: {latency} ms", message.chat.id, msg.message_id)

# ================= DOCUMENT HANDLER =================
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "Bot locked, cannot accept files.")
        return
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"File limit ({current_files}/{limit_str}) reached. Delete files first.")
        return
    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "No file name.")
        return
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "Unsupported type! Only .py, .js, .zip allowed.")
        return
    max_file_size = 20 * 1024 * 1024
    if doc.file_size > max_file_size:
        bot.reply_to(message, f"File too large (Max: {max_file_size // 1024 // 1024} MB).")
        return
    try:
        download_wait_msg = bot.reply_to(message, f"Downloading {file_name}...")
        file_info_tg_doc = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        user_folder = get_user_folder(user_id)
        file_path = os.path.join(user_folder, file_name)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file_content)
        bot.edit_message_text(f"✅ Downloaded {file_name}", chat_id, download_wait_msg.message_id)
        
        if file_ext == '.py':
            handle_py_file(file_path, user_id, user_folder, file_name, message)
        elif file_ext == '.js':
            handle_js_file(file_path, user_id, user_folder, file_name, message)
        elif file_ext == '.zip':
            temp_dir = tempfile.mkdtemp()
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                py_files = [f for f in os.listdir(temp_dir) if f.endswith('.py')]
                js_files = [f for f in os.listdir(temp_dir) if f.endswith('.js')]
                main_script_name = None
                file_type = None
                preferred_py = ['main.py', 'bot.py', 'app.py']
                preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
                for p in preferred_py:
                    if p in py_files:
                        main_script_name = p; file_type = 'py'; break
                if not main_script_name:
                    for p in preferred_js:
                        if p in js_files:
                            main_script_name = p; file_type = 'js'; break
                if not main_script_name:
                    if py_files: main_script_name = py_files[0]; file_type = 'py'
                    elif js_files: main_script_name = js_files[0]; file_type = 'js'
                if not main_script_name:
                    bot.reply_to(message, "❌ No .py or .js script found in archive!")
                    return
                for item_name in os.listdir(temp_dir):
                    src_path = os.path.join(temp_dir, item_name)
                    dest_path = os.path.join(user_folder, item_name)
                    if os.path.isdir(dest_path): shutil.rmtree(dest_path)
                    elif os.path.exists(dest_path): os.remove(dest_path)
                    shutil.move(src_path, dest_path)
                save_user_file(user_id, main_script_name, file_type)
                main_script_path = os.path.join(user_folder, main_script_name)
                if approval_required:
                    bot.reply_to(message, f"File uploaded: '{main_script_name}'. Waiting for admin approval...")
                else:
                    bot.reply_to(message, f"✅ File uploaded: '{main_script_name}'. Auto-starting...")
                    if file_type == 'py':
                        threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
                    else:
                        threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
            except zipfile.BadZipFile as e:
                bot.reply_to(message, f"❌ Invalid/corrupted ZIP. {e}")
            finally:
                if temp_dir and os.path.exists(temp_dir):
                    try: shutil.rmtree(temp_dir)
                    except: pass
    except Exception as e:
        logger.error(f"General error handling file: {e}", exc_info=True)
        bot.reply_to(message, f"Unexpected error: {str(e)}")

# ================= CALLBACK HANDLERS =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats']:
        bot.answer_callback_query(call.id, "Bot locked by admin.", show_alert=True)
        return
    try:
        if data == 'upload':
            upload_callback(call)
        elif data == 'check_files':
            check_files_callback(call)
        elif data.startswith('file_'):
            file_control_callback(call)
        elif data.startswith('start_'):
            start_bot_callback(call)
        elif data.startswith('stop_'):
            stop_bot_callback(call)
        elif data.startswith('restart_'):
            restart_bot_callback(call)
        elif data.startswith('delete_'):
            delete_bot_callback(call)
        elif data.startswith('logs_'):
            logs_bot_callback(call)
        elif data.startswith('approve_'):
            approve_file_callback(call)
        elif data.startswith('reject_'):
            reject_file_callback(call)
        elif data.startswith('getfile_'):
            get_file_callback(call)
        elif data == 'speed':
            speed_callback(call)
        elif data == 'back_to_main':
            back_to_main_callback(call)
        elif data.startswith('confirm_broadcast_'):
            handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast':
            handle_cancel_broadcast(call)
        elif data == 'subscription':
            admin_required_callback(call, subscription_management_callback)
        elif data == 'stats':
            stats_callback(call)
        elif data == 'lock_bot':
            admin_required_callback(call, lock_bot_callback)
        elif data == 'unlock_bot':
            admin_required_callback(call, unlock_bot_callback)
        elif data == 'run_all_scripts':
            admin_required_callback(call, run_all_scripts_callback)
        elif data == 'broadcast':
            admin_required_callback(call, broadcast_init_callback)
        elif data == 'admin_panel':
            admin_required_callback(call, admin_panel_callback)
        elif data == 'toggle_approval':
            admin_required_callback(call, toggle_approval_callback)
        elif data == 'add_admin':
            owner_required_callback(call, add_admin_init_callback)
        elif data == 'remove_admin':
            owner_required_callback(call, remove_admin_init_callback)
        elif data == 'list_admins':
            admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription':
            admin_required_callback(call, add_subscription_init_callback)
        elif data == 'remove_subscription':
            admin_required_callback(call, remove_subscription_init_callback)
        elif data == 'check_subscription':
            admin_required_callback(call, check_subscription_init_callback)
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
    except Exception as e:
        logger.error(f"Error handling callback '{data}': {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "Error processing request.", show_alert=True)
        except: pass

def admin_required_callback(call, func_to_run):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin permissions required.", show_alert=True)
        return
    func_to_run(call)

def owner_required_callback(call, func_to_run):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "Owner permissions required.", show_alert=True)
        return
    func_to_run(call)

def upload_callback(call):
    user_id = call.from_user.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"File limit ({current_files}/{limit_str}) reached.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Send your Python (.py), JS (.js), or ZIP (.zip) file.")

def check_files_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if user_id in admin_ids:
        all_files = []
        for uid, files_list in user_files.items():
            for file_name, file_type in files_list:
                key = f"{uid}_{file_name}"
                approval_status = 'pending'
                if key in pending_files:
                    approval_status = pending_files[key].get('status', 'pending')
                all_files.append((uid, file_name, file_type, approval_status))
        if not all_files:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
            try: bot.edit_message_text("📁 All Files (Admin View):\n\n(No files uploaded)", chat_id, call.message.message_id, reply_markup=markup)
            except: pass
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for uid, file_name, file_type, approval_status in all_files:
            is_running = is_bot_running(uid, file_name)
            status_icon = "🟢 Running" if is_running else "🔴 Stopped"
            btn_text = f"[{uid}] {file_name} ({file_type}) - {status_icon} - {approval_status}"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{uid}_{file_name}'))
        markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
        try: bot.edit_message_text("📁 All Files (Admin View):", chat_id, call.message.message_id, reply_markup=markup)
        except: pass
    else:
        user_files_list = user_files.get(user_id, [])
        if not user_files_list:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
            try: bot.edit_message_text("📁 Your files:\n\n(No files uploaded)", chat_id, call.message.message_id, reply_markup=markup)
            except: pass
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for file_name, file_type in sorted(user_files_list):
            is_running = is_bot_running(user_id, file_name)
            status_icon = "🟢 Running" if is_running else "🔴 Stopped"
            btn_text = f"{file_name} ({file_type}) - {status_icon}"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
        markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
        try: bot.edit_message_text("📁 Your files:", chat_id, call.message.message_id, reply_markup=markup)
        except: pass

def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "You can only manage your own files.", show_alert=True)
            return
        is_running = is_bot_running(script_owner_id, file_name)
        file_type = next((f[1] for f in user_files.get(script_owner_id, []) if f[0] == file_name), '?')
        bot.edit_message_text(
            f"Controls for:\n{file_name} ({file_type}) of User {script_owner_id}\nStatus: {'🟢 Running' if is_running else '🔴 Stopped'}",
            call.message.chat.id, call.message.message_id,
            reply_markup=create_control_buttons(script_owner_id, file_name, is_running)
        )
    except Exception as e:
        logger.error(f"Error in file_control: {e}")

def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        file_info = next((f for f in user_files.get(script_owner_id, []) if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); return
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "File missing! Re-upload.", show_alert=True); return
        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, "Already running.", show_alert=True); return
        bot.answer_callback_query(call.id, f"Starting {file_name}...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        time.sleep(1.5)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id, file_name, is_bot_running(script_owner_id, file_name)))
    except Exception as e:
        logger.error(f"Error in start_bot: {e}")

def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        script_key = f"{script_owner_id}_{file_name}"
        if not is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, "Already stopped.", show_alert=True); return
        bot.answer_callback_query(call.id, f"Stopping {file_name}...")
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id, file_name, False))
    except Exception as e:
        logger.error(f"Error in stop_bot: {e}")

def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        file_info = next((f for f in user_files.get(script_owner_id, []) if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); return
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
                if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(0.5)
        bot.answer_callback_query(call.id, f"Restarting {file_name}...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        time.sleep(1.5)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id, file_name, is_bot_running(script_owner_id, file_name)))
    except Exception as e:
        logger.error(f"Error in restart_bot: {e}")

def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
                if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(0.5)
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass
        if os.path.exists(log_path):
            try: os.remove(log_path)
            except: pass
        remove_user_file_db(script_owner_id, file_name)
        bot.answer_callback_query(call.id, f"Deleted {file_name}.")
        bot.edit_message_text(f"✅ Record '{file_name}' deleted!", call.message.chat.id, call.message.message_id)
    except Exception as e:
        logger.error(f"Error in delete_bot: {e}")

def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, f"No logs for '{file_name}'.", show_alert=True); return
        bot.answer_callback_query(call.id)
        file_size = os.path.getsize(log_path)
        max_log_kb = 100
        if file_size == 0:
            log_content = "(Log empty)"
        elif file_size > max_log_kb * 1024:
            with open(log_path, 'rb') as f:
                f.seek(-max_log_kb * 1024, os.SEEK_END)
                log_bytes = f.read()
                log_content = log_bytes.decode('utf-8', errors='ignore')
                log_content = f"(Last {max_log_kb}KB)\n" + log_content
        else:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()
        if len(log_content) > 4000:
            log_content = log_content[-4000:]
        bot.send_message(call.message.chat.id, f"📜 Logs for '{file_name}':\n```\n{log_content}\n```")
    except Exception as e:
        logger.error(f"Error in logs_bot: {e}")

def approve_file_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
        key = f"{script_owner_id}_{file_name}"
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('UPDATE file_approval SET status = ? WHERE user_id = ? AND file_name = ?', ('approved', script_owner_id, file_name))
            conn.commit(); conn.close()
        if key in pending_files:
            pending_files[key]['status'] = 'approved'
        bot.answer_callback_query(call.id, f"File '{file_name}' approved.")
        bot.edit_message_text(f"✅ File '{file_name}' (User {script_owner_id}) APPROVED.", call.message.chat.id, call.message.message_id)
        try: bot.send_message(script_owner_id, f"Your file '{file_name}' has been approved!")
        except: pass
        file_info = next((f for f in user_files.get(script_owner_id, []) if f[0] == file_name), None)
        if file_info:
            file_type = file_info[1]
            user_folder = get_user_folder(script_owner_id)
            file_path = os.path.join(user_folder, file_name)
            if os.path.exists(file_path) and file_type in ('py', 'js'):
                if not is_bot_running(script_owner_id, file_name):
                    dummy_msg = type('DummyMsg', (), {'chat': type('DummyChat', (), {'id': script_owner_id}), 'from_user': type('DummyUser', (), {'id': script_owner_id, 'first_name': 'Admin'})})()
                    if file_type == 'py':
                        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, dummy_msg)).start()
                    else:
                        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, dummy_msg)).start()
    except Exception as e:
        logger.error(f"Error in approve: {e}")

def reject_file_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
        key = f"{script_owner_id}_{file_name}"
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('UPDATE file_approval SET status = ? WHERE user_id = ? AND file_name = ?', ('rejected', script_owner_id, file_name))
            conn.commit(); conn.close()
        if key in pending_files:
            pending_files[key]['status'] = 'rejected'
        bot.answer_callback_query(call.id, f"❌ File '{file_name}' rejected.")
        bot.edit_message_text(f"❌ File '{file_name}' (User {script_owner_id}) REJECTED.", call.message.chat.id, call.message.message_id)
        try: bot.send_message(script_owner_id, f"Your file '{file_name}' has been rejected.")
        except: pass
    except Exception as e:
        logger.error(f"Error in reject: {e}")

def get_file_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); return
        bot.answer_callback_query(call.id)
        with open(file_path, 'rb') as f:
            bot.send_document(call.message.chat.id, f)
    except Exception as e:
        logger.error(f"Error in get_file: {e}")

def speed_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    start_cb_ping_time = time.time()
    try:
        bot.edit_message_text("⏳ Testing speed...", chat_id, call.message.message_id)
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_cb_ping_time) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "👤 Free User"
        bot.edit_message_text(f"⚡ Speed: {response_time} ms\nStatus: {status}\nLevel: {user_level}", chat_id, call.message.message_id)
    except Exception as e:
        logger.error(f"Error in speed_callback: {e}")

def back_to_main_callback(call):
    try:
        bot.edit_message_text("Main Menu:", call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e:
        logger.error(f"Error in back_to_main: {e}")

def stats_callback(call):
    bot.answer_callback_query(call.id)
    _logic_statistics(call.message)

def lock_bot_callback(call):
    global bot_locked
    bot_locked = True
    bot.answer_callback_query(call.id, "Bot locked.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except: pass

def unlock_bot_callback(call):
    global bot_locked
    bot_locked = False
    bot.answer_callback_query(call.id, "Bot unlocked.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except: pass

def run_all_scripts_callback(call):
    _logic_run_all_scripts(call)

def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "Not authorized."); return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Broadcast cancelled."); return
    broadcast_text = message.text
    if not broadcast_text:
        bot.reply_to(message, "Cannot broadcast empty message.")
        return
    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Confirm & Send", callback_data=f'confirm_broadcast_{int(time.time())}'),
        types.InlineKeyboardButton("❌ Cancel", callback_data='cancel_broadcast')
    )
    bot.send_message(message.chat.id, f"Broadcast to {target_count} users. Confirm?", reply_markup=markup)

def handle_confirm_broadcast(call):
    try:
        bot.answer_callback_query(call.id, "Starting broadcast...")
        bot.edit_message_text(f"Broadcasting to {len(active_users)} users...", call.message.chat.id, call.message.message_id, reply_markup=None)
        threading.Thread(target=execute_broadcast, args=(call.message.reply_to_message.text if call.message.reply_to_message else "Broadcast", call.message.chat.id)).start()
    except Exception as e:
        logger.error(f"Error in confirm broadcast: {e}")

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Broadcast cancelled.")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

def execute_broadcast(broadcast_text, admin_chat_id):
    sent_count = 0; failed_count = 0
    for user_id_bc in list(active_users):
        try:
            bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            sent_count += 1
        except Exception:
            failed_count += 1
        time.sleep(0.05)
    try: bot.send_message(admin_chat_id, f"Broadcast complete.\nSent: {sent_count}\nFailed: {failed_count}")
    except: pass

def admin_panel_callback(call):
    bot.answer_callback_query(call.id)
    try: bot.edit_message_text("👑 Admin Panel:", call.message.chat.id, call.message.message_id, reply_markup=create_admin_panel())
    except: pass

def toggle_approval_callback(call):
    global approval_required
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
    approval_required = not approval_required
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)', ('approval_required', str(approval_required)))
            conn.commit(); conn.close()
    except Exception as e:
        logger.error(f"Error saving approval setting: {e}")
    status = "ON" if approval_required else "OFF"
    bot.answer_callback_query(call.id, f"File approval: {status}", show_alert=True)
    try: bot.edit_message_text("👑 Admin Panel:", call.message.chat.id, call.message.message_id, reply_markup=create_admin_panel())
    except: pass

def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID to promote to Admin.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_admin_id)

def process_add_admin_id(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "Owner only."); return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled."); return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id <= 0: raise ValueError("ID must be positive")
        if new_admin_id == OWNER_ID:
            bot.reply_to(message, "Owner is already Owner."); return
        if new_admin_id in admin_ids:
            bot.reply_to(message, f"User {new_admin_id} already Admin."); return
        add_admin_db(new_admin_id)
        bot.reply_to(message, f"User {new_admin_id} promoted to Admin.")
        try: bot.send_message(new_admin_id, "Congrats! You are now an Admin.")
        except: pass
    except ValueError:
        bot.reply_to(message, "Invalid ID.")

def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter Admin ID to remove.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_admin_id)

def process_remove_admin_id(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "Owner only."); return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled."); return
    try:
        admin_id_remove = int(message.text.strip())
        if admin_id_remove <= 0: raise ValueError("ID must be positive")
        if admin_id_remove == OWNER_ID:
            bot.reply_to(message, "Cannot remove Owner."); return
        if admin_id_remove not in admin_ids:
            bot.reply_to(message, f"User {admin_id_remove} not Admin."); return
        if remove_admin_db(admin_id_remove):
            bot.reply_to(message, f"Admin {admin_id_remove} removed.")
            try: bot.send_message(admin_id_remove, "You are no longer an Admin.")
            except: pass
        else:
            bot.reply_to(message, "Failed to remove admin.")
    except ValueError:
        bot.reply_to(message, "Invalid ID.")

def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    admins_list = "\n".join([f"`{a}`" for a in admin_ids])
    bot.edit_message_text(f"👑 Admins:\n{admins_list}", call.message.chat.id, call.message.message_id)

def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    try: bot.edit_message_text("💳 Subscription Management\nSelect action:", call.message.chat.id, call.message.message_id, reply_markup=create_subscription_menu())
    except: pass

def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter: USER_ID DAYS\nExample: 123456789 30\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_subscription)

def process_add_subscription(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only."); return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled."); return
    try:
        parts = message.text.split()
        if len(parts) != 2: raise ValueError("Incorrect format")
        sub_user_id = int(parts[0]); days = int(parts[1])
        if sub_user_id <= 0 or days <= 0: raise ValueError("Positive values only")
        current_expiry = user_subscriptions.get(sub_user_id, {}).get('expiry')
        start_date = datetime.now()
        if current_expiry and current_expiry > start_date:
            start_date = current_expiry
        new_expiry = start_date + timedelta(days=days)
        save_subscription(sub_user_id, new_expiry)
        bot.reply_to(message, f"Sub for {sub_user_id} by {days} days.\nNew expiry: {new_expiry:%Y-%m-%d}")
        try: bot.send_message(sub_user_id, f"Sub activated/extended by {days} days!")
        except: pass
    except ValueError:
        bot.reply_to(message, "Invalid format. Send: USER_ID DAYS")

def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID to remove sub from.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_subscription)

def process_remove_subscription(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only."); return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled."); return
    try:
        sub_user_id_remove = int(message.text.strip())
        if sub_user_id_remove <= 0: raise ValueError("ID must be positive")
        remove_subscription_db(sub_user_id_remove)
        bot.reply_to(message, f"Sub for {sub_user_id_remove} removed.")
        try: bot.send_message(sub_user_id_remove, "Your subscription removed by admin.")
        except: pass
    except ValueError:
        bot.reply_to(message, "Invalid ID.")

def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID to check.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_check_subscription)

def process_check_subscription(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin only."); return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled."); return
    try:
        sub_user_id_check = int(message.text.strip())
        if sub_user_id_check <= 0: raise ValueError("ID must be positive")
        if sub_user_id_check in user_subscriptions:
            expiry_dt = user_subscriptions[sub_user_id_check].get('expiry')
            if expiry_dt:
                days_left = (expiry_dt - datetime.now()).days
                if days_left >= 0:
                    bot.reply_to(message, f"User {sub_user_id_check} active sub.\nExpires: {expiry_dt:%Y-%m-%d %H:%M:%S} ({days_left} days left).")
                else:
                    bot.reply_to(message, f"User {sub_user_id_check} expired.")
                    remove_subscription_db(sub_user_id_check)
            else:
                bot.reply_to(message, f"User {sub_user_id_check} in list but expiry missing.")
        else:
            bot.reply_to(message, f"User {sub_user_id_check} no active sub record.")
    except ValueError:
        bot.reply_to(message, "Invalid ID.")

# ================= CLEANUP & MAIN =================
def cleanup():
    logger.warning("Shutdown. Cleaning up processes...")
    script_keys_to_stop = list(bot_scripts.keys())
    if not script_keys_to_stop:
        return
    for key in script_keys_to_stop:
        if key in bot_scripts:
            kill_process_tree(bot_scripts[key])

atexit.register(cleanup)

if __name__ == '__main__':
    logger.info("=" * 40 + "\nBot Starting Up...\n" + "=" * 40)
    keep_alive()
    logger.info("Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("Polling ReadTimeout. Restarting in 5s..."); time.sleep(5)
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"Polling ConnectionError: {ce}. Retrying in 15s..."); time.sleep(15)
        except Exception as e:
            logger.critical(f"Unrecoverable polling error: {e}", exc_info=True)
            logger.info("Restarting polling in 30s..."); time.sleep(30)
        finally:
            time.sleep(1)
