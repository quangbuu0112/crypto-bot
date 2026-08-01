import ccxt
import pandas as pd
import pandas_ta as ta

exchange = ccxt.binance({'enableRateLimit': True})

def fetch_ohlcv_data(symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
    """Lấy dữ liệu nến từ Binance và chuyển thành Pandas DataFrame"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"❌ Lỗi kết nối API Binance ({symbol} - {timeframe}): {e}")
        return None

def analyze_technical_signal(symbol: str):
    """
    Phân tích kỹ thuật Đa khung thời gian (4H Trend + 1H Entry).
    Nếu thỏa mãn, trả về dict thông số kỹ thuật. Ngược lại trả về None.
    """
    df_4h = fetch_ohlcv_data(symbol, timeframe="4h", limit=300)
    df_1h = fetch_ohlcv_data(symbol, timeframe="1h", limit=100)

    if df_4h is None or df_1h is None:
        return None

    # 1. KIỂM TRA KHUNG 4H (BỘ LỌC XU HƯỚNG)
    df_4h['EMA_200_4h'] = ta.ema(df_4h['close'], length=200)
    is_uptrend_4h = df_4h['close'].iloc[-2] > df_4h['EMA_200_4h'].iloc[-2]

    # Nếu 4H không phải Uptrend -> Bỏ qua ngay
    if not is_uptrend_4h:
        return None

    # 2. KIỂM TRA KHUNG 1H (BỘ LỌC VÀO LỆNH)
    df_1h['EMA_20_1h'] = ta.ema(df_1h['close'], length=20)
    df_1h['RSI_1h'] = ta.rsi(df_1h['close'], length=14)
    
    adx_df = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
    df_1h['ADX_14_1h'] = adx_df['ADX_14']
    df_1h['VOL_MA20_1h'] = df_1h['volume'].rolling(20).mean()

    # Nến 1H vừa đóng cửa (iloc[-2])
    past_candle = df_1h.iloc[-2]

    cond_ema = past_candle['close'] > past_candle['EMA_20_1h']
    cond_rsi = 50 < past_candle['RSI_1h'] < 68
    cond_adx = past_candle['ADX_14_1h'] > 20
    cond_vol = past_candle['volume'] > (1.1 * past_candle['VOL_MA20_1h'])

    # Nếu thỏa mãn toàn bộ bộ lọc Kỹ thuật
    if cond_ema and cond_rsi and cond_adx and cond_vol:
        # Tóm tắt 5 nến 1H gần nhất làm chuỗi text cho Gemini
        last_5_candles = df_1h.iloc[-6:-1]
        candles_summary = ""
        for _, row in last_5_candles.iterrows():
            candles_summary += (
                f"- Nến {row['timestamp'].strftime('%H:%M')}: "
                f"O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}\n"
            )

        vol_ratio = past_candle['volume'] / past_candle['VOL_MA20_1h']

        return {
            "symbol": symbol,
            "entry_price": float(past_candle['close']),
            "rsi": float(past_candle['RSI_1h']),
            "adx": float(past_candle['ADX_14_1h']),
            "vol_ratio": float(vol_ratio),
            "candles_summary": candles_summary,
            "closed_time": past_candle['timestamp'].strftime('%Y-%m-%d %H:%M UTC')
        }

    return None