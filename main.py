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

# ================= CONFIG (الإعدادات والتوكن) =================
BOT_TOKEN = "8264292822:AAHV3fhjjFmc--qhwoVBp-Fh24uMmIIHM3g"
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

# ================= دالة حذف الرسالة =================
def delete_msg_after_time(chat_id, message_id, delay):
    time.sleep(delay)
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

# ================= منطق التحليل والمؤشرات الـ 30 =================
def analyze_logic(chat_id):
    state = user_states.get(chat_id)
    if not state: return None, 0
    try:
        ws = websocket.create_connection(WS_URL, timeout=15)
        ws.send(json.dumps({"ticks_history": state['pair'], "count": 3500, "end": "latest", "style": "ticks"}))
        res = json.loads(ws.recv())
        ws.close()
        
        ticks = res.get("history", {}).get("prices", [])
        if len(ticks) < 110: return None, 0

        # شرط الـ 55 تيك (30 أولى / 25 أخيرة)
        last_55 = ticks[-55:]
        first_30 = last_55[:30]
        last_25 = last_55[30:]

        is_buy_condition = (first_30[-1] < first_30[0]) and (last_25[-1] > last_25[0])
        is_sell_condition = (first_30[-1] > first_30[0]) and (last_25[-1] < last_25[0])

        if not (is_buy_condition or is_sell_condition):
            return None, 0

        # تحويل التيكات إلى شموع (كل شمعة 30 تيك) للتحليل الفني
        candle_data = [ticks[i:i+30][-1] for i in range(0, len(ticks), 30)]
        prices = pd.Series(candle_data)
        curr = prices.iloc[-1]
        prev = prices.iloc[-2]
        
        # مصفوفة الـ 30 مؤشر
        sigs = []
        sigs.append(curr > prices.rolling(10).mean().iloc[-1]) # 1
        diff = prices.diff(); gain = diff.where(diff > 0, 0).rolling(7).mean(); loss = -diff.where(diff < 0, 0).rolling(7).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 0.0000001)).iloc[-1]))
        sigs.append(rsi < 50) # 2
        macd = prices.ewm(span=12).mean().iloc[-1] - prices.ewm(span=26).mean().iloc[-1]
        sigs.append(macd > 0) # 3
        l_min, h_max = prices.rolling(10).min().iloc[-1], prices.rolling(10).max().iloc[-1]
        sigs.append(((curr - l_min) / (h_max - l_min + 0.0000001)) * 100 > 50) # 4
        sigs.append(((h_max - curr) / (h_max - l_min + 0.0000001)) * -100 > -50) # 5
        tp = prices.rolling(10).mean().iloc[-1]; mad = prices.rolling(10).apply(lambda x: np.abs(x - x.mean()).mean()).iloc[-1]
        sigs.append(((curr - tp) / (0.015 * mad + 0.0000001)) > 0) # 6
        sigs.append(curr > prices.iloc[-5]) # 7
        sigs.append(((curr - prices.iloc[-8]) / prices.iloc[-8]) > 0) # 8
        sigs.append(curr > prices.ewm(span=13).mean().iloc[-1]) # 9
        sigs.append(curr > prev) # 10
        ma_bb, std_bb = prices.rolling(10).mean().iloc[-1], prices.rolling(10).std().iloc[-1]
        sigs.append(curr < (ma_bb + std_bb)) # 11
        sigs.append(curr > (ma_bb - std_bb)) # 12
        sigs.append(curr > prices.rolling(5).mean().iloc[-1]) # 13
        sigs.append(curr > (prices.rolling(10).max().iloc[-1] + prices.rolling(10).min().iloc[-1])/2) # 14
        sigs.append(prices.iloc[-5:].var() < prices.iloc[-15:].var()) # 15
        sigs.append(curr > prices.mean()) # 16
        sigs.append(curr > prices.iloc[-3:].mean()) # 17
        sigs.append(abs(curr - prev) > prices.diff().abs().mean()) # 18
        sigs.append((prices.iloc[-1] - prices.iloc[-4]) > 0) # 19
        sigs.append(prices.rolling(5).std().iloc[-1] > prices.rolling(10).std().iloc[-1]) # 20
        sigs.append(curr > prices.iloc[-10]) # 21
        sigs.append(curr > prices.min()) # 22
        sigs.append(curr > (prices.max() + prices.min() + curr)/3) # 23
        sigs.append(curr > (prices.rolling(9).max().iloc[-1] + prices.rolling(9).min().iloc[-1])/2) # 24
        sigs.append(curr > (prices.rolling(14).max().iloc[-1] + prices.rolling(14).min().iloc[-1])/2) # 25
        sigs.append((curr - prev) > (prev - prices.iloc[-3])) # 26
        sigs.append(curr > prices.median()) # 27
        sigs.append(np.log(curr / (prev + 0.0000001)) >= 0) # 28
        sigs.append(curr > prices.iloc[0]) # 29
        sigs.append(curr > prices.iloc[-15:].mean()) # 30

        buy_votes = sigs.count(True)
        accuracy = int((max(buy_votes, 30 - buy_votes) / 30) * 100)
        final_dir = "BUY 🟢 CALL" if is_buy_condition else "SELL 🔴 PUT"
        return final_dir, accuracy
    except: return None, 0

