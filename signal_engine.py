import ccxt
import pandas as pd
import pandas_ta as ta
import config

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

def analyze_technical_signal(symbol: str) -> tuple:
    """
    Phân tích kỹ thuật Đa khung thời gian Thích ứng Kép (Dual-Regime Adaptive Engine).
    Tự động chọn 1 trong 2 chế độ:
      1. 🎯 SNIPER_TREND  : Khi 4H có Trend mạnh (Pullback EMA20, RSI tối ưu, gồng TP1/TP2)
      2. 📦 SIDEWAY_RANGE : Khi thị trường đi ngang (Bắt đáy dải dưới Lower BB, RSI quá bán <= 38, nến rút chân)
    Trả về: (tech_signal_dict, diagnostics_dict)
    """
    diagnostics = {
        "step2_trend_4h": None,
        "step3_trigger_1h": None
    }

    df_4h = fetch_ohlcv_data(symbol, timeframe="4h", limit=220)
    df_1h = fetch_ohlcv_data(symbol, timeframe="1h", limit=60)

    if df_4h is None or df_1h is None:
        diagnostics["step2_trend_4h"] = {
            "status": "ERROR",
            "detail": "Không thể kết nối lấy dữ liệu nến từ sàn Binance"
        }
        return None, diagnostics

    # 1. TÍNH TOÁN CHỈ BÁO KHUNG 4H
    df_4h['EMA_50_4h'] = ta.ema(df_4h['close'], length=50)
    df_4h['EMA_200_4h'] = ta.ema(df_4h['close'], length=200)
    past_4h = df_4h.iloc[-2]
    close_4h = float(past_4h['close'])
    ema50_4h = float(past_4h['EMA_50_4h'])
    ema200_4h = float(past_4h['EMA_200_4h'])

    is_uptrend_4h = (close_4h > ema50_4h) and (ema50_4h > ema200_4h)

    # 2. TÍNH TOÁN CHỈ BÁO KHUNG 1H
    df_1h['EMA_20_1h'] = ta.ema(df_1h['close'], length=20)
    df_1h['SMA_20_1h'] = ta.sma(df_1h['close'], length=20)
    df_1h['RSI_1h'] = ta.rsi(df_1h['close'], length=14)
    adx_df = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
    df_1h['ADX_14_1h'] = adx_df['ADX_14']
    df_1h['VOL_MA20_1h'] = df_1h['volume'].rolling(20).mean()
    df_1h['ATR_14_1h'] = ta.atr(df_1h['high'], df_1h['low'], df_1h['close'], length=config.ATR_LENGTH)

    bb = ta.bbands(df_1h['close'], length=20, std=2.0)
    df_1h['BBL'] = bb.iloc[:, 0]  # Lower band
    df_1h['BBM'] = bb.iloc[:, 1]  # Mid band
    df_1h['BBU'] = bb.iloc[:, 2]  # Upper band

    past_candle = df_1h.iloc[-2]
    open_1h = float(past_candle['open'])
    high_1h = float(past_candle['high'])
    low_1h = float(past_candle['low'])
    close_1h = float(past_candle['close'])
    ema20_1h = float(past_candle['EMA_20_1h'])
    sma20_1h = float(past_candle['SMA_20_1h'])
    rsi_1h = float(past_candle['RSI_1h'])
    adx_1h = float(past_candle['ADX_14_1h'])
    vol_1h = float(past_candle['volume'])
    vol_ma20 = float(past_candle['VOL_MA20_1h'])
    vol_ratio = (vol_1h / vol_ma20) if vol_ma20 > 0 else 0.0
    atr_val = float(past_candle['ATR_14_1h']) if pd.notna(past_candle['ATR_14_1h']) else (close_1h * 0.02)
    bbl_1h = float(past_candle['BBL'])

    coin_cfg = config.get_coin_config(symbol) if hasattr(config, 'get_coin_config') else {}
    rsi_min = coin_cfg.get('rsi_min', getattr(config, 'RSI_MIN', 42))
    rsi_max = coin_cfg.get('rsi_max', getattr(config, 'RSI_MAX', 65))
    adx_min = coin_cfg.get('adx_min', getattr(config, 'ADX_MIN', 20))
    vol_min = coin_cfg.get('vol_mult', getattr(config, 'VOL_RATIO_MIN', 1.0))
    sl_mult = coin_cfg.get('atr_sl', getattr(config, 'ATR_SL_MULTIPLIER', 1.4))
    tp1_mult = coin_cfg.get('tp1_mult', getattr(config, 'ATR_TP1_MULTIPLIER', 1.2))
    tp2_mult = coin_cfg.get('tp2_mult', getattr(config, 'ATR_TP2_MULTIPLIER', 3.5))
    tp1_share = coin_cfg.get('tp1_share', getattr(config, 'TP1_SHARE', 0.3))
    tp2_share = coin_cfg.get('tp2_share', getattr(config, 'TP2_SHARE', 0.7))

    strategy_type = None

    # =========================================================================
    # NHÁNH 1: CHIẾN LƯỢC SNIPER TREND FOLLOWING (Ưu tiên khi có sóng lớn)
    # =========================================================================
    if is_uptrend_4h:
        cond_ema = close_1h > ema20_1h
        cond_rsi = rsi_min <= rsi_1h <= rsi_max
        cond_adx = adx_1h >= adx_min
        cond_vol = vol_ratio >= vol_min
        cond_not_extended = (atr_val == 0) or ((close_1h - ema20_1h) <= 1.5 * atr_val)

        if cond_ema and cond_rsi and cond_adx and cond_vol and cond_not_extended:
            strategy_type = "SNIPER_TREND"
            diagnostics["step2_trend_4h"] = {
                "status": "PASS",
                "detail": f"Giá 4H (${close_4h:,.2f}) > EMA50 > EMA200 -> Uptrend chuẩn."
            }
            diagnostics["step3_trigger_1h"] = {
                "status": "PASS",
                "detail": f"🎯 [SNIPER TREND] Giá > EMA20, RSI={rsi_1h:.1f}, ADX={adx_1h:.1f}, Volume={vol_ratio:.2f}x."
            }

    # =========================================================================
    # NHÁNH 2: CHIẾN LƯỢC SIDEWAY RANGE MEAN REVERSION (Bắt đáy biên hộp)
    # =========================================================================
    enable_dual = getattr(config, 'ENABLE_DUAL_REGIME', True)
    if strategy_type is None and enable_dual:
        sideway_rsi_max = getattr(config, 'SIDEWAY_RSI_MAX', 38)
        is_touch_bbl = (low_1h <= bbl_1h * 1.002) or (close_1h <= bbl_1h * 1.005)
        is_oversold = rsi_1h <= sideway_rsi_max
        is_bullish_reversal = (close_1h >= open_1h) or ((close_1h - low_1h) >= 0.4 * (high_1h - low_1h + 1e-8))

        if is_touch_bbl and is_oversold and is_bullish_reversal:
            strategy_type = "SIDEWAY_RANGE"
            diagnostics["step2_trend_4h"] = {
                "status": "PASS",
                "detail": f"📦 [DUAL REGIME] Thị trường đi ngang/tích lũy (Kích hoạt chế độ Sideway Range)."
            }
            diagnostics["step3_trigger_1h"] = {
                "status": "PASS",
                "detail": f"📦 [SIDEWAY RANGE] Chạm đáy Lower BB (${bbl_1h:,.2f}), RSI quá bán={rsi_1h:.1f} <= {sideway_rsi_max}, Nến rút chân đảo chiều."
            }

    # =========================================================================
    # TỔNG HỢP VÀ ĐÓNG GÓI TÍN HIỆU
    # =========================================================================
    if strategy_type is None:
        if diagnostics["step2_trend_4h"] is None:
            diagnostics["step2_trend_4h"] = {
                "status": "REJECT",
                "detail": "Không có Uptrend 4H và không thỏa mãn điều kiện bắt đáy Sideway."
            }
        if diagnostics["step3_trigger_1h"] is None:
            diagnostics["step3_trigger_1h"] = {
                "status": "REJECT",
                "detail": f"RSI={rsi_1h:.1f}, ADX={adx_1h:.1f}, Giá=${close_1h:,.2f}, Lower BB=${bbl_1h:,.2f} -> Chưa có điểm vào lệnh đạt chuẩn."
            }
        return None, diagnostics

    entry_price = close_1h
    last_5_candles = df_1h.iloc[-6:-1]
    candles_summary = ""
    for _, row in last_5_candles.iterrows():
        candles_summary += (
            f"- Nến {row['timestamp'].strftime('%H:%M')}: "
            f"O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}\n"
        )

    if strategy_type == "SNIPER_TREND":
        stop_loss = entry_price - (sl_mult * atr_val)
        take_profit_1 = entry_price + (tp1_mult * atr_val)
        take_profit_2 = entry_price + (tp2_mult * atr_val)
        take_profit = take_profit_2
        sl_pct = (entry_price - stop_loss) / entry_price
        tp1_pct = (take_profit_1 - entry_price) / entry_price
        tp2_pct = (take_profit_2 - entry_price) / entry_price
        tp_pct = tp2_pct
        act_tp1_share = tp1_share
        act_tp2_share = tp2_share
        strategy_desc = f"🎯 SNIPER TREND: {coin_cfg.get('desc', 'Trend Pullback')}"
    else:
        # SIDEWAY RANGE: Cắt lỗ chặt 1.2x ATR, Chốt lời tại SMA20 hoặc tối thiểu +2.2%
        sideway_sl_mult = getattr(config, 'SIDEWAY_SL_ATR_MULT', 1.2)
        sideway_tp_min = getattr(config, 'SIDEWAY_TP_MIN_PCT', 0.022)
        stop_loss = entry_price - (sideway_sl_mult * atr_val)
        target_tp = max(sma20_1h, entry_price * (1 + sideway_tp_min))
        take_profit_1 = target_tp
        take_profit_2 = target_tp
        take_profit = target_tp
        sl_pct = (entry_price - stop_loss) / entry_price
        tp_pct = (take_profit - entry_price) / entry_price
        tp1_pct = tp_pct
        tp2_pct = tp_pct
        act_tp1_share = 1.0
        act_tp2_share = 0.0
        strategy_desc = "📦 SIDEWAY RANGE: Bắt đáy Lower BB + RSI quá bán, Chốt lời SMA20 / +2.2%"

    signal_data = {
        "symbol": symbol,
        "strategy_type": strategy_type,
        "strategy_desc": strategy_desc,
        "entry_price": entry_price,
        "rsi": rsi_1h,
        "adx": adx_1h,
        "vol_ratio": float(vol_ratio),
        "atr": atr_val,
        "stop_loss": float(stop_loss),
        "take_profit_1": float(take_profit_1),
        "take_profit_2": float(take_profit_2),
        "take_profit": float(take_profit),
        "sl_pct": float(sl_pct),
        "tp1_pct": float(tp1_pct),
        "tp2_pct": float(tp2_pct),
        "tp_pct": float(tp_pct),
        "tp1_share": float(act_tp1_share),
        "tp2_share": float(act_tp2_share),
        "coin_strategy_desc": strategy_desc,
        "candles_summary": candles_summary,
        "closed_time": past_candle['timestamp'].strftime('%Y-%m-%d %H:%M UTC')
    }
    return signal_data, diagnostics