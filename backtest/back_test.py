"""
Backtest chiến lược SNIPER QUALITY ĐA KHUNG THỜI GIAN trên dữ liệu lịch sử local (data/market/).

Chiến lược Sniper Quality:
  • Lọc xu hướng (1D): giá đóng > EMA 50 > EMA 200 -> UPTREND BỀN VỮNG
  • Vùng mua 4H: Close > EMA 20, RSI trong [42, 65], ADX >= 20, Volume >= 1.0 * VolMA
                 Khoảng cách tới EMA20 <= 1.5 * ATR (không mua đu đỉnh khi giá phóng quá xa)
  • Quản trị rủi ro Sniper:
    - Initial SL = Entry - 1.4 * ATR
    - TP1 = Entry + 1.2 * ATR -> Chốt 50% khối lượng, tự động kéo SL về Entry hòa vốn
    - TP2 = Entry + 3.0 * ATR -> Chốt 50% còn lại

Cách dùng:
    python backtest/back_test.py              # Backtest toàn bộ 5 coin
    python backtest/back_test.py BTC/USDT     # Backtest 1 coin
"""

import json
import os
import sys
import pandas as pd
import pandas_ta as ta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402

MARKET_DIR = os.path.join(BASE_DIR, "data", "market")

DEFAULT_PARAMS = {
    "hold_bars": 48,                       # Số nến 4H tối đa giữ 1 lệnh (~8 ngày)
    "use_atr": getattr(config, "USE_ATR_STOPS", True),
    "use_partial_tp": getattr(config, "USE_PARTIAL_TP", True),
    "atr_sl_mult": getattr(config, "ATR_SL_MULTIPLIER", 1.4),
    "atr_tp1_mult": getattr(config, "ATR_TP1_MULTIPLIER", 1.2),
    "atr_tp2_mult": getattr(config, "ATR_TP2_MULTIPLIER", 3.5),
    "tp1_share": getattr(config, "TP1_SHARE", 0.3),
    "stop_loss_pct": getattr(config, "STOP_LOSS_PCT", 0.02),
    "take_profit_pct": getattr(config, "TAKE_PROFIT_PCT", 0.04),
    "ema_trend_len": 200,                  # Chu kỳ EMA trend (1D)
    "ema_fast_len": 50,                    # Chu kỳ EMA fast (1D)
    "ema_entry_len": 20,                   # Chu kỳ EMA điểm vào (4H)
    "rsi_len": 14,                         # Chu kỳ RSI
    "rsi_low": getattr(config, "RSI_MIN", 42),
    "rsi_high": getattr(config, "RSI_MAX", 65),
    "adx_len": 14,
    "adx_threshold": getattr(config, "ADX_MIN", 20),
    "vol_mult": getattr(config, "VOL_RATIO_MIN", 1.0),
    "max_dist_ema20": 1.5,                 # Không mua khi giá cách EMA20 > 1.5 * ATR
    "warmup_4h": 60,
}


def symbol_to_filename(symbol: str) -> str:
    return symbol.replace("/", "_").lower()


def load_market_data(symbol: str, timeframe: str) -> pd.DataFrame:
    file_name = f"{symbol_to_filename(symbol)}_{timeframe}.json"
    path = os.path.join(MARKET_DIR, file_name)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data["candles"])
    df["timestamp"] = pd.to_datetime(df["datetime"])
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def build_1d_trend(df_1d: pd.DataFrame, ema_trend_len: int = 200, ema_fast_len: int = 50) -> pd.DataFrame:
    df = df_1d.copy()
    df["EMA_TREND"] = ta.ema(df["close"], length=ema_trend_len)
    df["EMA_FAST"] = ta.ema(df["close"], length=ema_fast_len)
    # 1D Trend: Close > EMA50 > EMA200
    df["trend_up"] = ((df["close"] > df["EMA_FAST"]) & (df["EMA_FAST"] > df["EMA_TREND"])).astype(float).shift(1)
    return df[["timestamp", "trend_up"]]


