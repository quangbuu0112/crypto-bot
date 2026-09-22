"""
Backtest Thử Nghiệm: Tích Hợp 3 Lớp Giáp Bảo Vệ (Defensive Shields)
So sánh Trước và Sau khi trang bị:
1. Giáp 1: BTC Macro Filter (Nếu BTC 1D đóng dưới EMA50 và RSI 1D < 45 -> Cấm bắt đáy Altcoin).
2. Giáp 2: Panic Volume Filter (Nếu nến giảm có Volume > 2.2x VOL_MA -> Cá voi xả hoảng loạn, cấm bắt dao rơi).
3. Giáp 3: Consecutive Loss Cooldown (Nếu 1 coin dính 2 SL liên tiếp trong 48h -> Khóa coin đó 3 ngày).
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
    # BTC Bearish Shock = Đóng dưới EMA50 VÀ RSI 1D < 45
    df["BTC_MACRO_BEARISH"] = (df["close"] < df["BTC_EMA_50"]) & (df["BTC_RSI_1D"] < 45)
    return df[["timestamp", "BTC_MACRO_BEARISH", "BTC_RSI_1D"]]

def simulate_trades(df_merged: pd.DataFrame, symbol: str, use_shields: bool = True) -> list:
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

    btc_macro_bearish = df_merged["BTC_MACRO_BEARISH"].to_numpy() if "BTC_MACRO_BEARISH" in df_merged.columns else np.zeros(n, dtype=bool)

    coin_cfg = config.get_coin_config(symbol)

    trades = []
    recent_losses = [] # Lưu timestamp của các lệnh thua gần nhất để check Cooldown
    cooldown_until_idx = 0

    i = 60
    while i < n - 1:
        # Kiểm tra Giáp 3: Cooldown nếu dính chuỗi thua liên tiếp
        if use_shields and i < cooldown_until_idx:
            i += 1
            continue

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
                # ÁP DỤNG CÁC LỚP GIÁP BẢO VỆ CHO SIDEWAY:
                if use_shields:
                    # Giáp 1: BTC Macro Filter - Nếu BTC đang sập mạnh trên 1D -> Cấm bắt đáy Altcoin
                    if symbol != "BTC/USDT" and btc_macro_bearish[i]:
                        i += 1
                        continue

                    # Giáp 2: Panic Volume Filter - Nếu nến trước là nến xả đỏ đặc Volume khủng -> Bỏ qua
                    prev_c = closes[i - 1]
                    prev_o = opens[i - 1]
                    prev_vol = volumes[i - 1]
                    prev_vol_ma = vol_ma[i - 1] if not pd.isna(vol_ma[i - 1]) else 1.0
                    is_panic_dump = (prev_c < prev_o) and (prev_vol >= 2.2 * prev_vol_ma) and ((prev_o - prev_c) >= 1.2 * atr_val)
                    if is_panic_dump:
                        i += 1
                        continue

                trade_type = "SIDEWAY_RANGE"

        if trade_type is None:
            i += 1
            continue

        entry_price = c
        entry_time = pd.Timestamp(timestamps[i])

        if trade_type == "SNIPER_TREND":
            atr_sl_mult = 1.4
            tp1_mult = 1.5
            tp2_mult = 5.5
            tp1_share = 0.35
            tp2_share = 0.65
            hold_bars = 60

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
            sideway_sl_mult = 1.2
            sl_price = entry_price - (sideway_sl_mult * atr_val)
            tp_price = max(sma20[i], entry_price + 1.3 * atr_val)
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

        # Cập nhật Cooldown Giáp 3 nếu dính chuỗi 2 lệnh thua
        if use_shields:
            if result == "LOSS":
                recent_losses.append(i)
                # Nếu có 2 lệnh thua trong vòng 18 nến (72 giờ) -> kích hoạt Cooldown 18 nến (3 ngày)
                if len(recent_losses) >= 2 and (recent_losses[-1] - recent_losses[-2] <= 18):
                    cooldown_until_idx = i + 18

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
    
    # 1. Load data & BTC Macro
    df_btc_1d = load_market_data("BTC/USDT", "1d")
    btc_macro = build_btc_macro(df_btc_1d)

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
        # Ghép thêm BTC Macro
        merged = pd.merge_asof(
            merged.sort_values("timestamp"),
            btc_macro.sort_values("timestamp"),
            on="timestamp",
            direction="backward"
        )
        data_by_sym[sym] = merged

    no_shield_trades = []
    shielded_trades = []

    for sym in symbols:
        no_shield_trades.extend(simulate_trades(data_by_sym[sym], sym, use_shields=False))
        shielded_trades.extend(simulate_trades(data_by_sym[sym], sym, use_shields=True))

    df_sample = pd.DataFrame(no_shield_trades)
    max_dt = df_sample["entry_time"].max()

    horizons = {
        "24 Tháng (Toàn bộ chu kỳ)": (max_dt - timedelta(days=730), None),
        "12 Tháng (1 năm)": (max_dt - timedelta(days=365), None),
        "9 Tháng gần nhất (Từng bị âm)": (max_dt - timedelta(days=270), None),
        "6 Tháng ở giữa (Pha thị trường xấu)": (max_dt - timedelta(days=270), max_dt - timedelta(days=90)),
        "3 Tháng gần nhất (Pha thị trường tốt)": (max_dt - timedelta(days=90), None),
    }

    results = {}
    for h_name, (start_dt, end_dt) in horizons.items():
        raw = calc_detailed_stats(no_shield_trades, start_dt, end_dt, 500.0, 0.015)
        shielded = calc_detailed_stats(shielded_trades, start_dt, end_dt, 500.0, 0.015)
        results[h_name] = {
            "KHONG_GIAP (Raw Dual)": raw,
            "CO_3_LOP_GIAP (Shielded Pro)": shielded
        }

    out_file = os.path.join(BASE_DIR, "reports", "defensive_shields_comparison.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n==========================================================================================")
    print("           KẾT QUẢ BACKTEST: ĐO LƯỜNG SỨC MẠNH CỦA 3 LỚP GIÁP BẢO VỆ THỊ TRƯỜNG           ")
    print("==========================================================================================")
    for h_name, data in results.items():
        r = data["KHONG_GIAP (Raw Dual)"]
        s = data["CO_3_LOP_GIAP (Shielded Pro)"]
        print(f"\n>>> GIAI ĐOẠN: {h_name.upper()}")
        print(f"  [CHƯA CÓ GIÁP] Lệnh: {r['trades']} (W:{r['wins']}/L:{r['losses']}) | WR: {r['win_rate']}% | PF: {r['profit_factor']} | ROI: {r['roi']}% (${r['final_balance']}) | MDD: {r['max_dd']}%")
        print(f"  [CÓ 3 LỚP GIÁP] Lệnh: {s['trades']} (W:{s['wins']}/L:{s['losses']}) | WR: {s['win_rate']}% | PF: {s['profit_factor']} | ROI: {s['roi']}% (${s['final_balance']}) | MDD: {s['max_dd']}%")

if __name__ == "__main__":
    main()
