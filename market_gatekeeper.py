import time
import requests
import ccxt
import pandas as pd
import pandas_ta as ta
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import config

# Khởi tạo Gemini Client & Binance Exchange
client = genai.Client(api_key=config.GEMINI_API_KEY)
exchange = ccxt.binance({'enableRateLimit': True})

# Cache kết quả kiểm tra thị trường để tránh gọi API liên tục
_cached_market_health = None
_last_check_time = 0
CACHE_DURATION_SECONDS = 900  # 15 phút


class MarketHealthReport(BaseModel):
    market_regime: str = Field(
        description="Chế độ thị trường: 'BULLISH_SAFE', 'CHOPPY_CAUTION', hoặc 'BEARISH_DANGER'"
    )
    can_open_trades: bool = Field(
        description="True nếu an toàn để mở lệnh mua Altcoin, False nếu BTC đang xấu/rủi ro cao"
    )
    min_confidence_score: int = Field(
        description="Ngưỡng điểm tin cậy AI tối thiểu cho Altcoin (7 nếu BULLISH_SAFE, 8 nếu CHOPPY_CAUTION, 10 nếu BEARISH_DANGER)"
    )
    fng_summary: str = Field(
        description="Đánh giá ngắn gọn về chỉ số Fear & Greed"
    )
    summary: str = Field(
        description="Tóm tắt 1-2 câu về bối cảnh BTC và quyết định điều phối lệnh"
    )


def fetch_fear_and_greed() -> dict:
    """Lấy chỉ số Crypto Fear & Greed Index từ Alternative.me"""
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", [])
            if data:
                return {
                    "value": int(data[0].get("value", 50)),
                    "classification": data[0].get("value_classification", "Neutral")
                }
    except Exception as e:
        print(f"⚠️ Không thể lấy chỉ số Fear & Greed: {e}")
    return {"value": 50, "classification": "Neutral"}


def fetch_btc_overview() -> dict:
    """Lấy dữ liệu nến 4H và 1H của BTC/USDT để phân tích bối cảnh"""
    try:
        ohlcv_4h = exchange.fetch_ohlcv('BTC/USDT', timeframe='4h', limit=250)
        df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_4h['EMA_50'] = ta.ema(df_4h['close'], length=50)
        df_4h['EMA_200'] = ta.ema(df_4h['close'], length=200)

        ohlcv_1h = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=10)
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='ms')

        past_4h = df_4h.iloc[-2]
        latest_1h = df_1h.iloc[-2]

        is_uptrend = (past_4h['close'] > past_4h['EMA_50']) and (past_4h['EMA_50'] > past_4h['EMA_200'])
        is_downtrend = (past_4h['close'] < past_4h['EMA_50']) and (past_4h['EMA_50'] < past_4h['EMA_200'])

        trend_desc = "UPTREND MẠNH (Giá > EMA50 > EMA200)" if is_uptrend else (
            "DOWNTREND (Giá < EMA50 < EMA200)" if is_downtrend else "SIDEWAY / PHÂN KỲ"
        )

        last_4_candles = df_1h.iloc[-5:-1]
        candles_summary = ""
        for _, row in last_4_candles.iterrows():
            candles_summary += (
                f"- Nến {row['timestamp'].strftime('%H:%M')}: "
                f"O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}\n"
            )

        return {
            "btc_price": float(latest_1h['close']),
            "trend_4h": trend_desc,
            "ema50_4h": float(past_4h['EMA_50']),
            "ema200_4h": float(past_4h['EMA_200']),
            "candles_summary": candles_summary
        }
    except Exception as e:
        print(f"❌ Lỗi lấy dữ liệu BTC overview: {e}")
        return None


