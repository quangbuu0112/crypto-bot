"""
Backtest chiến lược ĐA KHUNG THỜI GIAN trên dữ liệu lịch sử local (data/market/).

Chiến lược (giống signal_engine.py, thích nghi với khung 1D + 4H):
  • Lọc xu hướng (1D): giá đóng > EMA trend  ->  UPTREND
  • Vào lệnh (4H)    : close > EMA entry, RSI trong (rsi_low, rsi_high),
                       ADX > adx_threshold, Volume > vol_mult * VolMA
  • Quản trị vốn     : SL -stop_loss_pct, TP +take_profit_pct

Dữ liệu đọc từ:
  data/market/<coin>_1d.json   (24 tháng, ~730 nến)
  data/market/<coin>_4h.json   (24 tháng, ~4320 nến)

Cách dùng:
    python backtest/back_test.py              # Backtest toàn bộ 5 coin (bộ tham số mặc định)
    python backtest/back_test.py BTC/USDT     # Backtest 1 coin
"""

import json
import os
import sys

import pandas as pd
import pandas_ta as ta

# Thư mục gốc dự án (cha của thư mục backtest/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402

MARKET_DIR = os.path.join(BASE_DIR, "data", "market")

# Bộ tham số mặc định (đã tối ưu bằng grid search — xem optimize_params.py).
# Có thể ghi đè bằng cách truyền dict params.
DEFAULT_PARAMS = {
    "hold_bars": 96,                       # Số nến 4H tối đa giữ 1 lệnh (~16 ngày)
    "use_atr": getattr(config, "USE_ATR_STOPS", True),
    "atr_sl_mult": getattr(config, "ATR_SL_MULTIPLIER", 1.5),
    "atr_tp_mult": getattr(config, "ATR_TP_MULTIPLIER", 3.0),
    "stop_loss_pct": getattr(config, "STOP_LOSS_PCT", 0.02),
    "take_profit_pct": getattr(config, "TAKE_PROFIT_PCT", 0.04),
    "ema_trend_len": 200,                  # Chu kỳ EMA lọc xu hướng (khung 1D)
    "ema_entry_len": 30,                   # Chu kỳ EMA điểm vào (khung 4H)
    "rsi_len": 21,                         # Chu kỳ RSI
    "rsi_low": 50,                         # Ngưỡng dưới RSI
    "rsi_high": 68,                        # Ngưỡng trên RSI
    "adx_len": 14,                         # Chu kỳ ADX
    "adx_threshold": 20,                   # Ngưỡng ADX
    "vol_mult": 1.0,                       # Volume > vol_mult * VolMA
    "warmup_4h": 60,                       # Bỏ qua n nến 4H đầu
}


def symbol_to_filename(symbol: str) -> str:
    """BTC/USDT -> btc_usdt"""
    return symbol.replace("/", "_").lower()


def load_market_data(symbol: str, timeframe: str) -> pd.DataFrame:
    """Đọc file JSON dữ liệu nến từ data/market/ và trả về DataFrame."""
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
    """Tính xu hướng 1D theo Trend Alignment: close > EMA50 > EMA200, dịch 1 ngày để tránh look-ahead."""
    df = df_1d.copy()
    df["EMA_TREND"] = ta.ema(df["close"], length=ema_trend_len)
    df["EMA_FAST"] = ta.ema(df["close"], length=ema_fast_len)

    # shift(1): nến 4H chỉ dùng xu hướng của ngày ĐÃ ĐÓNG trước đó
    df["trend_up"] = ((df["close"] > df["EMA_FAST"]) & (df["EMA_FAST"] > df["EMA_TREND"])).astype(float).shift(1)
    return df[["timestamp", "trend_up"]]


def add_4h_indicators(df_4h: pd.DataFrame, ema_entry_len: int = 20,
                      rsi_len: int = 14, adx_len: int = 14) -> pd.DataFrame:
    """Thêm các chỉ báo vào khung 4H."""
    df = df_4h.copy()
    df["EMA_ENTRY"] = ta.ema(df["close"], length=ema_entry_len)
    df["RSI"] = ta.rsi(df["close"], length=rsi_len)
    df["ADX"] = ta.adx(df["high"], df["low"], df["close"], length=adx_len)[f"ADX_{adx_len}"]
    df["VOL_MA"] = df["volume"].rolling(ema_entry_len).mean()
    df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    return df