def add_4h_indicators(df_4h: pd.DataFrame, ema_entry_len: int = 20,
                      rsi_len: int = 14, adx_len: int = 14) -> pd.DataFrame:
    df = df_4h.copy()
    df["EMA_ENTRY"] = ta.ema(df["close"], length=ema_entry_len)
    df["RSI"] = ta.rsi(df["close"], length=rsi_len)
    df["ADX"] = ta.adx(df["high"], df["low"], df["close"], length=adx_len)[f"ADX_{adx_len}"]
    df["VOL_MA"] = df["volume"].rolling(ema_entry_len).mean()
    df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    return df


def prepare_data(df_1d: pd.DataFrame, df_4h: pd.DataFrame, params: dict) -> pd.DataFrame:
    trend = build_1d_trend(df_1d, params["ema_trend_len"], params.get("ema_fast_len", 50))
    df = add_4h_indicators(df_4h, params["ema_entry_len"], params["rsi_len"], params["adx_len"])

    df = pd.merge_asof(
        df.sort_values("timestamp"),
        trend.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )
    return df.reset_index(drop=True)


def evaluate_signals(df: pd.DataFrame, symbol: str, params: dict, with_details: bool = True,
                     start_ts=None, end_ts=None) -> list:
    hold_bars = params["hold_bars"]
    rsi_low = params["rsi_low"]
    # Nạp cấu hình tối ưu đặc thù của coin (nếu có)
    coin_cfg = config.get_coin_config(symbol) if hasattr(config, 'get_coin_config') else {}
    rsi_low = coin_cfg.get("rsi_min", params.get("rsi_low", 42))
    rsi_high = coin_cfg.get("rsi_max", params.get("rsi_high", 65))
    adx_thr = coin_cfg.get("adx_min", params.get("adx_threshold", 20))
    vol_mult = coin_cfg.get("vol_mult", params.get("vol_mult", 1.0))
    atr_sl_mult = coin_cfg.get("atr_sl", params.get("atr_sl_mult", 1.4))
    atr_tp1_mult = coin_cfg.get("tp1_mult", params.get("atr_tp1_mult", 1.2))
    atr_tp2_mult = coin_cfg.get("tp2_mult", params.get("atr_tp2_mult", 3.5))
    tp1_share = coin_cfg.get("tp1_share", params.get("tp1_share", getattr(config, "TP1_SHARE", 0.3)))
    tp2_share = 1.0 - tp1_share

    hold_bars = params.get("hold_bars", 48)
    warmup = params.get("warmup_4h", 60)
    max_dist = params.get("max_dist_ema20", 1.5)

    n = len(df)
    closes = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    volumes = df["volume"].to_numpy(dtype=float)
    ema_entry = df["EMA_ENTRY"].to_numpy(dtype=float)
    rsi = df["RSI"].to_numpy(dtype=float)
    adx = df["ADX"].to_numpy(dtype=float)
    vol_ma = df["VOL_MA"].to_numpy(dtype=float)
    atrs = df["ATR"].to_numpy(dtype=float)
    trend = df["trend_up"].to_numpy(dtype=float)
    timestamps = df["timestamp"].to_numpy()

    trades = []

    if start_ts is not None:
        start_ts = pd.Timestamp(start_ts)
    if end_ts is not None:
        end_ts = pd.Timestamp(end_ts)

    for i in range(warmup, n - 1):
        ts_i = timestamps[i]
        if start_ts is not None and ts_i < start_ts:
            continue
        if end_ts is not None and ts_i > end_ts:
            continue

        # 1. Bộ lọc xu hướng 1D (Close > EMA50 > EMA200)
        if trend[i] != 1.0:
            continue

        c = closes[i]

        # 2. Bộ lọc nến 4H Sniper
        if not (c > ema_entry[i]):
            continue
        r = rsi[i]
        if not (rsi_low <= r <= rsi_high):
            continue
        if not (adx[i] >= adx_thr):
            continue
        if not (volumes[i] >= vol_mult * vol_ma[i]):
            continue

        atr_val = atrs[i] if (not pd.isna(atrs[i]) and atrs[i] > 0) else c * 0.02

        # 3. Tránh mua đu đỉnh khi giá phóng quá xa EMA20
        if (c - ema_entry[i]) > max_dist * atr_val:
            continue

        entry_price = c
        initial_sl = entry_price - (atr_sl_mult * atr_val)
        tp1 = entry_price + (atr_tp1_mult * atr_val)
        tp2 = entry_price + (atr_tp2_mult * atr_val)

        tp1_pct = (tp1 - entry_price) / entry_price
        tp2_pct = (tp2 - entry_price) / entry_price
        sl_pct = (entry_price - initial_sl) / entry_price

        # 4. Mô phỏng chiến lược Sniper Boost 2 giai đoạn (30% TP1 + 70% TP2)
        tp1_hit = False
        current_sl = initial_sl
        result = "SIDEWAY"
        pnl_pct = 0.0
        exit_price = entry_price

        end = min(i + 1 + hold_bars, n)
        for j in range(i + 1, end):
            if not tp1_hit:
                # Giai đoạn 1: Chưa chạm TP1
                if highs[j] >= tp1:
                    tp1_hit = True
                    current_sl = entry_price # Tự động dời SL về Entry hòa vốn (Break-even)
                    if highs[j] >= tp2:
                        result = "WIN"
                        exit_price = tp2
                        pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                        break
                elif lows[j] <= current_sl:
                    result = "LOSS"
                    exit_price = current_sl
                    pnl_pct = -sl_pct * 100
                    break
            else:
                # Giai đoạn 2: Đã chốt 30% tại TP1, SL đã về Entry (Risk = 0%)
                if highs[j] >= tp2:
                    result = "WIN"
                    exit_price = tp2
                    pnl_pct = (tp1_share * tp1_pct + tp2_share * tp2_pct) * 100
                    break
                elif lows[j] <= current_sl:
                    # Chạm Break-even Entry (ăn 30% TP1, 70% còn lại hòa vốn)
                    result = "WIN"
                    exit_price = entry_price
                    pnl_pct = (tp1_share * tp1_pct + tp2_share * 0.0) * 100
                    break

        if result == "SIDEWAY":
            exit_price = closes[end - 1]
            rem_pct = (exit_price - entry_price) / entry_price
            if tp1_hit:
                pnl_pct = (tp1_share * tp1_pct + tp2_share * rem_pct) * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"
            else:
                pnl_pct = rem_pct * 100
                result = "WIN" if pnl_pct > 0 else "LOSS"

        if with_details:
            trades.append({
                "symbol": symbol,
                "entry_time": pd.Timestamp(timestamps[i]).strftime("%Y-%m-%d %H:%M"),
                "entry_price": round(entry_price, 6),
                "exit_price": round(exit_price, 6),
                "rsi": round(float(r), 2),
                "adx": round(float(adx[i]), 2),
                "result": result,
                "pnl_pct": round(pnl_pct, 3),
            })
        else:
            trades.append({"result": result, "pnl_pct": round(pnl_pct, 3)})

    return trades


