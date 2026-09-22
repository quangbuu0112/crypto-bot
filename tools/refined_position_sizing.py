"""
Phân tích so sánh 3 phương pháp Position Sizing:
1. FIXED POSITION SIZE ($50 / $100)
2. FIXED RISK USD ($10 Risk / SL_ATR)
3. DYNAMIC % RISK (1.0%, 1.5%, 2.0% Balance / SL_ATR)
"""

import os
import sys
import json
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
from tools.compare_pre_post_dual import add_indicators, simulate_strategy
from backtest.back_test import load_market_data, build_1d_trend

def run_analysis():
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

    all_trades = []
    for sym in symbols:
        all_trades.extend(simulate_strategy(data_by_sym[sym], sym, is_dual=True))

    df_trades = pd.DataFrame(all_trades).sort_values("entry_time").reset_index(drop=True)
    initial_cap = 500.0

    methods = {
        "1. Cố định $50 / lệnh": {"type": "fixed", "amt": 50.0},
        "2. Cố định $100 / lệnh": {"type": "fixed", "amt": 100.0},
        "3. Fixed Risk $10 / lệnh (ATR Sizing)": {"type": "fixed_risk_usd", "risk_usd": 10.0},
        "4. Risk 1.0% Vốn (Lãi kép ATR)": {"type": "dynamic_risk_pct", "risk_pct": 0.010},
        "5. Risk 1.5% Vốn (Lãi kép ATR)": {"type": "dynamic_risk_pct", "risk_pct": 0.015},
        "6. Risk 2.0% Vốn (Lãi kép ATR)": {"type": "dynamic_risk_pct", "risk_pct": 0.020},
    }

    out = {}
    for name, cfg in methods.items():
        bal = initial_cap
        curve = [bal]
        pos_sizes = []

        for _, r in df_trades.iterrows():
            sl_pct = 0.022 if r["type"] == "SIDEWAY_RANGE" else 0.030

            if cfg["type"] == "fixed":
                pos = cfg["amt"]
            elif cfg["type"] == "fixed_risk_usd":
                pos = cfg["risk_usd"] / sl_pct
                # Giới hạn an toàn tối đa 30% vốn ban đầu
                pos = min(pos, 150.0)
            elif cfg["type"] == "dynamic_risk_pct":
                risk_usd = bal * cfg["risk_pct"]
                pos = risk_usd / sl_pct
                # Giới hạn an toàn tối đa 25% tổng tài khoản hiện tại
                pos = min(pos, bal * 0.25)

            pos_sizes.append(pos)
            profit = pos * (r["pnl_pct"] / 100.0)
            bal += profit
            curve.append(bal)

        peaks = np.maximum.accumulate(curve)
        dd = (peaks - curve) / peaks * 100.0
        max_dd = np.max(dd)

        out[name] = {
            "vốn_ban_đầu": initial_cap,
            "số_dư_cuối": round(bal, 2),
            "lợi_nhuận_usd": round(bal - initial_cap, 2),
            "roi_pct": round((bal - initial_cap) / initial_cap * 100.0, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "calmar_ratio": round(((bal - initial_cap) / initial_cap * 100.0) / (max_dd + 1e-6), 2),
            "khối_lượng_lệnh_trung_bình_usd": round(float(np.mean(pos_sizes)), 2)
        }

    out_file = os.path.join(BASE_DIR, "reports", "refined_position_sizing.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Refined sizing analysis done!")
    return out

if __name__ == "__main__":
    res = run_analysis()
    print(json.dumps(res, indent=2))
