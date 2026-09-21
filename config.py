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
ORDER_AMOUNT_USDT = float(os.getenv("ORDER_AMOUNT_USDT", 50.0))  # Số vốn mô phỏng USDT cho mỗi lệnh

# Danh sách coin quét tín hiệu
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

# Cấu hình Chiến lược Bắn Tỉa Tối Ưu (Sniper Boost Quality Mode - Mặc định)
MIN_AI_CONFIDENCE_SCORE = 8       # Điểm AI tối thiểu để duyệt lệnh (>= 8/10)
USE_PARTIAL_TP = True             # Bật cơ chế chốt lời 2 giai đoạn (TP1 + TP2)
USE_ATR_STOPS = True              # Sử dụng SL/TP động theo biến động thị trường ATR
ATR_LENGTH = 14                   # Chu kỳ tính ATR

ATR_SL_MULTIPLIER = 1.4           # Cắt lỗ mặc định
ATR_TP1_MULTIPLIER = 1.2          # TP1 mặc định (Chốt 30%)
ATR_TP2_MULTIPLIER = 3.5          # TP2 mặc định (Gồng 70%)
TP1_SHARE = 0.3                   # Tỷ trọng chốt ở TP1: 30%
TP2_SHARE = 0.7                   # Tỷ trọng chốt ở TP2: 70%

# Cấu hình bộ lọc kỹ thuật vùng mua Sniper mặc định
RSI_MIN = 42
RSI_MAX = 65
ADX_MIN = 20
VOL_RATIO_MIN = 1.0

# ==============================================================================
# 🎯 CẤU HÌNH TỐI ƯU HÓA ĐẶC THÙ RIÊNG CHO TỪNG ĐỒNG COIN (COIN-SPECIFIC TUNING)
# ==============================================================================
COIN_CUSTOM_CONFIG = {
    'SOL/USDT': {
        'atr_sl': 1.6, 'tp1_mult': 1.0, 'tp2_mult': 3.0,
        'rsi_min': 40, 'rsi_max': 66, 'adx_min': 22, 'vol_mult': 1.1,
        'tp1_share': 0.3, 'tp2_share': 0.7,
        'desc': 'Nới SL 1.6x tránh quét râu, TP1 1.0x khóa hòa vốn siêu nhanh (WinRate 76%)'
    },
    'XRP/USDT': {
        'atr_sl': 1.6, 'tp1_mult': 1.0, 'tp2_mult': 3.5,
        'rsi_min': 40, 'rsi_max': 66, 'adx_min': 22, 'vol_mult': 0.9,
        'tp1_share': 0.3, 'tp2_share': 0.7,
        'desc': 'Bắt nhịp bơm xả, TP1 1.0x an toàn, TP2 3.5x gồng lãi cực đại (PnL +51.7%)'
    },
    'ETH/USDT': {
        'atr_sl': 1.6, 'tp1_mult': 1.5, 'tp2_mult': 4.0,
        'rsi_min': 40, 'rsi_max': 62, 'adx_min': 22, 'vol_mult': 0.9,
        'tp1_share': 0.3, 'tp2_share': 0.7,
        'desc': 'Gồng trend DeFi lớn, TP2 4.0x đạt Profit Factor 1.95x'
    },
    'BTC/USDT': {
        'atr_sl': 1.2, 'tp1_mult': 1.2, 'tp2_mult': 4.0,
        'rsi_min': 40, 'rsi_max': 62, 'adx_min': 22, 'vol_mult': 1.1,
        'tp1_share': 0.3, 'tp2_share': 0.7,
        'desc': 'Biến động êm, SL chặt 1.2x, TP2 gồng xa 4.0x đạt Profit Factor 1.85x'
    },
    'BNB/USDT': {
        'atr_sl': 1.6, 'tp1_mult': 1.5, 'tp2_mult': 3.0,
        'rsi_min': 40, 'rsi_max': 66, 'adx_min': 22, 'vol_mult': 1.1,
        'tp1_share': 0.3, 'tp2_share': 0.7,
        'desc': 'Lọc chặt ADX >= 22 tránh sideway Launchpool, SL 1.6x giữ vị thế vững'
    },
}

def get_coin_config(symbol: str) -> dict:
    """Trả về cấu hình tối ưu riêng của từng đồng coin (nếu có) hoặc cấu hình chung"""
    custom = COIN_CUSTOM_CONFIG.get(symbol, {})
    return {
        'atr_sl': custom.get('atr_sl', ATR_SL_MULTIPLIER),
        'tp1_mult': custom.get('tp1_mult', ATR_TP1_MULTIPLIER),
        'tp2_mult': custom.get('tp2_mult', ATR_TP2_MULTIPLIER),
        'rsi_min': custom.get('rsi_min', RSI_MIN),
        'rsi_max': custom.get('rsi_max', RSI_MAX),
        'adx_min': custom.get('adx_min', ADX_MIN),
        'vol_mult': custom.get('vol_mult', VOL_RATIO_MIN),
        'tp1_share': custom.get('tp1_share', TP1_SHARE),
        'tp2_share': custom.get('tp2_share', TP2_SHARE),
        'desc': custom.get('desc', 'Cấu hình Sniper mặc định')
    }

# Cấu hình dự phòng cố định (khi không có ATR)
STOP_LOSS_PCT = 0.02              # Cắt lỗ 2.0%
TAKE_PROFIT_PCT = 0.04            # Chốt lời 4.0%

# Cấu hình thời gian
SLEEP_INTERVAL_SECONDS = 900      # Quét lại sau mỗi 15 phút