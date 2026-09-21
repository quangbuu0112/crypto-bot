"""
Thử nghiệm Backtest Chiến Lược Sideway Mean Reversion (Bollinger Bands + RSI Oversold)
và Cơ chế Kết Hợp Dual-Regime (Trend + Sideway) trên dữ liệu 9 tháng và 3 tháng gần nhất.
"""

import os
import sys
import json
import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
from backtest.back_test import load_market_data, build_1d_trend, symbol_to_filename

def add_indicators(df_4h: pd.DataFrame) -> pd.DataFrame:
    df = df_4h.copy()
    df["EMA_20"] = ta.ema(df["close"], length=20)
    df["SMA_20"] = ta.sma(df["close"], length=20)
    df["RSI"] = ta.rsi(df["close"], length=14)
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    df["ADX"] = adx_df[f"ADX_14"]
    df["VOL_MA"] = df["volume"].rolling(20).mean()
    df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    
    # Bollinger Bands (20, 2.0)
    bb = ta.bbands(df["close"], length=20, std=2.0)
    df["BBL"] = bb.iloc[:, 0]  # Lower band
    df["BBM"] = bb.iloc[:, 1]  # Mid band
    df["BBU"] = bb.iloc[:, 2]  # Upper band
    
    return df

def simulate_trades(df_merged: pd.DataFrame, symbol: str, mode: str = "DUAL") -> list:
    """
    mode = "SNIPER_ONLY" : Chỉ đánh theo Trend
    mode = "SIDEWAY_ONLY": Chỉ đánh theo Mean Reversion
    mode = "DUAL"        : Kết hợp tự động theo bối cảnh ADX & Trend
    """
    n = len(df_merged)
    closes = df_merged["close"].to_numpy(dtype=float)
    highs = df_merged["high"].to_numpy(dtype=float)
    lows = df_merged["low"].to_numpy(dtype=float)
    opens = df_merged["open"].to_numpy(dtype=float)
    volumes = df_merged["volume"].to_numpy(dtype=float)
    rsi = df_merged["RSI"].to_numpy(dtype=float)
    adx = df_merged["ADX"].to_numpy(dtype=float)
    vol_ma = df_merged["VOL_MA"].to_numpy(dtype=float)
    atrs = df_merged["ATR"].to_numpy(dtype=float)
    ema20 = df_merged["EMA_20"].to_numpy(dtype=float)
    sma20 = df_merged["SMA_20"].to_numpy(dtype=float)
    bbl = df_merged["BBL"].to_numpy(dtype=float)
    trend = df_merged["trend_up"].to_numpy(dtype=float)
    timestamps = df_merged["timestamp"].to_numpy()

    coin_cfg = config.get_coin_config(symbol)
    atr_sl_mult = coin_cfg.get("atr_sl", 1.4)
    atr_tp1_mult = coin_cfg.get("tp1_mult", 1.2)
    atr_tp2_mult = coin_cfg.get("tp2_mult", 3.5)
    tp1_share = coin_cfg.get("tp1_share", 0.3)
    tp2_share = 1.0 - tp1_share

    trades = []
    i = 60
    while i < n - 1:
        c = closes[i]
        o = opens[i]
        h = highs[i]
        l = lows[i]
        atr_val = atrs[i] if (not pd.isna(atrs[i]) and atrs[i] > 0) else c * 0.02
        
        is_trend_regime = (trend[i] == 1.0) and (adx[i] >= 20)
        is_sideway_regime = (adx[i] < 22) or (trend[i] != 1.0)

        trade_type = None

        # -------------------------------------------------------------
        # 1. TÍN HIỆU SNIPER TREND FOLLOWING
        # -------------------------------------------------------------
        if mode in ["SNIPER_ONLY", "DUAL"] and is_trend_regime:
            if (c > ema20[i]) and (coin_cfg["rsi_min"] <= rsi[i] <= coin_cfg["rsi_max"]) and (volumes[i] >= coin_cfg["vol_mult"] * vol_ma[i]):
                if (c - ema20[i]) <= 1.5 * atr_val:
                    trade_type = "SNIPER_TREND"

        # -------------------------------------------------------------
        # 2. TÍN HIỆU SIDEWAY MEAN REVERSION (Bắt đáy biên hộp)
        # -------------------------------------------------------------
        if trade_type is None and mode in ["SIDEWAY_ONLY", "DUAL"] and is_sideway_regime:
            # Điều kiện Mua Sideway: Giá chạm hoặc đâm xuống dưới dải Lower BB + RSI <= 38 + nến xanh hoặc rút chân
            is_touch_bbl = (l <= bbl[i] * 1.002) or (c <= bbl[i] * 1.005)
            is_oversold = (rsi[i] <= 38)
            is_bullish_reversal = (c >= o) or ((c - l) >= 0.4 * (h - l + 1e-8))
            
            if is_touch_bbl and is_oversold and is_bullish_reversal:
                trade_type = "SIDEWAY_RANGE"

        if trade_type is None:
            i += 1
            continue

        entry_price = c
        entry_time = pd.Timestamp(timestamps[i])

        if trade_type == "SNIPER_TREND":
            # Chiến lược 2 giai đoạn: TP1 + TP2
            initial_sl = entry_price - (atr_sl_mult * atr_val)
            tp1 = entry_price + (atr_tp1_mult * atr_val)
            tp2 = entry_price + (atr_tp2_mult * atr_val)
            tp1_pct = (tp1 - entry_price) / entry_price
            tp2_pct = (tp2 - entry_price) / entry_price
            sl_pct = (entry_price - initial_sl) / entry_price

            tp1_hit = False
            current_sl = initial_sl
            result = "LOSS"
            pnl_pct = 0.0
            hold_bars = 48
            end = min(i + 1 + hold_bars, n)

            for j in range(i + 1, end):
                if not tp1_hit:
                    if highs[j] >= tp1:
                        tp1_hit = True
                        current_sl = entry_price
                        if highs[j] >= tp2:
                            result = "WIN"
                            pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                            break
                    elif lows[j] <= current_sl:
                        result = "LOSS"
                        pnl_pct = -sl_pct * 100
                        break
                else:
                    if highs[j] >= tp2:
                        result = "WIN"
                        pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                        break
                    elif lows[j] <= current_sl:
                        result = "WIN"
                        pnl_pct = (tp1_share * tp1_pct + tp2_share * 0.0) * 100
                        break
            if result != "WIN" and pnl_pct == 0.0:
                pnl_pct = ((closes[end - 1] - entry_price) / entry_price) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        else:
            # Chiêu thức Sideway: TP tại trục giữa SMA20 / Upper BB, SL chặt 1.2 * ATR, Giữ tối đa 16 nến 4H (~2.5 ngày)
            sl_price = entry_price - (1.2 * atr_val)
            # TP mục tiêu tại SMA20 hoặc tối thiểu +2.0%
            tp_price = max(sma20[i], entry_price * 1.022)
            sl_pct = (entry_price - sl_price) / entry_price
            tp_pct = (tp_price - entry_price) / entry_price
            hold_bars = 16
            end = min(i + 1 + hold_bars, n)
            result = "LOSS"
            pnl_pct = -sl_pct * 100

            for j in range(i + 1, end):
                if highs[j] >= tp_price:
                    result = "WIN"
                    pnl_pct = tp_pct * 100
                    break
                elif lows[j] <= sl_price:
                    result = "LOSS"
                    pnl_pct = -sl_pct * 100
                    break
            if result != "WIN" and pnl_pct == -sl_pct * 100:
                # Thoát hết hạn nến
                exit_c = closes[end - 1]
                pnl_pct = ((exit_c - entry_price) / entry_price) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        trades.append({
            "symbol": symbol,
            "type": trade_type,
            "entry_time": entry_time,
            "entry_price": round(entry_price, 4),
            "result": result,
            "pnl_pct": round(pnl_pct, 2)
        })

        # Dời con trỏ sau khi lệnh kết thúc
        i += 4

    return trades

