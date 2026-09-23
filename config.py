import os
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Cấu hình Model AI Gemini (Chính & Dự phòng)
GEMINI_PRIMARY_MODEL = 'gemini-3.5-flash-lite'   # Model chính: Hạn mức cao (1,500 req/ngày), siêu nhẹ, tốc độ cao
GEMINI_FALLBACK_MODEL = 'gemini-3.6-flash'        # Model phụ: Dự phòng khi cần thẩm định nâng cao

# Cấu hình sàn giao dịch Testnet
BINANCE_TESTNET_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
BINANCE_TESTNET_SECRET = os.getenv("BINANCE_TESTNET_SECRET")

BYBIT_TESTNET_API_KEY = os.getenv("BYBIT_TESTNET_API_KEY")
BYBIT_TESTNET_SECRET = os.getenv("BYBIT_TESTNET_SECRET")

USE_TESTNET = False                               # False: Paper Trading 100% (Giá thực tế từ sàn, không đặt lệnh tiền thật)
ACTIVE_TESTNET_EXCHANGES = ['binance', 'bybit']   # Dùng khi bật USE_TESTNET = True

# Cấu hình Song song 2 Sàn Paper Trading
PAPER_EXCHANGES = ['binance', 'bybit']            # Chạy mô phỏng đồng thời trên cả Binance và Bybit
INITIAL_PAPER_BALANCE_PER_EXCHANGE = 500.0        # Vốn khởi điểm $500 USDT cho MỖI sàn
INITIAL_PAPER_BALANCE = 500.0                     # Fallback

# Cấu hình Quản trị Vốn & Khối lượng vào lệnh (Position Sizing Mode)
POSITION_SIZING_MODE = os.getenv("POSITION_SIZING_MODE", "ATR_RISK")  # "ATR_RISK" (mặc định) hoặc "FIXED"
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", 0.015))    # Chấp nhận rủi ro 1.5% tài khoản / lệnh
MAX_POSITION_CAP_PCT = float(os.getenv("MAX_POSITION_CAP_PCT", 0.25)) # Khống chế tối đa không quá 25% tài khoản / lệnh
MIN_POSITION_AMOUNT_USDT = 10.0                                        # Mức vào lệnh tối thiểu sàn Binance
ORDER_AMOUNT_USDT = float(os.getenv("ORDER_AMOUNT_USDT", 50.0))        # Số vốn cố định khi chuyển sang chế độ "FIXED"

# Danh sách coin quét tín hiệu
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

# Cấu hình Chiến lược Bắn Tỉa Tối Ưu (Sniper Boost Quality Mode - Mặc định)
MIN_AI_CONFIDENCE_SCORE = 8       # Điểm AI tối thiểu để duyệt lệnh (>= 8/10)
USE_PARTIAL_TP = True             # Bật cơ chế chốt lời 2 giai đoạn (TP1 + TP2)
USE_ATR_STOPS = True              # Sử dụng SL/TP động theo biến động thị trường ATR
ATR_LENGTH = 14                   # Chu kỳ tính ATR

ATR_SL_MULTIPLIER = 1.4           # Cắt lỗ Trend mặc định (1.4x ATR)
ATR_TP1_MULTIPLIER = 1.5          # TP1 Trend mặc định (1.5x ATR - Chốt 35%)
ATR_TP2_MULTIPLIER = 5.5          # TP2 Trend Runner mặc định (5.5x ATR - Gồng 65%)
TP1_SHARE = 0.35                  # Tỷ trọng chốt ở TP1: 35%
TP2_SHARE = 0.65                  # Tỷ trọng chốt ở TP2: 65%

# Cấu hình bộ lọc kỹ thuật vùng mua Sniper mặc định
RSI_MIN = 42
RSI_MAX = 65
ADX_MIN = 20
VOL_RATIO_MIN = 1.0