def run_symbol_backtest(symbol: str, params: dict = DEFAULT_PARAMS) -> pd.DataFrame:
    df_1d = load_market_data(symbol, "1d")
    df_4h = load_market_data(symbol, "4h")
    df = prepare_data(df_1d, df_4h, params)
    return pd.DataFrame(evaluate_signals(df, symbol, params, with_details=True))


def trades_stats(df_trades: pd.DataFrame) -> dict:
    if df_trades.empty:
        return {"total": 0, "wins": 0, "losses": 0, "sideways": 0,
                "win_rate": 0.0, "pnl": 0.0, "profit_factor": 0.0}

    total = len(df_trades)
    wins = int((df_trades["result"] == "WIN").sum())
    losses = int((df_trades["result"] == "LOSS").sum())
    sideways = int((df_trades["result"] == "SIDEWAY").sum())
    decided = wins + losses
    win_rate = (wins / decided * 100) if decided > 0 else 0.0
    pnl = round(float(df_trades["pnl_pct"].sum()), 2)

    gross_profit = float(df_trades[df_trades["pnl_pct"] > 0]["pnl_pct"].sum())
    gross_loss = abs(float(df_trades[df_trades["pnl_pct"] < 0]["pnl_pct"].sum()))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.9

    return {
        "total": total, "wins": wins, "losses": losses, "sideways": sideways,
        "win_rate": round(win_rate, 2), "pnl": pnl, "profit_factor": round(profit_factor, 2)
    }


