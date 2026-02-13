import asyncio
import json
import pandas as pd
import websockets
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- سيرفر Flask لضمان استمرارية العمل على Render ---
server = Flask('')
@server.route('/')
def home(): return "Forex Pro Bot is Online!"

def run(): server.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- الإعدادات ---
APP_ID = '16929'
WS_URL = "wss://blue.derivws.com/websockets/v3?app_id=16929"
TELEGRAM_TOKEN = '8264292822:AAF9R8sAsIdlIUEgY9FnzcZc02yecc-_Avo'

# أزواج العملات (بدون frx هنا ليظهر الاسم نظيفاً للمستخدم)
FOREX_LIST = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", 
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", 
    "EURCHF", "AUDJPY", "GBPCAD", "AUDCAD", "XAUUSD"
]

# دالة حساب RSI يدوية فائقة السرعة
def calculate_rsi(prices, period=3):
    if len(prices) < period + 1: return 50
    s = pd.Series(prices)
    delta = s.diff()
    up = delta.clip(lower=0).rolling(window=period).mean()
    down = -delta.clip(upper=0).rolling(window=period).mean()
    rs = up / (down + 1e-10)
    return 100 - (100 / (1 + rs.iloc[-1]))

# دالة جلب البيانات مع إضافة frx وإصلاح مشكلة الـ Error
async def fetch_deriv_data(symbol):
    # التأكد من إضافة frx قبل الرمز عند الإرسال لـ Deriv
    deriv_symbol = f"frx{symbol}"
    try:
        async with websockets.connect(WS_URL, timeout=15) as ws:
            request = {
                "ticks_history": deriv_symbol,
                "count": 1000,
                "end": "latest",
                "style": "ticks"
            }
            await ws.send(json.dumps(request))
            
            # انتظار الرد مع مهلة زمنية
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(response)
            
            prices = data.get('history', {}).get('prices', [])
            return prices
    except Exception as e:
        print(f"Connection Error for {deriv_symbol}: {e}")
        return []

# تحليل الإشارة بناءً على شروطك (1000 تيك للدعم و30 تيك للسيولة)
def analyze_logic(prices):
    if not prices or len(prices) < 100: return None
    
    df = pd.Series(prices)
    # دعم ومقاومة من الـ 1000 تيك (حسب طلبك)
    support = df.min()
    resistance = df.max()
    current_price = prices[-1]
    
    # تحليل آخر 30 تيك (تقسيم 5 تيك لكل شمعة = 6 شموع)
    last_30_ticks = prices[-30:]
    rsi_value = calculate_rsi(last_30_ticks, 3)
    
    # شرط القوة والابتعاد عن مناطق الانفجار (Buffer 5%)
    buffer = (resistance - support) * 0.05
    is_safe = (current_price > support + buffer) and (current_price < resistance - buffer)
    
    signal = "WAIT ⏳"
    strength = 0
    
    if is_safe:
        if rsi_value > 75: 
            signal = "SELL 🔴"
            strength = 85
        elif rsi_value < 25: 
            signal = "BUY 🟢"
            strength = 85
            
    return {
        "sig": signal, 
        "str": strength, 
        "sup": round(support, 5), 
        "res": round(resistance, 5), 
        "price": current_price
    }

# --- واجهة التلغرام ---
async def delete_msg(context, chat_id, msg_id):
    await asyncio.sleep(15)
    try: await context.bot.delete_message(chat_id, msg_id)
    except: pass

def main_menu():
    keys = []
    for i in range(0, len(FOREX_LIST), 2):
        row = [InlineKeyboardButton(FOREX_LIST[i], callback_data=f"sel_{FOREX_LIST[i]}")]
        if i+1 < len(FOREX_LIST):
            row.append(InlineKeyboardButton(FOREX_LIST[i+1], callback_data=f"sel_{FOREX_LIST[i+1]}"))
        keys.append(row)
    return InlineKeyboardMarkup(keys)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💎 **Forex Scalper Pro**\nSelect a pair to start analysis:", 
                                   reply_markup=main_menu(), parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    
    if query.data.startswith("sel_"):
        symbol = query.data.split("_")[1]
        btn = [[InlineKeyboardButton("🔍 Get Signal", callback_data=f"anz_{symbol}")],
               [InlineKeyboardButton("⬅️ Back to Menu", callback_data="home")]]
        await query.edit_message_text(f"📍 Selected Pair: **{symbol}**\nClick below to milk the market:", 
                                     reply_markup=InlineKeyboardMarkup(btn), parse_mode='Markdown')
    
    elif query.data.startswith("anz_"):
        symbol = query.data.split("_")[1]
        # إظهار رسالة مؤقتة أثناء التحليل
        temp_msg = await context.bot.send_message(chat_id, f"⏳ Milking data for **{symbol}**...")
        
        prices = await fetch_deriv_data(symbol)
        analysis = analyze_logic(prices)
        
        # حذف رسالة الانتظار
        await context.bot.delete_message(chat_id, temp_msg.message_id)
        
        if analysis:
            text = (f"📊 **Asset:** {symbol}\n"
                    f"💰 **Current Price:** `{analysis['price']}`\n"
                    f"🛡️ **Support:** `{analysis['sup']}`\n"
                    f"🏰 **Resistance:** `{analysis['res']}`\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🎯 **Signal:** {analysis['sig']}\n"
                    f"⚡ **Strength:** {analysis['str']}%")
        else:
            text = f"❌ **Error:** Could not fetch data for {symbol}. Please try again."
            
        sent = await context.bot.send_message(chat_id, text + "\n\n⏱ *Auto-delete in 15s*", parse_mode='Markdown')
        asyncio.create_task(delete_msg(context, chat_id, sent.message_id))

    elif query.data == "home":
        await query.edit_message_text("💎 **Forex Scalper Pro**\nSelect a pair:", reply_markup=main_menu(), parse_mode='Markdown')

if __name__ == '__main__':
    keep_alive()
    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
