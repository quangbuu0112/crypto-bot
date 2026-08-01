import time
import requests
import config
from signal_engine import analyze_technical_signal
from gemini_auditor import audit_signal_with_gemini
from paper_trader import open_paper_trade, check_and_update_paper_trades

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
    print(f"\n🔍 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Đang quét tín hiệu mới...")

    # 1. QUÉT TÍN HIỆU VÀ LƯU LỆNH MỚI
    for symbol in config.SYMBOLS:
        tech_signal = analyze_technical_signal(symbol)

        if tech_signal:
            print(f"🎯 [KỸ THUẬT MATCH] {symbol}. Đang gửi Gemini 3.5 Flash thẩm định...")

            ai_audit = audit_signal_with_gemini(
                symbol=tech_signal['symbol'],
                entry_price=tech_signal['entry_price'],
                rsi=tech_signal['rsi'],
                adx=tech_signal['adx'],
                vol_ratio=tech_signal['vol_ratio'],
                candles_summary=tech_signal['candles_summary']
            )

            if ai_audit and ai_audit.decision == "APPROVE":
                # Mở lệnh Paper Trade
                trade = open_paper_trade(
                    symbol=symbol,
                    entry_price=tech_signal['entry_price'],
                    sl_pct=config.STOP_LOSS_PCT,
                    tp_pct=config.TAKE_PROFIT_PCT,
                    ai_score=ai_audit.confidence_score
                )

                if trade:
                    msg = (
                        f"📝 *MỞ LỆNH MUA MÔ PHỎNG (PAPER TRADE)* 📝\n\n"
                        f"• *Cặp coin:* `{symbol}`\n"
                        f"• *Giá Mua (Entry):* `${trade['entry_price']:.2f}`\n"
                        f"• *Mục tiêu TP (+1.5%):* `${trade['take_profit']:.2f}`\n"
                        f"• *Cắt lỗ SL (-1.0%):* `${trade['stop_loss']:.2f}`\n\n"
                        f"🧠 *AI Audit:* Điểm `{ai_audit.confidence_score}/10`\n"
                        f"• *Lý do:* {ai_audit.ai_reasoning}\n\n"
                        f"📌 *Hệ thống đã tự động lưu lệnh để theo dõi kết quả thực tế!*"
                    )
                    print(f"✅ [PAPER TRADE OPENED] {symbol} -> Gửi Telegram...")
                    send_telegram_alert(msg)

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
    print("==================================================")
    print("🤖 HYBRID PAPER TRADING BOT (PYTHON + GEMINI 3.5) ")
    print("==================================================")
    
    send_telegram_alert("🤖 *Bot Paper Trading đã khởi động! Đang theo dõi & đối chứng giá thực tế.*")

    while True:
        try:
            # 1. Kiểm tra khớp lệnh các vị thế đang mở
            monitor_paper_trades()
            
            # 2. Phân tích quét tín hiệu mới
            run_bot_cycle()
            
        except Exception as e:
            print(f"❌ Lỗi hệ thống: {e}")
            
        print(f"😴 Chờ {config.SLEEP_INTERVAL_SECONDS // 60} phút cho lần quét tiếp theo...")
        time.sleep(config.SLEEP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()