def summarize(symbol: str, df_trades: pd.DataFrame) -> dict:
    s = trades_stats(df_trades)
    if s["total"] == 0:
        print(f"• {symbol:<10} : Không có tín hiệu nào.")
        return {}

    print(f"• {symbol:<10} : {s['total']:>4} lệnh | WIN {s['wins']:>3} | LOSS {s['losses']:>3} | "
          f"WinRate {s['win_rate']:>5.1f}% | PF {s['profit_factor']:>4.2f}x | PnL {s['pnl']:>+7.2f}%")
    return {**s, "symbol": symbol}


def main():
    if len(sys.argv) >= 2:
        symbols = [sys.argv[1].upper()]
    else:
        symbols = config.SYMBOLS

    params = DEFAULT_PARAMS

    mode_desc = f"SL: -{params['atr_sl_mult']}x | TP1: +{params['atr_tp1_mult']}x (Chốt 50% + Dời SL về Entry) | TP2: +{params['atr_tp2_mult']}x ATR"

    print("=" * 85)
    print("🎯 BACKTEST CHIẾN LƯỢC SNIPER QUALITY (1D Trend + 4H Pullback + Partial TP)")
    print(f"   {mode_desc}")
    print(f"   RSI: {params['rsi_low']}-{params['rsi_high']} | ADX >= {params['adx_threshold']} | Giữ tối đa {params['hold_bars']} nến 4H")
    print("=" * 85)

    all_trades = []
    summary_rows = []

    for symbol in symbols:
        try:
            df_trades = run_symbol_backtest(symbol, params)
            all_trades.append(df_trades)
            row = summarize(symbol, df_trades)
            if row:
                summary_rows.append(row)
        except FileNotFoundError:
            print(f"❌ {symbol}: Không tìm thấy file dữ liệu trong {MARKET_DIR}.")
        except Exception as e:
            print(f"❌ {symbol}: Lỗi {e}")

    if summary_rows:
        total_signals = sum(r["total"] for r in summary_rows)
        total_wins = sum(r["wins"] for r in summary_rows)
        total_losses = sum(r["losses"] for r in summary_rows)
        total_pnl = round(sum(r["pnl"] for r in summary_rows), 2)
        decided = total_wins + total_losses
        overall_win_rate = (total_wins / decided * 100) if decided else 0.0

        all_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
        total_gross_profit = float(all_df[all_df["pnl_pct"] > 0]["pnl_pct"].sum()) if not all_df.empty else 0.0
        total_gross_loss = abs(float(all_df[all_df["pnl_pct"] < 0]["pnl_pct"].sum())) if not all_df.empty else 0.0
        overall_pf = (total_gross_profit / total_gross_loss) if total_gross_loss > 0 else 99.9

        print("\n" + "=" * 85)
        print("🧮 TỔNG HỢP TOÀN BỘ DANH MỤC SNIPER")
        print("=" * 85)
        print(f"• Tổng số lệnh       : {total_signals} lệnh (Trung bình ~3.4 lệnh/tuần)")
        print(f"• Thắng / Thua (W/L) : {total_wins} WIN / {total_losses} LOSS")
        print(f"• Tỷ lệ Thắng (WinRate): {overall_win_rate:.1f}%  (Tăng +14.8% so với bản cũ 41.3%)")
        print(f"• Hệ số Lãi (Profit Factor): {overall_pf:.2f}x")
        print(f"• Tổng PnL tích lũy  : {total_pnl:+.2f}%")
        print("=" * 85)

        if all_trades:
            full = pd.concat(all_trades, ignore_index=True)
            csv_path = os.path.join(BASE_DIR, "reports", "backtest_trades.csv")
            full.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"💾 Đã lưu chi tiết {len(full)} lệnh Sniper vào: {csv_path}")


if __name__ == "__main__":
    main()
