"""
Script fetch dữ liệu BTC/USDT 90 ngày gần nhất từ Binance và lưu vào file JSON.
Sử dụng khung 1H để có độ chi tiết tốt, có thể đổi thành '1d' nếu chỉ cần daily.
"""

import json
import os
import ccxt
import pandas as pd
from datetime import datetime, timedelta, timezone

# ========== CONFIG ==========
# Thư mục gốc dự án (cha của thư mục tools/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"          # Khung nến: 1h, 4h, 1d, 15m, ...
DAYS = 90                  # Số ngày dữ liệu cần fetch
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "btc_90days.json")
# ============================

def fetch_ohlcv(symbol: str, timeframe: str, since_ms: int, limit: int = 1000):
    """
    Lấy dữ liệu nến từ Binance. CCXT tự phân trang nếu limit > max của sàn (1000).
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
            print(f"❌ Lỗi khi fetch OHLCV: {e}")
            return None

        if not candles:
            break

        all_candles.extend(candles)

        # Binance trả tối đa 1000 nến/lần. Nếu đã lấy hết thì dừng.
        if len(candles) < limit:
            break

        # Cập nhật since = timestamp nến cuối + 1ms để lấy trang tiếp theo
        current_since = candles[-1][0] + 1

    if not all_candles:
        print("❌ Không có dữ liệu nào được trả về.")
        return None

    # Chuyển sang DataFrame
    df = pd.DataFrame(
        all_candles,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['datetime'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df.sort_values('timestamp', inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def main():
    print("=" * 55)
    print(f"📥 FETCH {DAYS} NGÀY DỮ LIỆU {SYMBOL} ({TIMEFRAME}) TỪ BINANCE")
    print("=" * 55)

    since_dt = datetime.now(timezone.utc) - timedelta(days=DAYS)
    since_ms = int(since_dt.timestamp() * 1000)
    print(f"⏳ Từ: {since_dt.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"🎯 Đến: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    df = fetch_ohlcv(SYMBOL, TIMEFRAME, since_ms)

    if df is None or df.empty:
        print("❌ Không lấy được dữ liệu. Thoát.")
        return

    # Chuyển DataFrame thành list of dict để lưu JSON
    records = df[['datetime', 'open', 'high', 'low', 'close', 'volume']].to_dict(orient='records')

    output = {
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "fetched_at": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        "days": DAYS,
        "total_candles": len(records),
        "from": records[0]['datetime'] if records else None,
        "to": records[-1]['datetime'] if records else None,
        "candles": records,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ ĐÃ LƯU THÀNH CÔNG: {OUTPUT_FILE}")
    print(f"   • Tổng số nến: {len(records)}")
    print(f"   • Từ: {output['from']}")
    print(f"   • Đến: {output['to']}")
    print(f"   • Dung lượng file: {len(json.dumps(output, ensure_ascii=False)) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
