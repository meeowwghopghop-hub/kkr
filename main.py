import os
import pytz
import pymongo
import random
import logging
import certifi
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
CHANNEL_ID = -100392036866ii5

# --- DATABASE ---
try:
    ca = certifi.where()
    MONGO_URI = "mongodb+srv://jaishah91zx_db_user:terimkcmedanda@cluster0.afkz5h8.mongodb.net/?appName=Cluster0"
    client = pymongo.MongoClient(MONGO_URI, tlsCAFile=ca, serverSelectionTimeoutMS=5000)
    db = client["chuza090_db"]
    users_col, color_bets_col, game_state_col = db["users"], db["color_bets"], db["game_state"]
    if not game_state_col.find_one({"id": "current"}):
        game_state_col.insert_one({"id": "current", "period": 1001, "forced_results": {}})
    logging.info("✅ MongoDB Connected")
except Exception as e:
    logging.error(f"❌ DB Error: {e}")

# --- SCHEDULES ---
IPL_SCHEDULE = {"23-04": [["MI", "CSK"]], "24-04": [["SRH", "RCB"]], "25-04" : [["PBKS", "DC"]]}
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
    if not get_user(uid): users_col.insert_one({"user_id": uid, "name": name, "balance": amt})
    else: users_col.update_one({"user_id": uid}, {"$inc": {"balance": amt}})

def is_betting_open(league, match_idx, bet_type):
    now = datetime.now(IST)
    curr, today = now.strftime("%H:%M"), now.strftime("%d-%m")
    matches = (IPL_SCHEDULE if league == 'IPL' else PSL_SCHEDULE).get(today, [])
    if not matches or match_idx >= len(matches): return False
    limit = ("14:50" if match_idx == 0 and len(matches) == 2 else "18:58") if bet_type == "TOSS" else \
            ("15:30" if match_idx == 0 and len(matches) == 2 else "19:30")
    return curr <= limit

# --- COLOR ENGINE (1 MINUTE TIMER) ---
async def declare_color_result(app: Application):
    state = game_state_col.find_one({"id": "current"})
    curr_p = state['period']
    forced_map = state.get('forced_results', {}) # Get the dictionary of fixed results
    
    # Check if this specific period is fixed
    forced = forced_map.get(str(curr_p))
    
    bets = list(color_bets_col.find({"period": curr_p, "status": "Pending"}))
    paisa = {"RED": 0, "GREEN": 0, "VIOLET": 0}
    for b in bets: paisa[b['color']] += b['amt']

    if forced:
        win_color = forced
        # Remove used fix from DB
        game_state_col.update_one({"id": "current"}, {"$unset": {f"forced_results.{curr_p}": ""}})
    else:
        active = [c for c in paisa if paisa[c] > 0]
        win_color = min(paisa, key=paisa.get) if active else random.choice(["RED", "GREEN"])

    for b in bets:
        uid, amt, color = b['user_id'], b['amt'], b['color']
        if color == win_color:
            update_bal(uid, "User", amt * 1.9)
            await app.bot.send_message(uid, f"🥳 *WIN!* Period: {curr_p}\nWon: ₹{amt*1.9}", parse_mode='Markdown')
        else: await app.bot.send_message(uid, f"😔 *LOSS!* Period: {curr_p}\nResult: {win_color}", parse_mode='Markdown')
    
    await app.bot.send_message(CHANNEL_ID, f"🏆 *RESULT* 🆔 `{curr_p}`\n🎨 Winner: *{win_color}*", parse_mode='Markdown')
    color_bets_col.update_many({"period": curr_p}, {"$set": {"status": "Completed"}})
    game_state_col.update_one({"id": "current"}, {"$inc": {"period": 1}})

# --- ADMIN COMMANDS ---
async def fix_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args: return await update.message.reply_text("Usage:\n`/fix RED` (Next)\n`/fix GREEN 1025` (Specific Period)", parse_mode='Markdown')
    
    choice = context.args[0].upper()
    state = game_state_col.find_one({"id": "current"})
    
    # If period is provided, use it. Else use next period.
    period = context.args[1] if len(context.args) > 1 else str(state['period'])
    
    if choice in ["RED", "GREEN", "VIOLET"]:
        game_state_col.update_one({"id": "current"}, {"$set": {f"forced_results.{period}": choice}})
        await update.message.reply_text(f"🎯 *Period {period}* fixed to: *{choice}*", parse_mode='Markdown')

