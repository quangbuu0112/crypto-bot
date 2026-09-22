"""
Master Production Backtest: Hệ thống Giao dịch Toàn diện (Toàn bộ Kỹ thuật & Tinh chỉnh Thực chiến)
Bao gồm:
1. Cơ chế Kép DUAL Regime (Sniper Trend + Sideway Range).
2. Dynamic Volatility-Adjusted ATR Risk Position Sizing (Risk 1.5%, Max Cap 25%, Compound từ $500).
3. Tách bạch R:R chuyên biệt:
   - Trend: SL 1.4 ATR, TP1 1.5 ATR (35%), TP2 Runner 5.5 ATR (65%), Buffer Breakeven & Dynamic Trailing.
   - Sideway: SL 1.2 ATR, TP tại SMA20 / 1.3 ATR (Biên độ hộp tối thiểu >= 2.0%).
4. Bộ 3 Lớp Giáp Bảo Vệ:
   - Giáp 1: BTC Macro Filter (BTC 1D < EMA50 & RSI < 45 -> Chặn bắt đáy Altcoin).
   - Giáp 2: Panic Volume Filter (Volume xả > 2.2x -> Hủy tín hiệu).
   - Giáp 3: Consecutive Loss Cooldown (2 SL trong 72h -> Khóa coin 3 ngày).
5. Tinh chỉnh Thực chiến:
   - Portfolio Cap: Giới hạn tối đa MAX_OPEN_TRADES = 2 vị thế mở cùng lúc trên toàn danh mục.
   - Phí sàn & Trượt giá: Trừ 0.08% Round-trip Taker fee trên mỗi lệnh.
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

def build_btc_macro(df_btc_1d: pd.DataFrame) -> pd.DataFrame:
    df = df_btc_1d.copy().sort_values("timestamp").reset_index(drop=True)
    df["BTC_EMA_50"] = ta.ema(df["close"], length=50)
    df["BTC_RSI_1D"] = ta.rsi(df["close"], length=14)
    df["BTC_MACRO_BEARISH"] = (df["close"] < df["BTC_EMA_50"]) & (df["BTC_RSI_1D"] < 45)
    return df[["timestamp", "BTC_MACRO_BEARISH", "BTC_RSI_1D"]]

def generate_signals(df_merged: pd.DataFrame, symbol: str) -> list:
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
    btc_bearish = df_merged["BTC_MACRO_BEARISH"].to_numpy() if "BTC_MACRO_BEARISH" in df_merged.columns else np.zeros(n, dtype=bool)

    coin_cfg = config.get_coin_config(symbol)
    signals = []

    for i in range(60, n - 1):
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
                # Giáp 1: BTC Macro Filter
                if symbol != "BTC/USDT" and btc_bearish[i]:
                    continue

                # Giáp 2: Panic Volume Filter
                prev_c = closes[i - 1]
                prev_o = opens[i - 1]
                prev_vol = volumes[i - 1]
                prev_vol_ma = vol_ma[i - 1] if not pd.isna(vol_ma[i - 1]) else 1.0
                if (prev_c < prev_o) and (prev_vol >= 2.2 * prev_vol_ma) and ((prev_o - prev_c) >= 1.2 * atr_val):
                    continue

                # Tinh chỉnh Edge Case ③: Biên độ hộp tối thiểu >= 2.0%
                box_amplitude_pct = (sma20[i] - bbl[i]) / bbl[i] * 100.0
                if box_amplitude_pct < 2.0:
                    continue

                trade_type = "SIDEWAY_RANGE"

        if trade_type is not None:
            signals.append({
                "bar_idx": i,
                "timestamp": pd.Timestamp(timestamps[i]),
                "symbol": symbol,
                "type": trade_type,
                "entry_price": c,
                "atr_val": atr_val,
                "sma20": sma20[i]
            })

    return signals

def run_portfolio_simulation(all_signals, data_by_sym, initial_cap=500.0, risk_pct=0.015, max_open_trades=2, fee_pct=0.08):
    # Sắp xếp tất cả tín hiệu từ các coin theo thứ tự thời gian
    sorted_signals = sorted(all_signals, key=lambda x: x["timestamp"])

    open_positions = [] # [{symbol, entry_time, exit_time, pnl_pct, ...}]
    closed_trades = []
    symbol_last_losses = {} # symbol -> list of loss timestamps (Giáp 3: Cooldown)
    symbol_cooldown_until = {} # symbol -> pd.Timestamp

    for sig in sorted_signals:
        sym = sig["symbol"]
        entry_time = sig["timestamp"]

        # Kiểm tra Giáp 3: Cooldown nếu coin đang bị khóa
        if sym in symbol_cooldown_until and entry_time < symbol_cooldown_until[sym]:
            continue

        # Cập nhật danh sách các lệnh đang mở (đóng các lệnh đã kết thúc trước entry_time)
        open_positions = [pos for pos in open_positions if pos["exit_time"] > entry_time]

        # Kiểm tra Tinh chỉnh Edge Case ②: Portfolio Cap (Tối đa MAX_OPEN_TRADES vị thế mở cùng lúc)
        if len(open_positions) >= max_open_trades:
            continue

        # Đã có vị thế mở trên chính coin này thì không vào trùng
        if any(pos["symbol"] == sym for pos in open_positions):
            continue

        # Mô phỏng diễn biến lệnh từ nến entry_price
        df_sym = data_by_sym[sym]
        i = sig["bar_idx"]
        n = len(df_sym)
        highs = df_sym["high"].to_numpy(dtype=float)
        lows = df_sym["low"].to_numpy(dtype=float)
        closes = df_sym["close"].to_numpy(dtype=float)
        timestamps = df_sym["timestamp"].to_numpy()

        entry_price = sig["entry_price"]
        atr_val = sig["atr_val"]
        trade_type = sig["type"]

        if trade_type == "SNIPER_TREND":
            initial_sl = entry_price - (1.4 * atr_val)
            tp1 = entry_price + (1.5 * atr_val)
            tp2 = entry_price + (5.5 * atr_val)
            tp1_pct = (tp1 - entry_price) / entry_price
            tp2_pct = (tp2 - entry_price) / entry_price
            sl_pct = (entry_price - initial_sl) / entry_price
            tp1_share = 0.35
            tp2_share = 0.65

            tp1_hit = False
            current_sl = initial_sl
            result = "LOSS"
            pnl_pct = 0.0
            hold_bars = 60
            end = min(i + 1 + hold_bars, n)
            exit_time = pd.Timestamp(timestamps[end - 1])

            for j in range(i + 1, end):
                if not tp1_hit:
                    if highs[j] >= tp1:
                        tp1_hit = True
                        # Tinh chỉnh Edge Case ①: Đặt SL đệm an toàn (Entry - 0.2 ATR) thay vì dính chặt tại Entry
                        current_sl = entry_price - 0.2 * atr_val
                        if highs[j] >= tp2:
                            result = "WIN"
                            pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                            exit_time = pd.Timestamp(timestamps[j])
                            break
                    elif lows[j] <= current_sl:
                        result = "LOSS"
                        pnl_pct = -sl_pct * 100
                        exit_time = pd.Timestamp(timestamps[j])
                        break
                else:
                    # Nâng SL khóa lãi khi giá đạt 3.0 ATR
                    if highs[j] >= entry_price + 3.0 * atr_val:
                        current_sl = max(current_sl, entry_price + 1.2 * atr_val)

                    if highs[j] >= tp2:
                        result = "WIN"
                        pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                        exit_time = pd.Timestamp(timestamps[j])
                        break
                    elif lows[j] <= current_sl:
                        result = "WIN"
                        locked_pct = (current_sl - entry_price) / entry_price
                        pnl_pct = (tp1_share * tp1_pct + tp2_share * locked_pct) * 100
                        exit_time = pd.Timestamp(timestamps[j])
                        break

            if result != "WIN" and pnl_pct == 0.0:
                pnl_pct = ((closes[end - 1] - entry_price) / entry_price) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        else: # SIDEWAY_RANGE
            sl_price = entry_price - (1.2 * atr_val)
            tp_price = max(sig["sma20"], entry_price + 1.3 * atr_val)
            sl_pct = (entry_price - sl_price) / entry_price
            tp_pct = (tp_price - entry_price) / entry_price
            hold_bars = 16
            end = min(i + 1 + hold_bars, n)
            result = "LOSS"
            pnl_pct = -sl_pct * 100
            exit_time = pd.Timestamp(timestamps[end - 1])

            for j in range(i + 1, end):
                if highs[j] >= tp_price:
                    result = "WIN"
                    pnl_pct = tp_pct * 100
                    exit_time = pd.Timestamp(timestamps[j])
                    break
                elif lows[j] <= sl_price:
                    result = "LOSS"
                    pnl_pct = -sl_pct * 100
                    exit_time = pd.Timestamp(timestamps[j])
                    break

            if result != "WIN" and pnl_pct == -sl_pct * 100:
                pnl_pct = ((closes[end - 1] - entry_price) / entry_price) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        # Trừ phí sàn Taker Round-trip (0.08%)
        net_pnl_pct = pnl_pct - fee_pct

        trade_info = {
            "symbol": sym,
            "type": trade_type,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": round(entry_price, 4),
            "sl_pct": round(sl_pct, 4),
            "result": "WIN" if net_pnl_pct > 0 else "LOSS",
            "pnl_pct": round(net_pnl_pct, 2)
        }

        # Cập nhật Giáp 3: Cooldown nếu dính 2 SL liên tiếp
        if trade_info["result"] == "LOSS":
            if sym not in symbol_last_losses:
                symbol_last_losses[sym] = []
            symbol_last_losses[sym].append(exit_time)
            if len(symbol_last_losses[sym]) >= 2:
                if (symbol_last_losses[sym][-1] - symbol_last_losses[sym][-2]).total_seconds() <= 72 * 3600:
                    symbol_cooldown_until[sym] = exit_time + timedelta(days=3)

        open_positions.append(trade_info)
        closed_trades.append(trade_info)

    return closed_trades

def calc_detailed_stats(trades_list, start_dt, end_dt=None, initial_cap=500.0, risk_pct=0.015):
    if not trades_list:
        return {}

    df = pd.DataFrame(trades_list)
    df = df[df["entry_time"] >= start_dt]
    if end_dt is not None:
        df = df[df["entry_time"] < end_dt]
    df = df.sort_values("entry_time").reset_index(drop=True)

    total = len(df)
    if total == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0.0, "pf": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "payoff": 0.0, "balance": initial_cap, "roi": 0.0, "max_dd": 0.0}

    wins = int((df["result"] == "WIN").sum())
    losses = total - wins
    wr = round(wins / total * 100, 2)

    win_pnls = df[df["pnl_pct"] > 0]["pnl_pct"]
    loss_pnls = df[df["pnl_pct"] < 0]["pnl_pct"]
    avg_win = round(float(win_pnls.mean()), 2) if len(win_pnls) > 0 else 0.0
    avg_loss = round(abs(float(loss_pnls.mean())), 2) if len(loss_pnls) > 0 else 0.0
    payoff = round(avg_win / avg_loss, 2) if avg_loss > 0 else 99.9

    gp = float(win_pnls.sum())
    gl = abs(float(loss_pnls.sum()))
    pf = round(gp / gl, 2) if gl > 0 else 99.9

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
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "profit_factor": pf,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "final_balance": round(balance, 2),
        "net_profit": round(balance - initial_cap, 2),
        "roi": roi,
        "max_dd": max_dd
    }

def main():
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
    df_btc_1d = load_market_data("BTC/USDT", "1d")
    btc_macro = build_btc_macro(df_btc_1d)

    data_by_sym = {}
    all_signals = []

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
        merged = pd.merge_asof(
            merged.sort_values("timestamp"),
            btc_macro.sort_values("timestamp"),
            on="timestamp",
            direction="backward"
        )
        data_by_sym[sym] = merged
        all_signals.extend(generate_signals(merged, sym))

    master_trades = run_portfolio_simulation(
        all_signals,
        data_by_sym,
        initial_cap=500.0,
        risk_pct=0.015,
        max_open_trades=2, # Giới hạn tối đa 2 lệnh mở cùng lúc
        fee_pct=0.08       # Trừ phí sàn thực tế
    )

    df_sample = pd.DataFrame(master_trades)
    max_dt = df_sample["entry_time"].max()

    horizons = {
        "24 Tháng (Toàn bộ chu kỳ)": max_dt - timedelta(days=730),
        "12 Tháng (1 năm)": max_dt - timedelta(days=365),
        "9 Tháng gần nhất": max_dt - timedelta(days=270),
        "3 Tháng gần nhất": max_dt - timedelta(days=90),
    }

    report = {}
    for h_name, dt in horizons.items():
        stats = calc_detailed_stats(master_trades, dt, None, 500.0, 0.015)
        report[h_name] = stats

    out_file = os.path.join(BASE_DIR, "reports", "master_production_backtest.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n==========================================================================================")
    print("        KẾT QUẢ MASTER PRODUCTION BACKTEST TOÀN DIỆN (ĐÃ TRỪ PHÍ SÀN & MAX 2 LỆNH)        ")
    print("==========================================================================================")
    for h_name, s in report.items():
        print(f"\n>>> MỐC THỜI GIAN: {h_name.upper()}")
        print(f"  Số Lệnh: {s['trades']} (Thắng: {s['wins']} / Thua: {s['losses']})")
        print(f"  Win Rate: {s['win_rate']}% | Profit Factor: {s['profit_factor']}x | Payoff Ratio: 1:{s['payoff_ratio']}")
        print(f"  Lãi TB: +{s['avg_win']}% | Lỗ TB: -{s['avg_loss']}%")
        print(f"  Số Dư: ${s['final_balance']} (Lãi ròng: +${s['net_profit']} | ROI: +{s['roi']}%)")
        print(f"  Max Drawdown (Sụt giảm tối đa): {s['max_dd']}%")

if __name__ == "__main__":
    main()
