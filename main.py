import os
import pytz
import pymongo
import random
import logging
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
BOT_TOKEN = "8648927877:AAGCYbBsXDngndIVoQBtetfncyHybfIc5yY"
ADMIN_IDS = [7978295530]
IST = pytz.timezone('Asia/Kolkata')
CHANNEL_ID = -1003920368665 

# --- DATABASE (MongoDB) ---
try:
    MONGO_URI = "mongodb+srv://jaishah91zx_db_user:terimkcmedanda@cluster0.afkz5h8.mongodb.net/?appName=Cluster0"
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["chuza090_db"]
    users_col = db["users"]
    color_bets_col = db["color_bets"]
    game_state_col = db["game_state"]
    
    if not game_state_col.find_one({"id": "current"}):
        game_state_col.insert_one({"id": "current", "period": 1001, "forced_result": None})
        
    logging.info("✅ MongoDB Connected")
except Exception as e:
    logging.error(f"❌ DB Error: {e}")

# --- SCHEDULE (Cricket) ---
# Format: "Date": [[TeamA, TeamB], [TeamC, TeamD]] -> List of lists for double headers
IPL_SCHEDULE = {
    "23-04": [["MI", "CSK"]], 
    "24-04": [["RCB", "GT"]], # Single Match
    "25-04": [["PBKS", "DC"], ["SRH", "RR"]], # Double Header
    "26-04": [["GT", "CSK"], ["LSG", "KKR"]]  # Double Header
}
PSL_SCHEDULE = {}

# --- WEB SERVER ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "SYSTEM ONLINE", 200
def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- HELPERS ---
def get_user(uid): return users_col.find_one({"user_id": uid})

def update_bal(uid, name, amt):
    if not get_user(uid):
        users_col.insert_one({"user_id": uid, "name": name, "balance": amt})
    else:
        users_col.update_one({"user_id": uid}, {"$inc": {"balance": amt}})

def is_bet_allowed(bet_type, match_idx, league):
    now = datetime.now(IST)
    current_time = now.strftime("%H:%M")
    today = now.strftime("%d-%m")
    
    matches = IPL_SCHEDULE.get(today, []) if league == 'IPL' else PSL_SCHEDULE.get(today, [])
    if not matches: return False
    
    is_double_header = len(matches) > 1

    # Timings
    TOSS_LOCK_DH1 = "14:50"
    MATCH_LOCK_DH1 = "15:30"
    TOSS_LOCK_STD = "18:58"
    MATCH_LOCK_STD = "19:30"

    if is_double_header and match_idx == 0: # First Match of Double Header
        if bet_type == "TOSS" and current_time >= TOSS_LOCK_DH1: return False
        if bet_type == "WIN" and current_time >= MATCH_LOCK_DH1: return False
    else: # Single Match or Second Match of Double Header
        if bet_type == "TOSS" and current_time >= TOSS_LOCK_STD: return False
        if bet_type == "WIN" and current_time >= MATCH_LOCK_STD: return False
    
    return True

