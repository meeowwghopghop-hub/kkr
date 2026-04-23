import os
import pytz
import pymongo
import random
import logging
import certifi  # SSL FIX
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

# --- DATABASE (MongoDB with SSL Fix) ---
try:
    ca = certifi.where()
    MONGO_URI = "mongodb+srv://jaishah91zx_db_user:terimkcmedanda@cluster0.afkz5h8.mongodb.net/?appName=Cluster0"
    # SSL/TLS Handshake fix added here
    client = pymongo.MongoClient(MONGO_URI, tlsCAFile=ca, serverSelectionTimeoutMS=5000)
    db = client["chuza090_db"]
    users_col = db["users"]
    color_bets_col = db["color_bets"]
    game_state_col = db["game_state"]
    
    if not game_state_col.find_one({"id": "current"}):
        game_state_col.insert_one({"id": "current", "period": 1001, "forced_result": None})
        
    logging.info("✅ MongoDB Connected with SSL Fix")
except Exception as e:
    logging.error(f"❌ DB Error: {e}")

# --- SCHEDULE (Cricket) ---
IPL_SCHEDULE = {
    "23-04": [["MI", "CSK"]], 
    "24-04": [["RCB", "GT"]], 
    "25-04": [["PBKS", "DC"], ["SRH", "RR"]], 
    "26-04": [["GT", "CSK"], ["LSG", "KKR"]]
}

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
    matches = IPL_SCHEDULE.get(today, [])
    if not matches: return False
    is_dh = len(matches) > 1
    if is_dh and match_idx == 0:
        if bet_type == "TOSS" and current_time >= "14:50": return False
        if bet_type == "WIN" and current_time >= "15:30": return False
    else:
        if bet_type == "TOSS" and current_time >= "18:58": return False
        if bet_type == "WIN" and current_time >= "19:30": return False
    return True

# --- NEW: FIX COLOR COMMAND ---
async def fix_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("❌ Usage: `/fix RED` or `/fix GREEN`", parse_mode='Markdown')
        return
    choice = context.args[0].upper()
    if choice in ["RED", "GREEN", "VIOLET"]:
        game_state_col.update_one({"id": "current"}, {"$set": {"forced_result": choice}})
        await update.message.reply_text(f"🎯 *Next result fixed to: {choice}*", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Use RED, GREEN or VIOLET")

# --- COLOR TRADING LOGIC ---
async def declare_color_result(app: Application):
    state = game_state_col.find_one({"id": "current"})
    curr_p, forced = state['period'], state['forced_result']
    bets = list(color_bets_col.find({"period": curr_p, "status": "Pending"}))
    
    paisa = {"RED": 0, "GREEN": 0, "VIOLET": 0}
    for b in bets: paisa[b['color']] += b['amt']

    if forced:
        win_color = forced
        game_state_col.update_one({"id": "current"}, {"$set": {"forced_result": None}}) # Reset after use
    else:
        # Profit Logic: Jitna kam paisa, utni winning probability
        active = [c for c in paisa if paisa[c] > 0]
        win_color = min(paisa, key=paisa.get) if active else random.choice(["RED", "GREEN"])

    for b in bets:
        uid, b_amt, b_color = b['user_id'], b['amt'], b['color']
        if b_color == win_color:
            update_bal(uid, "User", b_amt * 1.9)
            await app.bot.send_message(chat_id=uid, text=f"🥳 *WIN!* Period: {curr_p}\nWon: ₹{b_amt*1.9}", parse_mode='Markdown')
        else:
            await app.bot.send_message(chat_id=uid, text=f"😔 *LOSS!* Period: {curr_p}\nResult: {win_color}", parse_mode='Markdown')

    await app.bot.send_message(chat_id=CHANNEL_ID, text=f"🏆 *RESULT* 🆔 `{curr_p}`\n🎨 Winning Color: *{win_color}*", parse_mode='Markdown')
    color_bets_col.update_many({"period": curr_p}, {"$set": {"status": "Completed"}})
    game_state_col.update_one({"id": "current"}, {"$inc": {"period": 1}})

# --- REST OF HANDLERS (Same as before) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = update.effective_user.id, update.effective_user.first_name
    update_bal(uid, name, 0)
    kb = [[InlineKeyboardButton("🌈 Colour Trading", callback_data='COLOR')],
          [InlineKeyboardButton("🏏 Cricket Bet", callback_data='L_CHOOSE')],
          [InlineKeyboardButton("💰 Deposit", callback_data='D'), InlineKeyboardButton("🏦 Withdraw", callback_data='W')],
          [InlineKeyboardButton("💳 Balance", callback_data='AB')]]
    await update.message.reply_text(f"🏆 *Chuza090 PRO*\nBhai {name}, khel shuru kar!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    uid, data = query.from_user.id, query.data
    if data == 'COLOR':
        p = game_state_col.find_one({"id": "current"})['period']
        kb = [[InlineKeyboardButton("🔴 Red", callback_data='CB_RED'), InlineKeyboardButton("🟢 Green", callback_data='CB_GREEN')], [InlineKeyboardButton("🟣 Violet", callback_data='CB_VIOLET')]]
        await query.message.reply_text(f"🌈 *PERIOD:* `{p}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    elif data.startswith('CB_'):
        context.user_data['color'] = data.split('_')[1]
        await query.message.reply_text(f"🎨 {context.user_data['color']} selected. Amt:"); context.user_data['step'] = 'C_BET'
    elif data == 'AB':
        u = get_user(uid); await query.message.reply_text(f"💳 Balance: ₹{u['balance'] if u else 0}")
    # ... (Add other button logics as per previous code)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    uid, text = update.effective_user.id, update.message.text
    step = context.user_data.get('step')

    if step == 'C_BET' and text.isdigit():
        amt = float(text); u = get_user(uid); p = game_state_col.find_one({"id": "current"})['period']
        if not u or amt < 20 or amt > u['balance']: return await update.message.reply_text("❌ Check Balance!")
        update_bal(uid, "User", -amt)
        color_bets_col.insert_one({"user_id": uid, "amt": amt, "color": context.user_data['color'], "period": p, "status": "Pending"})
        await update.message.reply_text("✅ Bet Lag Gayi!")
    
    context.user_data['step'] = None

async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(declare_color_result, 'interval', minutes=2, args=[app])
    scheduler.start()

def main():
    Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fix", fix_color)) # FIXED COMMAND REGISTERED
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__': main()
