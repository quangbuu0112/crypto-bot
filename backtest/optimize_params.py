"""
Grid search tìm bộ tham số tốt nhất cho chiến lược backtest.
Chạy hoàn toàn trên dữ liệu local 24 tháng (không cần mạng, không gọi Gemini).

Hai giai đoạn:
  1. Tối ưu quản trị vốn (hold_bars, SL, TP) với bộ chỉ báo mặc định.
  2. Giữ TP/SL/hold tốt nhất, tối ưu chu kỳ chỉ báo (EMA/RSI/ADX/Volume).

Kết quả lưu vào: reports/optimize_results.csv

Cách dùng:
    python backtest/optimize_params.py
"""

import csv
import json
import itertools
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402
import back_test as bt  # noqa: E402

SYMBOLS = config.SYMBOLS

# Nạp dữ liệu thô 1 lần duy nhất (tránh đọc file JSON lặp lại)
RAW = {
    s: {
        "1d": bt.load_market_data(s, "1d"),
        "4h": bt.load_market_data(s, "4h"),
    }
    for s in SYMBOLS
}

ALL_ROWS = []  # lưu toàn bộ kết quả để xuất CSV


def run_all(params: dict) -> dict:
    """Chạy backtest toàn bộ coin với 1 bộ tham số, trả về thống kê tổng hợp."""
    total = wins = losses = sideways = 0
    pnl_sum = 0.0
    gross_profit = 0.0
    gross_loss = 0.0

    for s in SYMBOLS:
        df = bt.prepare_data(RAW[s]["1d"], RAW[s]["4h"], params)
        trades = bt.evaluate_signals(df, s, params, with_details=False)
        for t in trades:
            total += 1
            pnl_sum += t["pnl_pct"]
            if t["result"] == "WIN":
                wins += 1
                gross_profit += t["pnl_pct"]
            elif t["result"] == "LOSS":
                losses += 1
                gross_loss += abs(t["pnl_pct"])
            else:
                sideways += 1

    decided = wins + losses
    win_rate = (wins / decided * 100) if decided else 0.0
    avg_pnl = (pnl_sum / total) if total else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    return {
        "signals": total,
        "wins": wins,
        "losses": losses,
        "sideways": sideways,
        "win_rate": round(win_rate, 2),
        "pnl": round(pnl_sum, 2),
        "avg_pnl": round(avg_pnl, 4),
        "pf": round(profit_factor, 2),
    }


def search(grid: dict, base_params: dict, stage: str, min_signals: int = 40, top_n: int = 15):
    """Duyệt toàn bộ tổ hợp trong grid, xếp hạng theo PnL, in top N."""
    keys = list(grid.keys())

    for combo in itertools.product(*[grid[k] for k in keys]):
        params = dict(base_params)
        combo_map = dict(zip(keys, combo))
        params.update(combo_map)

        st = run_all(params)
        st["stage"] = stage
        st["combo"] = combo_map
        ALL_ROWS.append(st)

    eligible = [r for r in ALL_ROWS if r["stage"] == stage and r["signals"] >= min_signals]
    eligible.sort(key=lambda r: r["pnl"], reverse=True)

    print("\n" + "=" * 95)
    print(f"🔎 {stage}  (chỉ xét cấu hình >= {min_signals} lệnh)")
    print("=" * 95)
    print(f"{'PnL':>9} | {'WinRate':>7} | {'Lệnh':>5} | {'AvgPnL':>7} | {'PF':>6} | Params")
    print("-" * 95)
    for r in eligible[:top_n]:
        combo_str = ", ".join(f"{k}={v}" for k, v in r["combo"].items())
        print(f"{r['pnl']:+9.2f} | {r['win_rate']:6.1f}% | {r['signals']:>5} | "
              f"{r['avg_pnl']:>+7.3f} | {r['pf']:>6} | {combo_str}")

    return eligible


def save_results(path: str):
    """Xuất toàn bộ kết quả grid search ra CSV."""
    fieldnames = ["stage", "pnl", "win_rate", "signals", "wins", "losses", "sideways",
                  "avg_pnl", "pf"]
    combo_keys = sorted({k for r in ALL_ROWS for k in r["combo"]})
    fieldnames += combo_keys

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in ALL_ROWS:
            row = {k: r.get(k) for k in fieldnames}
            row.update(r["combo"])
            writer.writerow(row)

    print(f"\n💾 Đã lưu {len(ALL_ROWS)} cấu hình vào: {path}")


def main():
    print("=" * 95)
    print("🧪 TỐI ƯU THAM SỐ CHIẾN LƯỢC (1D trend + 4H entry) — Dữ liệu 24 tháng, 5 coin")
    print("=" * 95)

    base = dict(bt.DEFAULT_PARAMS)
    baseline = run_all(base)
    print(f"BASELINE (mặc định): PnL {baseline['pnl']:+.2f}% | WinRate {baseline['win_rate']:.1f}% "
          f"| {baseline['signals']} lệnh | AvgPnL {baseline['avg_pnl']:+.3f}% | PF {baseline['pf']}")

    # ============ GIAI ĐOẠN 1: quản trị vốn ============
    grid1 = {
        "hold_bars": [12, 24, 48, 96],
        "stop_loss_pct": [0.008, 0.01, 0.015, 0.02],
        "take_profit_pct": [0.015, 0.02, 0.03, 0.04],
    }
    res1 = search(grid1, base, "GIAI ĐOẠN 1: Tối ưu HOLD_BARS / SL / TP")

    best1 = res1[0]["combo"]
    base.update(best1)
    print(f"\n✅ Chọn tốt nhất giai đoạn 1: {best1}")

    # ============ GIAI ĐOẠN 2: chu kỳ chỉ báo ============
    grid2 = {
        "ema_trend_len": [100, 150, 200],
        "ema_entry_len": [15, 20, 30],
        "rsi_len": [10, 14, 21],
        "adx_threshold": [18, 20, 25],
        "vol_mult": [1.0, 1.1, 1.25],
    }
    res2 = search(grid2, base, "GIAI ĐOẠN 2: Tối ưu EMA / RSI / ADX / Volume")

    best2 = res2[0]["combo"]
    base.update(best2)
    print(f"\n✅ Chọn tốt nhất giai đoạn 2: {best2}")

    # ============ TỔNG KẾT ============
    final = run_all(base)

    print("\n" + "=" * 95)
    print("🏆 BỘ THAM SỐ TỐT NHẤT TÌM ĐƯỢC")
    print("=" * 95)
    print(json.dumps(base, indent=2, ensure_ascii=False))
    print("-" * 95)
    print(f"• PnL      : {final['pnl']:+.2f}%")
    print(f"• Win Rate : {final['win_rate']:.1f}%")
    print(f"• Số lệnh  : {final['signals']}")
    print(f"• Avg PnL  : {final['avg_pnl']:+.3f}% / lệnh")
    print(f"• PF       : {final['pf']}")
    print("-" * 95)
    print(f"BASELINE cũ   : PnL {baseline['pnl']:+.2f}% | WinRate {baseline['win_rate']:.1f}% | {baseline['signals']} lệnh")
    print(f"Cải thiện PnL : {final['pnl'] - baseline['pnl']:+.2f}%")
    print("=" * 95)

    save_results(os.path.join(BASE_DIR, "reports", "optimize_results.csv"))


if __name__ == "__main__":
    main()
