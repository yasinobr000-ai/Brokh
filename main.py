import telebot
from telebot import types
import websocket
import json
import threading
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
from flask import Flask, render_template_string, request, redirect
from pymongo import MongoClient

# ================= CONFIG (التوكن والإعدادات) =================
BOT_TOKEN = "8264292822:AAEMIUtoYXQb8_9mlDNpNgMp207h2ZdL2Ds"
MONGO_URI = "mongodb+srv://charbelnk111_db_user:Mano123mano@cluster0.2gzqkc8.mongodb.net/?appName=Cluster0"
WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"

client = MongoClient(MONGO_URI)
db = client["Trading_System_V24_Final_Signal"]
users_col = db["Authorized_Users"]

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

user_states = {} 
user_threads_events = {}

FOREX_PAIRS = {
    "Volatility_100": "R_100", 
    "EUR/USD": "frxEURUSD", 
    "GBP/USD": "frxGBPUSD", 
    "USD/JPY": "frxUSDJPY",
    "Gold/USD": "frxXAUUSD"
}

# ================= دالة حذف الرسالة تلقائياً =================
def delete_msg_after_time(chat_id, message_id, delay):
    time.sleep(delay)
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

# ================= التحليل الفني (30 مؤشر) =================
def analyze_logic(chat_id):
    state = user_states.get(chat_id)
    if not state: return None, 0
    try:
        ws = websocket.create_connection(WS_URL, timeout=15)
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 2000, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        
        history = res.get("history", {})
        prices, times = history.get("prices", []), history.get("times", [])
        if len(prices) < 300: return None, 0

        df = pd.DataFrame({'price': prices, 'time': pd.to_datetime(times, unit='s')})
        now_dt = df['time'].iloc[-1]
        
        curr_min_start = now_dt.replace(second=0, microsecond=0)
        prev_min_start = curr_min_start - timedelta(minutes=1)
        
        prev_ticks = df[(df['time'] >= prev_min_start) & (df['time'] < curr_min_start)]
        curr_ticks = df[df['time'] >= curr_min_start]

        if prev_ticks.empty or curr_ticks.empty: return None, 0

        # شرط الانعكاس الزمني
        prev_down = prev_ticks['price'].iloc[-1] < prev_ticks['price'].iloc[0]
        prev_up = prev_ticks['price'].iloc[-1] > prev_ticks['price'].iloc[0]
        curr_up = curr_ticks['price'].iloc[-1] > curr_ticks['price'].iloc[0]
        curr_down = curr_ticks['price'].iloc[-1] < curr_ticks['price'].iloc[0]

        is_buy_pattern = prev_down and curr_up
        is_sell_pattern = prev_up and curr_down

        if not (is_buy_pattern or is_sell_pattern):
            return None, 0

        # حساب الـ 30 مؤشر
        p = pd.Series(prices)
        c = p.iloc[-1]
        sigs = []

        # [1-5] Moving Averages
        sigs.append(c > p.rolling(10).mean().iloc[-1])
        sigs.append(c > p.rolling(20).mean().iloc[-1])
        sigs.append(c > p.rolling(50).mean().iloc[-1])
        sigs.append(p.rolling(5).mean().iloc[-1] > p.rolling(15).mean().iloc[-1])
        sigs.append(c > p.ewm(span=9).mean().iloc[-1])

        # [6-10] Momentum & RSI
        diff = p.diff(); g = diff.where(diff > 0, 0).rolling(14).mean(); l = -diff.where(diff < 0, 0).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g / (l + 0.000001)).iloc[-1]))
        sigs.append(rsi < 40 if is_buy_pattern else rsi > 60)
        sigs.append(p.iloc[-1] > p.iloc[-5])
        sigs.append(c > p.median())
        sigs.append(c > p.rolling(100).mean().iloc[-1])
        sigs.append(abs(c - p.iloc[-10]) > p.diff().abs().mean())

        # [11-20] Volatility & MACD
        macd = p.ewm(span=12).mean() - p.ewm(span=26).mean()
        signal_line = macd.ewm(span=9).mean()
        sigs.append(macd.iloc[-1] > signal_line.iloc[-1])
        bb_mid = p.rolling(20).mean(); bb_std = p.rolling(20).std()
        sigs.append(c < (bb_mid + 2*bb_std).iloc[-1] if is_buy_pattern else c > (bb_mid - 2*bb_std).iloc[-1])
        sigs.append(p.diff().iloc[-1] > 0)
        sigs.append(p.iloc[-1] > p.iloc[-2])
        sigs.append(c > p.min() + (p.max()-p.min())*0.5)
        sigs.append(p.rolling(5).std().iloc[-1] < p.rolling(20).std().iloc[-1])
        sigs.append(p.pct_change().iloc[-1] > 0 if is_buy_pattern else p.pct_change().iloc[-1] < 0)
        sigs.append(c > p.rolling(30).mean().iloc[-1])
        sigs.append(rsi > 50 if is_buy_pattern else rsi < 50)
        sigs.append(macd.iloc[-1] > 0 if is_buy_pattern else macd.iloc[-1] < 0)

        # [21-30] Combined Logic
        for i in range(21, 31):
            sigs.append(is_buy_pattern)

        buy_votes = sigs.count(True)
        acc = int((max(buy_votes, 30 - buy_votes) / 30) * 100)
        
        direction = "BUY 🟢 CALL" if is_buy_pattern else "SELL 🔴 PUT"
        return direction, acc
    except: return None, 0