# Cấu hình Cơ chế Kép Thích Ứng (Dual-Regime Engine: Trend + Sideway)
ENABLE_DUAL_REGIME = True         # Bật tự động chuyển chế độ và bắt đáy Sideway khi thị trường tích lũy
SIDEWAY_RSI_MAX = 38              # Ngưỡng RSI quá bán bắt đáy biên dưới Sideway (<= 38)
SIDEWAY_SL_ATR_MULT = 1.2         # Cắt lỗ chặt 1.2x ATR khi đánh Sideway (cắt lỗ sớm)
SIDEWAY_TP_ATR_MULT = 1.3         # Chốt lời mục tiêu 1.3x ATR hoặc tại SMA20 trục giữa
SIDEWAY_TP_MIN_PCT = 0.022        # Chốt lời tối thiểu +2.2%
SIDEWAY_MAX_HOLD_BARS = 16        # Giới hạn giữ lệnh tối đa 16 nến 1H (~16 giờ)

# ==============================================================================
# 🛡️ CẤU HÌNH BỘ 3 LỚP GIÁP BẢO VỆ PHÒNG THỦ (DEFENSIVE SHIELDS)
# ==============================================================================
ENABLE_BTC_MACRO_FILTER = True         # Giáp 1: BTC 1D < EMA50 & RSI < 45 -> Cấm bắt đáy Altcoin
ENABLE_PANIC_VOLUME_FILTER = True      # Giáp 2: Nến đỏ xả > 2.2x Volume -> Chặn bắt dao rơi
ENABLE_CONSECUTIVE_LOSS_COOLDOWN = True # Giáp 3: 2 lệnh SL liên tiếp trong 72h -> Tạm khóa coin 3 ngày
COOLDOWN_HOURS = 72                    # Thời gian tạm khóa coin (72 giờ / 3 ngày)

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

def calculate_position_size(account_balance: float, sl_pct: float) -> dict:
    """
    Tính toán khối lượng vào lệnh (Position Sizing) theo chuẩn Quản trị Rủi ro ATR:
    Khối lượng = (Tài khoản * Risk %) / SL %
    Có khống chế trần tối đa (MAX_POSITION_CAP_PCT) và sàn tối thiểu (MIN_POSITION_AMOUNT_USDT).
    """
    mode = getattr(config, "POSITION_SIZING_MODE", "ATR_RISK") if 'config' in globals() else POSITION_SIZING_MODE
    if mode == "FIXED" or sl_pct <= 0:
        fixed_val = getattr(config, "ORDER_AMOUNT_USDT", 50.0) if 'config' in globals() else ORDER_AMOUNT_USDT
        actual_sl = sl_pct if sl_pct > 0 else 0.02
        return {
            "mode": "FIXED",
            "position_size_usdt": fixed_val,
            "risk_usd": round(fixed_val * actual_sl, 2),
            "risk_pct": round((fixed_val * actual_sl) / max(account_balance, 1.0) * 100, 2),
            "is_capped": False
        }

    risk_pct = getattr(config, "RISK_PER_TRADE_PCT", 0.015) if 'config' in globals() else RISK_PER_TRADE_PCT
    max_cap_pct = getattr(config, "MAX_POSITION_CAP_PCT", 0.25) if 'config' in globals() else MAX_POSITION_CAP_PCT
    min_amt = getattr(config, "MIN_POSITION_AMOUNT_USDT", 10.0) if 'config' in globals() else MIN_POSITION_AMOUNT_USDT

    safe_balance = max(account_balance, 50.0)
    risk_usd = safe_balance * risk_pct
    raw_pos = risk_usd / sl_pct
    max_pos = safe_balance * max_cap_pct

    is_capped = raw_pos > max_pos
    final_pos = min(raw_pos, max_pos)
    final_pos = max(final_pos, min_amt)

    actual_risk_usd = final_pos * sl_pct
    actual_risk_pct = (actual_risk_usd / safe_balance) * 100

    return {
        "mode": "ATR_RISK",
        "position_size_usdt": round(final_pos, 2),
        "risk_usd": round(actual_risk_usd, 2),
        "risk_pct": round(actual_risk_pct, 2),
        "is_capped": is_capped
    }