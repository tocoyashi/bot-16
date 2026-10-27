import os
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import ccxt
import pandas as pd
import numpy as np
import requests
import time
import json
from datetime import datetime
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ================= Configuration =================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID')

TIMEFRAME_ENTRY = '15m'
LEVERAGE = 10

# ✅ وقف خسارة ثابت 1.5%
SL_PERCENT = 1.5

# ✅ هدفان فقط
TP1_PERCENT = 0.85
TP2_PERCENT = 2.0

# ✅ نافذة التداول: أول 15 ساعة من اليوم (00:00 - 15:00 UTC)
# تغطي: آسيا + أوروبا + أول ساعتين من أمريكا
TRADING_WINDOW_HOURS = 15

# Quality Filters
MIN_ATR_PERCENT = 0.03
VOLUME_LOOKBACK = 20
COOLDOWN_HOURS = 1
COOLDOWN_FILE = Path('cooldown.json')

# ✅ قائمة بيضاء بأزواج Futures الموثوقة فقط
WHITELIST = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
    "TRX/USDT", "LTC/USDT", "UNI/USDT", "ATOM/USDT", "XLM/USDT",
    "NEAR/USDT", "APT/USDT", "SUI/USDT", "ARB/USDT", "OP/USDT",
    "INJ/USDT", "FIL/USDT", "AAVE/USDT", "QNT/USDT", "FET/USDT",
    "RENDER/USDT", "TIA/USDT", "SEI/USDT", "PYTH/USDT", "STRK/USDT",
    "WLD/USDT", "ENA/USDT", "WIF/USDT", "BONK/USDT", "PEPE/USDT",
    "SHIB/USDT", "FLOKI/USDT", "BOME/USDT", "W/USDT", "JUP/USDT"
]

STABLECOINS = ['USDC/USDT', 'TUSD/USDT', 'DAI/USDT', 'FDUSD/USDT', 'USDP/USDT', 'PYUSD/USDT']
BLACKLIST = ['WXT/USDT', 'ANTFUN/USDT', 'UPC/USDT', 'RAIN/USDT', 'USD1/USDT', 'USDE/USDT', 'BEAT/USDT', 'AKE/USDT', 'MY/USDT', 'MBG/USDT', 'AIX/USDT', 'XPLK/USDT', 'ZAY/USDT', '9BIT/USDT', 'CYS/USDT', 'GOLD/USDT']


def _fmt(price):
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:,.4f}"
    else:
        return f"{price:,.6f}"