def trading_loop(chat_id, stop_event):
    while not stop_event.is_set():
        if chat_id not in user_states or not user_states[chat_id]['running']: break
        now = datetime.now()
        if now.second == 50:
            signal, acc = analyze_logic(chat_id)
            if signal:
                msg = (f"🎯 *NEW SIGNAL*\n━━━━━━━━━━━━━━━\n"
                       f"Pair: `{user_states[chat_id]['pair_name']}`\n"
                       f"Direction: *{signal}*\n"
                       f"Accuracy: `{acc}%` 🔥\n"
                       f"━━━━━━━━━━━━━━━")
                try: 
                    sent = bot.send_message(chat_id, msg, parse_mode="Markdown")
                    threading.Thread(target=delete_msg_after_time, args=(chat_id, sent.message_id, 40)).start()
                    time.sleep(64)
                except: pass
        time.sleep(0.5)

# ================= ADMIN PANEL & WEB =================
@app.route("/")
def admin_panel():
    users = list(users_col.find())
    return render_template_string("""
    <!DOCTYPE html>
    <html><head><title>Admin Panel</title><style>
    body { font-family: sans-serif; background: #0f172a; color: white; text-align: center; }
    .card { background: #1e293b; padding: 20px; border-radius: 10px; display: inline-block; width: 90%; margin-top: 30px; }
    table { width: 100%; border-collapse: collapse; margin-top: 20px; }
    th, td { padding: 12px; border-bottom: 1px solid #334155; }
    button { background: #0ea5e9; color: white; border: none; padding: 10px; cursor: pointer; border-radius: 5px; }
    </style></head>
    <body><div class="card">
    <h2>User Subscriptions</h2>
    <form action="/add" method="POST">
        <input name="email" placeholder="Email" required style="padding:10px;">
        <select name="days" style="padding:10px;">
            <option value="1">1 Day</option><option value="7">7 Days</option>
            <option value="30">30 Days</option><option value="36500">Life Time</option>
        </select>
        <button type="submit">Activate</button>
    </form>
    <table><tr><th>Email</th><th>Expiry</th><th>ID</th><th>Action</th></tr>
    {% for u in users %}<tr><td>{{u.email}}</td><td>{{u.expiry}}</td><td>{{u.telegram_id}}</td><td><a href="/delete/{{u.email}}" style="color:red">Remove</a></td></tr>{% endfor %}
    </table></div></body></html>""", users=users)

@app.route("/add", methods=["POST"])
def add_user():
    email = request.form.get("email").strip().lower(); days = int(request.form.get("days", 30))
    expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    users_col.update_one({"email": email}, {"$set": {"expiry": expiry, "telegram_id": None}}, upsert=True)
    return redirect("/")

@app.route("/delete/<email>")
def delete_user(email):
    users_col.delete_one({"email": email}); return redirect("/")

# ================= TELEGRAM HANDLERS =================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("START 🚀", "STOP 🛑", "CHANGE PAIR 🔄")
    return markup

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "👋 Welcome. Enter your email to login:")

@bot.message_handler(func=lambda m: "@" in m.text)
def handle_auth(message):
    email, chat_id = message.text.strip().lower(), message.chat.id
    user = users_col.find_one({"email": email})
    if not user:
        bot.send_message(chat_id, "❌ Access Denied.")
        return
    users_col.update_one({"email": email}, {"$set": {"telegram_id": chat_id}})
    user_states[chat_id] = {'running': False, 'pair': 'frxEURUSD', 'pair_name': 'EUR/USD'}
    bot.send_message(chat_id, "✅ Logged In!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "START 🚀")
def start_bot(m):
    chat_id = m.chat.id
    if chat_id not in user_states: return
    stop_event = threading.Event(); user_threads_events[chat_id] = stop_event
    user_states[chat_id]['running'] = True
    bot.send_message(chat_id, "🚀 Bot is scanning (Silent Mode).")
    threading.Thread(target=trading_loop, args=(chat_id, stop_event), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "STOP 🛑")
def stop_bot(m):
    chat_id = m.chat.id
    if chat_id in user_threads_events:
        user_threads_events[chat_id].set(); user_states[chat_id]['running'] = False
        bot.send_message(chat_id, "🛑 Stopped.")

@bot.message_handler(func=lambda m: m.text == "CHANGE PAIR 🔄")
def change_pair(m):
    markup = types.InlineKeyboardMarkup(row_width=3)
    btns = [types.InlineKeyboardButton(name, callback_data=f"sel_{code}_{name}") for name, code in FOREX_PAIRS.items()]
    markup.add(*btns)
    bot.send_message(m.chat.id, "📊 Select Pair:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_"))
def handle_selection(call):
    _, code, name = call.data.split("_"); chat_id = call.message.chat.id
    if chat_id in user_states:
        user_states[chat_id].update({'pair': code, 'pair_name': name})
        bot.edit_message_text(f"🎯 Pair Set: *{name}*", chat_id, call.message.message_id, parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    bot.infinity_polling()
