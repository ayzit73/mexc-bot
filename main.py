import ccxt
import pandas as pd
import requests
import os
import time
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread
import atexit
from dotenv import load_dotenv

# Ortam değişkenlerini yükle
load_dotenv()

# Telegram bilgileri
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

print(f"Telegram Token: {'✓ Loaded' if TELEGRAM_TOKEN else '✗ Missing'}")
print(f"Chat ID: {'✓ Loaded' if TELEGRAM_CHAT_ID else '✗ Missing'}")

def send_telegram_alert(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print(f"✓ Telegram mesajı gönderildi: {message[:50]}...")
        else:
            print(f"✗ Telegram hatası: {response.status_code} - {response.text}")
        return response
    except Exception as e:
        print(f"✗ Telegram bağlantı hatası: {e}")
        return None

# MEXC Futures borsası
exchange = ccxt.mexc({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

# Takip edilecek coinler
coin_list = [
    'PENGU', 'PROM', 'FUN', 'QNT', 'SYRUP', 'HYPE', 'BID', 'SPX',
    'MKR', 'AAVE', 'BNT', 'JST', 'CAKE', 'KAVA', 'CHEEMS', 'NEIROETH',
    'FARTCOIN', 'SUN', 'PENDLE', 'AVA', 'SEI', 'JELLYJELLY', 'BONK'
]

symbols_to_check = [f"{coin}/USDT" for coin in coin_list]

def check_ma_signals():
    try:
        print(f"🔍 MA sinyalleri kontrol ediliyor... {pd.Timestamp.now()}")
        markets = exchange.load_markets()
        available_symbols = set(markets.keys())
        alert_list = []
        checked_count = 0

        for symbol in symbols_to_check:
            if symbol not in available_symbols:
                print(f"⚠️ {symbol} MEXC'de bulunamadı")
                continue
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
                df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
                df['ma7'] = df['close'].rolling(window=7).mean()
                df['ma25'] = df['close'].rolling(window=25).mean()

                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                df['rsi'] = 100 - (100 / (1 + rs))

                condition = df['ma7'] < df['ma25']

                consecutive_hours = 0
                start_index = None
                for i in range(len(condition)-1, -1, -1):
                    if condition.iloc[i]:
                        consecutive_hours += 1
                        start_index = i
                    else:
                        break

                start_date = None
                if start_index is not None:
                    start_date = pd.to_datetime(df['time'].iloc[start_index], unit='ms')

                current_price = df['close'].iloc[-1]
                ma7_current = df['ma7'].iloc[-1]
                ma25_current = df['ma25'].iloc[-1]
                rsi_value = df['rsi'].iloc[-1]

                print(f"📊 {symbol}: Fiyat={current_price:.4f}, MA7={ma7_current:.4f}, MA25={ma25_current:.4f}, RSI={rsi_value:.2f}")

                if condition.iloc[-1]:
                    if rsi_value >= 70:
                        rsi_emoji = "🔴"
                    elif rsi_value <= 30:
                        rsi_emoji = "🟢"
                    else:
                        rsi_emoji = "⚪"

                    coin_name = symbol.replace('/USDT', '')
                    if start_date:
                        start_date_str = start_date.strftime("%d.%m %H:%M")
                        alert_list.append(f"{coin_name} ({start_date_str}|{consecutive_hours}h) RSI:{rsi_value:.1f}{rsi_emoji}")
                    else:
                        alert_list.append(f"{coin_name} ({consecutive_hours}h) RSI:{rsi_value:.1f}{rsi_emoji}")

                    print(f"🚨 ALERT: {symbol} MA7 < MA25 durumu tespit edildi! Başlangıç: {start_date_str if start_date else 'Bilinmiyor'}")

                checked_count += 1
            except Exception as e:
                print(f"❌ {symbol} hatası: {e}")

        print(f"✅ {checked_count} coin kontrol edildi, {len(alert_list)} alert bulundu")

        if alert_list:
            msg = "🔻 MA(7) < MA(25) 1H (MEXC):\n" + '\n'.join(alert_list)
            send_telegram_alert(msg)
        else:
            print("ℹ️ Hiçbir coin'de MA(7) < MA(25) koşulu sağlanmıyor")

    except Exception as e:
        error_msg = f"Bot hatası: {e}"
        print(f"❌ {error_msg}")
        send_telegram_alert(error_msg)

# Flask uygulaması
app = Flask('')

@app.route('/')
def home():
    return "MEXC MA Alert Bot is running!"

@app.route('/test')
def manual_test():
    print("🧪 Manuel test başlatıldı")
    check_ma_signals()
    return "Manuel test tamamlandı! Konsol loglarını kontrol edin."

@app.route('/status')
def status():
    return f"""
    <h2>Bot Durumu</h2>
    <p>Token: {'✓' if TELEGRAM_TOKEN else '✗'}</p>
    <p>Chat ID: {'✓' if TELEGRAM_CHAT_ID else '✗'}</p>
    <p>Kontrol edilen coinler: {len(coin_list)}</p>
    <p>Kontrol aralığı: 1 dakika</p>
    <a href="/test">Manuel Test Çalıştır</a>
    """

def run_web():
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

scheduler = None

def start_bot():
    global scheduler
    print("Bot başlatılıyor...")

    if scheduler and scheduler.running:
        try:
            scheduler.shutdown(wait=False)
        except:
            pass

    check_ma_signals()

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(check_ma_signals, 'interval', minutes=1, max_instances=1)
    scheduler.start()
    print(f"✅ Bot başarıyla başlatıldı. Her 1 dakikada bir kontrol yapacak.")

    atexit.register(lambda: scheduler.shutdown() if scheduler and scheduler.running else None)

if __name__ == "__main__":
    try:
        # Flask ve botu ayrı threadlerde çalıştır
        Thread(target=run_web, daemon=True).start()
        start_bot()

        # Ana thread açık kalsın
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        if scheduler and scheduler.running:
            scheduler.shutdown()
        print("Bot durduruldu.")
