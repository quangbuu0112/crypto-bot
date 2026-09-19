import ccxt
import pandas as pd
import pandas_ta as ta

exchange = ccxt.binance({'enableRateLimit': True})

def fetch_data(symbol, timeframe, limit=1000):
    """Lấy dữ liệu nến từ Binance và chuyển thành DataFrame"""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def run_multi_timeframe_backtest(symbol="BTC/USDT", limit=1000):
    print(f"🔄 Đang tải dữ liệu đa khung thời gian (4h & 1h) cho {symbol}...")
    
    # 1. Lấy dữ liệu 2 khung thời gian
    df_4h = fetch_data(symbol, timeframe="4h", limit=limit)
    df_1h = fetch_data(symbol, timeframe="1h", limit=limit)

    # ==================== 2. TÍNH CHỈ BÁO KHUNG 4H (TREND) ====================
    # Dùng EMA 200 trên 4h để làm bộ lọc xu hướng lớn
    df_4h['EMA_200_4h'] = ta.ema(df_4h['close'], length=200)
    # Xác định Uptrend 4h (1: Uptrend, 0: Downtrend/Sideway)
    df_4h['is_uptrend_4h'] = (df_4h['close'] > df_4h['EMA_200_4h']).astype(int)
    
    # Chỉ giữ lại các cột cần thiết từ khung 4h để ghép
    df_4h_subset = df_4h[['timestamp', 'is_uptrend_4h']].sort_values('timestamp')

    # ==================== 3. TÍNH CHỈ BÁO KHUNG 1H (ENTRY) ====================
    df_1h['EMA_20_1h'] = ta.ema(df_1h['close'], length=20)
    df_1h['RSI_1h'] = ta.rsi(df_1h['close'], length=14)
    
    adx_df = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
    df_1h['ADX_14_1h'] = adx_df['ADX_14']
    df_1h['VOL_MA20_1h'] = df_1h['volume'].rolling(20).mean()
    
    df_1h = df_1h.sort_values('timestamp')

    # ==================== 4. GHÉP DỮ LIỆU 4H VÀO 1H (MERGE) ====================
    # pd.merge_asof sẽ ánh ánh xu hướng 4h ĐÃ ĐÓNG CỬA gần nhất vào nến 1h
    df_merged = pd.merge_asof(
        df_1h, 
        df_4h_subset, 
        on='timestamp', 
        direction='backward' # Chỉ lấy nến 4h trong quá khứ, không lấy nến 4h tương lai
    )

    # ==================== 5. VÒNG LẶP BACKTEST ====================
    total_signals = 0
    correct_predictions = 0
    total_pnl_percent = 0.0

    STOP_LOSS_PCT = 0.01   # Cắt lỗ 1.0%
    TAKE_PROFIT_PCT = 0.015 # Chốt lời 1.5% (Risk/Reward = 1 : 1.5)

    # Bắt đầu duyệt từ nến thứ 200 (khi đã đủ dữ liệu tính EMA200)
    for i in range(200, len(df_merged) - 1):
        past = df_merged.iloc[i]
        future = df_merged.iloc[i + 1]

        # 1. ĐIỀU KIỆN KHUNG 4H: Bắt buộc 4h phải là UPTREND
        cond_trend_4h = past['is_uptrend_4h'] == 1

        # 2. ĐIỀU KIỆN KHUNG 1H: Tín hiệu kỹ thuật vào lệnh
        cond_ema_1h = past['close'] > past['EMA_20_1h']
        cond_rsi_1h = 50 < past['RSI_1h'] < 68
        cond_adx_1h = past['ADX_14_1h'] > 20
        cond_vol_1h = past['volume'] > (1.1 * past['VOL_MA20_1h'])

        # KẾT HỢP ĐA KHUNG THỜI GIAN
        if cond_trend_4h and cond_ema_1h and cond_rsi_1h and cond_adx_1h and cond_vol_1h:
            total_signals += 1
            
            entry_price = past['close']
            actual_close = future['close']
            
            price_change = (actual_close - entry_price) / entry_price

            if price_change > 0:
                correct_predictions += 1
                total_pnl_percent += TAKE_PROFIT_PCT * 100
            else:
                total_pnl_percent -= STOP_LOSS_PCT * 100

    # ==================== 6. BÁO CÁO KẾT QUẢ ====================
    win_rate = (correct_predictions / total_signals * 100) if total_signals > 0 else 0

    print("\n================ KẾT QUẢ BACKTEST ĐA KHUNG THỜI GIAN ================")
    print(f"• Cặp giao dịch           : {symbol}")
    print(f"• Bộ lọc Xu hướng (Trend) : Khung 4H (Giá > EMA 200)")
    print(f"• Điểm vào lệnh (Entry)   : Khung 1H (EMA20 + RSI + ADX + Vol)")
    print("--------------------------------------------------------------------")
    print(f"• Tổng số lệnh phát ra    : {total_signals} lệnh (Đã lọc bỏ lệnh ngược sóng 4h)")
    print(f"• Số lệnh DỰ ĐOÁN ĐÚNG    : {correct_predictions} lệnh")
    print(f"• Số lệnh DỰ ĐOÁN SAI     : {total_signals - correct_predictions} lệnh")
    print(f"• ĐỘ CHÍNH XÁC (WIN RATE) : {win_rate:.2f}%")
    print("--------------------------------------------------------------------")
    print(f"• Tỷ lệ Risk / Reward     : 1 : 1.5")
    print(f"• TỔNG LỢI NHUẬN TÍCH LŨY : {total_pnl_percent:+.2f}%")
    print("====================================================================\n")

if __name__ == "__main__":
    run_multi_timeframe_backtest(symbol="XRP/USDT", limit=1000)