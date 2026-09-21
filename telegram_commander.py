"""
Module tương tác 2 chiều với Telegram Bot (Interactive Telegram Commander).
Cho phép người dùng gửi lệnh điều khiển qua Telegram để:
  - /balance  : Xem số dư ví Binance & Bybit Testnet
  - /orders   : Xem các lệnh đang mở (OPEN) và lịch sử khớp lệnh
  - /market   : Xem đánh giá Macro Gatekeeper (BTC + Fear & Greed)
  - /scan     : Kích hoạt quét thị trường ngay lập tức
  - /status   : Xem trạng thái vận hành của bot
  - /help     : Xem danh sách lệnh điều khiển
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
import requests
import config
from market_gatekeeper import check_market_health
from paper_trader import load_trades
import multi_exchange_trader

_start_time = datetime.now()

def reply_telegram(chat_id: str, text: str):
    """Gửi tin nhắn phản hồi về Telegram của người dùng"""
    token = str(config.TELEGRAM_BOT_TOKEN).strip() if config.TELEGRAM_BOT_TOKEN else ""
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ [Telegram Commander] Lỗi gửi tin nhắn: {e}")

def get_help_message() -> str:
    return (
        "🤖 *DANH SÁCH LỆNH ĐIỀU KHIỂN BOT* 🤖\n\n"
        "💰 `/balance` hoặc `/sodu`\n"
        "└─ Kiểm tra số dư ví trên Binance & Bybit Testnet\n\n"
        "📜 `/orders` hoặc `/lenh`\n"
        "└─ Xem các vị thế đang chạy & lịch sử chốt lời/cắt lỗ\n\n"
        "📊 `/report` hoặc `/thongke`\n"
        "└─ Báo cáo tổng hợp hiệu suất (Win Rate %, Tổng PnL %, Lãi/Lỗ trung bình)\n\n"
        "🌐 `/market` hoặc `/vimo`\n"
        "└─ Xem báo cáo Macro Gatekeeper (BTC & Fear & Greed)\n\n"
        "⚡ `/scan` hoặc `/quet`\n"
        "└─ Kích hoạt quét 5 đồng coin ngay lập tức\n\n"
        "ℹ️ `/status`\n"
        "└─ Xem trạng thái hệ thống, model AI, cấu hình bot\n\n"
        "💡 *Mẹo:* Bạn chỉ cần gõ tên lệnh (VD: `balance`, `orders`, `scan`, `report`) mà không cần dấu `/` cũng được!"
    )

def handle_balance_command(chat_id: str):
    reply_telegram(chat_id, "⏳ *Đang truy vấn số dư các sàn giao dịch...*")
    balances = multi_exchange_trader.check_all_testnet_balances()

    # Lấy danh sách các coin mà bot đang theo dõi giao dịch
    target_coins = set(['USDT', 'USDC'])
    for s in getattr(config, 'SYMBOLS', []):
        base = s.split('/')[0].upper()
        target_coins.add(base)

    mode_str = "📄 *CHẾ ĐỘ:* `Live Paper Trading` (Giả lập với giá thật)" if not getattr(config, 'USE_TESTNET', False) else "🧪 *CHẾ ĐỘ:* `Testnet Multi-Exchange`"

    msg = f"💰 *BÁO CÁO SỐ DƯ TÀI KHOẢN* 💰\n{mode_str}\n\n"

    for ex_name, data in balances.items():
        msg += f"🏦 *Sàn {ex_name.upper()} (Testnet):*\n"
        if data.get("success"):
            assets = data.get("assets", {})
            displayed_assets = {}

            # Ưu tiên 1: Hiển thị các coin mục tiêu của bot (USDT, BTC, ETH, SOL, BNB, XRP...)
            for curr in sorted(target_coins):
                if curr in assets and assets[curr].get('total', 0) > 0.0001:
                    displayed_assets[curr] = assets[curr]

            # Ưu tiên 2: Thêm các coin có số dư lớn khác nếu chưa đủ 8 coin
            for curr, info in sorted(assets.items(), key=lambda x: x[1].get('total', 0), reverse=True):
                if len(displayed_assets) >= 8:
                    break
                if curr not in displayed_assets and info.get('total', 0) > 0.0001:
                    displayed_assets[curr] = info

            if displayed_assets:
                for curr, info in displayed_assets.items():
                    tot = info.get("total", 0)
                    free = info.get("free", 0)
                    msg += f"• `{curr:<6}`: *{tot:,.4f}* (Khả dụng: {free:,.4f})\n"
                if len(assets) > len(displayed_assets):
                    msg += f"• _...và {len(assets) - len(displayed_assets)} token testnet khác._\n"
            else:
                msg += "• _Ví trống hoặc chưa có số dư USDT/Crypto_\n"
        else:
            err_msg = str(data.get('error', 'Lỗi không xác định'))[:150]
            msg += f"• ❌ Lỗi kết nối: `{err_msg}`\n"
        msg += "\n"

    reply_telegram(chat_id, msg)

def handle_orders_command(chat_id: str):
    trades = load_trades()
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    closed_trades = [t for t in trades if t.get("status") != "OPEN"]

    msg = "📜 *BÁO CÁO VỊ THẾ & LỊCH SỬ LỆNH* 📜\n\n"

    msg += f"📌 *LỆNH ĐANG MỞ ({len(open_trades)} vị thế):*\n"
    if open_trades:
        for t in open_trades:
            msg += (
                f"• *{t['symbol']}* (AI: `{t.get('ai_score', 'N/A')}/10`)\n"
                f"  ├─ Giá vào (Entry): `${t['entry_price']:,.2f}`\n"
                f"  ├─ Mục tiêu TP: `${t.get('take_profit', 0):,.2f}` (+{t.get('tp_pct', 0):.1f}%)\n"
                f"  ├─ Cắt lỗ SL: `${t.get('stop_loss', 0):,.2f}` (-{t.get('sl_pct', 0):.1f}%)\n"
                f"  └─ Mở lúc: `{t.get('opened_at', 'N/A')}`\n"
            )
    else:
        msg += "• _Hiện không có vị thế nào đang mở._\n"

    msg += f"\n🏁 *5 LỆNH ĐÃ ĐÓNG GẦN NHẤT:*\n"
    if closed_trades:
        for t in closed_trades[-5:]:
            status_icon = "🟢" if "TP" in t.get("status", "") else "🔴"
            pnl = t.get("pnl_pct", 0)
            pnl_sign = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
            msg += (
                f"{status_icon} *{t['symbol']}* | `{t.get('status')}`\n"
                f"  ├─ PnL: *{pnl_sign}* | Entry: `${t['entry_price']:,.2f}` -> Đóng: `${t.get('close_price', 0):,.2f}`\n"
                f"  └─ Thời gian: `{t.get('closed_at', t.get('opened_at', 'N/A'))}`\n"
            )
    else:
        msg += "• _Chưa có lịch sử lệnh đã đóng._\n"

    reply_telegram(chat_id, msg)

def handle_market_command(chat_id: str):
    reply_telegram(chat_id, "⏳ *Đang gửi yêu cầu phân tích bối cảnh BTC & Fear & Greed...*")
    market_health = check_market_health(force_refresh=True)
    if not market_health:
        reply_telegram(chat_id, "❌ Không thể lấy dữ liệu bối cảnh thị trường.")
        return

    status_str = "🟢 AN TOÀN VÀO LỆNH" if market_health.can_open_trades else "🔴 KHÓA LỆNH MUA (RỦI RO CAO)"
    msg = (
        "🌐 *BÁO CÁO MACRO GATEKEEPER* 🌐\n\n"
        f"• *Trạng thái:* *{status_str}*\n"
        f"• *Chế độ thị trường:* `{market_health.market_regime}`\n"
        f"• *Tâm lý F&G:* {market_health.fng_summary}\n"
        f"• *Điểm AI tối thiểu:* `{market_health.min_confidence_score}/10`\n\n"
        f"🧠 *Nhận định BTC:* {market_health.summary}"
    )
    reply_telegram(chat_id, msg)

def handle_status_command(chat_id: str):
    uptime_delta = datetime.now() - _start_time
    hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    model_name = getattr(config, 'GEMINI_PRIMARY_MODEL', 'gemini-3.6-flash')
    fallback_name = getattr(config, 'GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')
    exchanges = getattr(config, 'ACTIVE_TESTNET_EXCHANGES', ['binance', 'bybit'])
    use_atr = getattr(config, 'USE_ATR_STOPS', True)

    msg = (
        "📊 *THÔNG TIN HỆ THỐNG BOT* 📊\n\n"
        f"• *Thời gian chạy (Uptime):* `{hours}h {minutes}m {seconds}s`\n"
        f"• *Chu kỳ quét:* Mỗi `{config.SLEEP_INTERVAL_SECONDS // 60} phút`\n"
        f"• *Danh mục theo dõi:* `{', '.join(config.SYMBOLS)}`\n"
        f"• *Sàn Testnet kích hoạt:* `{', '.join(exchanges)}` (Vốn: `${getattr(config, 'ORDER_AMOUNT_USDT', 50.0)} USDT/lệnh`)\n"
        f"• *Quản trị rủi ro ATR:* `{'Bật (SL: 1.5x, TP: 3.0x)' if use_atr else 'Tắt (Cố định 2%/4%)'}`\n"
        f"• *Model AI Chính:* `{model_name}`\n"
        f"• *Model AI Dự phòng:* `{fallback_name}`\n\n"
        "✅ *Trạng thái: Hoạt động bình thường 24/7!*"
    )
    reply_telegram(chat_id, msg)

def handle_report_command(chat_id: str):
    trades = load_trades()
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    closed_trades = [t for t in trades if t.get("status") != "OPEN"]

    if not closed_trades:
        info = "📊 *BÁO CÁO HIỆU SUẤT PAPER TRADING* 📊\n\n"
        if open_trades:
            info += (
                f"• _Chưa có lệnh nào đóng (TP/SL) để tính toán thống kê PnL._\n"
                f"• Hiện đang có *{len(open_trades)} vị thế đang mở*.\n\n"
                f"👉 Gõ `/orders` để theo dõi các lệnh đang chạy!"
            )
        else:
            info += (
                "• _Chưa có lịch sử giao dịch nào được ghi nhận._\n"
                "• Bot đang theo dõi và quét thị trường theo chu kỳ để tìm điểm vào lệnh đạt chuẩn.\n\n"
                "👉 Gõ `/scan` để yêu cầu bot quét thị trường ngay lập tức!"
            )
        reply_telegram(chat_id, info)
        return

    wins = [t for t in closed_trades if float(t.get("pnl_pct", 0)) > 0]
    losses = [t for t in closed_trades if float(t.get("pnl_pct", 0)) <= 0]
    total_closed = len(closed_trades)
    win_rate = (len(wins) / total_closed) * 100 if total_closed > 0 else 0.0
    total_pnl = sum(float(t.get("pnl_pct", 0)) for t in closed_trades)
    avg_win = sum(float(t.get("pnl_pct", 0)) for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(float(t.get("pnl_pct", 0)) for t in losses) / len(losses) if losses else 0.0

    msg = (
        "📊 *BÁO CÁO TỔNG HỢP HIỆU SUẤT BOT* 📊\n\n"
        f"• *Tổng số lệnh đã đóng:* `{total_closed} lệnh`\n"
        f"• *Thắng (WIN):* `{len(wins)} lệnh` (*{win_rate:.1f}%*)\n"
        f"• *Thua (LOSS):* `{len(losses)} lệnh` (*{100 - win_rate:.1f}%*)\n"
        f"• *Tổng PnL tích lũy:* *{total_pnl:+.2f}%*\n"
        f"• *Lãi trung bình / WIN:* `+{avg_win:.2f}%`\n"
        f"• *Lỗ trung bình / LOSS:* `{avg_loss:.2f}%`\n\n"
        "📁 _Toàn bộ nhật ký chi tiết được lưu trong paper_trades.json & CSV report._"
    )
    reply_telegram(chat_id, msg)

def process_message(chat_id: str, text: str, scan_callback=None):
    if not text:
        return
    tokens = text.strip().split()
    raw_cmd = tokens[0].lower() if tokens else ""
    # Tự động loại bỏ đuôi mention @bot_name (ví dụ /report@my_crypto_bot -> /report)
    cmd = raw_cmd.split('@')[0]

    if cmd in ['/start', '/help', 'help', 'menu', 'trogiup']:
        reply_telegram(chat_id, get_help_message())

    elif cmd in ['/balance', '/sodu', 'balance', 'sodu', 'vi']:
        handle_balance_command(chat_id)

    elif cmd in ['/orders', '/lenh', 'orders', 'lenh', 'positions']:
        handle_orders_command(chat_id)

    elif cmd in ['/report', '/thongke', 'report', 'thongke', 'pnl']:
        handle_report_command(chat_id)

    elif cmd in ['/market', '/vimo', 'market', 'vimo', 'btc']:
        handle_market_command(chat_id)

    elif cmd in ['/status', 'status', 'tt', 'hethong']:
        handle_status_command(chat_id)

    elif cmd in ['/scan', '/quet', 'scan', 'quet']:
        if scan_callback:
            reply_telegram(chat_id, "⚡ *Đang kích hoạt quét toàn bộ 5 đồng coin ngay lập tức...*")
            try:
                scan_callback()
                reply_telegram(chat_id, "✅ *Đã hoàn tất chu kỳ quét theo yêu cầu!*")
            except Exception as e:
                reply_telegram(chat_id, f"❌ Lỗi khi thực hiện quét: {e}")
        else:
            reply_telegram(chat_id, "⚠️ Chức năng quét tức thời chưa được gắn callback.")

    else:
        reply_telegram(chat_id, f"❓ Lệnh `{text}` không hợp lệ.\n\nGõ `/help` để xem danh sách lệnh hỗ trợ.")

def _listener_worker(scan_callback=None):
    token = str(config.TELEGRAM_BOT_TOKEN).strip() if config.TELEGRAM_BOT_TOKEN else ""
    authorized_chat_id = str(config.TELEGRAM_CHAT_ID).strip() if config.TELEGRAM_CHAT_ID else ""

    if not token or not authorized_chat_id:
        print("⚠️ [Telegram Commander] Chưa cấu hình TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID.")
        return

    print("🎮 [Telegram Commander] Đã kích hoạt bộ lắng nghe lệnh tương tác 2 chiều!")
    offset = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"timeout": 20}
            if offset:
                params["offset"] = offset

            res = requests.get(url, params=params, timeout=25)
            if res.status_code == 200:
                data = res.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        msg_obj = update.get("message")
                        if not msg_obj:
                            continue

                        sender_chat_id = str(msg_obj.get("chat", {}).get("id"))
                        msg_text = msg_obj.get("text", "")

                        if not msg_text:
                            continue

                        # Bảo mật: Chỉ người sở hữu (authorized_chat_id) mới có quyền điều khiển
                        if sender_chat_id != authorized_chat_id:
                            reply_telegram(sender_chat_id, "⛔ *Quyền truy cập bị từ chối.* Bạn không phải chủ sở hữu của Bot này.")
                            print(f"⚠️ [Telegram Commander] Từ chối truy cập từ chat_id lạ: {sender_chat_id}")
                            continue

                        # Xử lý lệnh
                        threading.Thread(
                            target=process_message,
                            args=(sender_chat_id, msg_text, scan_callback),
                            daemon=True
                        ).start()

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            # Ngủ nhẹ khi mất mạng để tránh spam vòng lặp
            time.sleep(3)

def start_telegram_listener(scan_callback=None):
    """Khởi động luồng chạy ngầm lắng nghe tin nhắn từ Telegram"""
    t = threading.Thread(target=_listener_worker, args=(scan_callback,), daemon=True)
    t.start()
    return t
