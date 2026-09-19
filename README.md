# Hybrid Paper Trading Bot (Python + Gemini)

Bot giao dịch mô phỏng (paper trading) crypto, kết hợp tín hiệu kỹ thuật đa khung thời gian (4H + 1H)
với thẩm định rủi ro bằng Gemini AI.

## Cấu trúc thư mục

```
c:\Code\
├── main.py                 # Entry point — chạy bot (python main.py)
├── config.py               # Cấu hình chung (API key, cặp coin, SL/TP, thời gian quét)
├── market_gatekeeper.py    # Phân tích vĩ mô thị trường (BTC + Fear & Greed) bằng Gemini AI
├── signal_engine.py        # Phân tích tín hiệu kỹ thuật (EMA, RSI, ADX, Volume, ATR)
├── gemini_auditor.py       # Thẩm định tín hiệu từng coin bằng Gemini AI
├── paper_trader.py         # Quản lý lệnh paper trade (mở/đóng lệnh)
├── paper_trades.json       # Nhật ký lệnh (dữ liệu runtime)
├── requirements.txt        # Các thư viện cần cài
├── .env                    # API keys (không commit lên git)
│
├── backtest/               # Script backtest / nghiên cứu hiệu năng
│   ├── back_test.py        # Backtest batch có Gemini thẩm định
│   ├── getCoinPrice.py     # Backtest đa khung thời gian thuần kỹ thuật
│   └── test.py             # So sánh win rate khi có/không có AI
│
├── tools/                  # Tiện ích xử lý dữ liệu & biểu đồ
│   ├── fetch_btc_data.py           # Tải dữ liệu nến BTC từ Binance -> data/
│   ├── fetch_market_metadata.py    # Tải OHLCV 1d/1w của 5 coin (24 tháng) -> data/market/
│   ├── resample_data.py            # Resample 1H -> 4H/1D/1W
│   ├── plot_candles.py             # Vẽ biểu đồ nến -> charts/
│   └── check_models.py             # Liệt kê các model Gemini khả dụng
│
├── data/                   # Dữ liệu OHLCV (JSON)
│   ├── btc_90days.json
│   ├── btc_90days_4h.json
│   ├── btc_90days_1d.json
│   ├── btc_90days_1w.json
│   └── market/             # Metadata 5 coin (24 tháng, khung 1d + 1w)
│       ├── btc_usdt_1d.json, btc_usdt_1w.json, ...
│       └── metadata.json   # File index tổng hợp
│
├── charts/                 # Biểu đồ HTML xuất ra
│   ├── btc_90days_4h_chart.html
│   └── btc_90days_1d_chart.html
│
└── reports/                # Báo cáo / tổng hợp (CSV, Excel)
    ├── crypto_summary.csv
    └── crypto_summary.xlsx
```

## Cách chạy

```bash
# Cài thư viện
pip install -r requirements.txt

# Chạy bot (quét tín hiệu + mở paper trade)
python main.py

# Tải lại dữ liệu BTC
python tools/fetch_btc_data.py

# Tải metadata 5 coin (24 tháng, khung 1d + 1w) để phân tích mô hình nến
python tools/fetch_market_metadata.py

# Resample dữ liệu
python tools/resample_data.py

# Vẽ biểu đồ
python tools/plot_candles.py

# Backtest có AI
python backtest/back_test.py BTC/USDT 2026-07-20 7
```

> Các script trong `tools/` và `backtest/` tự xác định đường dẫn tuyệt đối nên có thể chạy từ thư mục gốc dự án.
