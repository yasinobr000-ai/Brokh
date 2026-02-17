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

# ================= CONFIG (إعدادات البوت والبيانات) =================
BOT_TOKEN = "8264292822:AAENs24FD6QHGu_bgEBn1CkE4ojN7zruA1Q"
MONGO_URI = "mongodb+srv://charbelnk111_db_user:Mano123mano@cluster0.2gzqkc8.mongodb.net/?appName=Cluster0"

DB_NAME = "Trading_System_V24_Final_Signal"
USERS_COL = "Authorized_Users"
WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"

# قائمة الـ 20 زوج فوركس
FOREX_PAIRS = {
    "EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD", "USD/JPY": "frxUSDJPY",
    "EUR/GBP": "frxEURGBP", "AUD/USD": "frxAUDUSD", "USD/CHF": "frxUSDCHF",
    "USD/CAD": "frxUSDCAD", "NZD/USD": "frxNZDUSD", "EUR/JPY": "frxEURJPY",
    "GBP/JPY": "frxGBPJPY", "EUR/AUD": "frxEURAUD", "GBP/AUD": "frxGBPAUD",
    "AUD/JPY": "frxAUDJPY", "EUR/CAD": "frxEURCAD", "GBP/CAD": "frxGBPCAD",
    "AUD/CAD": "frxAUDCAD", "EUR/NZD": "frxEURNZD", "AUD/NZD": "frxAUDNZD",
    "GBP/CHF": "frxGBPCHF", "Gold/USD": "frxXAUUSD"
}

# ================= DATABASE =================
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
users_col = db[USERS_COL]

# ================= FLASK ADMIN PANEL (نفس تصميمك) =================
app = Flask(__name__)
user_states = {} # لتخزين حالة كل مستخدم (الزوج الحالي، حالة التشغيل، آخر إشارة)

