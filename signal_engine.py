import ccxt
import pandas as pd
import pandas_ta as ta
import config
import gc

# Khởi tạo Singleton Exchange instance duy nhất
_exchange = ccxt.binance({'enableRateLimit': True})

def fetch_ohlcv_data(symbol: str, timeframe: str, limit: int = 220) -> pd.DataFrame:
    """Lấy dữ liệu nến từ Binance và chuyển thành Pandas DataFrame (Tối ưu RAM)"""
    try:
        ohlcv = _exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        del ohlcv  # Giải phóng raw list lập tức
        return df
    except Exception as e:
        print(f"❌ Lỗi kết nối API Binance ({symbol} - {timeframe}): {e}")
        return None

def check_btc_macro_health() -> dict:
    """
    🛡️ GIÁP 1: BỘ LỌC VĨ MÔ BITCOIN (BTC MACRO FILTER)
    Kiểm tra trạng thái nến 1D của BTC:
    - Nếu BTC 1D < EMA50 VÀ RSI 1D < 45 -> Thị trường đang trong pha Bearish Shock (Cấm bắt đáy Altcoin).
    """
    df_btc_1d = fetch_ohlcv_data("BTC/USDT", timeframe="1d", limit=60)
    if df_btc_1d is None or len(df_btc_1d) < 50:
        if df_btc_1d is not None:
            del df_btc_1d
        return {"is_bearish": False, "detail": "Không đủ dữ liệu BTC 1D"}

    try:
        ema50_series = ta.ema(df_btc_1d['close'], length=50)
        rsi_series = ta.rsi(df_btc_1d['close'], length=14)

        close_btc = float(df_btc_1d['close'].iloc[-2])
        ema50_btc = float(ema50_series.iloc[-2])
        rsi_btc = float(rsi_series.iloc[-2])

        is_bearish = bool((close_btc < ema50_btc) and (rsi_btc < 45))
        return {
            "is_bearish": is_bearish,
            "close": close_btc,
            "ema50": ema50_btc,
            "rsi": rsi_btc,
            "detail": f"BTC 1D: Close=${close_btc:,.0f} {'<' if close_btc < ema50_btc else '>'} EMA50(${ema50_btc:,.0f}), RSI={rsi_btc:.1f}"
        }
    except Exception as e:
        return {"is_bearish": False, "detail": f"Lỗi tính BTC Macro: {e}"}
    finally:
        del df_btc_1d
        try:
            del ema50_series
            del rsi_series
        except Exception:
            pass

