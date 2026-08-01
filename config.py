import os
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Danh sách coin quét tín hiệu
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

# Cấu hình quản trị vốn (Risk / Reward)
STOP_LOSS_PCT = 0.01     # Cắt lỗ 1.0%
TAKE_PROFIT_PCT = 0.015   # Chốt lời 1.5%

# Cấu hình thời gian
SLEEP_INTERVAL_SECONDS = 900  # Quét lại sau mỗi 15 phút