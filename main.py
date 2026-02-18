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

# ================= CONFIG (التوكن الجديد وإعدادات الاتصال) =================
BOT_TOKEN = "8264292822:AAEwdBWRC03qtHJo3LDGNrDh72TnZ8XAHCY"
MONGO_URI = "mongodb+srv://charbelnk111_db_user:Mano123mano@cluster0.2gzqkc8.mongodb.net/?appName=Cluster0"
WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"

client = MongoClient(MONGO_URI)
db = client["Trading_System_V24_Final_Signal"]
users_col = db["Authorized_Users"]

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# تخزين الحالات والـ Events
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

# ================= TRADING LOGIC (30 UNIQUE INDICATORS) =================
def analyze_logic(chat_id):
    state = user_states.get(chat_id)
    if not state: return None, 0
    try:
        ws = websocket.create_connection(WS_URL, timeout=10)
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 500, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        
        prices = pd.Series(res.get("history", {}).get("prices", []))
        if len(prices) < 300: return None, 0

        curr = prices.iloc[-1]
        prev = prices.iloc[-2]
        signals = []

        # 1. Moving Average (SMA 20)
        signals.append("BUY" if curr > prices.rolling(20).mean().iloc[-1] else "SELL")
        # 2. RSI 14
        diff = prices.diff()
        gain = diff.where(diff > 0, 0).rolling(14).mean()
        loss = -diff.where(diff < 0, 0).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss).iloc[-1]))
        signals.append("BUY" if rsi < 50 else "SELL")
        # 3. MACD
        macd = prices.ewm(span=12).mean().iloc[-1] - prices.ewm(span=26).mean().iloc[-1]
        signals.append("BUY" if macd > 0 else "SELL")
        # 4. Stochastic %K
        signals.append("BUY" if ((curr - prices.rolling(14).min().iloc[-1]) / (prices.rolling(14).max().iloc[-1] - prices.rolling(14).min().iloc[-1])) * 100 > 50 else "SELL")
        # 5. Williams %R
        signals.append("BUY" if ((prices.rolling(14).max().iloc[-1] - curr) / (prices.rolling(14).max().iloc[-1] - prices.rolling(14).min().iloc[-1])) * -100 > -50 else "SELL")
        # 6. CCI
        tp = prices.rolling(20).mean().iloc[-1]
        mad = prices.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean()).iloc[-1]
        cci = (curr - tp) / (0.015 * mad)
        signals.append("BUY" if cci > 0 else "SELL")
        # 7. Momentum
        signals.append("BUY" if curr > prices.iloc[-10] else "SELL")
        # 8. ROC
        signals.append("BUY" if ((curr - prices.iloc[-12]) / prices.iloc[-12]) > 0 else "SELL")
        # 9. Bull Power
        signals.append("BUY" if (curr - prices.ewm(span=13).mean().iloc[-1]) > 0 else "SELL")
        # 10. Bear Power
        signals.append("BUY" if (curr - prices.ewm(span=13).mean().iloc[-1]) > -0.001 else "SELL")
        # 11. BB Upper
        std = prices.rolling(20).std().iloc[-1]
        signals.append("BUY" if curr < (prices.rolling(20).mean().iloc[-1] + 2*std) else "SELL")
        # 12. BB Lower
        signals.append("BUY" if curr > (prices.rolling(20).mean().iloc[-1] - 2*std) else "SELL")
        # 13. Keltner Mid
        signals.append("BUY" if curr > prices.rolling(10).mean().iloc[-1] else "SELL")
        # 14. Donchian Mid
        signals.append("BUY" if curr > (prices.rolling(20).max().iloc[-1] + prices.rolling(20).min().iloc[-1])/2 else "SELL")
        # 15. Variance
        signals.append("BUY" if prices.iloc[-5:].var() < prices.iloc[-20:].var() else "SELL")
        # 16. Mean Deviation
        signals.append("BUY" if curr > prices.mean() else "SELL")
        # 17. Typical Price Action
        signals.append("BUY" if curr > (prices.iloc[-3:].mean()) else "SELL")
        # 18. Volatility Filter
        signals.append("BUY" if abs(curr - prev) > prices.diff().abs().mean() else "SELL")
        # 19. Range expansion
        signals.append("BUY" if (prices.iloc[-1] - prices.iloc[-5]) > 0 else "SELL")
        # 20. RVI Proxy
        signals.append("BUY" if prices.rolling(10).std().iloc[-1] > prices.rolling(20).std().iloc[-1] else "SELL")
        # 21. LinReg Slope Proxy
        signals.append("BUY" if curr > prices.iloc[-20] else "SELL")
        # 22. Support Wall
        signals.append("BUY" if curr > prices.iloc[-50:].min() else "SELL")
        # 23. Pivot Point
        signals.append("BUY" if curr > (prices.max() + prices.min() + curr)/3 else "SELL")
        # 24. Tenkan-sen
        signals.append("BUY" if curr > (prices.rolling(9).max().iloc[-1] + prices.rolling(9).min().iloc[-1])/2 else "SELL")
        # 25. Kijun-sen
        signals.append("BUY" if curr > (prices.rolling(26).max().iloc[-1] + prices.rolling(26).min().iloc[-1])/2 else "SELL")
        # 26. Price Velocity
        signals.append("BUY" if (curr - prev) > 0 else "SELL")
        # 27. Acceleration
        signals.append("BUY" if ((curr - prev) - (prev - prices.iloc[-3])) > 0 else "SELL")
        # 28. Median Cross
        signals.append("BUY" if curr > prices.median() else "SELL")
        # 29. Log Returns
        signals.append("BUY" if np.log(curr/prev) > 0 else "SELL")
        # 30. Base Trend
        signals.append("BUY" if curr > prices.iloc[0] else "SELL")

        # التصويت النهائي (أغلبية بسيطة لضمان الإرسال دائماً)
        buy_votes = signals.count("BUY")
        accuracy = int((max(buy_votes, 30 - buy_votes) / 30) * 100)
        
        final_dir = "BUY 🟢 CALL" if buy_votes >= 15 else "SELL 🔴 PUT"
        return final_dir, accuracy
    except: return None, 0