@app.route("/")
def admin_panel():
    users = list(users_col.find())
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Panel</title>
        <style>
            body { font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 20px; }
            .card { background: #1e293b; padding: 30px; border-radius: 15px; display: inline-block; width: 100%; max-width: 500px; }
            input, select { padding: 12px; margin: 5px; border-radius: 8px; border: 1px solid #334155; background: #0f172a; color: white; width: 85%; }
            button { padding: 12px 25px; background: #38bdf8; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; margin-top:10px; }
            table { width: 100%; margin-top: 30px; border-collapse: collapse; }
            th { background: #334155; padding: 12px; }
            td { padding: 12px; border-bottom: 1px solid #334155; }
            .del { color: #f87171; text-decoration: none; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>User Management</h2>
            <form action="/add" method="POST">
                <input name="email" placeholder="Email" required><br>
                <select name="days">
                    <option value="1">1 Day</option>
                    <option value="7">7 Days</option>
                    <option value="30">30 Days</option>
                    <option value="36500">Lifetime</option>
                </select><br>
                <button type="submit">Activate User</button>
            </form>
            <table>
                <tr><th>Email</th><th>Expiry</th><th>Action</th></tr>
                {% for u in users %}
                <tr><td>{{u.email}}</td><td>{{u.expiry}}</td><td><a href="/delete/{{u.email}}" class="del">Remove</a></td></tr>
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
    users_col.update_one({"email": email}, {"$set": {"expiry": expiry}}, upsert=True)
    return redirect("/")

@app.route("/delete/<email>")
def delete_user(email):
    users_col.delete_one({"email": email})
    return redirect("/")

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ================= TELEGRAM BOT (START & STOP & CHANGE PAIR) =================
bot = telebot.TeleBot(BOT_TOKEN)

def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("START 🚀", "STOP 🛑")
    markup.add("CHANGE PAIR 🔄")
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "📧 Please enter your email:")

@bot.message_handler(func=lambda m: "@" in m.text)
def handle_auth(message):
    email = message.text.strip().lower()
    user = users_col.find_one({"email": email})
    if user:
        user_states[message.chat.id] = {'running': False, 'pair': 'frxEURUSD', 'pair_name': 'EUR/USD', 'last_signal': ''}
        bot.send_message(message.chat.id, "✅ Access Granted!", reply_markup=main_keyboard())
    else:
        bot.send_message(message.chat.id, "❌ Not authorized.")

@bot.message_handler(func=lambda m: m.text == "START 🚀")
def bot_on(message):
    if message.chat.id in user_states:
        user_states[message.chat.id]['running'] = True
        bot.send_message(message.chat.id, f"🚀 Bot Started on {user_states[message.chat.id]['pair_name']}")
        threading.Thread(target=trading_loop, args=(message.chat.id,), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "STOP 🛑")
def bot_off(message):
    if message.chat.id in user_states:
        user_states[message.chat.id]['running'] = False
        bot.send_message(message.chat.id, "🛑 Bot Stopped.")

@bot.message_handler(func=lambda m: m.text == "CHANGE PAIR 🔄")
def pairs_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=3)
    btns = [types.InlineKeyboardButton(name, callback_data=f"set_{code}_{name}") for name, code in FOREX_PAIRS.items()]
    markup.add(*btns)
    bot.send_message(message.chat.id, "📊 Select Forex Pair:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def set_pair(call):
    _, code, name = call.data.split("_")
    user_states[call.message.chat.id].update({'pair': code, 'pair_name': name})
    bot.answer_callback_query(call.id, f"Pair: {name}")
    bot.edit_message_text(f"🎯 Current Pair: {name}", call.message.chat.id, call.message.message_id)

# ================== TRADING ANALYSIS (الاستراتيجية المتقدمة) ==================

def analyze_pair(chat_id):
    try:
        state = user_states[chat_id]
        ws = websocket.create_connection(WS_URL)
        # جلب 3000 تيك للتحليل
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 3000, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        
        ticks = res.get("history", {}).get("prices", [])
        if len(ticks) < 3000: return None, 0

        # 1. جلب مناطق S/R من 3000 تيك (كل 30 تيك شمعة = 100 شمعة)
        candles_sr = [{"high": max(ticks[i:i+30]), "low": min(ticks[i:i+30])} for i in range(0, 3000, 30)]
        df_sr = pd.DataFrame(candles_sr)
        support, resistance = df_sr['low'].min(), df_sr['high'].max()

        # 2. تحليل آخر 60 تيك (كل 5 تيك شمعة = 12 شمعة)
        recent_ticks = ticks[-60:]
        fast_candles = [{"close": recent_ticks[i:i+5][-1], "open": recent_ticks[i:i+5][0]} for i in range(0, 60, 5)]
        df_fast = pd.DataFrame(fast_candles)
        curr_price = ticks[-1]

        # 3. حساب 20 مؤشر (SMA, EMA, Price Action)
        signals = []
        for p in [2, 3, 4, 5]:
            ma = df_fast['close'].rolling(window=p).mean().iloc[-1]
            signals.append("BUY" if curr_price > ma else "SELL")
            ema = df_fast['close'].ewm(span=p).mean().iloc[-1]
            signals.append("BUY" if curr_price > ema else "SELL")
        
        for i in range(1, 13):
            signals.append("BUY" if df_fast['close'].iloc[-1] > df_fast['close'].iloc[-i] else "SELL")

        buy_count = signals.count("BUY")
        accuracy = int((max(buy_count, 20-buy_count)/20)*100)

        # 4. الشروط الصارمة
        last_30_min, last_30_max = min(ticks[-30:]), max(ticks[-30:])
        
        if accuracy >= 75:
            # السعر بعيد عن المناطق ولم يخترقها في آخر 30 تيك
            if last_30_max < resistance and last_30_min > support:
                if abs(curr_price - resistance) > 0.00005 and abs(curr_price - support) > 0.00005:
                    final_sig = "BUY 🟢 CALL" if buy_count > 10 else "SELL 🔴 PUT"
                    
                    # منع التكرار (ما يبعت SELL مرتين ورا بعض)
                    if final_sig != state['last_signal']:
                        return final_sig, accuracy
        return None, 0
    except:
        return None, 0

def trading_loop(chat_id):
    while user_states.get(chat_id, {}).get('running'):
        now = datetime.now()
        if now.second == 30:
            signal, accuracy = analyze_pair(chat_id)
            if signal:
                user_states[chat_id]['last_signal'] = signal
                msg = (f"Pair: {user_states[chat_id]['pair_name']}\n"
                       f"TIME FRAME: M1\n"
                       f"Signal: {signal}\n"
                       f"Accuracy: {accuracy}%\n"
                       f"Entry Time: {(datetime.now() + timedelta(minutes=1)).strftime('%H:%M')}")
                try: bot.send_message(chat_id, msg)
                except: pass
                
                time.sleep(70) # ينام 70 ثانية
                continue
        time.sleep(0.5)

# ================== RUN ==================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Khoury Trading Bot is Online...")
    bot.infinity_polling()
