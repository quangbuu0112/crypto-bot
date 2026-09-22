"""
Backtest Kiểm thử Chuyên sâu: Tách bạch Cấu hình R:R giữa Trend và Sideway
So sánh 3 kịch bản trên 5 cặp coin (BTC, ETH, SOL, BNB, XRP) trong 24 Tháng, 12 Tháng, 9 Tháng, 3 Tháng:
1. BASELINE: Dùng chung quy chuẩn TP/SL cứng (Trend TP2 3.5 ATR, Sideway SL 1.8 ATR).
2. DUAL_SEPARATED_RR:
   - KÈO TREND: SL 1.4 ATR, TP1 1.5 ATR (chốt 35%), TP2 Runner 5.5 ATR (gồng 65% vị thế) + Dynamic Trailing Stop khi giá vượt 3.0 ATR.
   - KÈO SIDEWAY: SL siêu chặt 1.0 ATR (Cắt sớm khi thủng đáy), TP chốt nhanh tại SMA20 / 1.3 ATR (Mean Reversion).
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

def simulate_trades(df_merged: pd.DataFrame, symbol: str, mode: str = "DUAL_SEPARATED") -> list:
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
            if mode == "BASELINE":
                atr_sl_mult = coin_cfg.get("atr_sl", 1.4)
                tp1_mult = 1.2
                tp2_mult = 3.5
                tp1_share = 0.3
                hold_bars = 48
            else: # DUAL_SEPARATED
                atr_sl_mult = 1.4
                tp1_mult = 1.5
                tp2_mult = 5.5 # Gồng sóng lớn Runner
                tp1_share = 0.35
                hold_bars = 60

            tp2_share = 1.0 - tp1_share
            initial_sl = entry_price - (atr_sl_mult * atr_val)
            tp1 = entry_price + (tp1_mult * atr_val)
            tp2 = entry_price + (tp2_mult * atr_val)
            tp1_pct = (tp1 - entry_price) / entry_price
            tp2_pct = (tp2 - entry_price) / entry_price
            sl_pct = (entry_price - initial_sl) / entry_price

            tp1_hit = False
            current_sl = initial_sl
            result = "LOSS"
            pnl_pct = 0.0
            end = min(i + 1 + hold_bars, n)

            for j in range(i + 1, end):
                if not tp1_hit:
                    if highs[j] >= tp1:
                        tp1_hit = True
                        current_sl = entry_price # Breakeven
                        if highs[j] >= tp2:
                            result = "WIN"
                            pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                            break
                    elif lows[j] <= current_sl:
                        result = "LOSS"
                        pnl_pct = -sl_pct * 100
                        break
                else:
                    if mode == "DUAL_SEPARATED":
                        # Dynamic trailing stop: nếu giá vượt 3.0 ATR, nâng SL lên khóa lãi +1.2 ATR
                        if highs[j] >= entry_price + 3.0 * atr_val:
                            current_sl = max(current_sl, entry_price + 1.2 * atr_val)

                    if highs[j] >= tp2:
                        result = "WIN"
                        pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                        break
                    elif lows[j] <= current_sl:
                        result = "WIN"
                        locked_pct = (current_sl - entry_price) / entry_price
                        pnl_pct = (tp1_share * tp1_pct + tp2_share * locked_pct) * 100
                        break

            if result != "WIN" and pnl_pct == 0.0:
                pnl_pct = ((closes[end - 1] - entry_price) / entry_price) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        else: # SIDEWAY_RANGE
            if mode == "BASELINE":
                sideway_sl_mult = 1.8
                tp_price = max(sma20[i], entry_price * 1.022)
                hold_bars = 16
            else: # DUAL_SEPARATED (Siết SL siêu chặt 1.0 ATR, TP tại SMA20 / 1.3 ATR)
                sideway_sl_mult = 1.0
                tp_price = max(sma20[i], entry_price + 1.3 * atr_val)
                hold_bars = 14

            sl_price = entry_price - (sideway_sl_mult * atr_val)
            sl_pct = (entry_price - sl_price) / entry_price
            tp_pct = (tp_price - entry_price) / entry_price
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

def calc_regime_breakdown(trades_list, start_dt, initial_cap=500.0, risk_pct=0.015):
    if not trades_list:
        return {}

    df = pd.DataFrame(trades_list)
    df = df[df["entry_time"] >= start_dt].sort_values("entry_time").reset_index(drop=True)
    if len(df) == 0:
        return {}

    def stats_for_subset(sub_df):
        total = len(sub_df)
        if total == 0:
            return {"trades": 0, "wr": 0.0, "pf": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "payoff": 0.0}
        wins = int((sub_df["result"] == "WIN").sum())
        wr = round(wins / total * 100, 1)
        win_pnls = sub_df[sub_df["pnl_pct"] > 0]["pnl_pct"]
        loss_pnls = sub_df[sub_df["pnl_pct"] < 0]["pnl_pct"]
        avg_w = round(float(win_pnls.mean()), 2) if len(win_pnls) > 0 else 0.0
        avg_l = round(abs(float(loss_pnls.mean())), 2) if len(loss_pnls) > 0 else 0.0
        payoff = round(avg_w / avg_l, 2) if avg_l > 0 else 99.9
        gp = float(win_pnls.sum())
        gl = abs(float(loss_pnls.sum()))
        pf = round(gp / gl, 2) if gl > 0 else 99.9
        return {
            "trades": total,
            "wins": wins,
            "losses": total - wins,
            "wr": wr,
            "pf": pf,
            "avg_win": avg_w,
            "avg_loss": avg_l,
            "payoff": payoff
        }

    overall = stats_for_subset(df)
    trend_stats = stats_for_subset(df[df["type"] == "SNIPER_TREND"])
    sideway_stats = stats_for_subset(df[df["type"] == "SIDEWAY_RANGE"])

    # Mô phỏng số dư với ATR Risk
    balance = initial_cap
    curve = [balance]
    for _, r in df.iterrows():
        sl_d = max(r.get("sl_pct", 0.025), 0.005)
        risk_usd = balance * risk_pct
        pos_size = min(risk_usd / sl_d, balance * 0.25)
        pos_size = max(pos_size, 10.0)
        balance += pos_size * (r["pnl_pct"] / 100.0)
        curve.append(balance)

    peaks = np.maximum.accumulate(curve)
    drawdowns = (peaks - curve) / peaks * 100.0
    max_dd = round(np.max(drawdowns), 2)
    roi = round(((balance - initial_cap) / initial_cap) * 100.0, 2)

    return {
        "overall": overall,
        "trend": trend_stats,
        "sideway": sideway_stats,
        "final_balance": round(balance, 2),
        "net_profit": round(balance - initial_cap, 2),
        "roi": roi,
        "max_dd": max_dd
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
    separated_trades = []

    for sym in symbols:
        baseline_trades.extend(simulate_trades(data_by_sym[sym], sym, mode="BASELINE"))
        separated_trades.extend(simulate_trades(data_by_sym[sym], sym, mode="DUAL_SEPARATED"))

    df_sample = pd.DataFrame(baseline_trades)
    max_dt = df_sample["entry_time"].max()

    horizons = {
        "24 Tháng (Toàn bộ)": max_dt - timedelta(days=730),
        "12 Tháng (1 năm)": max_dt - timedelta(days=365),
        "9 Tháng gần nhất": max_dt - timedelta(days=270),
        "3 Tháng gần nhất": max_dt - timedelta(days=90),
    }

    full_results = {}
    for h_name, dt in horizons.items():
        base = calc_regime_breakdown(baseline_trades, dt, 500.0, 0.015)
        sep = calc_regime_breakdown(separated_trades, dt, 500.0, 0.015)
        full_results[h_name] = {
            "BASELINE": base,
            "DUAL_SEPARATED_RR": sep
        }

    out_file = os.path.join(BASE_DIR, "reports", "separated_rr_backtest.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)

    print("\n==========================================================================================")
    print("                 KẾT QUẢ SO SÁNH: TÁCH BẠCH CẤU HÌNH R:R (TREND vs SIDEWAY)                ")
    print("==========================================================================================")
    for h_name, data in full_results.items():
        b = data["BASELINE"]
        s = data["DUAL_SEPARATED_RR"]
        print(f"\n>>> THỜI GIAN: {h_name.upper()}")
        print(f"  [BASELINE]       Lệnh: {b['overall']['trades']} | WR: {b['overall']['wr']}% | PF: {b['overall']['pf']} | Payoff: 1:{b['overall']['payoff']} | ROI: +{b['roi']}% (${b['final_balance']}) | MDD: {b['max_dd']}%")
        print(f"    - Trend Trades:   {b['trend']['trades']} lệnh | WR: {b['trend']['wr']}% | Payoff: 1:{b['trend']['payoff']} (AvgWin +{b['trend']['avg_win']}% / AvgLoss -{b['trend']['avg_loss']}%)")
        print(f"    - Sideway Trades: {b['sideway']['trades']} lệnh | WR: {b['sideway']['wr']}% | Payoff: 1:{b['sideway']['payoff']} (AvgWin +{b['sideway']['avg_win']}% / AvgLoss -{b['sideway']['avg_loss']}%)")
        print(f"  ----------------------------------------------------------------------------------------")
        print(f"  [SEPARATED R:R]  Lệnh: {s['overall']['trades']} | WR: {s['overall']['wr']}% | PF: {s['overall']['pf']} | Payoff: 1:{s['overall']['payoff']} | ROI: +{s['roi']}% (${s['final_balance']}) | MDD: {s['max_dd']}%")
        print(f"    - Trend Trades:   {s['trend']['trades']} lệnh | WR: {s['trend']['wr']}% | Payoff: 1:{s['trend']['payoff']} (AvgWin +{s['trend']['avg_win']}% / AvgLoss -{s['trend']['avg_loss']}%)")
        print(f"    - Sideway Trades: {s['sideway']['trades']} lệnh | WR: {s['sideway']['wr']}% | Payoff: 1:{s['sideway']['payoff']} (AvgWin +{s['sideway']['avg_win']}% / AvgLoss -{s['sideway']['avg_loss']}%)")

if __name__ == "__main__":
    main()
