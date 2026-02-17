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

# ================= CONFIG (التوكن الجديد) =================
BOT_TOKEN = "8264292822:AAHMvwWEWTru_muNl0Oq4lyvdDFoj-0u-B0"
MONGO_URI = "mongodb+srv://charbelnk111_db_user:Mano123mano@cluster0.2gzqkc8.mongodb.net/?appName=Cluster0"
WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"

client = MongoClient(MONGO_URI)
db = client["Trading_System_V24_Final_Signal"]
users_col = db["Authorized_Users"]

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# تخزين الحالات والـ Events للتحكم في الـ Threads
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

# ================= ADMIN PANEL (Life Time Included) =================
@app.route("/")
def admin_panel():
    users = list(users_col.find())
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>KhouryBot Admin</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px; }
            .container { background: #1e293b; padding: 30px; border-radius: 20px; display: inline-block; width: 100%; max-width: 850px; }
            h2 { color: #38bdf8; }
            input, select { padding: 12px; margin: 10px; border-radius: 10px; background: #0f172a; color: white; border: 1px solid #334155; }
            button { padding: 12px 30px; background: #0ea5e9; border: none; border-radius: 10px; color: white; font-weight: bold; cursor: pointer; }
            table { width: 100%; margin-top: 30px; border-collapse: collapse; background: #0f172a; }
            th, td { padding: 15px; border-bottom: 1px solid #1e293b; text-align: center; }
            th { color: #38bdf8; background: #334155; }
            .del-btn { color: #fb7185; text-decoration: none; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>User Access Management</h2>
            <form action="/add" method="POST">
                <input name="email" placeholder="User Email" required>
                <select name="days">
                    <option value="1">1 Day</option>
                    <option value="7">7 Days</option>
                    <option value="30" selected>30 Days</option>
                    <option value="36500">Life Time</option>
                </select>
                <button type="submit">Activate Account</button>
            </form>
            <table>
                <tr><th>Email</th><th>Expiry Date</th><th>Device ID</th><th>Action</th></tr>
                {% for u in users %}
                <tr>
                    <td>{{u.email}}</td>
                    <td style="color: #fcd34d;">{{u.expiry}}</td>
                    <td>{{ u.telegram_id if u.telegram_id else 'Not Linked' }}</td>
                    <td><a href="/delete/{{u.email}}" class="del-btn">Remove</a></td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
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

# ================= TRADING LOGIC =================
def analyze_logic(chat_id):
    state = user_states.get(chat_id)
    if not state: return None, 0
    try:
        ws = websocket.create_connection(WS_URL, timeout=10)
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 210, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        ticks = res.get("history", {}).get("prices", [])
        if len(ticks) < 210: return None, 0

        # تحليل 7 شمعات (كل شمعة 30 تيك)
        f_candles = [{"close": ticks[i:i+30][-1]} for i in range(0, 210, 30)]
        df = pd.DataFrame(f_candles)
        curr_p = ticks[-1]

        signals = []
        for p in [2, 3, 4, 5]:
            sma = df['close'].rolling(window=p).mean().iloc[-1]
            signals.append("BUY" if curr_p > sma else "SELL")
        
        buy_votes = signals.count("BUY")
        accuracy = int((max(buy_votes, 4 - buy_votes) / 4) * 100)
        
        if accuracy >= 75:
            final = "BUY 🟢 CALL" if buy_votes >= 3 else "SELL 🔴 PUT"
            if final != state['last_signal']:
                return final, accuracy
        return None, 0
    except: return None, 0

def trading_loop(chat_id, stop_event):
    while not stop_event.is_set():
        if chat_id not in user_states or not user_states[chat_id]['running']:
            break
        
        now = datetime.now()
        if now.second == 30:
            signal, acc = analyze_logic(chat_id)
            if signal and not stop_event.is_set():
                user_states[chat_id]['last_signal'] = signal
                entry_time = (now + timedelta(minutes=1)).strftime("%H:%M")
                msg = (f"🎯 *SIGNAL DETECTED*\n━━━━━━━━━━━━━━━\n"
                       f"Pair: `{user_states[chat_id]['pair_name']}`\n"
                       f"Direction: *{signal}*\n"
                       f"Accuracy: `{acc}%`\n"
                       f"Entry At: `{entry_time}`\n━━━━━━━━━━━━━━━")
                try: bot.send_message(chat_id, msg, parse_mode="Markdown")
                except: pass
                stop_event.wait(70) # تجنب التكرار في نفس الدقيقة
        
        stop_event.wait(0.5)

# ================= TELEGRAM HANDLERS =================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("START 🚀", "STOP 🛑")
    markup.add("CHANGE PAIR 🔄")
    return markup

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "👋 Welcome to Khoury Trading Bot.\n📧 Please enter your registered email:")

@bot.message_handler(func=lambda m: "@" in m.text)
def handle_auth(message):
    email = message.text.strip().lower()
    chat_id = message.chat.id
    user = users_col.find_one({"email": email})

    if not user:
        bot.send_message(chat_id, "❌ This email is not registered.")
        return

    if datetime.strptime(user["expiry"], "%Y-%m-%d") < datetime.now():
        bot.send_message(chat_id, "your subscription was stopped.contact khourybot for resubscribe")
        return

    stored_id = user.get("telegram_id")
    if stored_id is not None and stored_id != chat_id:
        bot.send_message(chat_id, "🚫 Email already linked to another device.")
    else:
        if stored_id is None:
            users_col.update_one({"email": email}, {"$set": {"telegram_id": chat_id}})
        
        user_states[chat_id] = {'running': False, 'pair': 'frxEURUSD', 'pair_name': 'EUR/USD', 'last_signal': '', 'email': email}
        bot.send_message(chat_id, "✅ Activated!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "START 🚀")
def start_bot(m):
    chat_id = m.chat.id
    if chat_id not in user_states: return

    user = users_col.find_one({"email": user_states[chat_id]['email']})
    if datetime.strptime(user["expiry"], "%Y-%m-%d") < datetime.now():
        bot.send_message(chat_id, "your subscription was stopped.contact khourybot for resubscribe")
        return

    # قتل أي Thread قديم فوراً قبل البدء
    if chat_id in user_threads_events:
        user_threads_events[chat_id].set()
        time.sleep(0.3)

    # إنشاء Event جديد وبدء الـ Loop
    stop_event = threading.Event()
    user_threads_events[chat_id] = stop_event
    user_states[chat_id]['running'] = True
    
    bot.send_message(chat_id, "Waiting for signals ⏳")
    threading.Thread(target=trading_loop, args=(chat_id, stop_event), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "STOP 🛑")
def stop_bot(m):
    chat_id = m.chat.id
    if chat_id in user_threads_events:
        user_threads_events[chat_id].set() # قتل الـ Thread وحذفه
        user_states[chat_id]['running'] = False
        bot.send_message(chat_id, "🛑 Bot has been stopped.")

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
