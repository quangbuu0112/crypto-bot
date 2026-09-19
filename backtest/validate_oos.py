"""
Kiểm chứng out-of-sample (OOS) cho bộ tham số tối ưu.

Chia dữ liệu 24 tháng thành:
  • In-sample  (train): 70% đầu  -> dùng để TỐI ƯU tham số
  • Out-of-sample (test): 30% cuối -> dùng để KIỂM CHỨNG (chưa từng được tối ưu)

Quy trình:
  1. Tối ưu tham số CHỈ trên train (2 giai đoạn như optimize_params.py).
  2. Đánh giá cấu hình tìm được trên test.
  3. So sánh hiệu năng train vs test để xem chiến lược có bền vững không.

Cách dùng:
    python backtest/validate_oos.py
"""

import itertools
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402
import back_test as bt  # noqa: E402

SYMBOLS = config.SYMBOLS
SPLIT_RATIO = 0.7          # 70% train / 30% test

# Nạp dữ liệu thô 1 lần duy nhất
RAW = {
    s: {
        "1d": bt.load_market_data(s, "1d"),
        "4h": bt.load_market_data(s, "4h"),
    }
    for s in SYMBOLS
}


def run_all_window(params: dict, start_ts=None, end_ts=None) -> dict:
    """Chạy backtest toàn bộ coin trong 1 khoảng thời gian, trả về thống kê."""
    total = wins = losses = sideways = 0
    pnl_sum = 0.0
    gross_profit = 0.0
    gross_loss = 0.0

    for s in SYMBOLS:
        df = bt.prepare_data(RAW[s]["1d"], RAW[s]["4h"], params)
        trades = bt.evaluate_signals(df, s, params, with_details=False,
                                     start_ts=start_ts, end_ts=end_ts)
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


def search_on_window(grid: dict, base_params: dict, start_ts, end_ts,
                     min_signals: int = 30, top_n: int = 10, label: str = ""):
    """Grid search trong 1 khoảng thời gian, xếp hạng theo PnL."""
    keys = list(grid.keys())
    rows = []

    for combo in itertools.product(*[grid[k] for k in keys]):
        params = dict(base_params)
        combo_map = dict(zip(keys, combo))
        params.update(combo_map)

        st = run_all_window(params, start_ts, end_ts)
        st["combo"] = combo_map
        rows.append(st)

    eligible = [r for r in rows if r["signals"] >= min_signals]
    eligible.sort(key=lambda r: r["pnl"], reverse=True)

    print("\n" + "=" * 90)
    print(f"🔎 {label}  (chỉ xét >= {min_signals} lệnh)")
    print("=" * 90)
    print(f"{'PnL':>9} | {'WinRate':>7} | {'Lệnh':>5} | {'AvgPnL':>7} | {'PF':>6} | Params")
    print("-" * 90)
    for r in eligible[:top_n]:
        combo_str = ", ".join(f"{k}={v}" for k, v in r["combo"].items())
        print(f"{r['pnl']:+9.2f} | {r['win_rate']:6.1f}% | {r['signals']:>5} | "
              f"{r['avg_pnl']:>+7.3f} | {r['pf']:>6} | {combo_str}")

    return eligible


def print_stats(label: str, st: dict):
    print(f"{label:<24} | PnL {st['pnl']:+8.2f}% | WinRate {st['win_rate']:5.1f}% | "
          f"{st['signals']:>4} lệnh | AvgPnL {st['avg_pnl']:+.3f}% | PF {st['pf']}")


