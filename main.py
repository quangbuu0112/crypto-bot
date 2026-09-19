import time
import requests
import config
from signal_engine import analyze_technical_signal
from gemini_auditor import audit_signal_with_gemini
from paper_trader import open_paper_trade, check_and_update_paper_trades
from market_gatekeeper import check_market_health

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
    print(f"\n🔍 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Bắt đầu chu kỳ quét mới...")

    # 0. BỘ LỌC VĨ MÔ TOÀN THỊ TRƯỜNG (BTC TREND + FEAR & GREED INDEX)
    market_health = check_market_health()
    if market_health:
        print(f"🌐 [MACRO GATEKEEPER] Regime: {market_health.market_regime} | F&G: {market_health.fng_summary}")
        print(f"   └─ Đánh giá BTC: {market_health.summary}")

        # Nếu thị trường rủi ro sập (BEARISH_DANGER) -> Tạm dừng mở vị thế mua Altcoin
        if not market_health.can_open_trades:
            print("⛔ [MACRO LOCK] Thị trường BTC rủi ro cao. Khóa toàn bộ lệnh mua Altcoin chu kỳ này!")
            return

    min_required_score = market_health.min_confidence_score if market_health else 7

    # 1. QUÉT TÍN HIỆU VÀ LƯU LỆNH MỚI
    for symbol in config.SYMBOLS:
        tech_signal = analyze_technical_signal(symbol)

        if tech_signal:
            print(f"🎯 [KỸ THUẬT MATCH] {symbol}. Đang gửi Gemini AI thẩm định ({config.GEMINI_PRIMARY_MODEL})...")

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

            if ai_audit and ai_audit.decision == "APPROVE" and ai_audit.confidence_score >= min_required_score:
                # Mở lệnh Paper Trade với SL/TP động từ ATR
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