def analyze_technical_signal(symbol: str) -> tuple:
    """
    Phân tích kỹ thuật Đa khung thời gian Thích ứng Kép (Dual-Regime Adaptive Engine).
    Tự động chọn 1 trong 2 chế độ:
      1. 🎯 SNIPER_TREND  : Khi 4H có Trend mạnh (Pullback EMA20, RSI tối ưu, gồng TP1/TP2 Runner)
      2. 📦 SIDEWAY_RANGE : Khi thị trường đi ngang (Bắt đáy dải dưới Lower BB, RSI quá bán <= 38, nến rút chân)
    Được bảo vệ bởi 3 Lớp Giáp Phòng Thủ (BTC Macro, Panic Dump, Cooldown).
    Trả về: (tech_signal_dict, diagnostics_dict)
    """
    diagnostics = {
        "step2_trend_4h": None,
        "step3_trigger_1h": None
    }

    df_4h = fetch_ohlcv_data(symbol, timeframe="4h", limit=220)
    df_1h = fetch_ohlcv_data(symbol, timeframe="1h", limit=60)

    if df_4h is None or df_1h is None:
        if df_4h is not None: del df_4h
        if df_1h is not None: del df_1h
        diagnostics["step2_trend_4h"] = {
            "status": "ERROR",
            "detail": "Không thể kết nối lấy dữ liệu nến từ sàn Binance"
        }
        return None, diagnostics

    # Khởi tạo các biến indicator để giải phóng trong finally
    ema50_4h_s = None
    ema200_4h_s = None
    ema20_1h_s = None
    sma20_1h_s = None
    rsi_1h_s = None
    adx_df = None
    vol_ma20_s = None
    atr_s = None
    bb = None

    try:
        # 1. TÍNH TOÁN CHỈ BÁO KHUNG 4H
        ema50_4h_s = ta.ema(df_4h['close'], length=50)
        ema200_4h_s = ta.ema(df_4h['close'], length=200)
        close_4h = float(df_4h['close'].iloc[-2])
        ema50_4h = float(ema50_4h_s.iloc[-2])
        ema200_4h = float(ema200_4h_s.iloc[-2])

        is_uptrend_4h = bool((close_4h > ema50_4h) and (ema50_4h > ema200_4h))

        # 2. TÍNH TOÁN CHỈ BÁO KHUNG 1H
        ema20_1h_s = ta.ema(df_1h['close'], length=20)
        sma20_1h_s = ta.sma(df_1h['close'], length=20)
        rsi_1h_s = ta.rsi(df_1h['close'], length=14)
        adx_df = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
        vol_ma20_s = df_1h['volume'].rolling(20).mean()
        atr_s = ta.atr(df_1h['high'], df_1h['low'], df_1h['close'], length=config.ATR_LENGTH)
        bb = ta.bbands(df_1h['close'], length=20, std=2.0)

        open_1h = float(df_1h['open'].iloc[-2])
        high_1h = float(df_1h['high'].iloc[-2])
        low_1h = float(df_1h['low'].iloc[-2])
        close_1h = float(df_1h['close'].iloc[-2])
        vol_1h = float(df_1h['volume'].iloc[-2])
        closed_time_str = df_1h['timestamp'].iloc[-2].strftime('%Y-%m-%d %H:%M UTC')

        ema20_1h = float(ema20_1h_s.iloc[-2])
        sma20_1h = float(sma20_1h_s.iloc[-2])
        rsi_1h = float(rsi_1h_s.iloc[-2])
        adx_1h = float(adx_df['ADX_14'].iloc[-2])
        vol_ma20 = float(vol_ma20_s.iloc[-2]) if pd.notna(vol_ma20_s.iloc[-2]) else 1.0
        vol_ratio = float((vol_1h / vol_ma20) if vol_ma20 > 0 else 0.0)
        atr_val = float(atr_s.iloc[-2]) if pd.notna(atr_s.iloc[-2]) else (close_1h * 0.02)
        bbl_1h = float(bb.iloc[-2, 0])

        candles_summary = "".join([
            f"- Nến {df_1h['timestamp'].iloc[k].strftime('%H:%M')}: O={df_1h['open'].iloc[k]:.2f}, H={df_1h['high'].iloc[k]:.2f}, L={df_1h['low'].iloc[k]:.2f}, C={df_1h['close'].iloc[k]:.2f}\n"
            for k in range(-6, -1)
        ])

        coin_cfg = config.get_coin_config(symbol) if hasattr(config, 'get_coin_config') else {}
        rsi_min = coin_cfg.get('rsi_min', getattr(config, 'RSI_MIN', 42))
        rsi_max = coin_cfg.get('rsi_max', getattr(config, 'RSI_MAX', 65))
        adx_min = coin_cfg.get('adx_min', getattr(config, 'ADX_MIN', 20))
        vol_min = coin_cfg.get('vol_mult', getattr(config, 'VOL_RATIO_MIN', 1.0))
        sl_mult = coin_cfg.get('atr_sl', getattr(config, 'ATR_SL_MULTIPLIER', 1.4))
        tp1_mult = coin_cfg.get('tp1_mult', getattr(config, 'ATR_TP1_MULTIPLIER', 1.5))
        tp2_mult = coin_cfg.get('tp2_mult', getattr(config, 'ATR_TP2_MULTIPLIER', 5.5))
        tp1_share = coin_cfg.get('tp1_share', getattr(config, 'TP1_SHARE', 0.35))
        tp2_share = coin_cfg.get('tp2_share', getattr(config, 'TP2_SHARE', 0.65))

        strategy_type = None

        # =========================================================================
        # NHÁNH 1: CHIẾN LƯỢC SNIPER TREND FOLLOWING
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
        # NHÁNH 2: CHIẾN LƯỢC SIDEWAY RANGE MEAN REVERSION
        # =========================================================================
        enable_dual = getattr(config, 'ENABLE_DUAL_REGIME', True)
        if strategy_type is None and enable_dual:
            sideway_rsi_max = getattr(config, 'SIDEWAY_RSI_MAX', 38)
            is_touch_bbl = (low_1h <= bbl_1h * 1.002) or (close_1h <= bbl_1h * 1.005)
            is_oversold = rsi_1h <= sideway_rsi_max
            is_bullish_reversal = (close_1h >= open_1h) or ((close_1h - low_1h) >= 0.4 * (high_1h - low_1h + 1e-8))

            if is_touch_bbl and is_oversold and is_bullish_reversal:
                # 🛡️ KIỂM TRA GIÁP 1: BTC MACRO FILTER
                if getattr(config, 'ENABLE_BTC_MACRO_FILTER', True) and symbol != "BTC/USDT":
                    btc_macro = check_btc_macro_health()
                    if btc_macro["is_bearish"]:
                        diagnostics["step2_trend_4h"] = {
                            "status": "BLOCKED_BY_SHIELD",
                            "detail": f"🛡️ [GIÁP 1: BTC MACRO] {btc_macro['detail']} -> Chặn lệnh bắt đáy Altcoin để bảo toàn vốn."
                        }
                        return None, diagnostics

                # 🛡️ KIỂM TRA GIÁP 2: PANIC DUMP VOLUME FILTER
                if getattr(config, 'ENABLE_PANIC_VOLUME_FILTER', True) and len(df_1h) >= 3:
                    p_open = float(df_1h['open'].iloc[-3])
                    p_close = float(df_1h['close'].iloc[-3])
                    p_vol = float(df_1h['volume'].iloc[-3])
                    p_vol_ma = float(vol_ma20_s.iloc[-3]) if pd.notna(vol_ma20_s.iloc[-3]) else 1.0
                    is_panic_dump = (p_close < p_open) and (p_vol >= 2.2 * p_vol_ma) and ((p_open - p_close) >= 1.2 * atr_val)
                    if is_panic_dump:
                        diagnostics["step3_trigger_1h"] = {
                            "status": "BLOCKED_BY_SHIELD",
                            "detail": f"🛡️ [GIÁP 2: PANIC DUMP] Nến trước xả Volume={p_vol/p_vol_ma:.1f}x > 2.2x MA20. Hủy bỏ tín hiệu bắt dao rơi."
                        }
                        return None, diagnostics

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
            strategy_desc = f"🎯 SNIPER TREND: {coin_cfg.get('desc', 'Trend Pullback')} (TP1: 1.5x ATR, TP2: 5.5x ATR)"
        else:
            sideway_sl_mult = getattr(config, 'SIDEWAY_SL_ATR_MULT', 1.2)
            sideway_tp_mult = getattr(config, 'SIDEWAY_TP_ATR_MULT', 1.3)
            sideway_tp_min = getattr(config, 'SIDEWAY_TP_MIN_PCT', 0.022)
            stop_loss = entry_price - (sideway_sl_mult * atr_val)
            target_tp = max(sma20_1h, entry_price + sideway_tp_mult * atr_val, entry_price * (1 + sideway_tp_min))
            take_profit_1 = target_tp
            take_profit_2 = target_tp
            take_profit = target_tp
            sl_pct = (entry_price - stop_loss) / entry_price
            tp_pct = (take_profit - entry_price) / entry_price
            tp1_pct = tp_pct
            tp2_pct = tp_pct
            act_tp1_share = 1.0
            act_tp2_share = 0.0
            strategy_desc = "📦 SIDEWAY RANGE: Bắt đáy Lower BB + RSI quá bán, Chốt lời SMA20 / 1.3x ATR (SL 1.2x ATR)"

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
            "closed_time": closed_time_str
        }
        return signal_data, diagnostics

    finally:
        del df_4h
        del df_1h
        if ema50_4h_s is not None: del ema50_4h_s
        if ema200_4h_s is not None: del ema200_4h_s
        if ema20_1h_s is not None: del ema20_1h_s
        if sma20_1h_s is not None: del sma20_1h_s
        if rsi_1h_s is not None: del rsi_1h_s
        if adx_df is not None: del adx_df
        if vol_ma20_s is not None: del vol_ma20_s
        if atr_s is not None: del atr_s
        if bb is not None: del bb