def evaluate_portfolio(trades_df, start_dt, initial_cap=500.0, trade_size=50.0):
    if trades_df.empty:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0.0, "pnl": 0.0, "pf": 0.0, "balance": initial_cap, "roi": 0.0, "max_dd": 0.0}

    sub = trades_df[trades_df["entry_time"] >= start_dt].copy().sort_values("entry_time").reset_index(drop=True)
    total = len(sub)
    if total == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0.0, "pnl": 0.0, "pf": 0.0, "balance": initial_cap, "roi": 0.0, "max_dd": 0.0}

    wins = int((sub["result"] == "WIN").sum())
    losses = int((sub["result"] == "LOSS").sum())
    wr = (wins / total * 100) if total else 0.0
    pnl = float(sub["pnl_pct"].sum())

    gp = float(sub[sub["pnl_pct"] > 0]["pnl_pct"].sum())
    gl = abs(float(sub[sub["pnl_pct"] < 0]["pnl_pct"].sum()))
    pf = (gp / gl) if gl > 0 else 99.9

    balance = initial_cap
    curve = [balance]
    for _, r in sub.iterrows():
        balance += trade_size * (r["pnl_pct"] / 100.0)
        curve.append(balance)

    peaks = np.maximum.accumulate(curve)
    drawdowns = (peaks - curve) / peaks * 100.0
    max_dd = np.max(drawdowns)
    roi = ((balance - initial_cap) / initial_cap) * 100.0

    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "wr": round(wr, 1),
        "pnl": round(pnl, 2),
        "pf": round(pf, 2),
        "balance": round(balance, 2),
        "roi": round(roi, 2),
        "max_dd": round(max_dd, 2)
    }