def check_market_health(force_refresh: bool = False) -> MarketHealthReport:
    """
    Sử dụng Gemini làm Macro Gatekeeper:
    Đánh giá sức khỏe thị trường BTC và tâm lý Fear & Greed trước khi cho phép bot quét Altcoin.
    """
    global _cached_market_health, _last_check_time

    now = time.time()
    if not force_refresh and _cached_market_health and (now - _last_check_time < CACHE_DURATION_SECONDS):
        return _cached_market_health

    btc_data = fetch_btc_overview()
    fng_data = fetch_fear_and_greed()

    if not btc_data:
        # Fallback an toàn nếu lỗi mạng kết nối tới Binance
        return MarketHealthReport(
            market_regime="CHOPPY_CAUTION",
            can_open_trades=True,
            min_confidence_score=7,
            fng_summary=f"F&G: {fng_data['value']}/100 ({fng_data['classification']})",
            summary="Không lấy được dữ liệu nến BTC, sử dụng chế độ dự phòng."
        )

    prompt = f"""
    Bạn là Giám đốc Quản lý Quỹ Crypto (Crypto Portfolio Risk Manager).
    Trước khi hệ thống thuật toán mở bất kỳ vị thế Mua (Long) nào cho các Altcoin (ETH, SOL, BNB, XRP),
    nhiệm vụ của bạn là đánh giá BỐI CẢNH VĨ MÔ TOÀN THỊ TRƯỜNG để đảm bảo không vào lệnh khi thị trường sắp sập.

    === THÔNG SỐ VĨ MÔ HIỆN TẠI ===
    • Giá BTC hiện tại: ${btc_data['btc_price']:.2f}
    • Xu hướng BTC khung 4H: {btc_data['trend_4h']} (EMA50: ${btc_data['ema50_4h']:.2f}, EMA200: ${btc_data['ema200_4h']:.2f})
    • Diễn biến 4 nến 1H gần nhất của BTC:
{btc_data['candles_summary']}
    • Chỉ số Crypto Fear & Greed Index: {fng_data['value']}/100 ({fng_data['classification']})

    === QUY TẮC PHÂN LOẠI THỊ TRƯỜNG ===
    1. 'BEARISH_DANGER' (can_open_trades = False, min_confidence_score = 10):
       - BTC đang xuất hiện nến xả mạnh (râu trên dài, nhấn chìm giảm, nến đỏ đặc biên độ lớn).
       - Hoặc BTC nằm dưới cả EMA50 và EMA200 trong xu hướng giảm mạnh.
       - Tác động: Khóa toàn bộ lệnh mua Altcoin vì Altcoin sẽ sập mạnh hơn BTC!

    2. 'CHOPPY_CAUTION' (can_open_trades = True, min_confidence_score = 8):
       - BTC đang đi ngang, nến doji râu hai đầu, hoặc chỉ số F&G ở mức Quá Tham Lam (> 80) dễ có điều chỉnh giật râu.
       - Tác động: Chỉ cho phép vào lệnh Altcoin nếu điểm chất lượng cực cao (>= 8/10).

    3. 'BULLISH_SAFE' (can_open_trades = True, min_confidence_score = 7):
       - BTC giữ vững cấu trúc tăng (Uptrend 4H) hoặc tích lũy lành mạnh, không có dấu hiệu xả hàng.
       - Tác động: Cho phép mở lệnh Altcoin bình thường.
    """

    models_to_try = [
        getattr(config, 'GEMINI_PRIMARY_MODEL', 'gemini-3.6-flash'),
        getattr(config, 'GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')
    ]

    last_error = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MarketHealthReport,
                    temperature=0.1,
                ),
            )
            report = MarketHealthReport.model_validate_json(response.text)
            _cached_market_health = report
            _last_check_time = now
            return report
        except Exception as e:
            last_error = e
            print(f"[CANH BAO] [Gatekeeper] Model {model_name} gap su co: {e}. Dang chuyen sang model tiep theo...")
            time.sleep(1)

    print(f"[LOI] Khong the goi bat ky Gemini Macro Gatekeeper model nao: {last_error}")
    # Fallback an toàn
    return MarketHealthReport(
        market_regime="CHOPPY_CAUTION",
        can_open_trades=True,
        min_confidence_score=7,
        fng_summary=f"F&G: {fng_data['value']}/100 ({fng_data['classification']})",
        summary=f"Loi goi AI Gatekeeper: {last_error}"
    )
