import time
import gc
import ctypes
import requests
import config
from signal_engine import analyze_technical_signal
from gemini_auditor import audit_signal_with_gemini
from paper_trader import open_paper_trade, check_and_update_paper_trades, is_symbol_in_cooldown
from market_gatekeeper import check_market_health
from telegram_commander import start_telegram_listener

# Persistent HTTP Session cho thông báo Telegram
_alert_session = requests.Session()
_alert_adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=5, max_retries=2)
_alert_session.mount('https://', _alert_adapter)
_alert_session.mount('http://', _alert_adapter)

def release_system_memory():
    """Dọn sạch rác Python cả 3 thế hệ và ép Linux OS thu hồi 100% RAM dư thừa về hệ thống"""
    gc.collect(generation=2)
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
        _alert_session.post(url, json=payload, timeout=10)
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

        # 🛡️ KIỂM TRA GIÁP 3: MẠCH NGẮT CHUỖI THUA (COOLDOWN)
        cooldown_info = is_symbol_in_cooldown(symbol)
        if cooldown_info.get("in_cooldown"):
            print(f"   └─ 🛡️ [GIÁP 3: COOLDOWN] {cooldown_info.get('detail')} -> Tạm dừng quét coin này để bảo toàn vốn.")
            continue

        tech_signal, diag = analyze_technical_signal(symbol)

        # Bước 2: Trend Alignment (Khung 4H)
        step2 = diag.get("step2_trend_4h")
        if step2:
            if step2["status"] == "PASS":
                print(f"   ├─ Bước 2 (Trend 4H): [ĐẠT] {step2['detail']}")
            elif step2["status"] == "BLOCKED_BY_SHIELD":
                print(f"   └─ Bước 2 (Trend 4H): [CHẶN BỞI GIÁP BẢO VỆ] {step2['detail']}")
                continue
            else:
                print(f"   └─ Bước 2 (Trend 4H): [TỪ CHỐI] {step2['detail']}")
                continue

        # Bước 3: Trigger kỹ thuật (Khung 1H)
        step3 = diag.get("step3_trigger_1h")
        if step3:
            if step3["status"] == "PASS":
                print(f"   ├─ Bước 3 (Kỹ thuật 1H): [ĐẠT] {step3['detail']}")
            elif step3["status"] == "BLOCKED_BY_SHIELD":
                print(f"   └─ Bước 3 (Kỹ thuật 1H): [CHẶN BỞI GIÁP BẢO VỆ] {step3['detail']}")
                continue
            else:
                print(f"   └─ Bước 3 (Kỹ thuật 1H): [TỪ CHỐI] {step3['detail']}")
                continue

        # Bước 4: Gemini AI Audit
        strat_type = tech_signal.get('strategy_type', 'SNIPER_TREND')
        print(f"   ├─ Bước 4 (Gemini AI Audit - {strat_type}): Đang gửi thẩm định ({config.GEMINI_PRIMARY_MODEL})...")
        ai_audit = audit_signal_with_gemini(
            symbol=tech_signal['symbol'],
            entry_price=tech_signal['entry_price'],
            rsi=tech_signal['rsi'],
            adx=tech_signal['adx'],
            vol_ratio=tech_signal['vol_ratio'],
            candles_summary=tech_signal['candles_summary'],
            stop_loss=tech_signal.get('stop_loss'),
            take_profit=tech_signal.get('take_profit'),
            atr=tech_signal.get('atr'),
            strategy_type=strat_type
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

        # Bước 5: Quản trị vị thế & Mở lệnh (DUAL Regime)
        trade = open_paper_trade(
            symbol=symbol,
            entry_price=tech_signal['entry_price'],
            stop_loss=tech_signal.get('stop_loss'),
            take_profit=tech_signal.get('take_profit'),
            take_profit_1=tech_signal.get('take_profit_1'),
            take_profit_2=tech_signal.get('take_profit_2'),
            sl_pct=tech_signal.get('sl_pct'),
            tp_pct=tech_signal.get('tp_pct'),
            tp1_pct=tech_signal.get('tp1_pct'),
            tp2_pct=tech_signal.get('tp2_pct'),
            tp1_share=tech_signal.get('tp1_share'),
            tp2_share=tech_signal.get('tp2_share'),
            ai_score=ai_audit.confidence_score,
            macro_regime=market_health.market_regime if market_health else "N/A",
            fng_summary=market_health.fng_summary if market_health else "N/A",
            ai_reasoning=ai_audit.ai_reasoning,
            strategy_type=strat_type,
            strategy_desc=tech_signal.get('strategy_desc')
        )

        if trade:
            macro_info = (
                f"🌐 *Thị trường:* `{market_health.market_regime}` | *{market_health.fng_summary}*\n\n"
                if market_health else ""
            )
            pos_amt = trade.get('position_size_usdt', 50.0)
            risk_usd = trade.get('risk_usd', 0.0)
            risk_pct = trade.get('risk_pct', 0.0)
            sizing_mode = trade.get('sizing_mode', 'ATR_RISK')

            sizing_desc = f"${pos_amt:,.2f} USDT (Rủi ro: ${risk_usd:,.2f} ~ {risk_pct:.1f}%)" if sizing_mode == "ATR_RISK" else f"${pos_amt:,.2f} USDT (Cố định)"

            if strat_type == "SIDEWAY_RANGE":
                print(f"   └─ Bước 5 (Thực thi Sideway Range): [THÀNH CÔNG] Mở MUA ${pos_amt:,.2f} tại ${trade['entry_price']:,.2f} | Rủi ro: ${risk_usd:,.2f} ({risk_pct:.1f}%) | TP: ${trade['take_profit']:,.2f} | SL: ${trade['stop_loss']:,.2f}")
                msg = (
                    f"📦 *MỞ LỆNH MUA SIDEWAY RANGE* 📦\n\n"
                    f"{macro_info}"
                    f"• *Cặp coin:* `{symbol}`\n"
                    f"• *Khối lượng vào:* `{sizing_desc}`\n"
                    f"• *Chiến lược:* _Bắt đáy Lower BB + RSI quá bán ({tech_signal.get('rsi', 0):.1f})_\n"
                    f"• *Giá Mua (Entry):* `${trade['entry_price']:,.2f}`\n"
                    f"• *Mục tiêu Chốt lời (+{trade.get('tp_pct', 0):.1f}%):* `${trade['take_profit']:,.2f}` (Trục giữa SMA20)\n"
                    f"• *Cắt lỗ chặt (-{trade.get('sl_pct', 0):.1f}%):* `${trade['stop_loss']:,.2f}`\n\n"
                    f"🧠 *Gemini AI Audit:* Điểm `{ai_audit.confidence_score}/10` (Yêu cầu >={min_required_score})\n"
                    f"• *Lý do:* {ai_audit.ai_reasoning}\n\n"
                    f"⚡ *Cơ chế:* Quản lý vốn ATR Risk, lướt sóng biên hộp ngắn hạn!"
                )
            else:
                tp1_val = trade.get('take_profit_1', trade['take_profit'])
                tp2_val = trade.get('take_profit_2', trade['take_profit'])
                tp1_s = int(trade.get('tp1_share', 0.3) * 100)
                tp2_s = int(trade.get('tp2_share', 0.7) * 100)
                coin_note = tech_signal.get('coin_strategy_desc', 'Sniper Custom')
                print(f"   └─ Bước 5 (Thực thi Sniper Trend): [THÀNH CÔNG] Mở MUA ${pos_amt:,.2f} tại ${trade['entry_price']:,.2f} | Rủi ro: ${risk_usd:,.2f} ({risk_pct:.1f}%) | TP1: ${tp1_val:,.2f} | TP2: ${tp2_val:,.2f} | SL: ${trade['stop_loss']:,.2f}")
                msg = (
                    f"🎯 *MỞ LỆNH MUA SNIPER TREND* 🎯\n\n"
                    f"{macro_info}"
                    f"• *Cặp coin:* `{symbol}`\n"
                    f"• *Khối lượng vào:* `{sizing_desc}`\n"
                    f"• *Chiến lược riêng:* _{coin_note}_\n"
                    f"• *Giá Mua (Entry):* `${trade['entry_price']:,.2f}`\n"
                    f"• *Mục tiêu TP1 (+{trade.get('tp1_pct', 0):.1f}%):* `${tp1_val:,.2f}` (Chốt {tp1_s}% & kéo SL về Entry)\n"
                    f"• *Mục tiêu TP2 (+{trade.get('tp2_pct', 0):.1f}%):* `${tp2_val:,.2f}` (Gồng {tp2_s}% còn lại)\n"
                    f"• *Cắt lỗ SL (-{trade.get('sl_pct', 0):.1f}%):* `${trade['stop_loss']:,.2f}`\n\n"
                    f"🧠 *Gemini AI Audit:* Điểm `{ai_audit.confidence_score}/10` (Yêu cầu >={min_required_score})\n"
                    f"• *Lý do:* {ai_audit.ai_reasoning}\n\n"
                    f"🛡️ *Cơ chế:* Chạm TP1 tự động khóa rủi ro về 0%, gồng {tp2_s}% vị thế miễn phí rủi ro!"
                )
            send_telegram_alert(msg)
        else:
            print(f"   └─ Bước 5 (Thực thi lệnh): [BỎ QUA] Coin {symbol} đã có vị thế OPEN đang chạy, không mở thêm.")

        time.sleep(1)

def monitor_paper_trades():
    """Kiểm tra xem có lệnh mô phỏng nào khớp TP1/TP2/SL không để báo Telegram"""
    closed_events = check_and_update_paper_trades()
    for trade, result_title in closed_events:
        # Nếu là sự kiện TP1 (lệnh vẫn đang mở tiếp tục gồng)
        if trade.get("status") == "OPEN":
            msg = (
                f"🔔 *CẬP NHẬT TRẠNG THÁI VỊ THẾ* 🔔\n\n"
                f"• *Cặp coin:* `{trade['symbol']}`\n"
                f"• *Sự kiện:* {result_title}\n"
                f"• *Giá Mua:* `${trade['entry_price']:,.2f}` ➔ *Đã chốt 50% tại:* `${trade.get('tp1_price', 0):,.2f}`\n"
                f"• *Mục tiêu tiếp theo (TP2):* `${trade.get('take_profit_2', 0):,.2f}`\n\n"
                f"🛡️ *Stop Loss đã được dời về Entry: Rủi ro bằng 0%!*"
            )
        else:
            msg = (
                f"🔔 *KẾT QUẢ ĐÓNG VỊ THẾ* 🔔\n\n"
                f"• *Cặp coin:* `{trade['symbol']}`\n"
                f"• *Kết quả:* {result_title}\n"
                f"• *Giá Mua (Entry):* `${trade['entry_price']:,.2f}`\n"
                f"• *Giá Khớp Đóng:* `${trade.get('close_price', 0):,.2f}`\n"
                f"• *Tổng PnL:* `{trade.get('pnl_pct', 0):+.2f}%`\n"
                f"• *Điểm AI ban đầu:* `{trade.get('ai_score', 0)}/10`\n\n"
                f"📊 *Dữ liệu đã được lưu vào nhật ký Paper Trading.*"
            )
        print(f"📢 [PAPER TRADE EVENT] {trade['symbol']} -> {result_title}")
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