"""
Fetch dữ liệu OHLCV của 5 đồng coin phổ biến nhất (từ config.SYMBOLS)
trong 24 tháng gần nhất, theo khung ngày (1d) và tuần (1w), từ Binance.

Kết quả được lưu dưới dạng metadata JSON để phục vụ phân tích mô hình nến:
    data/market/<coin>_<timeframe>.json   # dữ liệu nến từng coin
    data/market/metadata.json             # file index tổng hợp

Cách dùng:
    python tools/fetch_market_metadata.py
"""

import json
import os
import sys
import ccxt
import pandas as pd
from datetime import datetime, timedelta, timezone

# Thư mục gốc dự án (cha của thư mục tools/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402  (danh sách 5 coin phổ biến nhất)

OUTPUT_DIR = os.path.join(BASE_DIR, "data", "market")
TIMEFRAMES = ["4h"]          # Khung ngày và khung tuần
MONTHS = 24                        # 12 tháng gần nhất
DAYS = int(MONTHS * 30.44)         # ~365 ngày


def fetch_ohlcv(symbol: str, timeframe: str, since_ms: int, limit: int = 1000):
    """
    Lấy dữ liệu nến từ Binance (có phân trang).
    Trả về DataFrame hoặc None nếu lỗi.
    """
    exchange = ccxt.binance({'enableRateLimit': True})

    all_candles = []
    current_since = since_ms

    while True:
        try:
            candles = exchange.fetch_ohlcv(
                symbol, timeframe=timeframe,
                since=current_since, limit=limit
            )
        except Exception as e:
            print(f"❌ Lỗi khi fetch {symbol} ({timeframe}): {e}")
            return None

        if not candles:
            break

        all_candles.extend(candles)

        # Binance trả tối đa 1000 nến/lần. Nếu đã lấy hết thì dừng.
        if len(candles) < limit:
            break

        current_since = candles[-1][0] + 1

    if not all_candles:
        print(f"❌ Không có dữ liệu {symbol} ({timeframe}).")
        return None

    df = pd.DataFrame(
        all_candles,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['datetime'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df.sort_values('timestamp', inplace=True)
    df.drop_duplicates(subset='timestamp', inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def symbol_to_filename(symbol: str) -> str:
    """BTC/USDT -> btc_usdt"""
    return symbol.replace('/', '_').lower()


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    since_dt = datetime.now(timezone.utc) - timedelta(days=DAYS)
    since_ms = int(since_dt.timestamp() * 1000)

    print("=" * 60)
    print(f"📥 FETCH METADATA {MONTHS} THÁNG ({TIMEFRAMES}) CHO {len(config.SYMBOLS)} COIN")
    print(f"⏳ Từ: {since_dt.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    index = {
        "description": "OHLCV metadata của 5 coin phổ biến nhất (24 tháng) để phân tích mô hình nến",
        "generated_at": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        "months": MONTHS,
        "timeframes": TIMEFRAMES,
        "symbols": config.SYMBOLS,
        "files": [],
    }

    for symbol in config.SYMBOLS:
        for tf in TIMEFRAMES:
            print(f"\n🔄 Đang fetch {symbol} ({tf})...")

            df = fetch_ohlcv(symbol, tf, since_ms)
            if df is None or df.empty:
                print(f"   ❌ Bỏ qua {symbol} ({tf}).")
                continue

            records = df[['datetime', 'open', 'high', 'low', 'close', 'volume']].to_dict(orient='records')

            file_name = f"{symbol_to_filename(symbol)}_{tf}.json"
            file_path = os.path.join(OUTPUT_DIR, file_name)

            output = {
                "symbol": symbol,
                "timeframe": tf,
                "fetched_at": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
                "months": MONTHS,
                "total_candles": len(records),
                "from": records[0]['datetime'] if records else None,
                "to": records[-1]['datetime'] if records else None,
                "candles": records,
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            print(f"   ✅ {file_name}: {len(records)} nến ({output['from']} → {output['to']})")

            index["files"].append({
                "file": file_name,
                "symbol": symbol,
                "timeframe": tf,
                "total_candles": len(records),
                "from": output['from'],
                "to": output['to'],
            })

    # Lưu file index tổng hợp
    with open(os.path.join(OUTPUT_DIR, "metadata.json"), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"✅ HOÀN TẤT: {len(index['files'])} file metadata")
    print(f"   📁 {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
