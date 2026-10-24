import telebot
import time
import os
import subprocess
import psutil
import re
import json
import sys
import zipfile
from telebot import types

# --- Configuration ---
# Render pe ye values "Environment" tab me set karo (code me mat likho)
API_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@autolikegc")

if not API_TOKEN:
    raise SystemExit("BOT_TOKEN environment variable set nahi hai! Render dashboard -> Environment me add karo.")
if not ADMIN_ID:
    print("⚠️  WARNING: ADMIN_ID set nahi hai ya 0 hai — admin panel kisi ko bhi nahi dikhega.")

bot = telebot.TeleBot(API_TOKEN)

DB_FILE = "users_data.json"
SETTINGS_FILE = "bot_settings.json"
DEPLOY_DIR = "deployed_bots"

if not os.path.exists(DEPLOY_DIR):
    os.makedirs(DEPLOY_DIR)

# --- Persistence Functions ---
def save_db():
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(users_db, f, ensure_ascii=False, indent=4)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_settings():
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

def load_settings():
    default = {
        "points_per_referral": 2, 
        "hosting_cost": 4,        
        "maintenance": False,
        "welcome_video": None 
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return default
    return default

users_db = load_db()
settings = load_settings()
running_processes = {} 

# --- Execution Logic & Error Catching ---
def run_user_file(f_path, user_id, f_name):
    ext = os.path.splitext(f_name)[1].lower()
    cmd = [sys.executable, f_path] if ext == '.py' else ['node', f_path]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        bot.send_message(user_id, "❌ Server par Node.js installed nahi hai, isliye .js files nahi chal sakti. Sirf .py upload karo, ya Render service me Node.js add karwao.")
        return False
    try:
        running_processes[f_path] = process
        
        time.sleep(3)
        if process.poll() is not None:
            _, stderr = process.communicate()
            error_msg = stderr if stderr else "Exited with unknown error."
            bot.send_message(user_id, f"⚠️ **Your Bot has a Runtime Error!**\n\nFile: `{f_name}`\nError Log:\n`{error_msg[:3000]}`")
            if f_path in running_processes: del running_processes[f_path]
            return False
        return True
    except Exception as e:
        bot.send_message(user_id, f"❌ Server Error: {e}")
        return False

# --- UI Designs ---
def get_welcome_text(message):
    user = message.from_user
    points = users_db.get(str(user.id), {}).get('points', 0)
    status = 'ONLINE ✅' if not settings.get('maintenance') else 'MAINTENANCE ⚠️'
    return (
        "┏━━━━━━━━━━━━━━━━━┓\n"
        "┃ ⚡ ʀ ʙᴏᴛ ᴘʀᴇᴍɪᴜᴍ ʜᴏsᴛɪɴɢ ʙᴏᴛ  ⚡\n"
        "┃    ᴘʀᴇᴍɪᴜᴍ 24/7 ᴄʟᴏᴜᴅ ꜱᴇʀᴠɪᴄᴇ \n"
        "┗━━━━━━━━━━━━━━━━━┛\n"
        f"┃ 👋 ᴡᴇʟᴄᴏᴍᴇ: {user.first_name.upper()} 𓇻\n"
        "┃\n"
        "┃ 📤 ᴅᴇᴘʟᴏʏ ᴘʏᴛʜᴏɴ & ᴊꜱ & ᴢɪᴘ\n"
        "┃ 🚀 ᴀᴜᴛᴏ ᴅᴇᴘᴇɴᴅᴇɴᴄɪᴇs\n"
        "┃ 🔍 ʀᴇᴀʟ-ᴛɪᴍᴇ ʟᴏɢs\n"
        "┃ ⚡ 24/7 ᴜᴘᴛɪᴍᴇ ᴀᴄᴛɪᴠᴇ\n"
        "┣━━━━━━━━━━━━━━━━━┫\n"
        f"┃ 🆔 ɪᴅ   : {user.id}\n"
        f"┃ 💰 ᴘᴛs  : {points}\n"
        f"┃ ⚡ sᴛᴀᴛ : {status}\n"
        f"┃ 🏆 ᴘʟᴀɴ : ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀ\n"
        "┗━━━━━━━━━━━━━━━━━┛\n\n"
        "👇 ᴜsᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴍᴀɴᴀɢᴇ!"
    )

def main_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("📢 Updates Channel"))
    markup.add(types.KeyboardButton("📤 Deploy File"), types.KeyboardButton("📂 My Files"))
    markup.add(types.KeyboardButton("💰 My Points"), types.KeyboardButton("🔗 Referral Link"))
    markup.add(types.KeyboardButton("📊 Statistics"), types.KeyboardButton("📞 Contact Owner"))
    if user_id == ADMIN_ID:
        markup.add(types.KeyboardButton("👑 Admin Panel"), types.KeyboardButton("🌍 All Files Control"))
    return markup

def admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    m_text = "🔴 Maintenance: ON" if settings['maintenance'] else "🟢 Maintenance: OFF"
    markup.add(types.InlineKeyboardButton("➕ Add Points", callback_data="adm_add_pts"),
               types.InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast"))
    markup.add(types.InlineKeyboardButton("🎥 Set Welcome Video", callback_data="adm_set_video"))
    if settings.get('welcome_video'):
        markup.add(types.InlineKeyboardButton("❌ Remove Welcome Video", callback_data="adm_del_video"))
    markup.add(types.InlineKeyboardButton(m_text, callback_data="adm_toggle_maint"))
    markup.add(types.InlineKeyboardButton("🖥 Server Stats", callback_data="adm_stats"))
    return markup

# --- Handlers ---
@bot.message_handler(commands=['start'])
def start(message):
    uid = str(message.from_user.id)
    if settings['maintenance'] and message.from_user.id != ADMIN_ID:
        return bot.send_message(message.chat.id, "⚠️ **System is under maintenance.**")
    
    is_new = uid not in users_db
    if is_new:
        users_db[uid] = {'points': 10, 'files': []}
        params = message.text.split()
        if len(params) > 1:
            ref_id = params[1]
            if ref_id in users_db and ref_id != uid:
                users_db[ref_id]['points'] += settings.get('points_per_referral', 2)
                try: bot.send_message(int(ref_id), f"🎁 **Referral Bonus!** User {uid} joined. You got +{settings['points_per_referral']} pts!")
                except: pass
        save_db()

    caption = get_welcome_text(message)
    video = settings.get('welcome_video')
    if video:
        try: bot.send_video(message.chat.id, video, caption=caption, reply_markup=main_keyboard(message.from_user.id))
        except: bot.send_message(message.chat.id, caption, reply_markup=main_keyboard(message.from_user.id))
    else:
        bot.send_message(message.chat.id, caption, reply_markup=main_keyboard(message.from_user.id))

@bot.message_handler(func=lambda m: m.text == "🔗 Referral Link")
def referral_link(message):
    bot_info = bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    bot.send_message(message.chat.id, f"🔗 **Your Referral Link:**\n\n`{ref_link}`\n\nShare this link to get **{settings['points_per_referral']} points** for every new user!")

@bot.message_handler(func=lambda m: m.text == "📂 My Files")
def show_my_files(message):
    uid = str(message.from_user.id)
    files = users_db.get(uid, {}).get('files', [])
    if not files: return bot.send_message(message.chat.id, "❌ No deployed files.")
    for f_name in files:
        f_path = os.path.normpath(os.path.join(DEPLOY_DIR, f"{uid}_{f_name}"))
        status = "🟢 Running" if f_path in running_processes and running_processes[f_path].poll() is None else "🔴 Stopped"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("▶️ RUN", callback_data=f"run_{f_name}_{uid}"),
                   types.InlineKeyboardButton("⏸ STOP", callback_data=f"stop_{f_name}_{uid}"))
        markup.add(types.InlineKeyboardButton("📥 Download", callback_data=f"down_{f_name}_{uid}"),
                   types.InlineKeyboardButton("❌ DELETE", callback_data=f"del_{f_name}_{uid}"))
        bot.send_message(message.chat.id, f"📄 `{f_name}`\nStatus: {status}", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🌍 All Files Control" and m.from_user.id == ADMIN_ID)
def admin_files_control(message):
    bot.send_message(message.chat.id, "🔍 **Global File Control:**")
    for target_uid, data in users_db.items():
        for f_name in data.get('files', []):
            f_path = os.path.normpath(os.path.join(DEPLOY_DIR, f"{target_uid}_{f_name}"))
            status = "🟢" if f_path in running_processes and running_processes[f_path].poll() is None else "🔴"
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("RUN", callback_data=f"run_{f_name}_{target_uid}"),
                types.InlineKeyboardButton("STOP", callback_data=f"stop_{f_name}_{target_uid}"),
                types.InlineKeyboardButton("📥 Download", callback_data=f"down_{f_name}_{target_uid}"),
                types.InlineKeyboardButton("DEL", callback_data=f"del_{f_name}_{target_uid}")
            )
            bot.send_message(message.chat.id, f"👤 User: `{target_uid}`\n📄 File: `{f_name}` {status}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = str(call.from_user.id)
    data = call.data

    if "_" in data and not data.startswith("adm_"):
        parts = data.split("_")
        action, f_name, target_uid = parts[0], "_".join(parts[1:-1]), parts[-1]
        f_path = os.path.normpath(os.path.join(DEPLOY_DIR, f"{target_uid}_{f_name}"))
        
        if action == "stop" and f_path in running_processes:
            running_processes[f_path].terminate()
            del running_processes[f_path]
            bot.answer_callback_query(call.id, "Stopped")
        elif action == "run":
            if run_user_file(f_path, int(target_uid), f_name):
                bot.answer_callback_query(call.id, "Running")
        elif action == "down":
            if os.path.exists(f_path):
                with open(f_path, 'rb') as f:
                    bot.send_document(call.message.chat.id, f)
            else: bot.answer_callback_query(call.id, "File not found!")
        elif action == "del":
            if f_path in running_processes:
                running_processes[f_path].terminate()
                del running_processes[f_path]
            if os.path.exists(f_path): os.remove(f_path)
            if f_name in users_db[target_uid]['files']: users_db[target_uid]['files'].remove(f_name)
            save_db()
            bot.delete_message(call.message.chat.id, call.message.message_id)

    if uid == str(ADMIN_ID):
        if data == "adm_toggle_maint":
            settings['maintenance'] = not settings['maintenance']
            save_settings()
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=admin_keyboard())
        elif data == "adm_broadcast":
            msg = bot.send_message(call.message.chat.id, "📝 Send the message to broadcast:")
            bot.register_next_step_handler(msg, broadcast_logic)
        elif data == "adm_del_video":
            settings['welcome_video'] = None
            save_settings()
            bot.answer_callback_query(call.id, "Welcome Video Deleted.")
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=admin_keyboard())
        elif data == "adm_set_video":
            msg = bot.send_message(call.message.chat.id, "📹 Send me the video:")
            bot.register_next_step_handler(msg, save_video_logic)
        elif data == "adm_add_pts":
            msg = bot.send_message(call.message.chat.id, "👤 Send User ID to add points:")
            bot.register_next_step_handler(msg, lambda m: bot.register_next_step_handler(bot.send_message(m.chat.id, "💰 How many points?"), lambda p: admin_add_pts(m.text, p.text, m.chat.id)))
        elif data == "adm_stats":
            bot.answer_callback_query(call.id, f"CPU: {psutil.cpu_percent()}% | RAM: {psutil.virtual_memory().percent}%", show_alert=True)

