import asyncio
import json
import pandas as pd
import websockets
import os
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

# --- WEB SERVER FOR RENDER ---
server = Flask('')
@server.route('/')
def home(): return "Forex High-Performance Bot is Live!"

def run(): server.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIGURATION ---
APP_ID = '16929'
WS_URL = f"wss://blue.derivws.com/websockets/v3?app_id={APP_ID}"
# التوكن الجديد الخاص بك
TELEGRAM_TOKEN = '8264292822:AAE6wEVtRJo70QcJ5umBnYd1jvZeH9lPmdg'

FOREX_PAIRS = [
    ("EUR/USD", "frxEURUSD"), ("GBP/USD", "frxGBPUSD"), ("USD/JPY", "frxUSDJPY"),
    ("AUD/USD", "frxAUDUSD"), ("USD/CAD", "frxUSDCAD"), ("USD/CHF", "frxUSDCHF"),
    ("NZD/USD", "frxNZDUSD"), ("EUR/GBP", "frxEURGBP"), ("EUR/JPY", "frxEURJPY"),
    ("GBP/JPY", "frxGBPJPY"), ("EUR/CHF", "frxEURCHF"), ("AUD/JPY", "frxAUDJPY"),
    ("GBP/CAD", "frxGBPCAD"), ("AUD/CAD", "frxAUDCAD"), ("XAU/USD", "frxXAUUSD")
]

# --- ANALYSIS LOGIC ---
def calculate_rsi(series, period=3):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))

class DerivScalper:
    async def get_data(self, symbol):
        try:
            async with websockets.connect(WS_URL) as ws:
                req = {"ticks_history": symbol, "count": 1000, "end": "latest", "style": "ticks"}
                await ws.send(json.dumps(req))
                res = await ws.recv()
                return json.loads(res).get('history', {}).get('prices', [])
        except: return []

    def analyze(self, prices):
        if len(prices) < 30: return "No Data", 0, 0, 0, 0
        candles = []
        for i in range(0, len(prices), 5):
            batch = prices[i:i+5]
            if len(batch)==5: candles.append({'low': min(batch), 'high': max(batch), 'close': batch[-1]})
        
        df = pd.DataFrame(candles)
        support = df['low'].tail(50).min()
        resistance = df['high'].tail(50).max()
        df['rsi'] = calculate_rsi(df['close'], 3)
        curr_rsi = df['rsi'].iloc[-1]
        curr_price = prices[-1]
        
        buffer = (resistance - support) * 0.05
        safe = (curr_price > support + buffer) and (curr_price < resistance - buffer)
        
        signal = "WAIT ⏳"
        strength = 0
        if safe:
            if curr_rsi > 75: signal = "SELL 🔴"; strength = 85
            elif curr_rsi < 25: signal = "BUY 🟢"; strength = 85
        return signal, strength, support, resistance, curr_price

# --- AUTO DELETE TASK ---
async def delete_message_after_delay(context: ContextTypes.DEFAULT_TYPE, message_id: int, chat_id: int, delay: int = 15):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (BadRequest, Exception):
        pass # الرسالة قد تكون حذفت يدوياً بالفعل

# --- TELEGRAM INTERFACE ---
def main_menu():
    keyboard = []
    for i in range(0, len(FOREX_PAIRS), 2):
        row = [InlineKeyboardButton(FOREX_PAIRS[i][0], callback_data=f"select_{FOREX_PAIRS[i][1]}")]
        if i+1 < len(FOREX_PAIRS):
            row.append(InlineKeyboardButton(FOREX_PAIRS[i+1][0], callback_data=f"select_{FOREX_PAIRS[i+1][1]}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💎 **Forex Scalper Pro**\nSelect a pair to analyze:", 
                                   reply_markup=main_menu(), parse_mode='Markdown')

async def handle_interaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    await query.answer()

    if data.startswith("select_"):
        symbol = data.replace("select_", "")
        keyboard = [[InlineKeyboardButton("🔍 Get Signal", callback_data=f"analyze_{symbol}")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_home")]]
        await query.edit_message_text(f"📍 Selected: **{symbol}**", 
                                     reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data.startswith("analyze_"):
        symbol = data.replace("analyze_", "")
        prices = await DerivScalper().get_data(symbol)
        sig, st, sup, res, price = DerivScalper().analyze(prices)
        
        msg_text = (f"📊 **Asset:** {symbol}\n💰 **Price:** `{price}`\n"
                    f"🎯 **Signal:** {sig}\n⚡ **Strength:** {st}%\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"⚠️ *This message will disappear in 15s*")
        
        # إرسال الرسالة كرسالة جديدة ليتم حذفها لاحقاً
        sent_msg = await context.bot.send_message(chat_id=chat_id, text=msg_text, parse_mode='Markdown')
        
        # تشغيل مهمة الحذف في الخلفية دون تعطيل البوت
        asyncio.create_task(delete_message_after_delay(context, sent_msg.message_id, chat_id))

    elif data == "back_home":
        await query.edit_message_text("💎 **Forex Scalper Pro**\nSelect a pair:", 
                                     reply_markup=main_menu(), parse_mode='Markdown')

if __name__ == '__main__':
    keep_alive()
    # استخدام نظام Concurrent لحل طلبات آلاف المستخدمين
    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_interaction))
    print("Bot is running with high-concurrency support...")
    app.run_polling()
