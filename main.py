import time
import gc
import ctypes
import requests
import config
from signal_engine import analyze_technical_signal
from gemini_auditor import audit_signal_with_gemini
from paper_trader import open_paper_trade, check_and_update_paper_trades
from market_gatekeeper import check_market_health
from telegram_commander import start_telegram_listener

def release_system_memory():
    """Dọn sạch rác Python và ép Linux OS thu hồi 100% RAM dư thừa về hệ thống"""
    gc.collect()
    try:
        # Lệnh can thiệp trực tiếp vào C runtime của Linux để trả RAM về cho OS
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

def send_telegram_alert(message: str):
    clean_token = str(config.TELEGRAM_BOT_TOKEN).strip()
    clean_chat_id = str(config.TELEGRAM_CHAT_ID).strip()
    
    url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
    payload = {
        "chat_id": clean_chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Lỗi gửi Telegram: {e}")

def run_bot_cycle():
    print("\n" + "=" * 55)
    print(f"🔍 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Bắt đầu chu kỳ quét mới...")
    print("=" * 55)

    # BƯỚC 1: BỘ LỌC VĨ MÔ TOÀN THỊ TRƯỜNG (MACRO GATEKEEPER)
    market_health = check_market_health()
    if market_health:
        status_b1 = "[ĐẠT] Đủ điều kiện an toàn để mở lệnh mua Altcoin." if market_health.can_open_trades else "[TỪ CHỐI] Khóa lệnh mua do thị trường rủi ro cao."
        print(f"🌐 [Bước 1: Macro Gatekeeper] {status_b1}")
        print(f"   ├─ Chế độ: {market_health.market_regime} | F&G: {market_health.fng_summary}")
        print(f"   └─ Đánh giá BTC: {market_health.summary}")

        if not market_health.can_open_trades:
            print("⛔ [MACRO LOCK] Thị trường BTC rủi ro cao. Khóa toàn bộ lệnh mua Altcoin chu kỳ này!")
            return

    min_required_score = market_health.min_confidence_score if market_health else 7

    # KIỂM TRA CHI TIẾT TỪNG ĐỒNG COIN THEO TỪNG BƯỚC
    for symbol in config.SYMBOLS:
        print(f"\n👉 [KIỂM TRA COIN] {symbol}:")
        tech_signal, diag = analyze_technical_signal(symbol)

        # Bước 2: Trend Alignment (Khung 4H)
        step2 = diag.get("step2_trend_4h")
        if step2:
            if step2["status"] == "PASS":
                print(f"   ├─ Bước 2 (Trend 4H): [ĐẠT] {step2['detail']}")
            else:
                print(f"   └─ Bước 2 (Trend 4H): [TỪ CHỐI] {step2['detail']}")
                continue

        # Bước 3: Trigger kỹ thuật (Khung 1H)
        step3 = diag.get("step3_trigger_1h")
        if step3:
            if step3["status"] == "PASS":
                print(f"   ├─ Bước 3 (Kỹ thuật 1H): [ĐẠT] {step3['detail']}")
            else:
                print(f"   └─ Bước 3 (Kỹ thuật 1H): [TỪ CHỐI] {step3['detail']}")
                continue

        # Bước 4: Gemini AI Audit
        print(f"   ├─ Bước 4 (Gemini AI Audit): Đang gửi thẩm định ({config.GEMINI_PRIMARY_MODEL})...")
        ai_audit = audit_signal_with_gemini(
            symbol=tech_signal['symbol'],
            entry_price=tech_signal['entry_price'],
            rsi=tech_signal['rsi'],
            adx=tech_signal['adx'],
            vol_ratio=tech_signal['vol_ratio'],
            candles_summary=tech_signal['candles_summary'],
            stop_loss=tech_signal.get('stop_loss'),
            take_profit=tech_signal.get('take_profit'),
            atr=tech_signal.get('atr')
        )

        if ai_audit:
            if ai_audit.decision == "APPROVE" and ai_audit.confidence_score >= min_required_score:
                print(f"   ├─ Bước 4 (Gemini AI Audit): [ĐẠT] Điểm {ai_audit.confidence_score}/10 (Yêu cầu >={min_required_score})")
                print(f"   │  └─ Lý do: {ai_audit.ai_reasoning}")
            else:
                print(f"   └─ Bước 4 (Gemini AI Audit): [TỪ CHỐI] Quyết định: {ai_audit.decision}, Điểm {ai_audit.confidence_score}/10 (Yêu cầu >={min_required_score})")
                print(f"      └─ Lý do: {ai_audit.ai_reasoning}")
                continue
        else:
            print("   └─ Bước 4 (Gemini AI Audit): [TỪ CHỐI] Không nhận được phản hồi từ AI.")
            continue

        # Bước 5: Quản trị vị thế & Mở lệnh
        trade = open_paper_trade(
            symbol=symbol,
            entry_price=tech_signal['entry_price'],
            stop_loss=tech_signal.get('stop_loss'),
            take_profit=tech_signal.get('take_profit'),
            sl_pct=tech_signal.get('sl_pct'),
            tp_pct=tech_signal.get('tp_pct'),
            ai_score=ai_audit.confidence_score
        )

        if trade:
            print(f"   └─ Bước 5 (Thực thi lệnh): [THÀNH CÔNG] Mở MUA tại ${trade['entry_price']:,.2f} | TP: ${trade['take_profit']:,.2f} | SL: ${trade['stop_loss']:,.2f}")
            macro_info = (
                f"🌐 *Thị trường:* `{market_health.market_regime}` | *{market_health.fng_summary}*\n\n"
                if market_health else ""
            )
            msg = (
                f"📝 *MỞ LỆNH MUA MÔ PHỎNG (PAPER TRADE)* 📝\n\n"
                f"{macro_info}"
                f"• *Cặp coin:* `{symbol}`\n"
                f"• *Giá Mua (Entry):* `${trade['entry_price']:.2f}`\n"
                f"• *Mục tiêu TP (+{trade.get('tp_pct', 0):.1f}%):* `${trade['take_profit']:.2f}`\n"
                f"• *Cắt lỗ SL (-{trade.get('sl_pct', 0):.1f}%):* `${trade['stop_loss']:.2f}`\n\n"
                f"🧠 *AI Audit:* Điểm `{ai_audit.confidence_score}/10` (Ngưỡng yêu cầu: {min_required_score})\n"
                f"• *Lý do:* {ai_audit.ai_reasoning}\n\n"
                f"📌 *Hệ thống đã tự động lưu lệnh để theo dõi kết quả thực tế!*"
            )
            send_telegram_alert(msg)
        else:
            print(f"   └─ Bước 5 (Thực thi lệnh): [BỎ QUA] Coin {symbol} đã có vị thế OPEN đang chạy, không mở thêm.")

        time.sleep(1)

def monitor_paper_trades():
    """Kiểm tra xem có lệnh mô phỏng nào khớp TP/SL không để báo Telegram"""
    closed_events = check_and_update_paper_trades()
    for trade, result_title in closed_events:
        msg = (
            f"🔔 *KẾT QUẢ GIAO DỊCH MÔ PHỎNG* 🔔\n\n"
            f"• *Cặp coin:* `{trade['symbol']}`\n"
            f"• *Kết quả:* {result_title}\n"
            f"• *Giá Mua (Entry):* `${trade['entry_price']:.2f}`\n"
            f"• *Giá Khớp Đóng:* `${trade['close_price']:.2f}`\n"
            f"• *PnL:* `{trade['pnl_pct']:+.1f}%`\n"
            f"• *Điểm AI ban đầu:* `{trade['ai_score']}/10`\n\n"
            f"📊 *Dữ liệu đối chứng đã được lưu vào nhật ký Paper Trading.*"
        )
        print(f"📢 [PAPER TRADE CLOSED] {trade['symbol']} -> PnL: {trade['pnl_pct']}%")
        send_telegram_alert(msg)

def main():
    model_name = getattr(config, 'GEMINI_PRIMARY_MODEL', 'gemini-3.6-flash')
    print("==================================================")
    print(f"🤖 HYBRID CRYPTO TRADING BOT (PYTHON + {model_name}) ")
    print("==================================================")
    print(f"📊 Danh sách coin theo dõi: {config.SYMBOLS}")
    print(f"⏱️ Chu kỳ quét: Mỗi {config.SLEEP_INTERVAL_SECONDS // 60} phút.")
    print("==================================================")

    send_telegram_alert("🚀 *Hệ thống Crypto Trading Bot vừa khởi động lại thành công! Đang quét thị trường 24/7.*")

    # Kích hoạt luồng tương tác 2 chiều với Telegram
    start_telegram_listener(scan_callback=run_bot_cycle)

    while True:
        try:
            # 1. Kiểm tra khớp lệnh các vị thế đang mở
            monitor_paper_trades()

            # 2. Phân tích quét tín hiệu mới
            run_bot_cycle()

        except Exception as e:
            print(f"❌ Lỗi hệ thống: {e}")
        finally:
            # 3. Thu hồi và giải phóng 100% RAM dư thừa về cho hệ điều hành
            release_system_memory()

        print(f"😴 Chờ {config.SLEEP_INTERVAL_SECONDS // 60} phút cho lần quét tiếp theo...")
        time.sleep(config.SLEEP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()