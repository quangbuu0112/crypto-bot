"""
Backtest so sánh Trước và Sau khi Tối ưu hóa Payoff Ratio:
1. BASELINE (Trước tối ưu):
   - Trend: TP1 = 1.2 ATR (30%), TP2 cố định = 3.5 ATR (70%), SL = Breakeven sau TP1.
   - Sideway: SL = 1.8 ATR, TP = SMA20.
2. OPTIMIZED (Sau tối ưu Payoff):
   - Trend TP2 Runner: TP1 = 1.5 ATR (chốt 40%), 60% còn lại gồng Trend mở rộng TP2 = 5.5 ATR kèm Dynamic Trailing Stop (dời SL lên TP1 khi vượt 3.0 ATR).
   - Sideway Early Cut: Siết Stop Loss xuống đúng 1.2 ATR để giảm thiểu Avg Loss.
"""

import os
import sys
import json
import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime, timedelta

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
from backtest.back_test import load_market_data, build_1d_trend

def add_indicators(df_4h: pd.DataFrame) -> pd.DataFrame:
    df = df_4h.copy()
    df["EMA_20"] = ta.ema(df["close"], length=20)
    df["SMA_20"] = ta.sma(df["close"], length=20)
    df["RSI"] = ta.rsi(df["close"], length=14)
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    df["ADX"] = adx_df["ADX_14"]
    df["VOL_MA"] = df["volume"].rolling(20).mean()
    df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    bb = ta.bbands(df["close"], length=20, std=2.0)
    df["BBL"] = bb.iloc[:, 0]
    df["BBM"] = bb.iloc[:, 1]
    df["BBU"] = bb.iloc[:, 2]
    return df

