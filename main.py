import asyncio
import json
import pandas as pd
import websockets
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- سيرفر الويب لضمان التشغيل المستمر على Render ---
server = Flask('')
@server.route('/')
def home(): return "Forex Pro Bot is Online!"

def run(): server.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- الإعدادات ---
APP_ID = '16929'
WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"
TELEGRAM_TOKEN = '8264292822:AAGTmIu8mn-fl4gmGwK-0KYc_MOqzQZa3Og'

FOREX_LIST = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", 
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", 
    "EURCHF", "AUDJPY", "GBPCAD", "AUDCAD", "XAUUSD"
]

def calculate_rsi(prices, period=3):
    if len(prices) < period + 1: return 50
    s = pd.Series(prices)
    delta = s.diff()
    up = delta.clip(lower=0).rolling(window=period).mean()
    down = -delta.clip(upper=0).rolling(window=period).mean()
    rs = up / (down + 1e-10)
    return 100 - (100 / (1 + rs.iloc[-1]))

# دالة جلب البيانات: تضمن إضافة frx وإصلاح خطأ الـ Connection
async def fetch_deriv_data(symbol):
    deriv_symbol = f"frx{symbol}" # إضافة frx برمجياً هنا لضمان قبول الطلب
    try:
        async with websockets.connect(WS_URL, timeout=15) as ws:
            request = {
                "ticks_history": deriv_symbol,
                "count": 1000,
                "end": "latest",
                "style": "ticks"
            }
            await ws.send(json.dumps(request))
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(response)
            return data.get('history', {}).get('prices', [])
    except Exception as e:
        print(f"Error for {deriv_symbol}: {e}")
        return []

def analyze_logic(prices):
    if not prices or len(prices) < 100: return None
    df = pd.Series(prices)
    support, resistance = df.min(), df.max()
    current_price = prices[-1]
    
    # تحليل آخر 30 تيك (حوالي 6 شموع)
    rsi_value = calculate_rsi(prices[-30:], 3)
    
    buffer = (resistance - support) * 0.05
    is_safe = (current_price > support + buffer) and (current_price < resistance - buffer)
    
    signal, strength = "WAIT ⏳", 0
    if is_safe:
        if rsi_value > 75: signal = "SELL 🔴"; strength = 85
        elif rsi_value < 25: signal = "BUY 🟢"; strength = 85
            
    return {"sig": signal, "str": strength, "sup": round(support, 5), "res": round(resistance, 5), "price": current_price}

# --- واجهة التلغرام وحذف الرسائل ---
async def delete_msg(context, chat_id, msg_id):
    await asyncio.sleep(15)
    try: await context.bot.delete_message(chat_id, msg_id)
    except: pass

def main_menu():
    keys = []
    for i in range(0, len(FOREX_LIST), 2):
        row = [InlineKeyboardButton(FOREX_LIST[i], callback_data=f"sel_{FOREX_LIST[i]}")]
        if i+1 < len(FOREX_LIST): row.append(InlineKeyboardButton(FOREX_LIST[i+1], callback_data=f"sel_{FOREX_LIST[i+1]}"))
    return InlineKeyboardMarkup(keys)

async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("💎 **Forex Scalper Pro**\nSelect a pair:", reply_markup=main_menu(), parse_mode='Markdown')

async def handle_callback(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    
    if q.data.startswith("sel_"):
        symbol = q.data.split("_")[1]
        btn = [[InlineKeyboardButton("🔍 Get Signal", callback_data=f"anz_{symbol}")], [InlineKeyboardButton("⬅️ Back", callback_data="home")]]
        await q.edit_message_text(f"📍 Selected: **{symbol}**", reply_markup=InlineKeyboardMarkup(btn), parse_mode='Markdown')
    
    elif q.data.startswith("anz_"):
        symbol = q.data.split("_")[1]
        prices = await fetch_deriv_data(symbol)
        analysis = analyze_logic(prices)
        
        if analysis:
            text = (f"📊 **Asset:** {symbol}\n💰 **Price:** `{analysis['price']}`\n"
                    f"🛡️ **S:** `{analysis['sup']}` | **R:** `{analysis['res']}`\n"
                    f"🎯 **Signal:** {analysis['sig']}\n⚡ **Strength:** {analysis['str']}%")
        else:
            text = f"❌ **Error:** Could not fetch data for {symbol}. Try again."
            
        sent = await c.bot.send_message(q.message.chat_id, text + "\n\n⏱ *Deletes in 15s*", parse_mode='Markdown')
        asyncio.create_task(delete_msg(c, q.message.chat_id, sent.message_id))

    elif q.data == "home":
        await q.edit_message_text("💎 **Forex Scalper Pro**\nSelect a pair:", reply_markup=main_menu(), parse_mode='Markdown')

if __name__ == '__main__':
    keep_alive()
    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
