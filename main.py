import asyncio
import json
import pandas as pd
import websockets
import os
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- WEB SERVER ---
server = Flask('')
@server.route('/')
def home(): return "Bot is Running!"

def run(): server.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIGURATION ---
APP_ID = '16929'
WS_URL = f"wss://blue.derivws.com/websockets/v3?app_id={APP_ID}"
TELEGRAM_TOKEN = '8264292822:AAGSnO_NDcd8m-b9jpojbtu2PuHxsDGQCz8'

FOREX_PAIRS = [
    "frxAUDCAD", "frxAUDCHF", "frxAUDJPY", "frxAUDNZD", "frxAUDUSD",
    "frxEURAUD", "frxEURCAD", "frxEURCHF", "frxEURGBP", "frxEURJPY",
    "frxEURUSD", "frxGBPAUD", "frxGBPJPY", "frxGBPUSD", "frxUSDCAD"
]

def calculate_rsi(series, period=3):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
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
        if len(prices) < 30: return None
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
            
        return {"sig": signal, "str": strength, "p": curr_price}

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for i in range(0, len(FOREX_PAIRS), 2):
        row = [InlineKeyboardButton(pair.replace("frx", ""), callback_data=pair) for pair in FOREX_PAIRS[i:i+2]]
        keyboard.append(row)
    await update.message.reply_text("📊 اختر زوج العملات للتحليل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = await DerivScalper().get_data(query.data)
    res = DerivScalper().analyze(data)
    
    if res:
        symbol_name = query.data.replace("frx", "")
        msg_text = (
            f"🎯 **توصية {symbol_name}**\n"
            f"━━━━━━━━━━━━\n"
            f"💰 السعر: {res['p']}\n"
            f"🚦 الإشارة: {res['sig']}\n"
            f"⚡ القوة: {res['str']}%\n"
            f"━━━━━━━━━━━━\n"
            f"⏱ ستختفي خلال 15 ثانية..."
        )
        
        # إرسال الرسالة
        sent_msg = await query.message.reply_text(msg_text, parse_mode='Markdown')
        
        # الانتظار 15 ثانية ثم الحذف
        async def delayed_delete():
            await asyncio.sleep(15)
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=sent_msg.message_id)
            except:
                pass # في حال تم حذف الرسالة يدوياً مسبقاً

        # تشغيل مهمة الحذف في الخلفية حتى لا يتوقف البوت عن الرد
        asyncio.create_task(delayed_delete())

if __name__ == '__main__':
    keep_alive()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle))
    print("Bot is online...")
    app.run_polling()
