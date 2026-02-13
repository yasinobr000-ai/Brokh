import asyncio
import json
import pandas as pd
import pandas_ta as ta
import websockets
import os
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- WEB SERVER FOR RENDER (Keep-Alive) ---
server = Flask('')

@server.route('/')
def home():
    return "I am alive!"

def run():
    server.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- CONFIGURATION ---
APP_ID = '16929'
WS_URL = f"wss://blue.derivws.com/websockets/v3?app_id={APP_ID}"
TELEGRAM_TOKEN = '8264292822:AAF1l1iRkWj6-tw-ZmPZkl_NvSxkmrve76Q'

class DerivScalper:
    def __init__(self):
        self.tick_limit = 1000
        self.ticks_per_candle = 5

    async def get_data(self, symbol):
        try:
            async with websockets.connect(WS_URL) as ws:
                request = {
                    "ticks_history": symbol,
                    "adjust_start_time": 1,
                    "count": self.tick_limit,
                    "end": "latest",
                    "style": "ticks"
                }
                await ws.send(json.dumps(request))
                response = await ws.recv()
                data = json.loads(response)
                return data.get('history', {}).get('prices', [])
        except Exception as e:
            print(f"Error: {e}")
            return []

    def convert_to_candles(self, prices):
        candles = []
        for i in range(0, len(prices), self.ticks_per_candle):
            batch = prices[i:i + self.ticks_per_candle]
            if len(batch) < self.ticks_per_candle: continue
            candles.append({'open': batch[0], 'high': max(batch), 'low': min(batch), 'close': batch[-1]})
        return pd.DataFrame(candles)

    def calculate_strategy(self, prices):
        if not prices: return None
        df_large = self.convert_to_candles(prices)
        support = df_large['low'].tail(100).min()
        resistance = df_large['high'].tail(100).max()
        last_30_ticks = prices[-30:]
        df_signal = self.convert_to_candles(last_30_ticks)
        df_signal['rsi'] = ta.rsi(df_signal['close'], length=3)
        current_price = prices[-1]
        current_rsi = df_signal['rsi'].iloc[-1]
        
        strength = 0
        signal = "NEUTRAL"
        zone_buffer = (resistance - support) * 0.05
        is_far_from_sr = (current_price > support + zone_buffer) and (current_price < resistance - zone_buffer)
        not_broken = max(last_30_ticks) < resistance and min(last_30_ticks) > support

        if is_far_from_sr and not_broken:
            if current_rsi < 30:
                signal = "BUY 🟢"; strength = 85 if current_rsi < 20 else 70
            elif current_rsi > 70:
                signal = "SELL 🔴"; strength = 85 if current_rsi > 80 else 70

        return {"signal": signal, "strength": strength, "support": support, "resistance": resistance, "price": current_price}

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("EUR/USD", callback_data='frxEURUSD')],
                [InlineKeyboardButton("Volatility 100", callback_data='R_100')]]
    await update.message.reply_text("Select Asset:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    scalper = DerivScalper()
    prices = await scalper.get_data(query.data)
    res = scalper.calculate_strategy(prices)
    if res:
        msg = f"🎯 Signal: {res['signal']}\n⚡ Strength: {res['strength']}%\n💰 Price: {res['price']}"
        await query.message.reply_text(msg)

if __name__ == '__main__':
    keep_alive() # تشغيل السيرفر الوهمي
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()
