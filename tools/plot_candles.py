"""
Vẽ biểu đồ nến (Candlestick Chart) từ file JSON dữ liệu OHLCV.
Xuất ra file HTML tương tác (có thể zoom, hover xem giá).

Cách dùng:
    python tools/plot_candles.py                          # Mặc định: data/btc_90days_1d.json
    python tools/plot_candles.py btc_90days_4h.json       # Chỉ định file (trong data/)
    python tools/plot_candles.py btc_90days_4h.json 50    # Chỉ hiển thị 50 nến cuối
"""

import json
import os
import sys
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# Thư mục gốc dự án (cha của thư mục tools/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHART_DIR = os.path.join(BASE_DIR, "charts")


def load_json(filepath: str) -> dict:
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Tính thêm EMA 20, EMA 50 và Volume MA 20."""
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    return df


def plot_candlestick(filepath: str, tail: int | None = None):
    print(f"📄 Đang đọc: {filepath} ...")
    data = load_json(filepath)

    symbol = data.get('symbol', '?')
    timeframe = data.get('timeframe', '?')
    candles = data.get('candles', [])

    if not candles:
        print("❌ File không có dữ liệu nến!")
        return

    df = pd.DataFrame(candles)
    df['timestamp'] = pd.to_datetime(df['datetime'])

    # Cắt đuôi nếu cần
    if tail and tail < len(df):
        df = df.tail(tail)

    df = add_indicators(df)
    print(f"   • {len(df)} nến | {symbol} | Khung {timeframe}")

    # ======================= VẼ BIỂU ĐỒ =======================
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
    )

    # --- Nến ---
    fig.add_trace(
        go.Candlestick(
            x=df['timestamp'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='Giá',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
        ),
        row=1, col=1,
    )

    # --- EMA ---
    fig.add_trace(
        go.Scatter(x=df['timestamp'], y=df['ema20'],
                   mode='lines', name='EMA 20',
                   line=dict(color='#FFD700', width=1)), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=df['timestamp'], y=df['ema50'],
                   mode='lines', name='EMA 50',
                   line=dict(color='#00BCD4', width=1)), row=1, col=1)

    # --- Volume ---
    colors = ['#ef5350' if c < o else '#26a69a' for o, c in zip(df['open'], df['close'])]
    fig.add_trace(
        go.Bar(x=df['timestamp'], y=df['volume'], name='Volume',
               marker_color=colors, opacity=0.5), row=2, col=1)
    fig.add_trace(
        go.Scatter(x=df['timestamp'], y=df['vol_ma20'],
                   mode='lines', name='Vol MA20',
                   line=dict(color='#FF9800', width=1)), row=2, col=1)

    # --- Layout ---
    fig.update_layout(
        title=dict(
            text=f"📊 {symbol} — {timeframe}",
            font=dict(size=20),
        ),
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        height=700,
        hovermode='x unified',
        margin=dict(l=10, r=10, t=50, b=10),
    )

    fig.update_yaxes(title_text="Giá (USDT)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#333', row=2, col=1)
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#333', row=1, col=1)

    # --- Xuất HTML ---
    out_file = os.path.join(CHART_DIR, os.path.basename(filepath).replace('.json', '_chart.html'))
    fig.write_html(out_file, auto_open=True)
    print(f"✅ Đã xuất biểu đồ: {out_file} (đã tự động mở trên trình duyệt)")


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) >= 1:
        filepath = args[0]
        # Nếu chỉ truyền tên file (không có thư mục) thì tự động trỏ vào data/
        if not os.path.dirname(filepath):
            filepath = os.path.join(DATA_DIR, filepath)
    else:
        filepath = os.path.join(DATA_DIR, "btc_90days_1d.json")
    tail = int(args[1]) if len(args) >= 2 else None

    plot_candlestick(filepath, tail)
