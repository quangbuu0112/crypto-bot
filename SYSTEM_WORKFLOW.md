# 🤖 TỔNG QUAN QUY TRÌNH VẬN HÀNH BOT (SYSTEM WORKFLOW)

> **Hệ thống:** Hybrid Paper & Live Testnet Trading Bot (Python + Gemini 3.6 Flash / 3.5 Flash-Lite)  
> **Tần suất quét:** Mỗi 15 phút một lần (`SLEEP_INTERVAL_SECONDS = 900`)  
> **Cặp coin theo dõi:** `BTC/USDT`, `ETH/USDT`, `SOL/USDT`, `BNB/USDT`, `XRP/USDT`  
> **Sàn giao dịch hỗ trợ:** Binance Spot Testnet & Bybit Spot Testnet (Chạy song song)

---

## 📊 1. Sơ đồ luồng xử lý tổng quan (Mermaid Flowchart)

```mermaid
flowchart TD
    Start([⏰ Bắt đầu chu kỳ quét 15 phút]) --> Stage1[GIAI ĐOẠN 1: Quản trị các lệnh đang mở]
    
    %% GIAI ĐOẠN 1
    Stage1 --> CheckTPSL{Đụng Take Profit hoặc Stop Loss?}
    CheckTPSL -- "Có" --> CloseTrade[1. Gửi lệnh BÁN MARKET trên Binance & Bybit Testnet<br>2. Cập nhật PnL vào paper_trades.json<br>3. Bắn thông báo Telegram kèm MACRO GATEKEEPER]
    CheckTPSL -- "Không" --> Stage2[GIAI ĐOẠN 2: Thẩm định vĩ mô Macro Gatekeeper]
    CloseTrade --> Stage2
    
    %% GIAI ĐOẠN 2
    Stage2 --> MacroAI[Lấy nến 4H/1H BTC + Chỉ số Fear & Greed<br>Gửi Gemini AI (3.6 Flash + Fallback 3.5 Lite) đánh giá thị trường]
    MacroAI --> RegimeCheck{Chế độ thị trường?}
    
    RegimeCheck -- "BEARISH_DANGER<br>(BTC xả mạnh / Vỡ cấu trúc)" --> StopCycle[⛔ KHÓA TOÀN BỘ LỆNH MUA<br>Dừng quét để tránh đu đỉnh]
    
    RegimeCheck -- "CHOPPY_CAUTION<br>(Đi ngang / F&G quá nóng)" --> SetHighThreshold[Yêu cầu điểm AI khắt khe hơn: >= 8/10]
    RegimeCheck -- "BULLISH_SAFE<br>(Uptrend lành mạnh)" --> SetNormalThreshold[Yêu cầu điểm AI chuẩn: >= 7/10]
    
    SetHighThreshold --> Stage3[GIAI ĐOẠN 3: Lọc kỹ thuật từng coin 4H + 1H]
    SetNormalThreshold --> Stage3
    
    %% GIAI ĐOẠN 3
    Stage3 --> Filter4H{Lọc 4H: Close > EMA 50 > EMA 200?}
    Filter4H -- "Không" --> SkipCoin[Bỏ qua coin này]
    Filter4H -- "Thỏa mãn" --> Filter1H{Lọc 1H: EMA20 + RSI + ADX + Vol?}
    Filter1H -- "Không" --> SkipCoin
    Filter1H -- "Thỏa mãn" --> Stage4[GIAI ĐOẠN 4: Thẩm định vi mô & Khớp lệnh]
    
    %% GIAI ĐOẠN 4
    Stage4 --> GeminiCoin[Tính SL/TP theo ATR 14<br>Gửi 5 nến 1H cho Gemini soi bẫy giá Fakeout]
    GeminiCoin --> AICheck{Gemini APPROVE & Đủ điểm?}
    AICheck -- "REJECT" --> RejectAlert[Hủy lệnh / Ghi nhận bẫy]
    AICheck -- "APPROVE" --> Execute[🚀 KHỚP LỆNH SONG SONG:<br>1. Mua $50 trên Binance Testnet<br>2. Mua $50 trên Bybit Testnet<br>3. Lưu vào paper_trades.json<br>4. Bắn thông báo MỞ LỆNH qua Telegram]
    
    %% KẾT THÚC CHU KỲ
    StopCycle --> Sleep([😴 Chờ 15 phút rồi lặp lại chu kỳ mới])
    SkipCoin --> Sleep
    RejectAlert --> Sleep
    Execute --> Sleep
```