# --- COLOR TRADING LOGIC ---
async def declare_color_result(app: Application):
    state = game_state_col.find_one({"id": "current"})
    curr_p, forced = state['period'], state['forced_result']
    bets = list(color_bets_col.find({"period": curr_p, "status": "Pending"}))
    
    paisa = {"RED": 0, "GREEN": 0, "VIOLET": 0}
    for b in bets: paisa[b['color']] += b['amt']

    if forced:
        win_color = forced
        game_state_col.update_one({"id": "current"}, {"$set": {"forced_result": None}})
    else:
        active = [c for c in paisa if paisa[c] > 0]
        win_color = min(paisa, key=paisa.get) if active else random.choice(["RED", "GREEN"])

    for b in bets:
        uid, b_amt, b_color = b['user_id'], b['amt'], b['color']
        if b_color == win_color:
            w_amt = b_amt * 1.9 
            update_bal(uid, "User", w_amt)
            await app.bot.send_message(chat_id=uid, text=f"🥳 *PERIOD WIN!*\n💰 Won: ₹{w_amt}\n🆔 Period: `{curr_p}`", parse_mode='Markdown')
        else:
            await app.bot.send_message(chat_id=uid, text=f"😔 *PERIOD LOSS!*\n🆔 Period: `{curr_p}`\n🎨 Result: {win_color}", parse_mode='Markdown')

    await app.bot.send_message(chat_id=CHANNEL_ID, text=f"🏆 *COLOR RESULT*\n🆔 Period: `{curr_p}`\n🎨 Winning Color: *{win_color}*", parse_mode='Markdown')
    color_bets_col.update_many({"period": curr_p}, {"$set": {"status": "Completed"}})
    game_state_col.update_one({"id": "current"}, {"$inc": {"period": 1}})

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = update.effective_user.id, update.effective_user.first_name
    update_bal(uid, name, 0)
    kb = [[InlineKeyboardButton("🌈 Colour Trading", callback_data='COLOR')],
          [InlineKeyboardButton("🏏 Cricket Bet", callback_data='L_CHOOSE')],
          [InlineKeyboardButton("💰 Deposit", callback_data='D'), InlineKeyboardButton("🏦 Withdraw", callback_data='W')],
          [InlineKeyboardButton("💳 Balance", callback_data='AB'), InlineKeyboardButton("🏆 Leaderboard", callback_data='LB')]]
    await update.message.reply_text(f"🏆 *Chuza090 PRO*\nWelcome {name}!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    uid, data = query.from_user.id, query.data
    
    if data == 'COLOR':
        p = game_state_col.find_one({"id": "current"})['period']
        kb = [[InlineKeyboardButton("🔴 Red", callback_data='CB_RED'), InlineKeyboardButton("🟢 Green", callback_data='CB_GREEN')], 
              [InlineKeyboardButton("🟣 Violet", callback_data='CB_VIOLET')]]
        await query.message.reply_text(f"🌈 *COLOUR TRADING*\n🆔 Period: `{p}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data.startswith('CB_'):
        context.user_data['color'] = data.split('_')[1]
        await query.message.reply_text(f"🎨 Selected: {context.user_data['color']}\nAmt (Min ₹20):"); context.user_data['step'] = 'C_BET'

    elif data == 'AB':
        u = get_user(uid); await query.message.reply_text(f"💳 Balance: *₹{u['balance'] if u else 0}*")

    elif data == 'L_CHOOSE':
        kb = [[InlineKeyboardButton("IPL 2026", callback_data='L_IPL'), InlineKeyboardButton("PSL 2026", callback_data='L_PSL')]]
        await query.message.reply_text("🏆 Select League:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('L_'):
        league = data.split('_')[1]; today = datetime.now(IST).strftime("%d-%m")
        matches = (IPL_SCHEDULE if league == 'IPL' else PSL_SCHEDULE).get(today, [])
        if not matches: return await query.message.reply_text(f"❌ Aaj match nahi hai.")
        context.user_data['league'] = league
        kb = [[InlineKeyboardButton(f"{m[0]} vs {m[1]}", callback_data=f"M_{i}")] for i, m in enumerate(matches)]
        await query.message.reply_text("🏏 Match Select:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('M_'):
        context.user_data['idx'] = int(data.split('_')[1])
        kb = [[InlineKeyboardButton("🪙 Toss", callback_data='T_TOSS'), InlineKeyboardButton("🏆 Winner", callback_data='T_WIN')]]
        await query.message.reply_text("Bet Type:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('T_'):
        b_type = data.split('_')[1]; idx = context.user_data['idx']; league = context.user_data['league']
        if not is_bet_allowed(b_type, idx, league):
            return await query.message.reply_text(f"❌ {b_type} Bets for this match are now CLOSED!")
        
        context.user_data['bt'] = b_type
        match = (IPL_SCHEDULE if league == 'IPL' else PSL_SCHEDULE).get(datetime.now(IST).strftime("%d-%m"))[idx]
        kb = [[InlineKeyboardButton(match[0], callback_data=f"TM_{match[0]}"), InlineKeyboardButton(match[1], callback_data=f"TM_{match[1]}")]]
        await query.message.reply_text(f"Select Team:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('TM_'):
        context.user_data['bet_team'] = data.split('_')[1]
        await query.message.reply_text(f"✅ Team: {context.user_data['bet_team']}\nAmt (Min ₹50):"); context.user_data['step'] = 'B_FINAL'
    
    elif data == 'D': await query.message.reply_text("Amt (Min ₹100):"); context.user_data['step'] = 'DEP'
    elif data == 'W': await query.message.reply_text("Amt (Min ₹100):"); context.user_data['step'] = 'WIT'

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    uid, text = update.effective_user.id, update.message.text
    step = context.user_data.get('step')

    # Admin Control
    if uid in ADMIN_IDS and update.message.reply_to_message:
        try:
            tid = int(update.message.reply_to_message.text.split("ID: ")[1].split("\n")[0])
            if text.startswith('+'):
                update_bal(tid, "User", float(text[1:]))
                await context.bot.send_message(tid, f"✅ ₹{text[1:]} added!")
                return await update.message.reply_text("Done.")
        except: pass

    if step == 'C_BET' and text.isdigit():
        amt = float(text); u = get_user(uid); p = game_state_col.find_one({"id": "current"})['period']
        if not u or amt < 20 or amt > u['balance']: return await update.message.reply_text("❌ Bal Error!")
        update_bal(uid, "User", -amt)
        color_bets_col.insert_one({"user_id": uid, "amt": amt, "color": context.user_data['color'], "period": p, "status": "Pending"})
        await update.message.reply_text("✅ Color Bet Done!")
    
    elif step == 'B_FINAL' and text.isdigit():
        amt = float(text); u = get_user(uid)
        if not u or amt < 50 or amt > u['balance']: return await update.message.reply_text("❌ Bal Error!")
        update_bal(uid, "User", -amt)
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🎲 *NEW BET*\nID: {uid}\nTeam: {context.user_data['bet_team']}\nType: {context.user_data['bt']}\nAmt: ₹{amt}")
        await update.message.reply_text("✅ Cricket Bet Done!")

    elif step == 'DEP' and text.isdigit():
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🛎 DEP\nID: {uid}\nAmt: ₹{text}")
        await update.message.reply_text("⏳ Admin QR bhej raha hai...")
    
    context.user_data['step'] = None

async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(declare_color_result, 'interval', minutes=2, args=[app])
    scheduler.start()

def main():
    Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__': main()
