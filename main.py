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
TELEGRAM_TOKEN = '8264292822:AAE_lhhOEBrLEI1z2T1tsX8KBZHL3konF5Q'

# قائمة الـ 15 زوج Forex (Deriv symbols)
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
        
        # تحويل لشموع (بناءً على إعداداتك: 5 تيكات لكل شمعة)
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
    # تنظيم الأزرار في صفوف (2 في كل صف)
    keyboard = []
    for i in range(0, len(FOREX_PAIRS), 2):
        row = [InlineKeyboardButton(pair.replace("frx", ""), callback_data=pair) for pair in FOREX_PAIRS[i:i+2]]
        keyboard.append(row)
        
    await update.message.reply_text("📊 اختر زوج العملات للتحليل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_message_after_delay(context: ContextTypes.DEFAULT_TYPE):
    """وظيفة لحذف الرسالة بعد الوقت المحدد"""
    job = context.job
    await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data)

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = await DerivScalper().get_data(query.data)
    res = DerivScalper().analyze(data)
    
    if res:
        symbol_name = query.data.replace("frx", "")
        # تطبيق معاييرك السابقة: Multiplier 14, SL/TP $10
        msg_text = (
            f"🎯 **توصية جديدة**\n"
            f"━━━━━━━━━━━━\n"
            f"💱 الزوج: {symbol_name}\n"
            f"💰 السعر: {res['p']}\n"
            f"🚦 الإشارة: {res['sig']}\n"
            f"⚡ القوة: {res['str']}%\n"
            f"━━━━━━━━━━━━\n"
            f"📝 ملاحظة: ستختفي هذه الرسالة بعد 15 ثانية."
        )
        
        sent_msg = await query.message.reply_text(msg_text, parse_mode='Markdown')
        
        # جدولة حذف الرسالة بعد 15 ثانية
        context.job_queue.run_once(
            delete_message_after_delay, 
            15, 
            data=sent_msg.message_id, 
            chat_id=query.message.chat_id
        )

if __name__ == '__main__':
    keep_alive()
    # إضافة JobQueue للتعامل مع مؤقت الحذف
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle))
    
    print("Bot is running...")
    app.run_polling()
