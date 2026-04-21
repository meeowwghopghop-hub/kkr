import os, pytz, sqlite3, random, logging
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
BOT_TOKEN = "8694462304:AAHSibwJqVMLMnJLo-66twdcJhB-TIkG8ZM"
ADMIN_IDS = [7978295530, 7010155909]
IST = pytz.timezone('Asia/Kolkata')
CHANNEL_ID = -1003792610411 

# --- MATCH DATA (IPL & PSL 2026) ---
IPL_SCHEDULE = {
    "21-04": [["SRH", "DC"]],
    "22-04": [["LSG", "RR"]],
    "23-04": [["MI", "CSK"]],
    "24-04": [["RCB", "GT"]],
    "25-04": [["DC", "KKR"]]
}
PSL_SCHEDULE = {
    "21-04": [["LQ", "QG"]],
    "22-04": [["PZ", "IU"]],
    "23-04": [["MS", "KK"]]
}

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, balance REAL DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS color_bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amt REAL, color TEXT, period INTEGER, status TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS game_state (id TEXT PRIMARY KEY, period INTEGER, forced_result TEXT)")
    cur.execute("INSERT OR IGNORE INTO game_state (id, period, forced_result) VALUES ('current', 1001, NULL)")
    conn.commit()
    conn.close()

def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()
    cur.execute(query, params)
    res = None
    if fetchone: res = cur.fetchone()
    if fetchall: res = cur.fetchall()
    if commit: conn.commit()
    conn.close()
    return res

init_db()