def main():
    # 1. Xác định khoảng thời gian và điểm chia
    times = pd.concat([RAW[s]["4h"]["timestamp"] for s in SYMBOLS])
    data_start = times.min()
    data_end = times.max()
    split_ts = data_start + (data_end - data_start) * SPLIT_RATIO

    print("=" * 90)
    print("🧪 KIỂM CHỨNG OUT-OF-SAMPLE (TRÁNH OVERFITTING)")
    print("=" * 90)
    print(f"• Dữ liệu     : {data_start.date()} → {data_end.date()}")
    print(f"• Điểm chia   : {split_ts.date()}  (train {SPLIT_RATIO * 100:.0f}% / test {(1 - SPLIT_RATIO) * 100:.0f}%)")
    print(f"• Train (IS)  : {data_start.date()} → {split_ts.date()}")
    print(f"• Test  (OOS) : {split_ts.date()} → {data_end.date()}")

    train_start, train_end = data_start, split_ts
    test_start, test_end = split_ts, data_end

    # 2. Hai mốc đối chiếu
    baseline = {  # tham số gốc ban đầu (trước khi tối ưu)
        "hold_bars": 24, "stop_loss_pct": 0.01, "take_profit_pct": 0.015,
        "ema_trend_len": 200, "ema_entry_len": 20, "rsi_len": 14,
        "rsi_low": 50, "rsi_high": 68, "adx_len": 14, "adx_threshold": 20,
        "vol_mult": 1.1, "warmup_4h": 60,
    }
    global_opt = dict(bt.DEFAULT_PARAMS)  # cấu hình +296% (tối ưu trên TOÀN BỘ dữ liệu)

    print("\n" + "=" * 90)
    print("📊 ĐỐI CHIẾU: In-sample (train) vs Out-of-sample (test)")
    print("=" * 90)
    print_stats("BASELINE — TRAIN", run_all_window(baseline, train_start, train_end))
    print_stats("BASELINE — TEST ", run_all_window(baseline, test_start, test_end))
    print_stats("GLOBAL OPT — TRAIN", run_all_window(global_opt, train_start, train_end))
    print_stats("GLOBAL OPT — TEST ", run_all_window(global_opt, test_start, test_end))

    # 3. Tối ưu CHỈ trên train (2 giai đoạn) — không dùng bất kỳ thông tin test nào
    base = dict(baseline)  # bắt đầu từ tham số gốc, độc lập hoàn toàn với test

    grid1 = {
        "hold_bars": [12, 24, 48, 96],
        "stop_loss_pct": [0.008, 0.01, 0.015, 0.02],
        "take_profit_pct": [0.015, 0.02, 0.03, 0.04],
    }
    res1 = search_on_window(grid1, base, train_start, train_end,
                            min_signals=30, label="TRAIN — GIAI ĐOẠN 1: HOLD/SL/TP")
    base.update(res1[0]["combo"])

    grid2 = {
        "ema_trend_len": [100, 150, 200],
        "ema_entry_len": [15, 20, 30],
        "rsi_len": [10, 14, 21],
        "adx_threshold": [18, 20, 25],
        "vol_mult": [1.0, 1.1, 1.25],
    }
    res2 = search_on_window(grid2, base, train_start, train_end,
                            min_signals=30, label="TRAIN — GIAI ĐOẠN 2: EMA/RSI/ADX/Volume")
    base.update(res2[0]["combo"])
    best_train = base

    print(f"\n✅ Cấu hình tối ưu TRÊN TRAIN: {best_train}")

    # 4. Đánh giá cấu hình train-tối-ưu trên cả train và test
    st_train = run_all_window(best_train, train_start, train_end)
    st_test = run_all_window(best_train, test_start, test_end)

    print("\n" + "=" * 90)
    print("🎯 KẾT QUẢ KIỂM CHỨNG CẤU HÌNH TỐI ƯU TRÊN TRAIN")
    print("=" * 90)
    print_stats("TRAIN (đã tối ưu)", st_train)
    print_stats("TEST  (chưa thấy)", st_test)

    # 5. Kết luận nhanh
    print("\n" + "-" * 90)
    print(f"• Chênh lệch PnL (test − train) : {st_test['pnl'] - st_train['pnl']:+.2f}%")
    print(f"• Chênh lệch WinRate            : {st_test['win_rate'] - st_train['win_rate']:+.1f} điểm %")
    if st_test["pnl"] > 0 and st_test["pf"] > 1.0:
        print("✅ Chiến lược vẫn có lợi nhuận trên dữ liệu ngoài mẫu → đáng tin cậy hơn.")
    else:
        print("⚠️ Hiệu năng sụt giảm trên dữ liệu ngoài mẫu → dấu hiệu overfitting, cần thận trọng.")
    print("=" * 90)


if __name__ == "__main__":
    main()