def trading_loop(chat_id, stop_event):
    while not stop_event.is_set():
        if chat_id not in user_states or not user_states[chat_id]['running']: break
        now = datetime.now()
        # التحليل عند الثانية 50 كما طلبت
        if now.second == 50:
            signal, acc = analyze_logic(chat_id)
            if signal:
                entry_time = (now + timedelta(seconds=10)).strftime("%H:%M:%S")
                msg_text = (f"🎯 *NEW SIGNAL*\n━━━━━━━━━━━━━━━\n"
                            f"Pair: `{user_states[chat_id]['pair_name']}`\n"
                            f"Direction: *{signal}*\n"
                            f"Accuracy: `{acc}%` 🔥\n"
                            f"Entry At: `{entry_time}`\n━━━━━━━━━━━━━━━")
                try: 
                    sent_msg = bot.send_message(chat_id, msg_text, parse_mode="Markdown")
                    threading.Thread(target=delete_msg_after_time, args=(chat_id, sent_msg.message_id, 20)).start()
                    time.sleep(70) 
                except: pass
        stop_event.wait(0.5)

# ================= لوحة التحكم HTML =================
@app.route("/")
def admin_panel():
    users = list(users_col.find())
    return render_template_string("""
    <!DOCTYPE html>
    <html><head><title>Admin Control</title><style>
    body { font-family: sans-serif; background: #0f172a; color: white; text-align: center; }
    .container { background: #1e293b; padding: 20px; border-radius: 15px; display: inline-block; width: 90%; margin-top: 50px; }
    input, select, button { padding: 10px; margin: 5px; border-radius: 5px; border: none; }
    button { background: #0ea5e9; color: white; cursor: pointer; }
    table { width: 100%; margin-top: 20px; border-collapse: collapse; }
    th, td { padding: 10px; border-bottom: 1px solid #334155; }
    </style></head>
    <body><div class="container"><h2>Subscriptions</h2>
    <form action="/add" method="POST">
        <input name="email" placeholder="Email" required>
        <select name="days">
            <option value="1">1 Day</option>
            <option value="7">7 Days</option>
            <option value="30">30 Days</option>
            <option value="36500">Life Time</option>
        </select>
        <button type="submit">Activate</button>
    </form>
    <table><tr><th>Email</th><th>Expiry</th><th>Telegram ID</th><th>Action</th></tr>
    {% for u in users %}<tr><td>{{u.email}}</td><td>{{u.expiry}}</td><td>{{u.telegram_id}}</td><td><a href="/delete/{{u.email}}" style="color:red">Remove</a></td></tr>{% endfor %}
    </table></div></body></html>
    """, users=users)

@app.route("/add", methods=["POST"])
def add_user():
    email = request.form.get("email").strip().lower(); days = int(request.form.get("days", 30))
    expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    users_col.update_one({"email": email}, {"$set": {"expiry": expiry, "telegram_id": None}}, upsert=True)
    return redirect("/")

@app.route("/delete/<email>")
def delete_user(email):
    users_col.delete_one({"email": email}); return redirect("/")

# ================= معالجات تلغرام =================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("START 🚀", "STOP 🛑", "CHANGE PAIR 🔄")
    return markup

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "👋 Welcome. Enter your email:")

@bot.message_handler(func=lambda m: "@" in m.text)
def handle_auth(message):
    email, chat_id = message.text.strip().lower(), message.chat.id
    user = users_col.find_one({"email": email})
    if not user:
        bot.send_message(chat_id, "❌ Not authorized.")
        return
    users_col.update_one({"email": email}, {"$set": {"telegram_id": chat_id}})
    user_states[chat_id] = {'running': False, 'pair': 'frxEURUSD', 'pair_name': 'EUR/USD', 'email': email}
    bot.send_message(chat_id, "✅ Activated!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "START 🚀")
def start_bot(m):
    chat_id = m.chat.id
    if chat_id not in user_states: return
    stop_event = threading.Event()
    user_threads_events[chat_id] = stop_event
    user_states[chat_id]['running'] = True
    bot.send_message(chat_id, "🚀 Running! Analyzing at :50s", reply_markup=main_menu())
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
    bot.send_message(m.chat.id, "📊 Select Pair:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_"))
def handle_selection(call):
    _, code, name = call.data.split("_"); chat_id = call.message.chat.id
    if chat_id in user_states:
        user_states[chat_id].update({'pair': code, 'pair_name': name})
        bot.edit_message_text(f"🎯 Current: *{name}*", chat_id, call.message.message_id, parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    bot.infinity_polling()
