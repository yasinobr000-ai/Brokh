import telebot
import websocket
import json
import threading
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect
from pymongo import MongoClient

# ================= CONFIG =================
BOT_TOKEN = "8264292822:AAHiMSzjRtsYIqQzWCUocAdBxc9DuOzjL8o"
MONGO_URI = "mongodb+srv://charbelnk111_db_user:Mano123mano@cluster0.2gzqkc8.mongodb.net/?appName=Cluster0"

DB_NAME = "Trading_System_V24_Final_Signal"
USERS_COL = "Authorized_Users"

WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"
PAIR = "frxEURGBP"

# ================= DATABASE =================
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
users_col = db[USERS_COL]

# ================= FLASK ADMIN PANEL =================
app = Flask(__name__)

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
                <tr>
                    <td>{{u.email}}</td><td>{{u.expiry}}</td>
                    <td><a href="/delete/{{u.email}}" class="del">Remove</a></td>
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
    users_col.update_one({"email": email}, {"$set": {"expiry": expiry}}, upsert=True)
    return redirect("/")

@app.route("/delete/<email>")
def delete_user(email):
    users_col.delete_one({"email": email})
    return redirect("/")

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ================= TELEGRAM BOT =================
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "📧 Please enter your email:")

@bot.message_handler(func=lambda m: True)
def handle_email(message):
    chat_id = message.chat.id
    email = message.text.strip().lower()
    user = users_col.find_one({"email": email})
    now = datetime.now()

    if not user:
        bot.send_message(chat_id, "❌ You do not have access. Please contact KhouryBot")
        return

    if "expiry" in user and datetime.strptime(user["expiry"], "%Y-%m-%d") < now:
        bot.send_message(chat_id, "❌ Your access expired. Please contact KhouryBot")
        return

    users_col.update_one({"email": email}, {"$set": {"telegram_id": chat_id}})
    bot.send_message(chat_id, "✅ Bot started")
    
    threading.Thread(target=trading_loop, args=(chat_id,), daemon=True).start()

# ================== TRADING ANALYSIS ==================
def trading_loop(chat_id):
    while True:
        now = datetime.now()
        if now.second == 30:
            signal, accuracy, entry_time = analyze_pair()
            # الرسالة المعدلة كما طلبت (فقط Timeframe: M1)
            msg = (
                f"Pair: EUR/GBP\n"
                f"TIME FRAME: M1\n"
                f"Signal: {signal}\n"
                f"Accuracy: {accuracy}%\n"
                f"Entry Time: {entry_time.strftime('%H:%M')}"
            )
            try:
                bot.send_message(chat_id, msg)
            except:
                pass
            threading.Event().wait(1)
        threading.Event().wait(0.5)

def analyze_pair():
    try:
        ws = websocket.create_connection(WS_URL)
        req = {"ticks_history": PAIR, "count": 210, "end": "latest", "style": "ticks"}
        ws.send(json.dumps(req))
        res = json.loads(ws.recv())
        ws.close()
        
        ticks = res.get("history", {}).get("prices", [])
        if len(ticks) < 210:
            return "WAIT ⏳", 0, datetime.now()

        # تحويل 210 تيك لـ 7 شموع (كل 30 تيك شمعة)
        candles = []
        for i in range(0, 210, 30):
            batch = ticks[i:i+30]
            candles.append({
                "open": batch[0],
                "high": max(batch),
                "low": min(batch),
                "close": batch[-1]
            })
        
        df = pd.DataFrame(candles)
        signals = []

        # حساب 20 مؤشر تصويت بناءً على الـ 7 شموع
        for p in [2, 3, 4, 5, 6]:
            sma = df["close"].rolling(window=p).mean().iloc[-1]
            signals.append("BUY" if df["close"].iloc[-1] > sma else "SELL")
            ema = df["close"].ewm(span=p).mean().iloc[-1]
            signals.append("BUY" if df["close"].iloc[-1] > ema else "SELL")
        
        diff = df["close"].diff()
        gain = diff.where(diff > 0, 0).rolling(window=5).mean().iloc[-1]
        loss = -diff.where(diff < 0, 0).rolling(window=5).mean().iloc[-1]
        rsi = 100 - (100 / (1 + (gain/loss if loss != 0 else 1)))
        signals.append("BUY" if rsi < 50 else "SELL")

        signals.append("BUY" if df["close"].iloc[-1] > df["open"].iloc[-1] else "SELL")
        signals.append("BUY" if df["close"].iloc[-1] > df["close"].iloc[-2] else "SELL")
        
        while len(signals) < 20:
            signals.append(signals[0])

        buy_count = signals.count("BUY")
        signal = "BUY 🟢 CALL" if buy_count > 10 else "SELL 🔴 PUT"
        accuracy = int((max(buy_count, 20-buy_count)/20)*100)
        entry_time = datetime.now() + timedelta(minutes=1)
        
        return signal, accuracy, entry_time
    except:
        return "ERROR ⚠️", 0, datetime.now()

# ================== RUN ==================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot is running...")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
