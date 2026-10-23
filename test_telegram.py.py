import os
import requests

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHANNEL_ID')

print(f"Testing with Token: {TOKEN[:10]}... and Chat ID: {CHAT_ID}")

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    'chat_id': CHAT_ID,
    'text': '✅ اختبار ناجح! البوت متصل بالقناة بشكل صحيح.',
    'parse_mode': 'HTML'
}

response = requests.post(url, json=payload)
print("Telegram API Response:", response.json())