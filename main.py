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
BOT_TOKEN = "8264292822:AAGKp-QgNPizvqoFqdsnm58JrfLkL5v_ock"
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

# قائمة الـ 20 زوج فوركس المعتمدة مع بادئة frx
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
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px; }
            .container { background: #1e293b; padding: 30px; border-radius: 20px; display: inline-block; width: 100%; max-width: 700px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }
            h2 { color: #38bdf8; margin-bottom: 25px; }
            input, select { padding: 12px; margin: 10px 0; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: white; width: 90%; }
            button { padding: 12px 30px; background: #0ea5e9; border: none; border-radius: 10px; color: white; font-weight: bold; cursor: pointer; transition: 0.3s; }
            button:hover { background: #0284c7; }
            table { width: 100%; margin-top: 30px; border-collapse: collapse; background: #0f172a; border-radius: 10px; overflow: hidden; }
            th, td { padding: 15px; border-bottom: 1px solid #1e293b; text-align: center; }
            th { background: #334155; color: #38bdf8; }
            .del-btn { color: #fb7185; text-decoration: none; font-weight: bold; }
            .status-waiting { color: #94a3b8; font-style: italic; }
            .status-linked { color: #4ade80; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>User Access Management</h2>
            <form action="/add" method="POST">
                <input name="email" placeholder="Enter User Email" required><br>
                <select name="days">
                    <option value="1">1 Day Access</option>
                    <option value="7">7 Days Access</option>
                    <option value="30" selected>30 Days Access</option>
                    <option value="36500">Lifetime Access</option>
                </select><br>
                <button type="submit">Activate Account</button>
            </form>
            <table>
                <thead>
                    <tr><th>Email</th><th>Device ID</th><th>Action</th></tr>
                </thead>
                <tbody>
                    {% for u in users %}
                    <tr>
                        <td>{{u.email}}</td>
                        <td class="{{ 'status-linked' if u.telegram_id else 'status-waiting' }}">
                            {{ u.telegram_id if u.telegram_id else 'Not Linked Yet' }}
                        </td>
                        <td><a href="/delete/{{u.email}}" class="del-btn" onclick="return confirm('Are you sure?')">Remove</a></td>
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
    # إضافة المستخدم مع تصفير الـ ID لربطه بأول جهاز
    users_col.update_one({"email": email}, {"$set": {"expiry": expiry, "telegram_id": None}}, upsert=True)
    return redirect("/")

@app.route("/delete/<email>")
def delete_user(email):
    users_col.delete_one({"email": email})
    return redirect("/")

# ================= استراتيجية التحليل المتقدمة (20 مؤشر) =================

def analyze_logic(chat_id):
    state = user_states[chat_id]
    try:
        ws = websocket.create_connection(WS_URL)
        # 1. سحب 3000 تيك للتحليل التاريخي والدعم والمقاومة
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 3000, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        
        ticks = res.get("history", {}).get("prices", [])
        if len(ticks) < 3000: return None, 0

        # استخراج S/R (تحويل 3000 تيك لـ 100 شمعة، كل شمعة 30 تيك)
        candles_30 = [{"high": max(ticks[i:i+30]), "low": min(ticks[i:i+30])} for i in range(0, 3000, 30)]
        df_sr = pd.DataFrame(candles_30)
        support = df_sr['low'].min()
        resistance = df_sr['high'].max()

        # 2. تحليل المؤشرات الـ 20 (على آخر 60 تيك مقسمة لشموع 5 تيك)
        recent_60 = ticks[-60:]
        fast_candles = []
        for i in range(0, 60, 5):
            batch = recent_60[i:i+5]
            fast_candles.append({"close": batch[-1], "open": batch[0]})
        
        df_f = pd.DataFrame(fast_candles)
        current_price = ticks[-1]

        signals = []
        # SMA & EMA (8 مؤشرات)
        for period in [2, 3, 4, 5]:
            sma = df_f['close'].rolling(window=period).mean().iloc[-1]
            ema = df_f['close'].ewm(span=period).mean().iloc[-1]
            signals.append("BUY" if current_price > sma else "SELL")
            signals.append("BUY" if current_price > ema else "SELL")
        
        # Momentum & Price Action (12 مؤشر)
        for i in range(1, 13):
            signals.append("BUY" if fast_candles[-1]['close'] > fast_candles[-i]['close'] else "SELL")

        buy_votes = signals.count("BUY")
        accuracy = int((max(buy_votes, 20 - buy_votes) / 20) * 100)
        
        # 3. الفلاتر الصارمة (الدقة + مناطق الـ S/R)
        last_30_ticks = ticks[-30:]
        if accuracy >= 75:
            # التأكد أن السعر لم يلمس أو يخترق القمة والقاع في آخر 30 حركة
            if max(last_30_ticks) < resistance and min(last_30_ticks) > support:
                # هامش أمان بسيط
                if (resistance - current_price) > 0.00003 and (current_price - support) > 0.00003:
                    final_decision = "BUY 🟢 CALL" if buy_votes > 10 else "SELL 🔴 PUT"
                    # منع تكرار نفس الاتجاه مرتين متتاليتين
                    if final_decision != state['last_signal']:
                        return final_decision, accuracy
        return None, 0
    except Exception as e:
        print(f"Analysis Error: {e}")
        return None, 0

def trading_loop(chat_id):
    while user_states.get(chat_id, {}).get('running'):
        now = datetime.now()
        # يبحث عن إشارة في الثانية 30 بالضبط
        if now.second == 30:
            signal, acc = analyze_logic(chat_id)
            if signal:
                user_states[chat_id]['last_signal'] = signal
                entry_time = (now + timedelta(minutes=1)).strftime("%H:%M")
                msg = (f"🎯 *SIGNAL DETECTED*\n"
                       f"━━━━━━━━━━━━━━━\n"
                       f"Pair: `{user_states[chat_id]['pair_name']}`\n"
                       f"Direction: *{signal}*\n"
                       f"Timeframe: `M1`\n"
                       f"Accuracy: `{acc}%`\n"
                       f"Entry At: `{entry_time}`\n"
                       f"━━━━━━━━━━━━━━━")
                try:
                    bot.send_message(chat_id, msg, parse_mode="Markdown")
                except: pass
                # ينام 70 ثانية لانتهاء الصفقة والتحليل التالي
                time.sleep(70)
        time.sleep(0.5)

# ================= واجهة تليجرام (TELEGRAM INTERFACE) =================

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
        bot.send_message(chat_id, "❌ This email is not registered in our system.")
        return

    # فحص نظام قفل الجهاز (Device Lock Logic)
    stored_id = user.get("telegram_id")
    
    if stored_id is not None and stored_id != chat_id:
        bot.send_message(chat_id, "🚫 This email was already work on another phone. contact khourybot for subscription")
    else:
        # ربط الـ ID إذا كان أول مرة
        if stored_id is None:
            users_col.update_one({"email": email}, {"$set": {"telegram_id": chat_id}})
        
        user_states[chat_id] = {
            'running': False, 
            'pair': 'frxEURUSD', 
            'pair_name': 'EUR/USD', 
            'last_signal': ''
        }
        bot.send_message(chat_id, "✅ Activation Successful!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "START 🚀")
def start_bot(m):
    if m.chat.id in user_states:
        if user_states[m.chat.id]['running']:
            bot.send_message(m.chat.id, "⚠️ Bot is already running.")
            return
        user_states[m.chat.id]['running'] = True
        bot.send_message(m.chat.id, f"🚀 Analyzing {user_states[m.chat.id]['pair_name']}... waiting for second 30.")
        threading.Thread(target=trading_loop, args=(m.chat.id,), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "STOP 🛑")
def stop_bot(m):
    if m.chat.id in user_states:
        user_states[m.chat.id]['running'] = False
        bot.send_message(m.chat.id, "🛑 Bot has been stopped.")

@bot.message_handler(func=lambda m: m.text == "CHANGE PAIR 🔄")
def change_pair(m):
    markup = types.InlineKeyboardMarkup(row_width=3)
    btns = [types.InlineKeyboardButton(name, callback_data=f"sel_{code}_{name}") for name, code in FOREX_PAIRS.items()]
    markup.add(*btns)
    bot.send_message(m.chat.id, "📊 Choose a Forex pair from the list:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_"))
def handle_selection(call):
    _, code, name = call.data.split("_")
    chat_id = call.message.chat.id
    if chat_id in user_states:
        user_states[chat_id]['pair'] = code
        user_states[chat_id]['pair_name'] = name
        bot.answer_callback_query(call.id, f"Switched to {name}")
        bot.edit_message_text(f"🎯 Current Pair: *{name}*\nPress START to begin.", chat_id, call.message.message_id, parse_mode="Markdown")

# ================= التشغيل النهائي (RUN) =================
if __name__ == "__main__":
    # تشغيل Flask في خيط منفصل
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    print("Khoury Trading Bot is now Online...")
    bot.infinity_polling()
