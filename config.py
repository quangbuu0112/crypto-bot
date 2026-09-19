import os
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Cấu hình sàn giao dịch Testnet
BINANCE_TESTNET_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
BINANCE_TESTNET_SECRET = os.getenv("BINANCE_TESTNET_SECRET")

BYBIT_TESTNET_API_KEY = os.getenv("BYBIT_TESTNET_API_KEY")
BYBIT_TESTNET_SECRET = os.getenv("BYBIT_TESTNET_SECRET")

USE_TESTNET = True                                # True: Bật đặt lệnh thật trên các sàn Testnet
ACTIVE_TESTNET_EXCHANGES = ['binance', 'bybit']   # Chạy song song cả 2 sàn!
ORDER_AMOUNT_USDT = 50.0                          # Số vốn USDT cho mỗi lệnh trên mỗi sàn

# Danh sách coin quét tín hiệu
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

# Cấu hình quản trị vốn (Risk / Reward)
USE_ATR_STOPS = True         # Sử dụng Stop Loss / Take Profit động theo ATR
ATR_LENGTH = 14              # Chu kỳ tính ATR
ATR_SL_MULTIPLIER = 1.5      # Cắt lỗ = Entry - 1.5 * ATR (khoảng 1.5% - 2.5% tùy biến động)
ATR_TP_MULTIPLIER = 3.0      # Chốt lời = Entry + 3.0 * ATR (tỷ lệ Risk/Reward = 1 : 2)

# Cấu hình dự phòng cố định (dùng khi không bật ATR hoặc không có dữ liệu ATR)
STOP_LOSS_PCT = 0.02         # Cắt lỗ 2.0% (nới rộng so với 1.0% cũ để tránh quét râu nến)
TAKE_PROFIT_PCT = 0.04       # Chốt lời 4.0% (tỷ lệ Risk/Reward = 1 : 2)

# Cấu hình thời gian
SLEEP_INTERVAL_SECONDS = 900  # Quét lại sau mỗi 15 phút