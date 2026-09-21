import os
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Cấu hình Model AI Gemini (Chính & Dự phòng)
GEMINI_PRIMARY_MODEL = 'gemini-3.6-flash'        # Model chính: Flash thế hệ mới, hạn mức cao
GEMINI_FALLBACK_MODEL = 'gemini-3.5-flash-lite'   # Model phụ: Siêu nhẹ, dự phòng khi model chính bận

# Cấu hình sàn giao dịch Testnet
BINANCE_TESTNET_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
BINANCE_TESTNET_SECRET = os.getenv("BINANCE_TESTNET_SECRET")

BYBIT_TESTNET_API_KEY = os.getenv("BYBIT_TESTNET_API_KEY")
BYBIT_TESTNET_SECRET = os.getenv("BYBIT_TESTNET_SECRET")

USE_TESTNET = False                               # False: Paper Trading 100% (Giá thực tế từ sàn Binance, không đặt lệnh tiền thật)
ACTIVE_TESTNET_EXCHANGES = ['binance', 'bybit']   # Dùng khi bật USE_TESTNET = True
ORDER_AMOUNT_USDT = 50.0                          # Số vốn mô phỏng USDT cho mỗi lệnh

# Danh sách coin quét tín hiệu
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

# Cấu hình Chiến lược Bắn Tỉa Chất Lượng Cao (Sniper Quality Mode)
MIN_AI_CONFIDENCE_SCORE = 8       # Điểm AI tối thiểu để duyệt lệnh (>= 8/10)
USE_PARTIAL_TP = True             # Bật cơ chế chốt lời 2 giai đoạn (TP1 + TP2)
USE_ATR_STOPS = True              # Sử dụng SL/TP động theo biến động thị trường ATR
ATR_LENGTH = 14                   # Chu kỳ tính ATR

ATR_SL_MULTIPLIER = 1.4           # Cắt lỗ ban đầu = Entry - 1.4 * ATR (khoảng 1.5% - 2.2%)
ATR_TP1_MULTIPLIER = 1.2          # Chốt lời TP1 = Entry + 1.2 * ATR (Chốt 50% vị thế, dời SL về Entry hòa vốn)
ATR_TP2_MULTIPLIER = 3.0          # Chốt lời TP2 = Entry + 3.0 * ATR (Gồng 50% vị thế còn lại)

# Cấu hình bộ lọc kỹ thuật vùng mua Sniper
RSI_MIN = 42                      # Ngưỡng dưới RSI (tránh thị trường quá yếu)
RSI_MAX = 65                      # Ngưỡng trên RSI (tránh mua đu đỉnh quá mua)
ADX_MIN = 20                      # Ngưỡng ADX tối thiểu (bắt buộc có lực đẩy xu hướng)
VOL_RATIO_MIN = 1.0               # Khối lượng nến >= 1.0x trung bình 20 phiên

# Cấu hình dự phòng cố định (khi không có ATR)
STOP_LOSS_PCT = 0.02              # Cắt lỗ 2.0%
TAKE_PROFIT_PCT = 0.04            # Chốt lời 4.0%

# Cấu hình thời gian
SLEEP_INTERVAL_SECONDS = 900      # Quét lại sau mỗi 15 phút