def broadcast_logic(message):
    text = message.text
    count = 0
    for uid in users_db:
        try:
            bot.send_message(int(uid), f"📢 **Announcement:**\n\n{text}")
            count += 1
        except: pass
    bot.send_message(message.chat.id, f"✅ Message sent to {count} users.")

def admin_add_pts(target, points, chat_id):
    try:
        if target in users_db:
            users_db[target]['points'] += int(points)
            save_db()
            bot.send_message(chat_id, f"✅ Done! Added {points} to {target}")
        else: bot.send_message(chat_id, "❌ User not found.")
    except: bot.send_message(chat_id, "❌ Invalid input.")

def save_video_logic(message):
    if message.video:
        settings['welcome_video'] = message.video.file_id
        save_settings()
        bot.send_message(message.chat.id, "✅ Welcome Video Set!")
    else: bot.send_message(message.chat.id, "❌ Not a video.")

@bot.message_handler(func=lambda m: m.text == "📤 Deploy File")
def start_deployment(message):
    if users_db.get(str(message.from_user.id), {}).get('points', 0) < settings['hosting_cost']:
        return bot.send_message(message.chat.id, f"❌ Need {settings['hosting_cost']} points.")
    msg = bot.send_message(message.chat.id, "📤 Send your file (.py, .js or .zip):")
    bot.register_next_step_handler(msg, process_upload)

