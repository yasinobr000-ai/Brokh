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
TELEGRAM_TOKEN = '8264292822:AAF1l1iRkWj6-tw-ZmPZkl_NvSxkmrve76Q'

# دالة حساب RSI يدوياً لتجنب مشاكل التثبيت
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
        
        # تحويل لشموع (كل 5 تيكات شمعة)
        candles = []
        for i in range(0, len(prices), 5):
            batch = prices[i:i+5]
            if len(batch)==5: candles.append({'low': min(batch), 'high': max(batch), 'close': batch[-1]})
        
        df = pd.DataFrame(candles)
        support = df['low'].tail(50).min()
        resistance = df['high'].tail(50).max()
        
        # مؤشر RSI لآخر 6 شموع
        df['rsi'] = calculate_rsi(df['close'], 3)
        curr_rsi = df['rsi'].iloc[-1]
        curr_price = prices[-1]
        
        # شروط الفلترة
        buffer = (resistance - support) * 0.05
        safe = (curr_price > support + buffer) and (curr_price < resistance - buffer)
        
        signal = "WAIT"
        strength = 0
        if safe:
            if curr_rsi > 75: signal = "SELL 🔴"; strength = 80
            elif curr_rsi < 25: signal = "BUY 🟢"; strength = 80
            
        return {"sig": signal, "str": strength, "p": curr_price}

# --- BOT HANDLERS ---
async def start(update, context):
    keys = [[InlineKeyboardButton("EUR/USD", callback_data='frxEURUSD')],
            [InlineKeyboardButton("Volatility 100", callback_data='R_100')]]
    await update.message.reply_text("Select Pair:", reply_markup=InlineKeyboardMarkup(keys))

async def handle(update, context):
    query = update.callback_query
    await query.answer()
    data = await DerivScalper().get_data(query.data)
    res = DerivScalper().analyze(data)
    if res:
        msg = f"Symbol: {query.data}\nPrice: {res['p']}\nSignal: {res['sig']}\nStrength: {res['str']}%"
        await query.message.reply_text(msg)

if __name__ == '__main__':
    keep_alive()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle))
    app.run_polling()
