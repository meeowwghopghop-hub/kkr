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
# --- SCHEDULE ---
# Yahan matches ki dates update karte rehna
IPL_SCHEDULE = {"23-04": [["MI", "CSK"]], "24-04": [["SRH", "RCB"]], "25-04" : [["PBKS", "DC"]]}
PSL_SCHEDULE = {}

# --- FLASK (For Render Uptime) ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "SYSTEM ONLINE", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- HELPERS ---
def get_color_keyboard(period):
    kb = [
        [InlineKeyboardButton("🔴 Red", callback_data='CB_RED'), 
         InlineKeyboardButton("🟢 Green", callback_data='CB_GREEN')],
        [InlineKeyboardButton("🟣 Violet", callback_data='CB_VIOLET')]
    ]
    return InlineKeyboardMarkup(kb)
def get_user(uid): 
    return users_col.find_one({"user_id": uid})

def update_bal(uid, name, amt):
    if not get_user(uid):
        users_col.insert_one({"user_id": uid, "name": name, "balance": amt})
    else:
        users_col.update_one({"user_id": uid}, {"$inc": {"balance": amt}})

def is_betting_open(league, match_idx, bet_type):
    now = datetime.now(IST)
    current_time = now.strftime("%H:%M")
    today = now.strftime("%d-%m")
    matches = (IPL_SCHEDULE if league == 'IPL' else PSL_SCHEDULE).get(today, [])
    if not matches or match_idx >= len(matches): return False
    
    num_matches = len(matches)
    if num_matches == 2:
        if match_idx == 0:
            toss_limit, match_limit = "14:50", "15:30"
        else:
            toss_limit, match_limit = "18:58", "19:30"
    else:
        toss_limit, match_limit = "18:58", "19:30"

    return current_time <= (toss_limit if bet_type == "TOSS" else match_limit)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name = update.effective_user.id, update.effective_user.first_name
    update_bal(uid, name, 0)
    kb = [[InlineKeyboardButton("🏏 Cricket Bet", callback_data='L_CHOOSE')],
          [InlineKeyboardButton("💰 Deposit", callback_data='D'), InlineKeyboardButton("🏦 Withdraw", callback_data='W')],
          [InlineKeyboardButton("💳 Balance", callback_data='AB'), InlineKeyboardButton("🏆 Leaderboard", callback_data='LB')],
          [InlineKeyboardButton("🎧 Support", callback_data='S_INFO')]]
    await update.message.reply_text(f"🏆 *Chuza090 PRO*\n\nWelcome {name}!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    uid, data = query.from_user.id, query.data
    
    if data == 'AB':
        u = get_user(uid)
        bal = u['balance'] if u else 0
        await query.message.reply_text(f"💳 Balance: *₹{bal}*", parse_mode='Markdown')
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
    elif data == 'S_INFO':
        await query.message.reply_text("🎧 Support ke liye command use karein:\n`/connect [Message]`")
    elif data == 'L_CHOOSE':
        kb = [[InlineKeyboardButton("IPL 2026", callback_data='L_IPL'), InlineKeyboardButton("PSL 2026", callback_data='L_PSL')]]
        await query.message.reply_text("🏆 Select League:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('L_'):
        league = data.split('_')[1]; today = datetime.now(IST).strftime("%d-%m")
        matches = (IPL_SCHEDULE if league == 'IPL' else PSL_SCHEDULE).get(today, [])
        if not matches: return await query.message.reply_text(f"❌ Aaj {league} ke matches nahi hain.")
        kb = [[InlineKeyboardButton(f"{m[0]} vs {m[1]}", callback_data=f"M_{league}_{i}")] for i, m in enumerate(matches)]
        await query.message.reply_text("🏏 Match Select Karein:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('M_'):
        _, l, idx = data.split('_'); context.user_data.update({'l': l, 'idx': int(idx)})
        kb = [[InlineKeyboardButton("🪙 Toss", callback_data='T_TOSS'), InlineKeyboardButton("🏆 Winner", callback_data='T_WIN')]]
        await query.message.reply_text("Bet Type:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('T_'):
        b_type = data.split('_')[1]
        l, idx = context.user_data.get('l'), context.user_data.get('idx')
        if not is_betting_open(l, idx, b_type):
            return await query.message.reply_text(f"❌ Betting Closed! {b_type} bets band ho chuki hain.")
        context.user_data['b_type'] = b_type
        match = (IPL_SCHEDULE if l == 'IPL' else PSL_SCHEDULE).get(datetime.now(IST).strftime("%d-%m"))[idx]
        kb = [[InlineKeyboardButton(match[0], callback_data=f"TM_{match[0]}"), InlineKeyboardButton(match[1], callback_data=f"TM_{match[1]}")] ]
        await query.message.reply_text(f"Team Select Karein:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('TM_'):
        context.user_data['bet_team'] = data.split('_')[1]
        await query.message.reply_text(f"✅ Selected: {context.user_data['bet_team']}\nAmount likho (Min ₹50):")
        context.user_data['step'] = 'BET_FINAL'

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text and not update.message.photo: return
    uid, text = update.effective_user.id, update.message.text
    step = context.user_data.get('step')
# --- COLOR TRADING LOGIC (The Core Engine) ---
async def declare_color_result(app):
    """
    Ye function har 2 minute mein result announce karega.
    """
    # 1. Database se current period aur forced result (Admin fix) uthao
    state = game_state_col.find_one({"id": "current"})
    curr_p, forced = state['period'], state['forced_result']
    
    # 2. Saari 'Pending' bets nikaalo is period ki
    bets = list(color_bets_col.find({"period": curr_p, "status": "Pending"}))
    
    # 3. Paisa calculate karo (Risk Management)
    paisa = {"RED": 0, "GREEN": 0, "VIOLET": 0}
    for b in bets: 
        paisa[b['color']] += b['amt']

    # 4. Result Selection
    if forced:
        # Agar Admin ne /fix use kiya hai
        win_color = forced
        game_state_col.update_one({"id": "current"}, {"$set": {"forced_result": None}}) # Use ke baad reset
    else:
        # Profit Logic: Jitna kam paisa, utna Admin ka profit
        active_bets = [c for c in paisa if paisa[c] > 0]
        if active_bets:
            # Sabse kam paise wala color jitega
            win_color = min(paisa, key=paisa.get)
        else:
            # Agar koi bet nahi hai toh random
            win_color = random.choice(["RED", "GREEN"])

    # 5. Winners aur Losers ko settle karo
    for b in bets:
        uid, b_amt, b_color = b['user_id'], b['amt'], b['color']
        if b_color == win_color:
            w_amt = b_amt * 1.9  # 1.9x Return
            update_bal(uid, "User", w_amt)
            await app.bot.send_message(uid, f"🥳 *PERIOD WIN!*\n💰 Won: ₹{w_amt}\n🆔 Period: `{curr_p}`", parse_mode='Markdown')
        else:
            await app.bot.send_message(uid, f"😔 *PERIOD LOSS!*\n🆔 Period: `{curr_p}`\n🎨 Result: {win_color}", parse_mode='Markdown')

    # 6. Channel par result bhej do
    await app.bot.send_message(chat_id=CHANNEL_ID, text=f"🏆 *COLOR RESULT*\n🆔 Period: `{curr_p}`\n🎨 Winning Color: *{win_color}*", parse_mode='Markdown')
    
    # 7. Database cleanup and next period
    color_bets_col.update_many({"period": curr_p}, {"$set": {"status": "Completed"}})
    game_state_col.update_one({"id": "current"}, {"$inc": {"period": 1}})

async def fix_color(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args: return
    
    choice = context.args[0].upper()
    if choice in ["RED", "GREEN", "VIOLET"]:
        game_state_col.update_one({"id": "current"}, {"$set": {"forced_result": choice}})
        await update.message.reply_text(f"🎯 Agla result {choice} fix kar diya!")

    # ADMIN REPLY
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
            else:
                await context.bot.send_message(tid, f"💬 *Admin:* {text}")
                return await update.message.reply_text("Message Sent.")
        except: pass

    # USER STEPS
    if update.message.photo:
        for aid in ADMIN_IDS: await context.bot.send_photo(aid, update.message.photo[-1].file_id, caption=f"💰 *DEP SS*\nID: {uid}\nReply with +Amt")
        await update.message.reply_text("✅ Screenshot admin ko bhej diya gaya hai.")
        return

    if step == 'DEP' and text and text.isdigit():
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🛎 *DEP REQ*\nID: {uid}\nAmt: ₹{text}\nReply with QR photo.")
        await update.message.reply_text("⏳ Admin QR bhej raha hai, wait karein..."); context.user_data['step'] = None
    elif step == 'WIT' and text and text.isdigit():
        context.user_data.update({'w_amt': int(text), 'step': 'W_UPI'})
        await update.message.reply_text("🏦 Apna UPI ID bhejein:")
    elif step == 'W_UPI' and text:
        amt = context.user_data['w_amt']; update_bal(uid, "User", -amt)
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🏦 *WITHDRAW*\nID: {uid}\nAmt: ₹{amt}\nUPI: {text}")
        await update.message.reply_text("✅ Withdrawal request sent!"); context.user_data['step'] = None
    elif step == 'BET_FINAL' and text and text.isdigit():
        amt = int(text); u = get_user(uid)
        if amt < 50 or (not u or amt > u.get('balance', 0)): 
            return await update.message.reply_text("❌ Error: Balance kam hai ya amount galat hai!")
        update_bal(uid, "User", -amt)
        for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🎲 *NEW BET*\nID: {uid}\nTeam: {context.user_data['bet_team']}\nType: {context.user_data['b_type']}\nAmt: ₹{amt}")
        await update.message.reply_text(f"✅ Bet Placed on {context.user_data['bet_team']}!"); context.user_data['step'] = None

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    msg = " ".join(context.args)
    if not msg: return await update.message.reply_text("❌ `/broadcast [Message]`")
    for u in users_col.find():
        try: await context.bot.send_message(u['user_id'], f"📢 *BROADCAST*\n\n{msg}", parse_mode='Markdown')
        except: pass
    await update.message.reply_text("✅ Broadcast Sent.")

async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("❌ `/connect [Message]`")
    msg = " ".join(context.args)
    for aid in ADMIN_IDS: await context.bot.send_message(aid, f"🎧 *SUPPORT*\nID: {update.effective_user.id}\nMsg: {msg}")
    await update.message.reply_text("✅ Message Admin ko bhej diya gaya hai.")

def main():
    Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("connect", connect))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    logging.info("🚀 Bot is Polling...")
    app.run_polling(drop_pending_updates=True, stop_signals=None, close_loop=False)

if __name__ == '__main__':
    main()