# --- WEB SERVER (For Render) ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "SYSTEM ONLINE", 200
def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- HELPERS ---
def get_user(uid): return db_query("SELECT * FROM users WHERE user_id=?", (uid,), fetchone=True)
def update_bal(uid, name, amt):
    if not get_user(uid): db_query("INSERT INTO users (user_id, name, balance) VALUES (?, ?, ?)", (uid, name, amt), commit=True)
    else: db_query("UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, uid), commit=True)

# --- AUTO RESULT LOGIC (Every 5 Mins) ---
async def declare_color_result(app: Application):
    state = db_query("SELECT period, forced_result FROM game_state WHERE id='current'", fetchone=True)
    curr_p, forced = state[0], state[1]
    bets = db_query("SELECT user_id, amt, color FROM color_bets WHERE period=? AND status='Pending'", (curr_p,), fetchall=True)
    
    paisa = {"RED": 0, "GREEN": 0, "VIOLET": 0}
    for b in bets: paisa[b[2]] += b[1]

    if forced:
        win_color = forced
        db_query("UPDATE game_state SET forced_result=NULL WHERE id='current'", commit=True)
    else:
        # Smart Logic: Win the color with LEAST money (or random if 0 bets)
        active = [c for c in paisa if paisa[c] > 0]
        win_color = min(paisa, key=paisa.get) if active else random.choice(["RED", "GREEN", "VIOLET"])

    for b in bets:
        uid, b_amt, b_color = b[0], b[1], b[2]
        if b_color == win_color:
            w_amt = b_amt * 1.9
            update_bal(uid, "User", w_amt)
            msg = f"🥳 *PERIOD WIN!*\n💰 Won: ₹{w_amt}\n🆔 Period: `{curr_p}`"
        else:
            msg = f"😔 *PERIOD LOSS!*\n🆔 Period: `{curr_p}`\n🎨 Result: {win_color}"
        try: await app.bot.send_message(chat_id=uid, text=msg, parse_mode='Markdown')
        except: pass

    try: await app.bot.send_message(chat_id=CHANNEL_ID, text=f"🏆 *COLOR RESULT*\n🆔 Period: `{curr_p}`\n🎨 Winning Color: *{win_color}*", parse_mode='Markdown')
    except: pass
    
    db_query("UPDATE color_bets SET status='Completed' WHERE period=?", (curr_p,), commit=True)
    db_query("UPDATE game_state SET period = period + 1 WHERE id='current'", commit=True)

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = update.effective_user.id, update.effective_user.first_name
    update_bal(uid, name, 0)
    kb = [[InlineKeyboardButton("🌈 Colour Trading", callback_data='COLOR')],
          [InlineKeyboardButton("🏏 Cricket Bet", callback_data='L_CHOOSE')],
          [InlineKeyboardButton("💰 Deposit", callback_data='D'), InlineKeyboardButton("🏦 Withdraw", callback_data='W')],
          [InlineKeyboardButton("💳 Bal", callback_data='AB'), InlineKeyboardButton("🏆 Leader", callback_data='LB')]]
    await update.message.reply_text(f"🏆 *Chuza090 Pro*\nHi {name}!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); uid = q.from_user.id; data = q.data
    
    if data == 'COLOR':
        p = db_query("SELECT period FROM game_state WHERE id='current'", fetchone=True)[0]
        kb = [[InlineKeyboardButton("🔴 Red", callback_data='CB_RED'), InlineKeyboardButton("🟢 Green", callback_data='CB_GREEN')], [InlineKeyboardButton("🟣 Violet", callback_data='CB_VIOLET')]]
        await q.message.reply_text(f"🌈 Period: `{p}`\nSelect Color:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('CB_'):
        context.user_data['color'] = data.split('_')[1]
        await q.message.reply_text("Amt Likho (Min ₹20):"); context.user_data['step'] = 'C_BET'
    elif data == 'AB':
        u = get_user(uid); await q.message.reply_text(f"💳 Balance: *₹{u[2]}*")
    elif data == 'LB':
        top = db_query("SELECT name, balance FROM users ORDER BY balance DESC LIMIT 5", fetchall=True)
        txt = "🔥 *LEADERBOARD*\n\n"
        for i, u in enumerate(top, 1): txt += f"{i}. {u[0]} - ₹{u[1]}\n"
        await q.message.reply_text(txt)
    elif data == 'D':
        await q.message.reply_text("💰 Deposit Amt (Min ₹100):"); context.user_data['step'] = 'DEP'
    elif data == 'W':
        await q.message.reply_text("🏦 Withdraw Amt (Min ₹100):"); context.user_data['step'] = 'WIT'
    elif data == 'L_CHOOSE':
        kb = [[InlineKeyboardButton("IPL 2026", callback_data='L_IPL'), InlineKeyboardButton("PSL 2026", callback_data='L_PSL')]]
        await q.message.reply_text("🏆 Select League:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('L_'):
        league = data.split('_')[1]; today = datetime.now(IST).strftime("%d-%m")
        matches = (IPL_SCHEDULE if league == 'IPL' else PSL_SCHEDULE).get(today, [])
        if not matches: return await q.message.reply_text("❌ No match today.")
        kb = [[InlineKeyboardButton(f"{m[0]} vs {m[1]}", callback_data=f"M_{league}_{i}")] for i, m in enumerate(matches)]
        await q.message.reply_text("🏏 Match Select:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('M_'):
        _, l, idx = data.split('_'); context.user_data.update({'l': l, 'idx': int(idx)})
        kb = [[InlineKeyboardButton("🪙 Toss", callback_data='T_TOSS'), InlineKeyboardButton("🏆 Winner", callback_data='T_WIN')]]
        await q.message.reply_text("Bet Type:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('T_'):
        context.user_data['bt'] = data.split('_')[1]; l, idx = context.user_data['l'], context.user_data['idx']
        m = (IPL_SCHEDULE if l == 'IPL' else PSL_SCHEDULE).get(datetime.now(IST).strftime("%d-%m"))[idx]
        kb = [[InlineKeyboardButton(m[0], callback_data=f"TM_{m[0]}"), InlineKeyboardButton(m[1], callback_data=f"TM_{m[1]} text")]]
        await q.message.reply_text("Select Team:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('TM_'):
        context.user_data['team'] = data.split('_')[1]
        await q.message.reply_text(f"✅ Selected: {context.user_data['team']}\nAmt (Min ₹50):")
        context.user_data['step'] = 'B_FINAL'

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    step = context.user_data.get('step')

    # ADMIN REPLY LOGIC
    if uid in ADMIN_IDS and update.message.reply_to_message:
        try:
            tid = int(update.message.reply_to_message.text.split("ID: ")[1].split("\n")[0])
            if text.startswith('+'):
                amt = float(text[1:]); update_bal(tid, "User", amt)
                await context.bot.send_message(tid, f"✅ ₹{amt} added to wallet!")
                return await update.message.reply_text("Done.")
            elif update.message.photo:
                await context.bot.send_photo(tid, update.message.photo[-1].file_id, caption="✅ *Kindly reply on this msg along with the payment ss*")
                return await update.message.reply_text("QR Sent.")
        except: pass

    # USER INPUTS
    if step == 'C_BET' and text.isdigit():
        amt = float(text); u = get_user(uid); p = db_query("SELECT period FROM game_state WHERE id='current'", fetchone=True)[0]
        if amt < 20 or amt > u[2]: return await update.message.reply_text("❌ Bal Error!")
        update_bal(uid, "User", -amt)
        db_query("INSERT INTO color_bets (user_id, amt, color, period, status) VALUES (?, ?, ?, ?, 'Pending')", (uid, amt, context.user_data['color'], p), commit=True)
        await update.message.reply_text("✅ Color Bet Done!"); context.user_data['step'] = None
    elif step == 'DEP' and text.isdigit():
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🛎 DEP REQ\nID: {uid}\nAmt: ₹{text}\nReply with QR.")
        await update.message.reply_text("⏳ Admin QR bhej raha hai..."); context.user_data['step'] = None
    elif step == 'WIT' and text.isdigit():
        context.user_data['wa'] = float(text); context.user_data['step'] = 'W_UPI'
        await update.message.reply_text("🏦 UPI ID Bhejein:")
    elif step == 'W_UPI' and text:
        amt = context.user_data['wa']; update_bal(uid, "User", -amt)
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🏦 WITHDRAW\nID: {uid}\nAmt: ₹{amt}\nUPI: {text}")
        await update.message.reply_text("✅ Req Sent!"); context.user_data['step'] = None
    elif step == 'B_FINAL' and text.isdigit():
        amt = float(text); u = get_user(uid)
        if amt < 50 or amt > u[2]: return await update.message.reply_text("❌ Bal Error!")
        update_bal(uid, "User", -amt)
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🎲 NEW BET\nID: {uid}\nTeam: {context.user_data['team']}\nType: {context.user_data['bt']}\nAmt: ₹{amt}")
        await update.message.reply_text("✅ Cricket Bet Done!"); context.user_data['step'] = None

async def set_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        col = context.args[0].upper()
        db_query("UPDATE game_state SET forced_result=? WHERE id='current'", (col,), commit=True)
        await update.message.reply_text(f"✅ Fixed: {col}")
    except: await update.message.reply_text("/setcolor RED")

# --- MAIN ---
async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(declare_color_result, 'interval', minutes=5, args=[app])
    scheduler.start()

def main():
    Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setcolor", set_color))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__': main()
