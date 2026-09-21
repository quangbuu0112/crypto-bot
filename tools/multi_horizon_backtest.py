"""
Script chạy Backtest Đa Khung Thời Gian (24 tháng, 12 tháng, 9 tháng, 3 tháng)
cho Chiến lược Sniper Quality & Phân Tích Tối Ưu Từng Đồng Coin.
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
from backtest.back_test import run_symbol_backtest, DEFAULT_PARAMS

def simulate_portfolio(df_all_trades, initial_capital=500.0, fixed_trade_size=50.0):
    """Mô phỏng tăng trưởng tài khoản với số tiền đi lệnh cố định"""
    if df_all_trades.empty:
        return {
            "final_balance": initial_capital,
            "net_profit": 0.0,
            "roi_pct": 0.0,
            "max_drawdown_pct": 0.0
        }

    # Sắp xếp lệnh theo thời gian vào lệnh
    df_sorted = df_all_trades.sort_values("entry_time").reset_index(drop=True)
    balance = initial_capital
    balance_history = [balance]

    for _, row in df_sorted.iterrows():
        pnl_pct = row["pnl_pct"] / 100.0
        profit_usd = fixed_trade_size * pnl_pct
        balance += profit_usd
        balance_history.append(balance)

    # Tính Max Drawdown
    peaks = np.maximum.accumulate(balance_history)
    drawdowns = (peaks - balance_history) / peaks * 100.0
    max_dd = np.max(drawdowns)

    net_profit = balance - initial_capital
    roi_pct = (net_profit / initial_capital) * 100.0

    return {
        "final_balance": round(balance, 2),
        "net_profit": round(net_profit, 2),
        "roi_pct": round(roi_pct, 2),
        "max_drawdown_pct": round(max_dd, 2)
    }

def run_multi_horizon():
    # 1. Chạy backtest toàn bộ dữ liệu 24 tháng cho 5 coin
    symbols = getattr(config, "SYMBOLS", ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT'])
    all_trade_dfs = []

    for sym in symbols:
        df = run_symbol_backtest(sym, DEFAULT_PARAMS)
        if not df.empty:
            df["symbol"] = sym
            all_trade_dfs.append(df)

    if not all_trade_dfs:
        print("❌ Không có dữ liệu giao dịch.")
        return

    full_trades = pd.concat(all_trade_dfs, ignore_index=True)
    full_trades["entry_time"] = pd.to_datetime(full_trades["entry_time"])
    full_trades.sort_values("entry_time", inplace=True)
    full_trades.reset_index(drop=True, inplace=True)

    max_date = full_trades["entry_time"].max()
    print(f"Data end date: {max_date.strftime('%Y-%m-%d %H:%M')}")

    horizons = {
        "24 tháng (Toàn bộ 2 năm)": max_date - timedelta(days=730),
        "12 tháng (1 năm gần nhất)": max_date - timedelta(days=365),
        "9 tháng gần nhất": max_date - timedelta(days=270),
        "3 tháng gần nhất": max_date - timedelta(days=90),
    }

    results = {}

    for name, start_dt in horizons.items():
        sub_df = full_trades[full_trades["entry_time"] >= start_dt].copy().reset_index(drop=True)
        total_trades = len(sub_df)
        wins = int((sub_df["result"] == "WIN").sum())
        losses = int((sub_df["result"] == "LOSS").sum())
        decided = wins + losses
        win_rate = (wins / decided * 100) if decided > 0 else 0.0

        total_pnl = float(sub_df["pnl_pct"].sum())
        gross_profit = float(sub_df[sub_df["pnl_pct"] > 0]["pnl_pct"].sum())
        gross_loss = abs(float(sub_df[sub_df["pnl_pct"] < 0]["pnl_pct"].sum()))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.9

        # Mô phỏng vốn $500 với fixed size $50 và $100
        sim_50 = simulate_portfolio(sub_df, initial_capital=500.0, fixed_trade_size=50.0)
        sim_100 = simulate_portfolio(sub_df, initial_capital=500.0, fixed_trade_size=100.0)

        # Thống kê từng coin
        coin_breakdown = {}
        for sym in symbols:
            c_df = sub_df[sub_df["symbol"] == sym]
            c_total = len(c_df)
            c_wins = int((c_df["result"] == "WIN").sum())
            c_losses = int((c_df["result"] == "LOSS").sum())
            c_decided = c_wins + c_losses
            c_wr = (c_wins / c_decided * 100) if c_decided > 0 else 0.0
            c_pnl = float(c_df["pnl_pct"].sum())
            c_gp = float(c_df[c_df["pnl_pct"] > 0]["pnl_pct"].sum())
            c_gl = abs(float(c_df[c_df["pnl_pct"] < 0]["pnl_pct"].sum()))
            c_pf = (c_gp / c_gl) if c_gl > 0 else 99.9

            coin_breakdown[sym] = {
                "trades": c_total,
                "wins": c_wins,
                "losses": c_losses,
                "win_rate": round(c_wr, 1),
                "profit_factor": round(c_pf, 2),
                "pnl": round(c_pnl, 2),
            }

        results[name] = {
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": max_date.strftime("%Y-%m-%d"),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "total_pnl": round(total_pnl, 2),
            "sim_50": sim_50,
            "sim_100": sim_100,
            "coins": coin_breakdown
        }

    return results

if __name__ == "__main__":
    res = run_multi_horizon()
    import json
    os.makedirs(os.path.join(BASE_DIR, "reports"), exist_ok=True)
    out_path = os.path.join(BASE_DIR, "reports", "multi_horizon_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"Results saved to: {out_path}")