def load_cooldown():
    if COOLDOWN_FILE.exists():
        try:
            with open(COOLDOWN_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cooldown(data):
    try:
        with open(COOLDOWN_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save cooldown: {e}")


def is_on_cooldown(symbol, cooldown_data):
    if symbol not in cooldown_data:
        return False
    try:
        last_time = datetime.fromisoformat(cooldown_data[symbol])
        elapsed = (datetime.now() - last_time).total_seconds() / 3600
        return elapsed < COOLDOWN_HOURS
    except Exception:
        return False


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("Missing TELEGRAM_TOKEN or CHANNEL_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHANNEL_ID,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        if not r.json().get('ok'):
            print(f"Telegram error: {r.json().get('description')}")
    except Exception as e:
        print(f"Network error sending Telegram: {e}")


def get_mexc_data(symbol, timeframe, limit=150):
    exchange = ccxt.mexc({'enableRateLimit': True})
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df


def get_top_mexc_coins(limit=50):
    print(f"Fetching top {limit} coins by volume from MEXC...")
    exchange = ccxt.mexc({'enableRateLimit': True})
    try:
        tickers = exchange.fetch_tickers()
        usdt_pairs = []
        for symbol, ticker in tickers.items():
            if symbol in WHITELIST:
                vol = ticker.get('quoteVolume') or 0
                if vol > 200000:
                    usdt_pairs.append({'symbol': symbol, 'volume': vol})
        usdt_pairs.sort(key=lambda x: x['volume'], reverse=True)
        top = [p['symbol'] for p in usdt_pairs[:limit]]
        print(f"Top coins: {top[:5]} ... ({len(top)} total)")
        return top
    except Exception as e:
        print(f"Error fetching coins: {e}")
        return []


def calculate_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def in_trading_window():
    """أول 15 ساعة من اليوم (00:00 - 15:00 UTC)"""
    now_utc = datetime.utcnow()
    return now_utc.hour < TRADING_WINDOW_HOURS


# ══════════════════════════════════════════════════════════════
# ✅ الاستراتيجية الجديدة: تحديد الاتجاه بـ EMA 20/50
# ══════════════════════════════════════════════════════════════

def get_trend_from_ema(df, ema_short=20, ema_long=50):
    """
    يحدد الاتجاه بناءً على EMA 20 و EMA 50 (بشكل مرن):
    
    لـ LONG:
    - EMA 20 > EMA 50 (شرط أساسي)
    - السعر فوق EMA 20 أو EMA 50 (أي واحد مقبول)
    
    لـ SHORT:
    - EMA 20 < EMA 50 (شرط أساسي)
    - السعر تحت EMA 20 أو EMA 50 (أي واحد مقبول)
    """
    if len(df) < ema_long + 5:
        return None
    
    df['ema20'] = df['close'].ewm(span=ema_short, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=ema_long, adjust=False).mean()
    
    last_close = df['close'].iloc[-1]
    ema20 = df['ema20'].iloc[-1]
    ema50 = df['ema50'].iloc[-1]
    
    # LONG: EMA 20 > EMA 50 والسعر فوق EMA 20 أو EMA 50
    if ema20 > ema50 and (last_close > ema20 or last_close > ema50):
        return "LONG"
    
    # SHORT: EMA 20 < EMA 50 والسعر تحت EMA 20 أو EMA 50
    if ema20 < ema50 and (last_close < ema20 or last_close < ema50):
        return "SHORT"
    
    return None


def get_daily_bias(symbol):
    """
    الخطوة 1: تحديد الاتجاه من الفريم اليومي باستخدام EMA 20 و EMA 50
    """
    try:
        df = get_mexc_data(symbol, '1d', limit=100)
        if len(df) < 55:
            return None
        
        direction = get_trend_from_ema(df, 20, 50)
        
        if direction is None:
            print(f"  {symbol}: No clear trend on Daily timeframe (EMA 20/50)")
            return None
        
        return direction
    except Exception as e:
        print(f"  {symbol}: Daily bias error - {e}")
        return None


def confirm_trend_4h(symbol, expected_direction):
    """
    الخطوة 2: تأكيد الاتجاه من فريم 4 ساعات
    يجب أن يكون الاتجاه على 4H مطابقاً للاتجاه على 1D
    """
    try:
        df = get_mexc_data(symbol, '4h', limit=100)
        if len(df) < 55:
            return False
        
        direction = get_trend_from_ema(df, 20, 50)
        
        if direction == expected_direction:
            return True
        else:
            print(f"  {symbol}: 4H trend ({direction}) does not match Daily ({expected_direction})")
            return False
    except Exception as e:
        print(f"  {symbol}: 4H confirmation error - {e}")
        return False


def analyze_symbol(symbol, direction):
    """
    الخطوة 3: البحث عن إشارة الدخول على فريم 15 دقيقة
    """
    try:
        df_15m = get_mexc_data(symbol, TIMEFRAME_ENTRY, limit=100)
        if len(df_15m) < 55:
            return None

        # === Indicators on 15m ===
        df_15m['ema20'] = df_15m['close'].ewm(span=20, adjust=False).mean()
        df_15m['ema50'] = df_15m['close'].ewm(span=50, adjust=False).mean()

        # RSI
        delta = df_15m['close'].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df_15m['rsi'] = 100 - (100 / (1 + rs))

        # MACD Histogram
        ema12 = df_15m['close'].ewm(span=12, adjust=False).mean()
        ema26 = df_15m['close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        df_15m['macd_hist'] = macd_line - signal_line

        # ATR & Volume
        df_15m['atr'] = calculate_atr(df_15m, 14)
        df_15m['atr_pct'] = (df_15m['atr'] / df_15m['close']) * 100
        df_15m['vol_sma'] = df_15m['volume'].rolling(window=VOLUME_LOOKBACK).mean()

        # ✅ آخر شمعة 15m *مغلقة*
        i = -2
        ema20 = df_15m['ema20'].iloc[i]
        ema50 = df_15m['ema50'].iloc[i]
        rsi = df_15m['rsi'].iloc[i]
        rsi_prev = df_15m['rsi'].iloc[i-1]
        macd_hist = df_15m['macd_hist'].iloc[i]
        macd_hist_prev = df_15m['macd_hist'].iloc[i-1]
        atr = df_15m['atr'].iloc[i]
        atr_pct = df_15m['atr_pct'].iloc[i]
        vol_now = df_15m['volume'].iloc[i]
        vol_avg = df_15m['vol_sma'].iloc[i]
        candle_low = df_15m['low'].iloc[i]
        candle_high = df_15m['high'].iloc[i]
        entry = float(df_15m['close'].iloc[i])

        # === Quality Filters ===
        if pd.isna(atr_pct) or atr_pct < MIN_ATR_PERCENT:
            print(f"  {symbol}: ATR too low ({atr_pct:.3f}%)")
            return None

        if pd.isna(vol_avg) or vol_now < vol_avg * 0.3:
            print(f"  {symbol}: Volume too low")
            return None

        if pd.isna(rsi) or pd.isna(macd_hist):
            print(f"  {symbol}: Indicators not ready")
            return None

        # === دخول الارتداد من EMA 20 أو EMA 50 باتجاه الاتجاه العام ===
        confidence = 65

        if direction == "LONG":
            ema_aligned = ema20 > ema50
            # السعر لمس EMA 20 أو EMA 50 ثم ارتد
            touched_ema20 = candle_low <= ema20 * 1.002
            touched_ema50 = candle_low <= ema50 * 1.002
            touched = touched_ema20 or touched_ema50
            bounced = entry > ema20 or entry > ema50
            
            rsi_ok = 50 < rsi <= 75
            macd_ok = macd_hist > 0 or macd_hist > macd_hist_prev

            if not (ema_aligned and touched and bounced and rsi_ok and macd_ok):
                print(f"  {symbol}: No LONG setup (EMA20/50: {ema20:.4f}/{ema50:.4f}, RSI: {rsi:.1f}, MACD: {macd_hist:.5f})")
                return None

            if rsi_prev <= 50 < rsi:
                confidence += 10
            if macd_hist > 0:
                confidence += 5
            if vol_now > vol_avg * 1.2:
                confidence += 5

            sl = entry * (1 - SL_PERCENT / 100)
            tp1 = entry * (1 + TP1_PERCENT / 100)
            tp2 = entry * (1 + TP2_PERCENT / 100)

        else:  # SHORT
            ema_aligned = ema20 < ema50
            # السعر لمس EMA 20 أو EMA 50 ثم ارتد
            touched_ema20 = candle_high >= ema20 * 0.998
            touched_ema50 = candle_high >= ema50 * 0.998
            touched = touched_ema20 or touched_ema50
            bounced = entry < ema20 or entry < ema50
            
            rsi_ok = 25 <= rsi < 50
            macd_ok = macd_hist < 0 or macd_hist < macd_hist_prev

            if not (ema_aligned and touched and bounced and rsi_ok and macd_ok):
                print(f"  {symbol}: No SHORT setup (EMA20/50: {ema20:.4f}/{ema50:.4f}, RSI: {rsi:.1f}, MACD: {macd_hist:.5f})")
                return None

            if rsi_prev >= 50 > rsi:
                confidence += 10
            if macd_hist < 0:
                confidence += 5
            if vol_now > vol_avg * 1.2:
                confidence += 5

            sl = entry * (1 + SL_PERCENT / 100)
            tp1 = entry * (1 - TP1_PERCENT / 100)
            tp2 = entry * (1 - TP2_PERCENT / 100)

        confidence = min(95, confidence)
        if confidence < 60:
            print(f"  {symbol}: Confidence too low ({confidence}%)")
            return None

        return {
            'symbol': symbol,
            'direction': direction,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'confidence': confidence,
            'atr_pct': atr_pct
        }

    except Exception as e:
        print(f"  {symbol}: Error - {e}")
        return None


def build_message(signal):
    """
    ✅ الصيغة القياسية المتوافقة مع Cornix
    - # قبل اسم الزوج ليتعرف Cornix على العملة فوراً
    - Entry: Market للدخول الفوري (بدون انتظار)
    """
    pair = signal['symbol'].replace('/', '')
    direction = signal['direction']
    icon = "🟢" if direction == "LONG" else "🔴"
    
    msg = f"""{icon} #{pair} {direction}

📌 Entry: Market
🎯 Take Profit:
✅ TP1: {_fmt(signal['tp1'])}
✅ TP2: {_fmt(signal['tp2'])}

🛑 Stop Loss: {_fmt(signal['sl'])}

⚙️ Leverage: Cross {LEVERAGE}x
⏰ Trading Hours: 00:00 to 15:00 UTC

-----------
Trade Crypto Forex & Gold  
Don't Miss The Daily prizes
https://bingx.com/invite/0S0T4S"""
    
    return msg


def main():
    print("=" * 50)
    print("Multi-Timeframe EMA Bot (v5.0)")
    print("Strategy: EMA 20/50 on 1D + 4H + 15m")
    print(f"Time (UTC): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("ERROR: TELEGRAM_TOKEN and CHANNEL_ID must be set!")
        return

    # ✅ فلتر النافذة الزمنية: أول 15 ساعة فقط
    if not in_trading_window():
        print(f"Outside trading window (allowed: 00:00–{TRADING_WINDOW_HOURS:02d}:00 UTC). Exiting.")
        return

    top_coins = get_top_mexc_coins(50)
    if not top_coins:
        print("No coins fetched. Aborting.")
        return

    cooldown_data = load_cooldown()
    signals_sent = 0
    skipped_cooldown = 0
    skipped_filter = 0
    daily_bias_cache = {}

    print("\nScanning coins (Multi-Timeframe Analysis)...")
    for symbol in top_coins:
        try:
            if is_on_cooldown(symbol, cooldown_data):
                skipped_cooldown += 1
                continue

            # 1️⃣ الخطوة الأولى: تحديد الاتجاه من الفريم اليومي (EMA 20/50)
            if symbol not in daily_bias_cache:
                time.sleep(0.3)
                daily_bias_cache[symbol] = get_daily_bias(symbol)

            direction = daily_bias_cache[symbol]
            if direction is None:
                skipped_filter += 1
                continue

            # 2️⃣ الخطوة الثانية: تأكيد الاتجاه من فريم 4 ساعات
            time.sleep(0.3)
            if not confirm_trend_4h(symbol, direction):
                skipped_filter += 1
                continue

            # 3️⃣ الخطوة الثالثة: البحث عن إشارة الدخول على فريم 15 دقيقة
            time.sleep(0.6)
            signal = analyze_symbol(symbol, direction)

            if signal is None:
                skipped_filter += 1
                continue

            msg = build_message(signal)
            send_telegram(msg)
            cooldown_data[symbol] = datetime.now().isoformat()
            signals_sent += 1
            print(f"  ✅ SIGNAL SENT: {symbol} {signal['direction']} (Conf: {signal['confidence']}%)")
            time.sleep(1.5)

        except Exception as e:
            print(f"  {symbol}: Exception - {e}")

    save_cooldown(cooldown_data)
    print(f"\n🏁 Done. Signals: {signals_sent} | Cooldown skipped: {skipped_cooldown} | Filter skipped: {skipped_filter}")


if __name__ == "__main__":
    main()
