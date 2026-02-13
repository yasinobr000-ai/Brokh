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

# --- سيرفر وهمي لـ Render ---
server = Flask('')
@server.route('/')
def home(): return "Bot is Online"

def run(): server.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- الإعدادات ---
APP_ID = '16929'
WS_URL = f"wss://blue.derivws.com/websockets/v3?app_id={APP_ID}"
# التوكن الجديد الذي أرسلته
TELEGRAM_TOKEN = '8264292822:AAHvxu3_Np_Zbfe3ogDkQGXxA8h5NBzquqM'

FOREX_PAIRS = [
    ("EUR/USD", "frxEURUSD"), ("GBP/USD", "frxGBPUSD"), ("USD/JPY", "frxUSDJPY"),
    ("AUD/USD", "frxAUDUSD"), ("USD/CAD", "frxUSDCAD"), ("USD/CHF", "frxUSDCHF"),
    ("NZD/USD", "frxNZDUSD"), ("EUR/GBP", "frxEURGBP"), ("EUR/JPY", "frxEURJPY"),
    ("GBP/JPY", "frxGBPJPY"), ("EUR/CHF", "frxEURCHF"), ("AUD/JPY", "frxAUDJPY"),
    ("GBP/CAD", "frxGBPCAD"), ("AUD/CAD", "frxAUDCAD"), ("XAU/USD", "frxXAUUSD")
]

# دالة حساب RSI يدوياً (سريعة وخفيفة)
def calculate_rsi(prices, period=3):
    if len(prices) < period + 1: return 50
    series = pd.Series(prices)
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs.iloc[-1]))

# دالة التحليل الأساسية
async def get_signal(symbol):
    try:
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({"ticks_history": symbol, "count": 1000, "style": "ticks"}))
            res = json.loads(await ws.recv())
            prices = res.get('history', {}).get('prices', [])
            if not prices: return "Error", 0, 0, 0, 0
            
            # حساب الدعم والمقاومة لآخر 200 شمعة (كل شمعة 5 تيكات)
            df = pd.DataFrame(prices).rolling(window=5).mean().dropna()
            sup, res_val = df[0].min(), df[0].max()
            
            rsi = calculate_rsi(prices[-30:], 3)
            curr_p = prices[-1]
            
            buffer = (res_val - sup) * 0.05
            is_safe = (curr_p > sup + buffer) and (curr_p < res_val - buffer)
            
            signal = "WAIT ⏳"
            strength = 0
            if is_safe:
                if rsi > 75: signal = "SELL 🔴"; strength = 85
                elif rsi < 25: signal = "BUY 🟢"; strength = 85
            return signal, strength, round(sup, 5), round(res_val, 5), curr_p
    except: return "Connection Error", 0, 0, 0, 0

# --- وظائف التلغرام ---
async def delete_msg(context, chat_id, msg_id):
    await asyncio.sleep(15)
    try: await context.bot.delete_message(chat_id, msg_id)
    except: pass

def main_menu():
    keys = []
    for i in range(0, len(FOREX_PAIRS), 2):
        row = [InlineKeyboardButton(FOREX_PAIRS[i][0], callback_data=f"sel_{FOREX_PAIRS[i][1]}")]
        if i+1 < len(FOREX_PAIRS): row.append(InlineKeyboardButton(FOREX_PAIRS[i+1][0], callback_data=f"sel_{FOREX_PAIRS[i+1][1]}"))
        keys.append(row)
    return InlineKeyboardMarkup(keys)

async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("💎 **Forex Scalper Pro**\nSelect pair:", reply_markup=main_menu(), parse_mode='Markdown')

async def cb_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    
    if q.data.startswith("sel_"):
        sym = q.data.split("_")[1]
        keys = [[InlineKeyboardButton("🔍 Get Signal", callback_data=f"anz_{sym}")], [InlineKeyboardButton("⬅️ Back", callback_data="home")]]
        await q.edit_message_text(f"📍 Selected: **{sym}**", reply_markup=InlineKeyboardMarkup(keys), parse_mode='Markdown')
    
    elif q.data.startswith("anz_"):
        sym = q.data.split("_")[1]
        sig, st, sup, res, p = await get_signal(sym)
        text = f"📊 **{sym}**\n💰 Price: `{p}`\n🎯 Signal: **{sig}**\n⚡ Strength: `{st}%`"
        sent = await c.bot.send_message(q.message.chat_id, text, parse_mode='Markdown')
        asyncio.create_task(delete_msg(c, q.message.chat_id, sent.message_id))
    
    elif q.data == "home":
        await q.edit_message_text("💎 **Forex Scalper Pro**\nSelect pair:", reply_markup=main_menu(), parse_mode='Markdown')

if __name__ == '__main__':
    keep_alive()
    # نظام الـ concurrent للتعامل مع آلاف المستخدمين
    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.run_polling()