---

## ⚙️ 2. Chi tiết 4 giai đoạn vận hành mỗi 15 phút

### 🟢 Giai đoạn 1: Quản trị vị thế đang chạy (`monitor_paper_trades`)
* **Mục tiêu:** Bảo vệ lợi nhuận và cắt lỗ kịp thời theo thời gian thực.
* **Quy trình:**
  1. Đọc toàn bộ danh sách lệnh có trạng thái `OPEN` trong [paper_trades.json](file:///c:/Code/paper_trades.json).
  2. Lấy giá tức thời từ Binance (`ticker['last']`).
  3. **Kiểm tra điều kiện đóng lệnh:**
     * **Chốt lời (Take Profit):** Khi `Current Price >= Take Profit Price` $\rightarrow$ Đóng vị thế `CLOSED_TP`.
     * **Cắt lỗ (Stop Loss):** Khi `Current Price <= Stop Loss Price` $\rightarrow$ Đóng vị thế `CLOSED_SL`.
  4. **Thực thi trên sàn thật (nếu bật Testnet):**
     * Tự động gửi lệnh **BÁN MARKET** trên cả **Binance Testnet** và **Bybit Testnet** để thu hồi USDT.
  5. **Thông báo Telegram:** Bắn thông báo kết quả PnL kèm theo báo cáo bối cảnh thị trường của **MACRO GATEKEEPER**.

---

### 🌐 Giai đoạn 2: Người gác cổng vĩ mô (`market_gatekeeper.py`)
* **Mục tiêu:** Loại bỏ hoàn toàn rủi ro "mua đúng đỉnh" khi Bitcoin và toàn bộ thị trường chuẩn bị sập.
* **Dữ liệu đầu vào:**
  * **Chỉ số Crypto Fear & Greed Index** (Lấy từ Alternative.me): 0 – 100 điểm.
  * **Cấu trúc kỹ thuật Bitcoin (BTC/USDT):** Nến 4H, EMA 50, EMA 200, và 4 nến 1H gần nhất.
* **Quyết định từ Gemini AI (3.6 Flash + Fallback 3.5 Lite):**
  * 🔴 **`BEARISH_DANGER`** (`can_open_trades = False`): BTC xuất hiện nến xả mạnh, thủng hỗ trợ $\rightarrow$ **Khóa toàn bộ lệnh mua mới trong chu kỳ này**.
  * 🟡 **`CHOPPY_CAUTION`** (`can_open_trades = True`): BTC đi ngang, thị trường nhiễu $\rightarrow$ Cho phép quét Altcoin nhưng **nâng điểm AI yêu cầu lên $\ge 8/10$**.
  * 🟢 **`BULLISH_SAFE`** (`can_open_trades = True`): BTC giữ vững cấu trúc tăng lành mạnh $\rightarrow$ Cho phép quét với điểm AI chuẩn $\ge 7/10$.

---

### 📊 Giai đoạn 3: Bộ lọc kỹ thuật định lượng 2 tầng (`signal_engine.py`)
Bot lần lượt duyệt qua danh mục 5 đồng coin (`BTC`, `ETH`, `SOL`, `BNB`, `XRP`):

#### 1. Bộ lọc xu hướng khung 4H (Trend Alignment):
$$\text{Close}_{4H} > \text{EMA 50}_{4H} > \text{EMA 200}_{4H}$$
* Chỉ khi đường trung bình ngắn nằm trên đường dài hạn và giá giữ vững trên cả hai, bot mới xác nhận Uptrend chuẩn để tìm điểm vào lệnh.

#### 2. Bộ lọc kích hoạt điểm vào khung 1H (Trigger):
* $\text{Close}_{1H} > \text{EMA 20}_{1H}$ (Đang giữ nhịp tăng ngắn hạn).
* $50 < \text{RSI}_{1H} < 68$ (Lực mua tốt nhưng chưa bị quá mua / overbought).
* $\text{ADX}_{14} > 20$ (Xu hướng có xung lực đáng kể, không phải đi ngang).
* $\text{Volume} > 1.1 \times \text{Vol\_MA20}$ (Dòng tiền mua chủ động đột biến).

#### 3. Quản trị rủi ro động theo ATR (Average True Range):
Thay vì dùng tỷ lệ phần trăm cố định dễ bị quét râu nến, bot đo độ biến động thực tế của nến 1H:
* **Stop Loss (Cắt lỗ):** $\text{Entry} - (1.5 \times \text{ATR})$
* **Take Profit (Chốt lời):** $\text{Entry} + (3.0 \times \text{ATR})$
* **Tỷ lệ Risk / Reward chuẩn:** **$1 : 2.0$** (Lợi nhuận kỳ vọng gấp đôi rủi ro).

---

### 🧠 Giai đoạn 4: AI thẩm định nến vi mô & Khớp lệnh song song (`gemini_auditor.py` & `multi_exchange_trader.py`)

1. **Thẩm định Price Action bằng Gemini AI (3.6 Flash / 3.5 Flash-Lite):**
   * Trích xuất 5 cây nến 1H gần nhất của coin có tín hiệu gửi cho Gemini.
   * AI kiểm tra: Có râu nến trên dài xả hàng không? Có dấu hiệu kiệt sức (Exhaustion)? Có cản cứng gần kề không?
   * Gemini trả về: Quyết định `APPROVE` / `REJECT` và Điểm tin cậy `confidence_score` (1 – 10).
2. **Khớp lệnh song song đa sàn (Multi-Exchange Execution):**
   * Nếu Gemini **`APPROVE`** và **`confidence_score >= min_required_score`**:
     * 🚀 Đặt lệnh **MUA MARKET** trên **Binance Spot Testnet** (vốn: `$50 USDT`).
     * 🚀 Đặt lệnh **MUA MARKET** trên **Bybit Spot Testnet** (vốn: `$50 USDT`).
     * 📝 Ghi nhận mã lệnh (Order IDs) vào [paper_trades.json](file:///c:/Code/paper_trades.json).
     * 🔔 Bắn tin nhắn thông báo chi tiết qua Telegram kèm nhận định AI.

---

## 📱 3. Cấu trúc tin nhắn Telegram thực tế

### Khi khớp mở lệnh mua mới:
```text
📝 MỞ LỆNH MUA MÔ PHỎNG (PAPER TRADE) 📝

🌐 MACRO GATEKEEPER
• Chế độ thị trường: BULLISH_SAFE
• Tâm lý F&G: Chỉ số Fear & Greed ở mức 71 (Greed)
• Nhận định BTC: BTC duy trì cấu trúc tăng trưởng mạnh mẽ trên khung 4H và đang tích lũy quanh vùng 81k.

• Cặp coin: SOL/USDT
• Giá Mua (Entry): $135.50
• Mục tiêu TP (+4.5%): $141.60
• Cắt lỗ SL (-2.2%): $132.50

🧠 AI Audit: Điểm 8/10 (Ngưỡng yêu cầu: 7)
• Lý do: Cấu trúc nến tích lũy tốt, volume vào đều, không có dấu hiệu kiệt sức đà tăng.

📌 Hệ thống đã tự động lưu lệnh để theo dõi kết quả thực tế!
```

### Khi khớp đóng lệnh (Chốt lời / Cắt lỗ):
```text
🔔 KẾT QUẢ GIAO DỊCH MÔ PHỎNG 🔔

• Cặp coin: ETH/USDT
• Kết quả: ✅ CHỐT LỜI (TAKE PROFIT)
• Giá Mua (Entry): $2,600.00
• Giá Khớp Đóng: $2,710.50
• PnL: +4.25%
• Điểm AI ban đầu: 8/10

🌐 MACRO GATEKEEPER
• Chế độ thị trường: BULLISH_SAFE
• Tâm lý F&G: Chỉ số Fear & Greed ở mức 71 (Greed)
• Nhận định BTC: BTC duy trì cấu trúc tăng trưởng lành mạnh.

📊 Dữ liệu đối chứng đã được lưu vào nhật ký Paper Trading.
```

---

## 🚀 4. Hướng dẫn các lệnh vận hành

| Mục đích | Lệnh thực thi |
| :--- | :--- |
| **Chạy bot tự động 24/7 (Local / Server)** | `python main.py` |
| **Chạy test nhanh đúng 1 chu kỳ rồi dừng** | `python main.py --once` |
| **Kiểm tra số dư các sàn Testnet (Binance, Bybit)** | `python multi_exchange_trader.py` |
| **Chạy backtest 24 tháng đối chứng** | `python backtest/back_test.py` |
| **Xem log trực tiếp trên server Linux (systemd)** | `journalctl -u crypto-bot -f` |
| **Khởi động lại bot trên server Linux** | `sudo systemctl restart crypto-bot` |

---

## 🛡️ 5. Kiến trúc Live Trading: Native Exchange SL/TP Execution (Sàn giữ Stop Loss trực tiếp)

> [!IMPORTANT]
> **Quy tắc Vàng cho Trade Thật (Live Trading):** Không bao giờ để Bot giữ Stop Loss trong bộ nhớ RAM của tiến trình.
> Ngay khi lệnh Mua MARKET khớp thành công, hệ thống **bắt buộc phải đẩy ngay lập tức** cặp lệnh OCO hoặc lệnh Stop-Loss Limit lên Orderbook của Binance & Bybit.

### 5.1. Lý do & Cơ chế Phòng ngừa Rủi ro
1. **Bảo vệ khi Server sập / Mất mạng / OOM:** Nếu AWS EC2 bị mất kết nối mạng, khởi động lại, hoặc bot bị crash, lệnh Cắt lỗ đã nằm sẵn trên Matching Engine của Sàn (Binance/Bybit). Sàn sẽ tự động bán cắt lỗ chính xác tại mức giá đã định mà không phụ thuộc vào trạng thái online của Bot.
2. **Khắc phục trượt giá (Slippage) khi Flash Crash:** Khi thị trường sập đột ngột trong vài giây (Flash dump), lệnh Stop Loss đặt sẵn trên sàn sẽ được ưu tiên khớp lệnh đầu tiên trên orderbook.

### 5.2. Triển khai Kỹ thuật trên từng sàn (trong [multi_exchange_trader.py](file:///c:/Code/multi_exchange_trader.py))
- **Binance Spot:** 
  - Đặt lệnh **OCO (One-Cancels-the-Other)** qua `privatePostOrderOco`: Đồng thời đặt Chốt lời (Limit Sell tại TP) và Cắt lỗ (Stop-Loss Limit tại SL).
  - Nếu chạm TP, lệnh SL tự hủy. Nếu chạm SL, lệnh TP tự hủy.
- **Bybit Spot / Unified:**
  - Đặt lệnh **Conditional Stop Loss Order** với `triggerPrice = SL`, `triggerBy = LastPrice`.
  - Tự động kích hoạt lệnh Market/Limit Sell khi giá chạm ngưỡng SL.
- **Cơ chế dời SL về Hòa vốn (Breakeven) khi chạm TP1:**
  - Khi bot phát hiện giá chạm TP1, bot gọi `cancel_all_native_protection_orders()` để hủy lệnh SL cũ và gọi `place_native_exchange_sltp()` để cập nhật mức SL mới (`SL = Entry`) trực tiếp trên sàn cho khối lượng còn lại.

