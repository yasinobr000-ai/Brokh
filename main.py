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
BOT_TOKEN = "8264292822:AAEpUhtlH2cZVpNbCDdR50B6F7DNLUxZSSQ"
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
    "EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD", "USD/JPY": "frxUSDJPY",
    "EUR/GBP": "frxEURGBP", "AUD/USD": "frxAUDUSD", "USD/CHF": "frxUSDCHF",
    "USD/CAD": "frxUSDCAD", "NZD/USD": "frxNZDUSD", "EUR/JPY": "frxEURJPY",
    "GBP/JPY": "frxGBPJPY", "EUR/AUD": "frxEURAUD", "GBP/AUD": "frxGBPAUD",
    "AUD/JPY": "frxAUDJPY", "EUR/CAD": "frxEURCAD", "GBP/CAD": "frxGBPCAD",
    "AUD/CAD": "frxAUDCAD", "EUR/NZD": "frxEURNZD", "AUD/NZD": "frxAUDNZD",
    "GBP/CHF": "frxGBPCHF", "Gold/USD": "frxXAUUSD"
}

# ================= ADMIN PANEL =================
@app.route("/")
def admin_panel():
    users = list(users_col.find())
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head><title>KhouryBot Admin</title><style>
    body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px; }
    .container { background: #1e293b; padding: 30px; border-radius: 20px; display: inline-block; width: 100%; max-width: 850px; }
    table { width: 100%; margin-top: 30px; border-collapse: collapse; background: #0f172a; }
    th, td { padding: 15px; border-bottom: 1px solid #1e293b; text-align: center; }
    button { padding: 10px 20px; background: #0ea5e9; border: none; color: white; border-radius: 5px; cursor: pointer; }
    </style></head>
    <body><div class="container"><h2>User Access Management</h2>
    <form action="/add" method="POST"><input name="email" placeholder="User Email" required>
    <select name="days"><option value="30">30 Days</option><option value="36500">Life Time</option></select>
    <button type="submit">Activate</button></form>
    <table><tr><th>Email</th><th>Expiry</th><th>Action</th></tr>
    {% for u in users %}<tr><td>{{u.email}}</td><td>{{u.expiry}}</td><td><a href="/delete/{{u.email}}">Remove</a></td></tr>{% endfor %}
    </table></div></body></html>
    """, users=users)

@app.route("/add", methods=["POST"])
def add_user():
    email = request.form.get("email").strip().lower()
    days = int(request.form.get("days", 30))
    expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    users_col.update_one({"email": email}, {"$set": {"expiry": expiry, "telegram_id": None}}, upsert=True)
    return redirect("/")

@app.route("/delete/<email>")
def delete_user(email):
    users_col.delete_one({"email": email})
    return redirect("/")

# ================= TRADING LOGIC (30 INDICATORS / 1 CANDLE = 15 TICKS) =================
def analyze_logic(chat_id):
    state = user_states.get(chat_id)
    if not state: return None, 0
    try:
        ws = websocket.create_connection(WS_URL, timeout=10)
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 750, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        
        ticks = res.get("history", {}).get("prices", [])
        if len(ticks) < 450: return None, 0

        candle_data = [ticks[i:i+15][-1] for i in range(0, len(ticks), 15)]
        prices = pd.Series(candle_data)
        
        curr = prices.iloc[-1]
        prev = prices.iloc[-2]
        signals = []

        # --- 30 المؤشرات ---
        signals.append("BUY" if curr > prices.rolling(10).mean().iloc[-1] else "SELL")
        diff = prices.diff()
        gain = diff.where(diff > 0, 0).rolling(7).mean()
        loss = -diff.where(diff < 0, 0).rolling(7).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 0.0000001)).iloc[-1]))
        signals.append("BUY" if rsi < 50 else "SELL")
        macd = prices.ewm(span=12).mean().iloc[-1] - prices.ewm(span=26).mean().iloc[-1]
        signals.append("BUY" if macd > 0 else "SELL")
        l_min, h_max = prices.rolling(10).min().iloc[-1], prices.rolling(10).max().iloc[-1]
        signals.append("BUY" if ((curr - l_min) / (h_max - l_min + 0.0000001)) * 100 > 50 else "SELL")
        signals.append("BUY" if ((h_max - curr) / (h_max - l_min + 0.0000001)) * -100 > -50 else "SELL")
        tp = prices.rolling(10).mean().iloc[-1]
        mad = prices.rolling(10).apply(lambda x: np.abs(x - x.mean()).mean()).iloc[-1]
        signals.append("BUY" if ((curr - tp) / (0.015 * mad + 0.0000001)) > 0 else "SELL")
        signals.append("BUY" if curr > prices.iloc[-5] else "SELL")
        signals.append("BUY" if ((curr - prices.iloc[-8]) / prices.iloc[-8]) > 0 else "SELL")
        signals.append("BUY" if (curr - prices.ewm(span=13).mean().iloc[-1]) > 0 else "SELL")
        signals.append("BUY" if (curr - prev) > 0 else "SELL")
        ma_bb, std_bb = prices.rolling(10).mean().iloc[-1], prices.rolling(10).std().iloc[-1]
        signals.append("BUY" if curr < (ma_bb + std_bb) else "SELL") 
        signals.append("BUY" if curr > (ma_bb - std_bb) else "SELL")
        signals.append("BUY" if curr > prices.rolling(5).mean().iloc[-1] else "SELL")
        signals.append("BUY" if curr > (prices.rolling(10).max().iloc[-1] + prices.rolling(10).min().iloc[-1])/2 else "SELL")
        signals.append("BUY" if prices.iloc[-5:].var() < prices.iloc[-15:].var() else "SELL")
        signals.append("BUY" if curr > prices.mean() else "SELL")
        signals.append("BUY" if curr > prices.iloc[-3:].mean() else "SELL")
        signals.append("BUY" if abs(curr - prev) > prices.diff().abs().mean() else "SELL")
        signals.append("BUY" if (prices.iloc[-1] - prices.iloc[-4]) > 0 else "SELL")
        signals.append("BUY" if prices.rolling(5).std().iloc[-1] > prices.rolling(10).std().iloc[-1] else "SELL")
        signals.append("BUY" if curr > prices.iloc[-10] else "SELL")
        signals.append("BUY" if curr > prices.min() else "SELL")
        signals.append("BUY" if curr > (prices.max() + prices.min() + curr)/3 else "SELL")
        signals.append("BUY" if curr > (prices.rolling(9).max().iloc[-1] + prices.rolling(9).min().iloc[-1])/2 else "SELL")
        signals.append("BUY" if curr > (prices.rolling(14).max().iloc[-1] + prices.rolling(14).min().iloc[-1])/2 else "SELL")
        signals.append("BUY" if (curr - prev) > 0 else "SELL")
        signals.append("BUY" if ((curr - prev) - (prev - prices.iloc[-3])) > 0 else "SELL")
        signals.append("BUY" if curr > prices.median() else "SELL")
        signals.append("BUY" if np.log(curr / (prev + 0.0000001)) >= 0 else "SELL")
        signals.append("BUY" if curr > prices.iloc[0] else "SELL")

        buy_votes = signals.count("BUY")
        accuracy = int((max(buy_votes, 30 - buy_votes) / 30) * 100)
        
        # فلتر الدقة 70% (21 مؤشر من أصل 30)
        if accuracy >= 70:
            final_dir = "BUY 🟢 CALL" if buy_votes > 15 else "SELL 🔴 PUT"
            return final_dir, accuracy
        
        return None, 0
    except: return None, 0

def trading_loop(chat_id, stop_event):
    while not stop_event.is_set():
        if chat_id not in user_states or not user_states[chat_id]['running']: break
        
        now = datetime.now()
        if now.second == 30:
            signal, acc = analyze_logic(chat_id)
            if signal:
                entry_time = (now + timedelta(minutes=1)).strftime("%H:%M")
                msg = (f"🎯 *NEW SIGNAL*\n━━━━━━━━━━━━━━━\n"
                       f"Pair: `{user_states[chat_id]['pair_name']}`\n"
                       f"Direction: *{signal}*\n"
                       f"Accuracy: `{acc}%` 🔥\n"
                       f"Candle: `15 Ticks`\n"
                       f"Entry At: `{entry_time}`\n━━━━━━━━━━━━━━━")
                try: 
                    bot.send_message(chat_id, msg, parse_mode="Markdown")
                    time.sleep(70) # ينام 70 ثانية بعد الإرسال
                except: pass
        
        stop_event.wait(0.5)

# ================= TELEGRAM HANDLERS =================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("START 🚀", "STOP 🛑")
    markup.add("CHANGE PAIR 🔄")
    return markup

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "👋 Welcome. Enter your email:")

@bot.message_handler(func=lambda m: "@" in m.text)
def handle_auth(message):
    email, chat_id = message.text.strip().lower(), message.chat.id
    user = users_col.find_one({"email": email})
    if not user:
        bot.send_message(chat_id, "❌ Not registered.")
        return
    users_col.update_one({"email": email}, {"$set": {"telegram_id": chat_id}})
    user_states[chat_id] = {'running': False, 'pair': 'frxEURUSD', 'pair_name': 'EUR/USD', 'email': email}
    bot.send_message(chat_id, "✅ Activated!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "START 🚀")
def start_bot(m):
    chat_id = m.chat.id
    if chat_id not in user_states: return
    if chat_id in user_threads_events: user_threads_events[chat_id].set()
    stop_event = threading.Event()
    user_threads_events[chat_id] = stop_event
    user_states[chat_id]['running'] = True
    bot.send_message(chat_id, "🚀 Running! (Accuracy Filter: 70%+ | Sleep: 70s)")
    threading.Thread(target=trading_loop, args=(chat_id, stop_event), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "STOP 🛑")
def stop_bot(m):
    chat_id = m.chat.id
    if chat_id in user_threads_events:
        user_threads_events[chat_id].set()
        user_states[chat_id]['running'] = False
        bot.send_message(chat_id, "🛑 Stopped.")

@bot.message_handler(func=lambda m: m.text == "CHANGE PAIR 🔄")
def change_pair(m):
    markup = types.InlineKeyboardMarkup(row_width=3)
    btns = [types.InlineKeyboardButton(name, callback_data=f"sel_{code}_{name}") for name, code in FOREX_PAIRS.items()]
    markup.add(*btns)
    bot.send_message(m.chat.id, "📊 Choose Pair:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_"))
def handle_selection(call):
    _, code, name = call.data.split("_")
    chat_id = call.message.chat.id
    if chat_id in user_states:
        user_states[chat_id].update({'pair': code, 'pair_name': name})
        bot.edit_message_text(f"🎯 Current: *{name}*", chat_id, call.message.message_id, parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    bot.delete_webhook(drop_pending_updates=True)
    bot.infinity_polling(skip_pending=True)