# --- HANDLERS (Cricket Fix Included) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = update.effective_user.id, update.effective_user.first_name
    update_bal(uid, name, 0)
    kb = [[InlineKeyboardButton("🌈 Color Trading", callback_data='COLOR')],
          [InlineKeyboardButton("🏏 Cricket Bet", callback_data='L_CHOOSE')],
          [InlineKeyboardButton("💰 Deposit", callback_data='D'), InlineKeyboardButton("🏦 Withdraw", callback_data='W')],
          [InlineKeyboardButton("💳 Balance", callback_data='AB'), InlineKeyboardButton("🏆 Leaderboard", callback_data='LB')]]
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
        await query.message.reply_text("Amt (Min ₹20):"); context.user_data['step'] = 'C_BET'
    elif data == 'AB':
        u = get_user(uid); await query.message.reply_text(f"💳 Balance: *₹{u['balance'] if u else 0}*", parse_mode='Markdown')
    elif data == 'L_CHOOSE':
        kb = [[InlineKeyboardButton("IPL 2026", callback_data='L_IPL'), InlineKeyboardButton("PSL 2026", callback_data='L_PSL')]]
        await query.message.reply_text("🏆 Select League:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('L_'):
        l = data.split('_')[1]; today = datetime.now(IST).strftime("%d-%m")
        matches = (IPL_SCHEDULE if l == 'IPL' else PSL_SCHEDULE).get(today, [])
        if not matches: return await query.message.reply_text("❌ No Match Today")
        kb = [[InlineKeyboardButton(f"{m[0]} vs {m[1]}", callback_data=f"M_{l}_{i}")] for i, m in enumerate(matches)]
        await query.message.reply_text("🏏 Select Match:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('M_'):
        _, l, idx = data.split('_'); context.user_data.update({'l': l, 'idx': int(idx)})
        kb = [[InlineKeyboardButton("🪙 Toss", callback_data='T_TOSS'), InlineKeyboardButton("🏆 Match Winner", callback_data='T_WINNER')]]
        await query.message.reply_text("Bet Type:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('T_'):
        b_type = data.split('_')[1]; l, idx = context.user_data['l'], context.user_data['idx']
        if not is_betting_open(l, idx, b_type): return await query.message.reply_text("❌ Betting Closed!")
        context.user_data['b_type'] = "TOSS" if b_type == "TOSS" else "MATCH WINNER"
        m = (IPL_SCHEDULE if l == 'IPL' else PSL_SCHEDULE).get(datetime.now(IST).strftime("%d-%m"))[idx]
        kb = [[InlineKeyboardButton(m[0], callback_data=f"TM_{m[0]}"), InlineKeyboardButton(m[1], callback_data=f"TM_{m[1]}")]]
        await query.message.reply_text(f"Select Team for *{context.user_data['b_type']}*:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    elif data.startswith('TM_'):
        context.user_data['bet_team'] = data.split('_')[1]
        await query.message.reply_text(f"✅ Selected: {context.user_data['bet_team']} ({context.user_data['b_type']})\nAmt (Min ₹50):"); context.user_data['step'] = 'BET_FINAL'
    elif data == 'D':
        await query.message.reply_text("💰 Kitna deposit karna hai? (Min ₹100):"); context.user_data['step'] = 'DEP'

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    step = context.user_data.get('step')

    # Admin Logic
    if uid in ADMIN_IDS and update.message.reply_to_message:
        try:
            orig = update.message.reply_to_message.text or update.message.reply_to_message.caption
            tid = int(orig.split("ID: ")[1].split("\n")[0])
            if text and text.startswith('+'):
                amt = int(text[1:].strip()); update_bal(tid, "User", amt)
                await context.bot.send_message(tid, f"✅ ₹{amt} added to wallet!"); return
            elif update.message.photo:
                await context.bot.send_photo(tid, update.message.photo[-1].file_id, caption="✅ *Scan & Pay!*"); return
        except: pass

    # Bet Logic
    if step == 'BET_FINAL' and text.isdigit():
        amt = int(text); u = get_user(uid)
        if amt < 50 or not u or amt > u['balance']: return await update.message.reply_text("❌ Check Bal!")
        update_bal(uid, "User", -amt)
        b_type = context.user_data['b_type']
        team = context.user_data['bet_team']
        # Admin Notification with clear Labels
        for aid in ADMIN_IDS:
            await context.bot.send_message(aid, f"🎲 *NEW CRICKET BET*\nID: {uid}\n📍 Type: *{b_type}*\n🏏 Team: *{team}*\n💰 Amt: ₹{amt}", parse_mode='Markdown')
        await update.message.reply_text(f"✅ Bet Placed!\n{b_type}: {team}\nAmount: ₹{amt}", parse_mode='Markdown')
        context.user_data['step'] = None
    elif step == 'C_BET' and text.isdigit():
        amt = int(text); u = get_user(uid); p = game_state_col.find_one({"id": "current"})['period']
        if amt < 20 or not u or amt > u['balance']: return await update.message.reply_text("❌ Check Bal!")
        update_bal(uid, "User", -amt)
        color_bets_col.insert_one({"user_id": uid, "amt": amt, "color": context.user_data['color'], "period": p, "status": "Pending"})
        await update.message.reply_text(f"✅ Color Bet Placed!\nPeriod: {p}\nColor: {context.user_data['color']}", parse_mode='Markdown')
        context.user_data['step'] = None
    elif step == 'DEP' and text.isdigit():
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🛎 *DEP REQ*\nID: {uid}\nAmt: ₹{text}\nReply with QR photo.")
        await update.message.reply_text("⏳ Admin QR bhej raha hai..."); context.user_data['step'] = None

async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(declare_color_result, 'interval', minutes=1, args=[app]) # TIMER 1 MINUTE
    scheduler.start()

def main():
    Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fix", fix_color))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__': main()
