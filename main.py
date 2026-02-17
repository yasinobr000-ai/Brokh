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

# ================= إعدادات النظام (CONFIG) =================
BOT_TOKEN = "8264292822:AAHPvQnMePiIRtUIAlfL2bwAN-SjRRtMPN8"
MONGO_URI = "mongodb+srv://charbelnk111_db_user:Mano123mano@cluster0.2gzqkc8.mongodb.net/?appName=Cluster0"
WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"

# ربط قاعدة البيانات
client = MongoClient(MONGO_URI)
db = client["Trading_System_V24_Final_Signal"]
users_col = db["Authorized_Users"]

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# تخزين حالة المستخدمين في الذاكرة
user_states = {} 

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

# ================= لوحة التحكم (ADMIN PANEL HTML) =================
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
            .container { background: #1e293b; padding: 30px; border-radius: 20px; display: inline-block; width: 100%; max-width: 850px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }
            h2 { color: #38bdf8; margin-bottom: 25px; }
            input, select { padding: 12px; margin: 10px 5px; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: white; width: 40%; }
            button { padding: 12px 30px; background: #0ea5e9; border: none; border-radius: 10px; color: white; font-weight: bold; cursor: pointer; }
            table { width: 100%; margin-top: 30px; border-collapse: collapse; background: #0f172a; border-radius: 10px; overflow: hidden; }
            th, td { padding: 15px; border-bottom: 1px solid #1e293b; text-align: center; }
            th { background: #334155; color: #38bdf8; }
            .del-btn { color: #fb7185; text-decoration: none; font-weight: bold; }
            .status-linked { color: #4ade80; font-weight: bold; }
            .status-waiting { color: #94a3b8; font-style: italic; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>User Management System</h2>
            <form action="/add" method="POST">
                <input name="email" placeholder="User Email" required>
                <select name="days">
                    <option value="1">1 Day</option>
                    <option value="7">7 Days</option>
                    <option value="30" selected>30 Days</option>
                    <option value="36500">life time</option>
                </select><br>
                <button type="submit">Activate Account</button>
            </form>
            <table>
                <thead>
                    <tr>
                        <th>Email</th>
                        <th>Expiry Date</th>
                        <th>Device ID</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for u in users %}
                    <tr>
                        <td>{{u.email}}</td>
                        <td style="color: #fcd34d;">{{u.expiry}}</td>
                        <td class="{{ 'status-linked' if u.telegram_id else 'status-waiting' }}">
                            {{ u.telegram_id if u.telegram_id else 'Not Linked' }}
                        </td>
                        <td><a href="/delete/{{u.email}}" class="del-btn" onclick="return confirm('Delete this user?')">Remove</a></td>
                    </tr>
                    {% endfor %}
                </tbody>
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

# ================= استراتيجية التحليل (Logic) =================

def analyze_logic(chat_id):
    state = user_states.get(chat_id)
    if not state: return None, 0
    try:
        ws = websocket.create_connection(WS_URL)
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 3000, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        
        ticks = res.get("history", {}).get("prices", [])
        if len(ticks) < 3000: return None, 0

        candles_30 = [{"high": max(ticks[i:i+30]), "low": min(ticks[i:i+30])} for i in range(0, 3000, 30)]
        df_sr = pd.DataFrame(candles_30)
        support, resistance = df_sr['low'].min(), df_sr['high'].max()

        recent_60 = ticks[-60:]
        f_candles = [{"close": recent_60[i:i+5][-1]} for i in range(0, 60, 5)]
        df_f = pd.DataFrame(f_candles)
        curr_p = ticks[-1]

        signals = []
        for p in [2, 3, 4, 5]:
            sma = df_f['close'].rolling(window=p).mean().iloc[-1]
            signals.append("BUY" if curr_p > sma else "SELL")
        
        for i in range(1, 13):
            signals.append("BUY" if f_candles[-1]['close'] > f_candles[-i]['close'] else "SELL")

        buy_votes = signals.count("BUY")
        accuracy = int((max(buy_votes, 20 - buy_votes) / 20) * 100)
        
        if accuracy >= 75:
            if max(ticks[-30:]) < resistance and min(ticks[-30:]) > support:
                final = "BUY 🟢 CALL" if buy_votes > 10 else "SELL 🔴 PUT"
                if final != state['last_signal']:
                    return final, accuracy
        return None, 0
    except: return None, 0

def trading_loop(chat_id):
    # تشغيل Loop واحد فقط يعتمد على حالة running اللحظية
    while chat_id in user_states and user_states[chat_id].get('running'):
        now = datetime.now()
        if now.second == 30:
            signal, acc = analyze_logic(chat_id)
            if signal and user_states.get(chat_id, {}).get('running'):
                user_states[chat_id]['last_signal'] = signal
                entry_time = (now + timedelta(minutes=1)).strftime("%H:%M")
                msg = (f"🎯 *SIGNAL DETECTED*\n━━━━━━━━━━━━━━━\n"
                       f"Pair: `{user_states[chat_id]['pair_name']}`\n"
                       f"Direction: *{signal}*\n"
                       f"Accuracy: `{acc}%`\n"
                       f"Entry At: `{entry_time}`\n━━━━━━━━━━━━━━━")
                try: bot.send_message(chat_id, msg, parse_mode="Markdown")
                except: pass
                time.sleep(70)
        time.sleep(0.5)

# ================= واجهة تليجرام (Handlers) =================

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

    # فحص الصلاحية
    if datetime.strptime(user["expiry"], "%Y-%m-%d") < datetime.now():
        bot.send_message(chat_id, "your subscription was stopped.contact khourybot for resubscribe")
        return

    # قفل الجهاز
    stored_id = user.get("telegram_id")
    if stored_id is not None and stored_id != chat_id:
        bot.send_message(chat_id, "🚫 This email was already work on another phone. contact khourybot for subscription")
    else:
        if stored_id is None:
            users_col.update_one({"email": email}, {"$set": {"telegram_id": chat_id}})
        
        user_states[chat_id] = {'running': False, 'pair': 'frxEURUSD', 'pair_name': 'EUR/USD', 'last_signal': '', 'email': email}
        bot.send_message(chat_id, "✅ Activation Successful!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "START 🚀")
def start_bot(m):
    chat_id = m.chat.id
    if chat_id not in user_states: return

    # فحص الصلاحية عند كل محاولة تشغيل
    user = users_col.find_one({"email": user_states[chat_id]['email']})
    if datetime.strptime(user["expiry"], "%Y-%m-%d") < datetime.now():
        bot.send_message(chat_id, "your subscription was stopped.contact khourybot for resubscribe")
        return

    if user_states[chat_id]['running']:
        bot.send_message(chat_id, "⚠️ Bot is already running.")
        return
    
    user_states[chat_id]['running'] = True
    bot.send_message(chat_id, "Waiting for signals ⏳")
    threading.Thread(target=trading_loop, args=(chat_id,), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "STOP 🛑")
def stop_bot(m):
    chat_id = m.chat.id
    if chat_id in user_states and user_states[chat_id]['running']:
        user_states[chat_id]['running'] = False
        bot.send_message(chat_id, "🛑 Bot has been stopped.")

@bot.message_handler(func=lambda m: m.text == "CHANGE PAIR 🔄")
def change_pair(m):
    markup = types.InlineKeyboardMarkup(row_width=3)
    btns = [types.InlineKeyboardButton(name, callback_data=f"sel_{code}_{name}") for name, code in FOREX_PAIRS.items()]
    markup.add(*btns)
    bot.send_message(m.chat.id, "📊 Select Forex Pair:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_"))
def handle_selection(call):
    _, code, name = call.data.split("_")
    chat_id = call.message.chat.id
    if chat_id in user_states:
        user_states[chat_id].update({'pair': code, 'pair_name': name})
        bot.edit_message_text(f"🎯 Current Pair: *{name}*", chat_id, call.message.message_id, parse_mode="Markdown")

# ================= التشغيل (RUN) =================
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    print("Khoury Trading Bot is now Online...")
    bot.infinity_polling()