def prepare_data(df_1d: pd.DataFrame, df_4h: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Ghép xu hướng 1D vào nến 4H, trả về DataFrame đầy đủ chỉ báo."""
    trend = build_1d_trend(df_1d, params["ema_trend_len"])
    df = add_4h_indicators(df_4h, params["ema_entry_len"], params["rsi_len"], params["adx_len"])

    # Chỉ lấy nến 1D đã đóng trong quá khứ (direction='backward')
    df = pd.merge_asof(
        df.sort_values("timestamp"),
        trend.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )
    return df.reset_index(drop=True)


def evaluate_signals(df: pd.DataFrame, symbol: str, params: dict, with_details: bool = True,
                     start_ts=None, end_ts=None) -> list:
    """Duyệt nến 4H, sinh tín hiệu và đối chứng TP/SL trong hold_bars nến tới.

    start_ts/end_ts (pd.Timestamp, tùy chọn): chỉ sinh tín hiệu trong khoảng
    thời gian này (dùng cho kiểm chứng out-of-sample).
    """
    hold_bars = params["hold_bars"]
    sl_pct = params["stop_loss_pct"]
    tp_pct = params["take_profit_pct"]
    rsi_low = params["rsi_low"]
    rsi_high = params["rsi_high"]
    adx_thr = params["adx_threshold"]
    vol_mult = params["vol_mult"]
    warmup = params["warmup_4h"]

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
        # 0. Lọc theo khoảng thời gian (dùng cho kiểm chứng out-of-sample)
        ts_i = timestamps[i]
        if start_ts is not None and ts_i < start_ts:
            continue
        if end_ts is not None and ts_i > end_ts:
            continue

        # 1. Bộ lọc xu hướng 1D
        if trend[i] != 1.0:
            continue

        c = closes[i]

        # 2. Bộ lọc vào lệnh 4H
        if not (c > ema_entry[i]):
            continue
        r = rsi[i]
        if not (rsi_low < r < rsi_high):
            continue
        if not (adx[i] > adx_thr):
            continue
        if not (volumes[i] > vol_mult * vol_ma[i]):
            continue

        entry_price = c
        if params.get("use_atr", False) and not pd.isna(atrs[i]):
            atr_val = atrs[i]
            stop_loss = entry_price - params.get("atr_sl_mult", 1.5) * atr_val
            take_profit = entry_price + params.get("atr_tp_mult", 3.0) * atr_val
            trade_sl_pct = (entry_price - stop_loss) / entry_price
            trade_tp_pct = (take_profit - entry_price) / entry_price
        else:
            stop_loss = entry_price * (1 - sl_pct)
            take_profit = entry_price * (1 + tp_pct)
            trade_sl_pct = sl_pct
            trade_tp_pct = tp_pct

        # 3. Đối chứng trong hold_bars nến 4H tiếp theo
        result = "SIDEWAY"
        exit_price = entry_price

        end = min(i + 1 + hold_bars, n)
        for j in range(i + 1, end):
            if highs[j] >= take_profit and lows[j] <= stop_loss:
                result = "LOSS"
                exit_price = stop_loss
                break
            elif highs[j] >= take_profit:
                result = "WIN"
                exit_price = take_profit
                break
            elif lows[j] <= stop_loss:
                result = "LOSS"
                exit_price = stop_loss
                break

        if result == "WIN":
            pnl_pct = trade_tp_pct * 100
        elif result == "LOSS":
            pnl_pct = -trade_sl_pct * 100
        else:
            pnl_pct = 0.0

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
    """Chạy backtest 1 coin, trả về DataFrame các lệnh đã sinh ra."""
    df_1d = load_market_data(symbol, "1d")
    df_4h = load_market_data(symbol, "4h")
    df = prepare_data(df_1d, df_4h, params)
    return pd.DataFrame(evaluate_signals(df, symbol, params, with_details=True))


def trades_stats(df_trades: pd.DataFrame) -> dict:
    """Tính thống kê từ DataFrame lệnh."""
    if df_trades.empty:
        return {"total": 0, "wins": 0, "losses": 0, "sideways": 0,
                "win_rate": 0.0, "pnl": 0.0}

    total = len(df_trades)
    wins = int((df_trades["result"] == "WIN").sum())
    losses = int((df_trades["result"] == "LOSS").sum())
    sideways = int((df_trades["result"] == "SIDEWAY").sum())
    decided = wins + losses
    win_rate = (wins / decided * 100) if decided > 0 else 0.0
    pnl = round(float(df_trades["pnl_pct"].sum()), 2)

    return {"total": total, "wins": wins, "losses": losses, "sideways": sideways,
            "win_rate": round(win_rate, 2), "pnl": pnl}


def summarize(symbol: str, df_trades: pd.DataFrame) -> dict:
    """In kết quả 1 coin và trả về dict thống kê."""
    s = trades_stats(df_trades)
    if s["total"] == 0:
        print(f"• {symbol:<10} : Không có tín hiệu nào.")
        return {}

    print(f"• {symbol:<10} : {s['total']:>4} lệnh | WIN {s['wins']} | LOSS {s['losses']} | "
          f"SIDEWAY {s['sideways']} | WinRate {s['win_rate']:5.1f}% | PnL {s['pnl']:+7.2f}%")
    return {**s, "symbol": symbol}


def main():
    if len(sys.argv) >= 2:
        symbols = [sys.argv[1].upper()]
    else:
        symbols = config.SYMBOLS

    params = DEFAULT_PARAMS

    if params.get("use_atr"):
        mode_desc = f"SL: -{params['atr_sl_mult']}x ATR | TP: +{params['atr_tp_mult']}x ATR (R:R = 1:{params['atr_tp_mult']/params['atr_sl_mult']:.1f})"
    else:
        mode_desc = f"SL: -{params['stop_loss_pct'] * 100:.1f}% | TP: +{params['take_profit_pct'] * 100:.1f}%"

    print("=" * 70)
    print("📊 BACKTEST ĐA KHUNG THỜI GIAN (1D trend + 4H entry) TRÊN DỮ LIỆU 24 THÁNG")
    print(f"   {mode_desc} | Giữ tối đa {params['hold_bars']} nến 4H")
    print("=" * 70)

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

        print("\n" + "=" * 70)
        print("🧮 TỔNG HỢP CHUNG")
        print("=" * 70)
        print(f"• Tổng tín hiệu : {total_signals} lệnh")
        print(f"• Win / Loss    : {total_wins} / {total_losses}")
        print(f"• Win Rate      : {overall_win_rate:.1f}%")
        print(f"• Tổng PnL      : {total_pnl:+.2f}%")
        print("=" * 70)

        # Lưu chi tiết các lệnh ra CSV để phân tích thêm
        if all_trades:
            full = pd.concat(all_trades, ignore_index=True)
            csv_path = os.path.join(BASE_DIR, "reports", "backtest_trades.csv")
            full.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"💾 Đã lưu chi tiết {len(full)} lệnh vào: {csv_path}")


if __name__ == "__main__":
    main()
