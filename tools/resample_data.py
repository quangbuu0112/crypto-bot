"""
Đọc file JSON chứa dữ liệu nến 1H và resample sang các khung lớn hơn (4H, 1D, 1W).
Không cần fetch thêm từ Binance.

Cách dùng:
    python tools/resample_data.py                 # Mặc định resample BTC 1H -> 4H, 1D, 1W
    python tools/resample_data.py ETH/USDT         # Chỉ định file json khác (nếu có)
"""

import json
import os
import sys
import pandas as pd

# Thư mục gốc dự án (cha của thư mục tools/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def load_from_json(filepath: str) -> pd.DataFrame | None:
    """Đọc file JSON và trả về DataFrame với timestamp là index."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    candles = data.get('candles', [])
    if not candles:
        print(f"❌ File {filepath} không chứa dữ liệu nến.")
        return None

    df = pd.DataFrame(candles)
    df['timestamp'] = pd.to_datetime(df['datetime'])
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)

    print(f"📄 Đã đọc {len(df)} nến từ {data.get('from')} đến {data.get('to')} "
          f"({data.get('timeframe', '?')})")
    return df


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Gộp nến từ khung nhỏ lên khung lớn hơn.
    'rule' theo pandas offset: '4h', '1d', '1w', ...
    """
    resampled = df.resample(rule).agg({
        'open':   'first',
        'high':   'max',
        'low':    'min',
        'close':  'last',
        'volume': 'sum',
    })
    resampled.dropna(inplace=True)
    return resampled


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Chuyển DataFrame thành list of dict (định dạng giống file gốc)."""
    records = []
    for ts, row in df.iterrows():
        records.append({
            'datetime': ts.strftime('%Y-%m-%d %H:%M:%S'),
            'open':     round(float(row['open']), 2),
            'high':     round(float(row['high']), 2),
            'low':      round(float(row['low']), 2),
            'close':    round(float(row['close']), 2),
            'volume':   round(float(row['volume']), 2),
        })
    return records


def main():
    # Xác định file nguồn
    if len(sys.argv) > 1:
        symbol = sys.argv[1].upper()
        filepath = os.path.join(DATA_DIR, f"{symbol.replace('/', '_').lower()}_90days.json")
    else:
        filepath = os.path.join(DATA_DIR, "btc_90days.json")

    print("=" * 55)
    print(f"🔄 RESAMPLE DỮ LIỆU TỪ FILE: {filepath}")
    print("=" * 55)

    df = load_from_json(filepath)
    if df is None:
        return

    # Resample sang các khung
    timeframes = {
        '4h': '4h',
        '1d': '1D',
        '1w': '1W',
    }

    base_name = os.path.splitext(os.path.basename(filepath))[0]  # VD: "btc_90days"
    coin = base_name.replace('_90days', '').split('_')[0].upper() + "/USDT"

    for label, rule in timeframes.items():
        df_tf = resample_ohlcv(df, rule)
        records = df_to_records(df_tf)

        out_file = os.path.join(DATA_DIR, f"{base_name}_{label}.json")
        output = {
            "symbol": coin,
            "timeframe": label,
            "source": filepath,
            "total_candles": len(records),
            "from": records[0]['datetime'],
            "to": records[-1]['datetime'],
            "candles": records,
        }

        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"✅ [{label.upper()}] {len(records):>5} nến → {out_file}")

    print("\n🎉 Hoàn tất! Bạn có thể dùng các file JSON mới để phân tích.")


if __name__ == "__main__":
    main()