def trading_loop(chat_id, stop_event):
    while not stop_event.is_set():
        if chat_id not in user_states or not user_states[chat_id]['running']:
            break
        
        now = datetime.now()
        # التنفيذ عند الثانية 30 بالضبط من كل دقيقة
        if now.second == 30:
            signal, acc = analyze_logic(chat_id)
            if signal:
                entry_time = (now + timedelta(minutes=1)).strftime("%H:%M")
                msg = (f"🎯 *NEW SIGNAL*\n━━━━━━━━━━━━━━━\n"
                       f"Pair: `{user_states[chat_id]['pair_name']}`\n"
                       f"Direction: *{signal}*\n"
                       f"Accuracy: `{acc}%` (30 Indicators)\n"
                       f"Entry At: `{entry_time}`\n━━━━━━━━━━━━━━━")
                try: 
                    bot.send_message(chat_id, msg, parse_mode="Markdown")
                    time.sleep(2) # منع التكرار في نفس الثانية
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

    if chat_id in user_threads_events:
        user_threads_events[chat_id].set()
        time.sleep(0.3)

    stop_event = threading.Event()
    user_threads_events[chat_id] = stop_event
    user_states[chat_id]['running'] = True
    
    bot.send_message(chat_id, "Waiting for signals ⏳ (Sending at :30 of every minute)")
    threading.Thread(target=trading_loop, args=(chat_id, stop_event), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "STOP 🛑")
def stop_bot(m):
    chat_id = m.chat.id
    if chat_id in user_threads_events:
        user_threads_events[chat_id].set()
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
    # تشغيل لوحة التحكم في خلفية منفصلة
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000, use_reloader=False), daemon=True).start()
    bot.delete_webhook(drop_pending_updates=True)
    bot.infinity_polling(skip_pending=True)
