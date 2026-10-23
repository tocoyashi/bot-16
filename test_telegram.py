import os
import requests

# يبحث عن TELEGRAM_TOKEN أولاً، ثم BOT_TOKEN كخيار احتياطي
TOKEN = os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHANNEL_ID')

if not TOKEN or not CHAT_ID:
    print("❌ خطأ: تأكد من وجود TELEGRAM_TOKEN و CHANNEL_ID في متغيرات البيئة.")
else:
    print(f"Testing with Token: {TOKEN[:10]}... and Chat ID: {CHAT_ID}")
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': '✅ اختبار ناجح! البوت متصل بالقناة بشكل صحيح.',
        'parse_mode': 'HTML'
    }
    
    response = requests.post(url, json=payload)
    print("Telegram API Response:", response.json())
