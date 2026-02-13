import asyncio
import json
import pandas as pd
import websockets
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- سيرفر الويب لمنع توقف البوت ---
server = Flask('')
@server.route('/')
def home(): return "Bot is Online"
def run(): server.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- الإعدادات ---
TOKEN = '8264292822:AAHXarMK2eGhPdlPXTnC9oRpNNrfY57DO2A'
APP_ID = '16929' 
WS_URL = f"wss://blue.derivws.com/websockets/v3?app_id={APP_ID}"

# قائمة الـ 15 زوجاً
FOREX_LIST = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
    "EURCHF", "AUDJPY", "GBPCAD", "AUDCAD", "XAUUSD"
]

# دالة بناء القائمة (تم إصلاحها لتظهر الأزرار يقيناً)
def get_main_keyboard():
    keyboard = []
    # بناء الأزرار صفاً بصف (كل صف فيه زوجين)
    for i in range(0, len(FOREX_LIST), 2):
        row = [InlineKeyboardButton(FOREX_LIST[i], callback_data=f"sel_{FOREX_LIST[i]}")]
        if i + 1 < len(FOREX_LIST):
            row.append(InlineKeyboardButton(FOREX_LIST[i+1], callback_data=f"sel_{FOREX_LIST[i+1]}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# تحليل RSI
def calculate_rsi_manual(prices, period=3):
    if len(prices) < period + 1: return 50
    s = pd.Series(prices)
    delta = s.diff()
    up = delta.clip(lower=0).rolling(window=period).mean()
    down = -delta.clip(upper=0).rolling(window=period).mean()
    rs = up / (down + 1e-10)
    return 100 - (100 / (1 + rs.iloc[-1]))

# جلب البيانات من Deriv
async def fetch_data(symbol):
    deriv_symbol = f"frx{symbol}"
    try:
        async with websockets.connect(WS_URL, timeout=10) as ws:
            req = {"ticks_history": deriv_symbol, "count": 100, "end": "latest", "style": "ticks"}
            await ws.send(json.dumps(req))
            resp = await asyncio.wait_for(ws.recv(), timeout=8)
            data = json.loads(resp)
            return data.get('history', {}).get('prices', [])
    except: return []

# --- معالجة الأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # إرسال القائمة فوراً عند كتابة /start
    await update.message.reply_text(
        "💎 **Forex Scalper Pro**\nإختر الزوج الذي تود تحليله من القائمة أدناه:",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("sel_"):
        symbol = query.data.split("_")[1]
        keyboard = [[InlineKeyboardButton("🔍 Get Signal", callback_data=f"anz_{symbol}")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="home")]]
        await query.edit_message_text(
            f"📍 الزوج المختار: **{symbol}**\nاضغط على الزر للتحليل الآن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("anz_"):
        symbol = query.data.split("_")[1]
        temp_msg = await context.bot.send_message(query.message.chat_id, f"⏳ جاري فحص {symbol}...")
        
        prices = await fetch_data(symbol)
        if not prices:
            await temp_msg.edit_text("❌ فشل في جلب البيانات، حاول مجدداً.")
            return

        rsi = calculate_rsi_manual(prices)
        price = prices[-1]
        signal = "WAIT ⏳"
        if rsi > 70: signal = "SELL 🔴 (85%)"
        elif rsi < 30: signal = "BUY 🟢 (85%)"

        result_text = (f"📊 **الزوج:** {symbol}\n💰 **السعر:** `{price}`\n"
                       f"🎯 **الإشارة:** {signal}\n\n⏱ *سيتم حذف هذه الرسالة بعد 15 ثانية*")
        
        await temp_msg.edit_text(result_text, parse_mode='Markdown')
        
        # حذف تلقائي بعد 15 ثانية
        await asyncio.sleep(15)
        try: await context.bot.delete_message(query.message.chat_id, temp_msg.message_id)
        except: pass

    elif query.data == "home":
        await query.edit_message_text(
            "💎 **Forex Scalper Pro**\nإختر الزوج الذي تود تحليله من القائمة أدناه:",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )

if __name__ == '__main__':
    keep_alive()
    app = Application.builder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
