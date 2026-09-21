"""
Công cụ phân tích & tổng hợp hiệu suất Paper Trading thực tế.
Đọc dữ liệu từ paper_trades.json, tính toán thống kê chi tiết và xuất báo cáo CSV.

Cách dùng:
    python tools/analyze_paper_trades.py
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

TRADES_FILE = os.path.join(BASE_DIR, "paper_trades.json")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
REPORT_CSV = os.path.join(REPORT_DIR, "live_paper_performance.csv")

def analyze_performance():
    if not os.path.exists(TRADES_FILE):
        print("📁 Chưa tìm thấy file paper_trades.json!")
        return

    with open(TRADES_FILE, "r", encoding="utf-8") as f:
        try:
            trades = json.load(f)
        except Exception as e:
            print(f"❌ Lỗi đọc paper_trades.json: {e}")
            return

    if not trades:
        print("📭 Chưa có lệnh nào trong nhật ký paper_trades.json.")
        return

    df = pd.DataFrame(trades)

    total_trades = len(df)
    open_trades = df[df["status"] == "OPEN"]
    closed_trades = df[df["status"] != "OPEN"].copy()

    print("\n" + "=" * 65)
    print("📊 BÁO CÁO HIỆU SUẤT PAPER TRADING THỰC TẾ (LIVE MARKET)")
    print(f"⏰ Thời điểm xuất báo cáo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    print(f"\n🔢 TỔNG QUAN:")
    print(f"   • Tổng số lệnh đã ghi nhận : {total_trades}")
    print(f"   • Số lệnh đang mở (OPEN)    : {len(open_trades)}")
    print(f"   • Số lệnh đã đóng (CLOSED)  : {len(closed_trades)}")

    if len(closed_trades) == 0:
        print("\n⏳ Chưa có lệnh nào đóng vị thế để tính toán Winrate và PnL.")
        print("=" * 65 + "\n")
        return

    closed_trades["pnl_pct"] = pd.to_numeric(closed_trades["pnl_pct"], errors="coerce").fillna(0.0)

    wins = closed_trades[closed_trades["pnl_pct"] > 0]
    losses = closed_trades[closed_trades["pnl_pct"] <= 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / len(closed_trades)) * 100 if len(closed_trades) > 0 else 0.0
    total_pnl = closed_trades["pnl_pct"].sum()
    avg_win = wins["pnl_pct"].mean() if len(wins) > 0 else 0.0
    avg_loss = losses["pnl_pct"].mean() if len(losses) > 0 else 0.0
    profit_factor = abs(wins["pnl_pct"].sum() / losses["pnl_pct"].sum()) if losses["pnl_pct"].sum() != 0 else float("inf")

    print(f"\n🎯 KẾT QUẢ GIAO DỊCH:")
    print(f"   • Số lệnh Thắng (WIN)       : {win_count} ({win_rate:.1f}%)")
    print(f"   • Số lệnh Thua (LOSS)       : {loss_count} ({100 - win_rate:.1f}%)")
    print(f"   • Tổng PnL tích lũy         : {total_pnl:+.2f}%")
    print(f"   • Lãi trung bình / lệnh WIN : {avg_win:+.2f}%")
    print(f"   • Lỗ trung bình / lệnh LOSS : {avg_loss:.2f}%")
    print(f"   • Tỷ số Lời/Lỗ (Profit Factor): {profit_factor:.2f}")

    # 1. Thống kê theo từng cặp coin
    print(f"\n🪙 THỐNG KÊ CHI TIẾT THEO TỪNG COIN:")
    for sym, group in closed_trades.groupby("symbol"):
        sym_wins = group[group["pnl_pct"] > 0]
        sym_wr = (len(sym_wins) / len(group)) * 100 if len(group) > 0 else 0.0
        sym_pnl = group["pnl_pct"].sum()
        print(f"   • {sym:10s}: {len(group):2d} lệnh | WinRate: {sym_wr:5.1f}% | PnL: {sym_pnl:+6.2f}%")

    # 2. Thống kê theo Điểm AI thẩm định
    if "ai_score" in closed_trades.columns:
        print(f"\n🧠 THỐNG KÊ THEO ĐIỂM TIN CẬY GEMINI AI:")
        for score, group in closed_trades.groupby("ai_score"):
            sc_wins = group[group["pnl_pct"] > 0]
            sc_wr = (len(sc_wins) / len(group)) * 100 if len(group) > 0 else 0.0
            sc_pnl = group["pnl_pct"].sum()
            print(f"   • Điểm AI {score:2}/10 : {len(group):2d} lệnh | WinRate: {sc_wr:5.1f}% | PnL: {sc_pnl:+6.2f}%")

    # 3. Xuất file CSV
    os.makedirs(REPORT_DIR, exist_ok=True)
    closed_trades.to_csv(REPORT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n💾 Đã xuất toàn bộ chi tiết {len(closed_trades)} lệnh ra file:")
    print(f"   👉 {REPORT_CSV}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    analyze_performance()
