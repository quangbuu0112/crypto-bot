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
    Phân tích kỹ thuật Đa khung thời gian (4H Trend + 1H Entry).
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

    # 1. KIỂM TRA KHUNG 4H (BỘ LỌC XU HƯỚNG TREND ALIGNMENT)
    df_4h['EMA_50_4h'] = ta.ema(df_4h['close'], length=50)
    df_4h['EMA_200_4h'] = ta.ema(df_4h['close'], length=200)
    past_4h = df_4h.iloc[-2]
    close_4h = float(past_4h['close'])
    ema50_4h = float(past_4h['EMA_50_4h'])
    ema200_4h = float(past_4h['EMA_200_4h'])

    is_uptrend_4h = (close_4h > ema50_4h) and (ema50_4h > ema200_4h)

    if is_uptrend_4h:
        diagnostics["step2_trend_4h"] = {
            "status": "PASS",
            "detail": f"Giá 4H (${close_4h:,.2f}) > EMA50 (${ema50_4h:,.2f}) > EMA200 (${ema200_4h:,.2f}) -> Uptrend chuẩn."
        }
    else:
        reasons_4h = []
        if close_4h <= ema50_4h:
            reasons_4h.append(f"Giá 4H (${close_4h:,.2f}) <= EMA50 (${ema50_4h:,.2f})")
        if ema50_4h <= ema200_4h:
            reasons_4h.append(f"EMA50 (${ema50_4h:,.2f}) <= EMA200 (${ema200_4h:,.2f}) (Downtrend/Sideway dài hạn)")
        diagnostics["step2_trend_4h"] = {
            "status": "REJECT",
            "detail": "; ".join(reasons_4h) if reasons_4h else "Chưa đạt cấu trúc Uptrend 4H"
        }
        return None, diagnostics

    # 2. KIỂM TRA KHUNG 1H (BỘ LỌC VÀO LỆNH)
    df_1h['EMA_20_1h'] = ta.ema(df_1h['close'], length=20)
    df_1h['RSI_1h'] = ta.rsi(df_1h['close'], length=14)
    adx_df = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
    df_1h['ADX_14_1h'] = adx_df['ADX_14']
    df_1h['VOL_MA20_1h'] = df_1h['volume'].rolling(20).mean()
    df_1h['ATR_14_1h'] = ta.atr(df_1h['high'], df_1h['low'], df_1h['close'], length=config.ATR_LENGTH)

    past_candle = df_1h.iloc[-2]
    close_1h = float(past_candle['close'])
    ema20_1h = float(past_candle['EMA_20_1h'])
    rsi_1h = float(past_candle['RSI_1h'])
    adx_1h = float(past_candle['ADX_14_1h'])
    vol_1h = float(past_candle['volume'])
    vol_ma20 = float(past_candle['VOL_MA20_1h'])
    vol_ratio = (vol_1h / vol_ma20) if vol_ma20 > 0 else 0.0

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

    atr_val = float(past_candle['ATR_14_1h']) if pd.notna(past_candle['ATR_14_1h']) else 0.0

    cond_ema = close_1h > ema20_1h
    cond_rsi = rsi_min <= rsi_1h <= rsi_max
    cond_adx = adx_1h >= adx_min
    cond_vol = vol_ratio >= vol_min
    # Tránh mua đu đỉnh khi giá đã phóng quá 1.5x ATR tính từ EMA20
    cond_not_extended = True
    if atr_val > 0 and (close_1h - ema20_1h) > 1.5 * atr_val:
        cond_not_extended = False

    reject_reasons_1h = []
    if not cond_ema:
        reject_reasons_1h.append(f"Giá 1H (${close_1h:,.2f}) <= EMA20 (${ema20_1h:,.2f})")
    if not cond_rsi:
        if rsi_1h < rsi_min:
            reject_reasons_1h.append(f"RSI 1H ({rsi_1h:.1f}) < {rsi_min} (Lực mua yếu)")
        else:
            reject_reasons_1h.append(f"RSI 1H ({rsi_1h:.1f}) > {rsi_max} (Quá mua / Overbought, rủi ro đu đỉnh)")
    if not cond_adx:
        reject_reasons_1h.append(f"ADX 1H ({adx_1h:.1f}) < {adx_min} (Xung lực xu hướng yếu / Sideway)")
    if not cond_vol:
        reject_reasons_1h.append(f"Volume ({vol_ratio:.2f}x VolMA) < {vol_min}x")
    if not cond_not_extended:
        reject_reasons_1h.append(f"Giá phóng quá xa EMA20 (+{(close_1h - ema20_1h)/atr_val:.1f}x ATR - rủi ro đu ngọn nến)")

    if cond_ema and cond_rsi and cond_adx and cond_vol and cond_not_extended:
        diagnostics["step3_trigger_1h"] = {
            "status": "PASS",
            "detail": f"Thỏa mãn toàn bộ tiêu chuẩn Sniper ({coin_cfg.get('desc', 'Custom')}): Giá > EMA20, RSI={rsi_1h:.1f}, ADX={adx_1h:.1f}, Volume={vol_ratio:.2f}x."
        }

        entry_price = close_1h
        use_atr = getattr(config, 'USE_ATR_STOPS', True)

        if use_atr and atr_val > 0:
            stop_loss = entry_price - (sl_mult * atr_val)
            take_profit_1 = entry_price + (tp1_mult * atr_val)
            take_profit_2 = entry_price + (tp2_mult * atr_val)
            take_profit = take_profit_2 # Mốc chốt tối đa
            sl_pct = (entry_price - stop_loss) / entry_price
            tp1_pct = (take_profit_1 - entry_price) / entry_price
            tp2_pct = (take_profit_2 - entry_price) / entry_price
            tp_pct = tp2_pct
        else:
            sl_pct = config.STOP_LOSS_PCT
            tp_pct = config.TAKE_PROFIT_PCT
            stop_loss = entry_price * (1 - sl_pct)
            take_profit_1 = entry_price * (1 + tp_pct * tp1_share)
            take_profit_2 = entry_price * (1 + tp_pct)
            take_profit = take_profit_2
            tp1_pct = tp_pct * tp1_share
            tp2_pct = tp_pct

        last_5_candles = df_1h.iloc[-6:-1]
        candles_summary = ""
        for _, row in last_5_candles.iterrows():
            candles_summary += (
                f"- Nến {row['timestamp'].strftime('%H:%M')}: "
                f"O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}\n"
            )

        signal_data = {
            "symbol": symbol,
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
            "tp1_share": float(tp1_share),
            "tp2_share": float(tp2_share),
            "coin_strategy_desc": coin_cfg.get('desc', 'Sniper Custom'),
            "candles_summary": candles_summary,
            "closed_time": past_candle['timestamp'].strftime('%Y-%m-%d %H:%M UTC')
        }
        return signal_data, diagnostics
    else:
        diagnostics["step3_trigger_1h"] = {
            "status": "REJECT",
            "detail": "; ".join(reject_reasons_1h)
        }
        return None, diagnostics