"""
Phân tích regime (chế độ thị trường) giữa train và test để hiểu vì sao
chiến lược trend-following thua lỗ ngoài mẫu.

Tính cho từng giai đoạn và từng coin:
  • Lợi nhuận tích lũy (%)
  • Max Drawdown (%)
  • Biến động (annualized volatility, %)
  • % số ngày đóng cửa trên EMA 200  (mức độ UPTREND)
  • ADX trung bình (độ mạnh xu hướng)
  • % ngày tăng

Từ đó phân loại regime: UPTREND / DOWNTREND / SIDEWAY-CHOPPY.

Cách dùng:
    python backtest/regime_analysis.py
"""

import os
import sys

import numpy as np
import pandas as pd
import pandas_ta as ta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402
import back_test as bt  # noqa: E402

SYMBOLS = config.SYMBOLS
SPLIT_RATIO = 0.7
EMA_TREND = 200


def period_stats(df: pd.DataFrame, start_ts, end_ts) -> dict:
    """Tính các chỉ số regime của 1 coin trong 1 khoảng thời gian."""
    mask = (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
    d = df[mask]

    closes = d["close"].astype(float)
    ret_total = (closes.iloc[-1] / closes.iloc[0] - 1) * 100

    daily = closes.pct_change().dropna()
    ann_vol = daily.std() * np.sqrt(365) * 100

    cummax = closes.cummax()
    max_dd = ((closes / cummax) - 1).min() * 100

    valid = d["EMA200"].notna()
    above_ema = (d.loc[valid, "close"] > d.loc[valid, "EMA200"]).mean() * 100 if valid.any() else float("nan")

    adx_avg = d["ADX14"].mean()  # mean() tự bỏ NaN
    up_days = (daily > 0).mean() * 100

    return {
        "return_pct": round(ret_total, 2),
        "max_dd_pct": round(max_dd, 2),
        "ann_vol_pct": round(ann_vol, 2),
        "above_ema200": round(above_ema, 2),
        "adx_avg": round(adx_avg, 2),
        "up_days": round(up_days, 2),
    }


def classify_regime(ret: float, above_ema: float, vol: float, adx: float) -> str:
    """Phân loại chế độ thị trường dựa trên BTC."""
    if ret > 20 and above_ema > 55:
        return "UPTREND (tăng mạnh)"
    if ret < -15:
        return "DOWNTREND (giảm)"
    if vol > 80 and adx < 25:
        return "CHOPPY (đi ngang, nhiễu cao)"
    return "SIDEWAY (đi ngang)"


def main():
    # Nạp dữ liệu 1D của các coin, tính sẵn EMA200 & ADX14 trên toàn bộ lịch sử
    full = {}
    for s in SYMBOLS:
        df = bt.load_market_data(s, "1d")
        df["EMA200"] = ta.ema(df["close"], length=EMA_TREND)
        df["ADX14"] = ta.adx(df["high"], df["low"], df["close"], length=14)["ADX_14"]
        full[s] = df

    times = pd.concat([full[s]["timestamp"] for s in SYMBOLS])
    data_start = times.min()
    data_end = times.max()
    split_ts = data_start + (data_end - data_start) * SPLIT_RATIO

    print("=" * 92)
    print("🌦️  PHÂN TÍCH REGIME THỊ TRƯỜNG (khung 1D)")
    print("=" * 92)
    print(f"• Dữ liệu   : {data_start.date()} → {data_end.date()}")
    print(f"• Điểm chia : {split_ts.date()}  (train {SPLIT_RATIO * 100:.0f}% / test {(1 - SPLIT_RATIO) * 100:.0f}%)")

    periods = [
        ("TRAIN (đã tối ưu)", data_start, split_ts),
        ("TEST  (chưa thấy) ", split_ts, data_end),
    ]

    header = (f"{'Coin':<10} | {'Return':>8} | {'MaxDD':>7} | {'AnnVol':>7} | "
              f"{'%>EMA200':>8} | {'ADX':>6} | {'%UpDays':>7}")
    print("\n" + header)
    print("-" * 92)

    btc_summary = {}

    for pname, ps, pe in periods:
        print(f"\n▶ {pname}  ({ps.date()} → {pe.date()})")
        print("-" * 92)
        for s in SYMBOLS:
            st = period_stats(full[s], ps, pe)
            print(f"{s:<10} | {st['return_pct']:>+7.2f}% | {st['max_dd_pct']:>+6.2f}% | "
                  f"{st['ann_vol_pct']:>6.2f}% | {st['above_ema200']:>7.1f}% | "
                  f"{st['adx_avg']:>5.2f} | {st['up_days']:>6.1f}%")
            if s == "BTC/USDT":
                btc_summary[pname] = st

    # Kết luận regime cho từng giai đoạn
    print("\n" + "=" * 92)
    print("🧭 KẾT LUẬN REGIME")
    print("=" * 92)
    for pname, ps, pe in periods:
        st = btc_summary[pname]
        regime = classify_regime(st["return_pct"], st["above_ema200"],
                                 st["ann_vol_pct"], st["adx_avg"])
        print(f"• {pname.strip():<18} : BTC {st['return_pct']:+.2f}% | "
              f"%>EMA200 {st['above_ema200']:.0f}% | ADX {st['adx_avg']:.1f} | "
              f"AnnVol {st['ann_vol_pct']:.0f}%  →  {regime}")

    # Biến động BTC theo từng tháng để thấy sự dịch chuyển regime
    print("\n" + "=" * 92)
    print("📅 BIẾN ĐỘNG BTC THEO THÁNG (đánh dấu train/test)")
    print("=" * 92)
    btc = full["BTC/USDT"].copy()
    btc["month"] = btc["timestamp"].dt.to_period("M")
    monthly = btc.groupby("month")["close"].agg(first="first", last="last")
    monthly["ret_pct"] = (monthly["last"] / monthly["first"] - 1) * 100

    for month, row in monthly.iterrows():
        tag = "TRAIN" if month.start_time <= split_ts else "TEST"
        bar = "█" * min(int(abs(row["ret_pct"]) / 2), 25)
        sign = "+" if row["ret_pct"] >= 0 else ""
        print(f"  {month}  {sign}{row['ret_pct']:6.2f}%  {bar:<25} [{tag}]")

    print("=" * 92)


if __name__ == "__main__":
    main()