def process_upload(message):
    if not message.document: return
    f_name, uid = message.document.file_name, str(message.from_user.id)
    f_path = os.path.normpath(os.path.join(DEPLOY_DIR, f"{uid}_{f_name}"))
    prog = bot.send_message(message.chat.id, "⏳ Deploying...")
    try:
        f_info = bot.get_file(message.document.file_id)
        file_content = bot.download_file(f_info.file_path)
        with open(f_path, 'wb') as f: f.write(file_content)
        
        if f_name.endswith('.zip'):
            extract_dir = os.path.join(DEPLOY_DIR, f"{uid}_{f_name.replace('.zip', '')}")
            with zipfile.ZipFile(f_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            os.remove(f_path)
            f_path = extract_dir
        
        if not os.path.isdir(f_path):
            with open(f_path, 'r', encoding='utf-8') as f:
                libs = re.findall(r'^(?:import|from)\s+([\w\d_]+)', f.read(), re.MULTILINE)
            for lib in set(libs):
                if lib not in ['os','sys','time']: 
                    subprocess.run([sys.executable, '-m', 'pip', 'install', lib], stderr=subprocess.DEVNULL)

        if run_user_file(f_path, int(uid), f_name):
            users_db[uid]['points'] -= settings['hosting_cost']
            if f_name not in users_db[uid]['files']: users_db[uid]['files'].append(f_name)
            save_db()
            bot.edit_message_text(f"🚀 Success: `{f_name}` is LIVE!", message.chat.id, prog.message_id)
    except Exception as e: bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(func=lambda m: m.text == "💰 My Points")
def my_pts(message):
    pts = users_db.get(str(message.from_user.id), {}).get('points', 0)
    bot.send_message(message.chat.id, f"💰 Balance: **{pts} Points**", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📊 Statistics")
def show_stats(message):
    uploaders = len([u for u in users_db if len(users_db[u].get('files', [])) > 0])
    bot.send_message(message.chat.id, f"📊 Total Users: {len(users_db)}\n📤 Users with Uploads: {uploaders}\n🤖 Bots Running: {len(running_processes)}")

@bot.message_handler(func=lambda m: m.text == "👑 Admin Panel" and m.from_user.id == ADMIN_ID)
def show_admin_panel(message):
    bot.send_message(message.chat.id, "🎛 **Admin Control Center**", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "📞 Contact Owner")
def contact(message): bot.send_message(message.chat.id, "👤 Owner: @sakaki_zlt")

@bot.message_handler(func=lambda m: m.text == "📢 Updates Channel")
def updates(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("JOIN CHANNEL", url=f"https://t.me/{CHANNEL_ID.replace('@','')}"))
    bot.send_message(message.chat.id, "📢 Keep updated here:", reply_markup=markup)

if __name__ == "__main__":
    print("🤖 ⚡ ʀ ʙᴏᴛ ᴘʀᴇᴍɪᴜᴍ ʜᴏsᴛɪɴɢ ʙᴏᴛ  ⚡ Online...")
    bot.infinity_polling()