def simulate_trades(df_merged: pd.DataFrame, symbol: str, mode: str = "BASELINE") -> list:
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

    # Cấu hình theo Mode
    if mode == "BASELINE":
        trend_tp1_mult = coin_cfg.get("tp1_mult", 1.2)
        trend_tp2_mult = coin_cfg.get("tp2_mult", 3.5)
        trend_tp1_share = 0.3
        sideway_sl_mult = 1.8
        sideway_tp_mult = 1.5
    else:  # OPTIMIZED
        trend_tp1_mult = 1.5
        trend_tp2_mult = 5.5  # Thả lỏng Trend Runner ăn sóng dài
        trend_tp1_share = 0.4 # Chốt 40% an toàn tại 1.5 ATR
        sideway_sl_mult = 1.2 # Cắt lỗ sớm Sideway tại 1.2 ATR
        sideway_tp_mult = 1.8 # Đón hồi phục lên dải trên

    trend_tp2_share = 1.0 - trend_tp1_share
    trades = []
    i = 60
    while i < n - 1:
        c = closes[i]
        o = opens[i]
        h = highs[i]
        l = lows[i]
        atr_val = atrs[i] if (not pd.isna(atrs[i]) and atrs[i] > 0) else c * 0.02

        trade_type = None

        # 1. Trend Signal (1D Trend Up + 4H Pullback EMA20)
        if trend[i] == 1.0:
            if (c > ema20[i]) and (coin_cfg["rsi_min"] <= rsi[i] <= coin_cfg["rsi_max"]) and (adx[i] >= coin_cfg["adx_min"]) and (volumes[i] >= coin_cfg["vol_mult"] * vol_ma[i]):
                if (c - ema20[i]) <= 1.5 * atr_val:
                    trade_type = "SNIPER_TREND"

        # 2. Sideway Signal
        if trade_type is None:
            is_sideway = (adx[i] < 22) or (trend[i] != 1.0)
            is_touch_bbl = (l <= bbl[i] * 1.002) or (c <= bbl[i] * 1.005)
            is_oversold = (rsi[i] <= 38)
            is_bullish_reversal = (c >= o) or ((c - l) >= 0.4 * (h - l + 1e-8))

            if is_sideway and is_touch_bbl and is_oversold and is_bullish_reversal:
                trade_type = "SIDEWAY_RANGE"

        if trade_type is None:
            i += 1
            continue

        entry_price = c
        entry_time = pd.Timestamp(timestamps[i])

        if trade_type == "SNIPER_TREND":
            initial_sl = entry_price - (atr_sl_mult * atr_val)
            tp1 = entry_price + (trend_tp1_mult * atr_val)
            tp2 = entry_price + (trend_tp2_mult * atr_val)
            tp1_pct = (tp1 - entry_price) / entry_price
            tp2_pct = (tp2 - entry_price) / entry_price
            sl_pct = (entry_price - initial_sl) / entry_price

            tp1_hit = False
            current_sl = initial_sl
            result = "LOSS"
            pnl_pct = 0.0
            hold_bars = 60 if mode == "OPTIMIZED" else 48
            end = min(i + 1 + hold_bars, n)

            for j in range(i + 1, end):
                if not tp1_hit:
                    if highs[j] >= tp1:
                        tp1_hit = True
                        current_sl = entry_price # Breakeven
                        if highs[j] >= tp2:
                            result = "WIN"
                            pnl_pct = (trend_tp1_share * tp1_pct + trend_tp2_share * tp2_pct) * 100
                            break
                    elif lows[j] <= current_sl:
                        result = "LOSS"
                        pnl_pct = -sl_pct * 100
                        break
                else:
                    # Dynamic Trailing cho Runner (Nếu giá vượt 3.0 ATR, dời SL lên khoá lãi 1.0 ATR)
                    if mode == "OPTIMIZED" and highs[j] >= entry_price + 3.0 * atr_val:
                        current_sl = max(current_sl, entry_price + 1.0 * atr_val)

                    if highs[j] >= tp2:
                        result = "WIN"
                        pnl_pct = (trend_tp1_share * tp1_pct + trend_tp2_share * tp2_pct) * 100
                        break
                    elif lows[j] <= current_sl:
                        result = "WIN"
                        locked_pct = (current_sl - entry_price) / entry_price
                        pnl_pct = (trend_tp1_share * tp1_pct + trend_tp2_share * locked_pct) * 100
                        break

            if result != "WIN" and pnl_pct == 0.0:
                pnl_pct = ((closes[end - 1] - entry_price) / entry_price) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        else: # SIDEWAY_RANGE
            sl_price = entry_price - (sideway_sl_mult * atr_val)
            tp_price = max(sma20[i], entry_price + sideway_tp_mult * atr_val)
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
                exit_c = closes[end - 1]
                pnl_pct = ((exit_c - entry_price) / entry_price) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        trades.append({
            "symbol": symbol,
            "type": trade_type,
            "entry_time": entry_time,
            "entry_price": round(entry_price, 4),
            "sl_pct": round(sl_pct, 4),
            "result": result,
            "pnl_pct": round(pnl_pct, 2)
        })
        i += 4

    return trades