def main():
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
    data_by_symbol = {}

    for sym in symbols:
        df_1d = load_market_data(sym, "1d")
        df_4h = load_market_data(sym, "4h")
        trend = build_1d_trend(df_1d, 200, 50)
        df_4h_ind = add_indicators(df_4h)
        merged = pd.merge_asof(
            df_4h_ind.sort_values("timestamp"),
            trend.sort_values("timestamp"),
            on="timestamp",
            direction="backward"
        )
        data_by_symbol[sym] = merged

    modes = ["SNIPER_ONLY", "SIDEWAY_ONLY", "DUAL"]
    all_results = {}

    for m in modes:
        mode_trades = []
        for sym in symbols:
            t = simulate_trades(data_by_symbol[sym], sym, mode=m)
            mode_trades.extend(t)
        all_results[m] = pd.DataFrame(mode_trades)

    # Lấy mốc thời gian
    sample_df = all_results["SNIPER_ONLY"]
    max_date = sample_df["entry_time"].max()

    date_9m = max_date - timedelta(days=270)
    date_3m = max_date - timedelta(days=90)
    date_24m = max_date - timedelta(days=730)

    comparison = {}
    for horizon_name, dt in [("3 Tháng", date_3m), ("9 Tháng", date_9m), ("24 Tháng (Toàn bộ)", date_24m)]:
        comparison[horizon_name] = {}
        for m in modes:
            res_50 = evaluate_portfolio(all_results[m], dt, initial_cap=500.0, trade_size=50.0)
            res_100 = evaluate_portfolio(all_results[m], dt, initial_cap=500.0, trade_size=100.0)
            comparison[horizon_name][m] = {
                "size_50": res_50,
                "size_100": res_100
            }

    os.makedirs(os.path.join(BASE_DIR, "reports"), exist_ok=True)
    out_file = os.path.join(BASE_DIR, "reports", "sideway_experiment_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f"Comparison saved to {out_file}")

if __name__ == "__main__":
    main()