def calc_detailed_stats(trades_list, start_dt, initial_cap=500.0, risk_pct=0.015):
    if not trades_list:
        return {}

    df = pd.DataFrame(trades_list)
    df = df[df["entry_time"] >= start_dt].sort_values("entry_time").reset_index(drop=True)
    total = len(df)
    if total == 0:
        return {}

    wins = int((df["result"] == "WIN").sum())
    losses = int((df["result"] == "LOSS").sum())
    wr = (wins / total * 100) if total else 0.0

    win_pnls = df[df["pnl_pct"] > 0]["pnl_pct"]
    loss_pnls = df[df["pnl_pct"] < 0]["pnl_pct"]

    avg_win_pct = float(win_pnls.mean()) if len(win_pnls) > 0 else 0.0
    avg_loss_pct = abs(float(loss_pnls.mean())) if len(loss_pnls) > 0 else 0.0
    payoff_ratio = (avg_win_pct / avg_loss_pct) if avg_loss_pct > 0 else 99.9

    gross_profit = float(win_pnls.sum())
    gross_loss = abs(float(loss_pnls.sum()))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else 99.9

    # Mô phỏng Dynamic ATR Risk Sizing ($500 balance, risk 1.5%, cap 25%)
    balance = initial_cap
    curve = [balance]
    total_dollar_pnl = 0.0

    for _, r in df.iterrows():
        sl_d = max(r.get("sl_pct", 0.025), 0.005)
        risk_usd = balance * risk_pct
        pos_size = min(risk_usd / sl_d, balance * 0.25)
        pos_size = max(pos_size, 10.0)

        dollar_pnl = pos_size * (r["pnl_pct"] / 100.0)
        balance += dollar_pnl
        total_dollar_pnl += dollar_pnl
        curve.append(balance)

    peaks = np.maximum.accumulate(curve)
    drawdowns = (peaks - curve) / peaks * 100.0
    max_dd = np.max(drawdowns)
    roi = ((balance - initial_cap) / initial_cap) * 100.0

    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wr, 2),
        "profit_factor": round(pf, 2),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "payoff_ratio": round(payoff_ratio, 2),
        "total_pnl_pct": round(float(df["pnl_pct"].sum()), 2),
        "final_balance": round(balance, 2),
        "net_profit_usd": round(balance - initial_cap, 2),
        "roi_pct": round(roi, 2),
        "max_drawdown_pct": round(max_dd, 2)
    }

def main():
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
    data_by_sym = {}
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
        data_by_sym[sym] = merged

    baseline_trades = []
    optimized_trades = []

    for sym in symbols:
        baseline_trades.extend(simulate_trades(data_by_sym[sym], sym, mode="BASELINE"))
        optimized_trades.extend(simulate_trades(data_by_sym[sym], sym, mode="OPTIMIZED"))

    df_sample = pd.DataFrame(baseline_trades)
    max_dt = df_sample["entry_time"].max()

    horizons = {
        "24 Tháng (Toàn bộ)": max_dt - timedelta(days=730),
        "12 Tháng (1 năm)": max_dt - timedelta(days=365),
        "9 Tháng gần nhất": max_dt - timedelta(days=270),
        "3 Tháng gần nhất": max_dt - timedelta(days=90),
    }

    comparison = {}
    for h_name, dt in horizons.items():
        base_stats = calc_detailed_stats(baseline_trades, dt, initial_cap=500.0, risk_pct=0.015)
        opt_stats = calc_detailed_stats(optimized_trades, dt, initial_cap=500.0, risk_pct=0.015)

        comparison[h_name] = {
            "TRUOC_TOI_UU (Baseline)": base_stats,
            "SAU_TOI_UU (Payoff Upgraded)": opt_stats
        }

    out_file = os.path.join(BASE_DIR, "reports", "payoff_optimization_comparison.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)

    print("=== BACKTEST SO SÁNH TRƯỚC VÀ SAU KHI TỐI ƯU HÓA PAYOFF ===")
    for h_name, data in comparison.items():
        b = data["TRUOC_TOI_UU (Baseline)"]
        o = data["SAU_TOI_UU (Payoff Upgraded)"]
        print(f"\n--- {h_name.upper()} ---")
        print(f"  [TRƯỚC TỐI ƯU] Lệnh: {b['trades']} | WinRate: {b['win_rate']}% | PF: {b['profit_factor']} | Payoff: 1:{b['payoff_ratio']} | AvgWin: +{b['avg_win_pct']}% | AvgLoss: -{b['avg_loss_pct']}% | ROI: +{b['roi_pct']}% (${b['final_balance']}) | MDD: {b['max_drawdown_pct']}%")
        print(f"  [SAU TỐI ƯU]   Lệnh: {o['trades']} | WinRate: {o['win_rate']}% | PF: {o['profit_factor']} | Payoff: 1:{o['payoff_ratio']} | AvgWin: +{o['avg_win_pct']}% | AvgLoss: -{o['avg_loss_pct']}% | ROI: +{o['roi_pct']}% (${o['final_balance']}) | MDD: {o['max_drawdown_pct']}%")

if __name__ == "__main__":
    main()
