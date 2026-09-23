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
import ctypes
from datetime import datetime, timezone
import requests
from concurrent.futures import ThreadPoolExecutor
import config
from market_gatekeeper import check_market_health
from paper_trader import load_trades
import multi_exchange_trader

_start_time = datetime.now()

# Persistent HTTP Session với Connection Pooling cố định
_http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=2)
_http_session.mount('https://', adapter)
_http_session.mount('http://', adapter)

# Giới hạn tối đa 3 worker thread xử lý lệnh (thay vì spawn vô hạn thread)
_thread_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="TgWorker")

def reply_telegram(chat_id: str, text: str):
    """Gửi tin nhắn phản hồi về Telegram của người dùng (có fallback plain text nếu lỗi Markdown)"""
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
        res = _http_session.post(url, json=payload, timeout=10)
        # Nếu Telegram báo lỗi 400 (lỗi entity Markdown parse), tự động gửi lại dưới dạng plain text
        if res.status_code != 200:
            plain_text = text.replace("*", "").replace("`", "").replace("_", "")
            _http_session.post(url, json={"chat_id": chat_id, "text": plain_text}, timeout=10)
    except Exception as e:
        print(f"❌ [Telegram Commander] Lỗi gửi tin nhắn: {e}")

def get_help_message() -> str:
    return (
        "🤖 *DANH SÁCH LỆNH ĐIỀU KHIỂN BOT* 🤖\n\n"
        "🎯 `/risk [số_%]` hoặc `/ruiro [số_%]`\n"
        "└─ Xem hoặc chỉnh % rủi ro mỗi lệnh theo ATR (VD: `/risk 1.5` hoặc `/risk 2.0`)\n\n"
        "💵 `/amount [số_tiền]` hoặc `/tien [số_tiền]`\n"
        "└─ Xem hoặc chuyển sang đi vốn cố định (VD: `/amount 100`)\n\n"
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
        "└─ Xem trạng thái hệ thống, model AI, cấu hình Quản trị Vốn\n\n"
        "💡 *Mẹo:* Bạn chỉ cần gõ tên lệnh (VD: `risk 1.5`, `amount 100`, `orders`, `report`) mà không cần dấu `/` cũng được!"
    )

def handle_balance_command(chat_id: str):
    from paper_trader import get_current_paper_balance, load_trades

    bal_data = get_current_paper_balance()
    initial_cap_per_ex = float(getattr(config, 'INITIAL_PAPER_BALANCE_PER_EXCHANGE', 500.0))
    exchanges = getattr(config, 'PAPER_EXCHANGES', ['binance', 'bybit'])
    total_initial = initial_cap_per_ex * len(exchanges)

    bal_binance = bal_data.get('binance', initial_cap_per_ex)
    bal_bybit = bal_data.get('bybit', initial_cap_per_ex)
    bal_total = bal_data.get('total', total_initial)

    binance_profit = bal_binance - initial_cap_per_ex
    binance_roi = (binance_profit / initial_cap_per_ex) * 100.0 if initial_cap_per_ex > 0 else 0.0

    bybit_profit = bal_bybit - initial_cap_per_ex
    bybit_roi = (bybit_profit / initial_cap_per_ex) * 100.0 if initial_cap_per_ex > 0 else 0.0

    total_profit = bal_total - total_initial
    total_roi = (total_profit / total_initial) * 100.0 if total_initial > 0 else 0.0

    trades = load_trades()
    open_binance = [t for t in trades if t.get("status") == "OPEN" and t.get("exchange", "binance") == "binance"]
    closed_binance = [t for t in trades if t.get("status") != "OPEN" and t.get("exchange", "binance") == "binance"]

    open_bybit = [t for t in trades if t.get("status") == "OPEN" and t.get("exchange", "binance") == "bybit"]
    closed_bybit = [t for t in trades if t.get("status") != "OPEN" and t.get("exchange", "binance") == "bybit"]

    msg = (
        "💰 *BÁO CÁO SỐ DƯ TÀI KHOẢN (DUAL-EXCHANGE)* 💰\n"
        "📄 *Chế độ:* `Live Parallel Paper Trading (Binance + Bybit)`\n\n"
        "🏦 *SÀN BINANCE PAPER:*\n"
        f"• *Vốn khởi điểm:* `${initial_cap_per_ex:,.2f} USDT`\n"
        f"• *Số dư khả dụng:* `💵 ${bal_binance:,.2f} USDT`\n"
        f"• *Realized PnL:* `{binance_profit:+,.2f} USDT` (`{binance_roi:+.2f}%`)\n"
        f"• *Vị thế OPEN:* `{len(open_binance)} lệnh` | *Đã đóng:* `{len(closed_binance)} lệnh`\n\n"
        "🏦 *SÀN BYBIT PAPER:*\n"
        f"• *Vốn khởi điểm:* `${initial_cap_per_ex:,.2f} USDT`\n"
        f"• *Số dư khả dụng:* `💵 ${bal_bybit:,.2f} USDT`\n"
        f"• *Realized PnL:* `{bybit_profit:+,.2f} USDT` (`{bybit_roi:+.2f}%`)\n"
        f"• *Vị thế OPEN:* `{len(open_bybit)} lệnh` | *Đã đóng:* `{len(closed_bybit)} lệnh`\n\n"
        "💼 *TỔNG DANH MỤC TOÀN HỆ THỐNG:*\n"
        f"• *Tổng vốn ban đầu:* `${total_initial:,.2f} USDT`\n"
        f"• *Tổng tài sản hiện tại:* `💵 ${bal_total:,.2f} USDT`\n"
        f"• *Tổng Realized PnL:* `{total_profit:+,.2f} USDT` (`{total_roi:+.2f}%`)\n"
        f"• *Tổng vị thế đang chạy:* `{len(open_binance) + len(open_bybit)} lệnh`\n\n"
    )

    # Nếu có cấu hình Testnet thì truy vấn thêm số dư sàn Testnet
    if getattr(config, 'USE_TESTNET', False) or (getattr(config, 'BINANCE_TESTNET_API_KEY', '') and getattr(config, 'BINANCE_TESTNET_SECRET', '')):
        try:
            balances = multi_exchange_trader.check_all_testnet_balances()
            msg += "🏦 *SỐ DƯ SÀN TESTNET THỰC TẾ (API TESTNET):*\n"
            for ex_name, data in balances.items():
                msg += f"• *Sàn {ex_name.upper()}:* "
                if data.get("success"):
                    assets = data.get("assets", {})
                    usdt_info = assets.get("USDT", {})
                    usdt_total = usdt_info.get("total", 0)
                    msg += f"`{usdt_total:,.2f} USDT`\n"
                else:
                    msg += "`Chưa kết nối / Lỗi API`\n"
            msg += "\n"
        except Exception:
            pass

    msg += "💡 *Mẹo:* Bạn có thể gõ `/orders` để xem chi tiết các lệnh, hoặc `/report` để xem thống kê hiệu suất."
    reply_telegram(chat_id, msg)

def handle_orders_command(chat_id: str):
    trades = load_trades()
    open_binance = [t for t in trades if t.get("status") == "OPEN" and t.get("exchange", "binance") == "binance"]
    open_bybit = [t for t in trades if t.get("status") == "OPEN" and t.get("exchange", "binance") == "bybit"]
    closed_trades = [t for t in trades if t.get("status") != "OPEN"]

    msg = "📜 *BÁO CÁO VỊ THẾ & LỊCH SỬ LỆNH (DUAL-EXCHANGE)* 📜\n\n"

    def format_open_trade(t):
        strat_icon = "🎯" if t.get("strategy_type") == "SNIPER_TREND" else "📦"
        strat_label = "SNIPER TREND" if t.get("strategy_type") == "SNIPER_TREND" else "SIDEWAY RANGE"
        pos_sz = t.get('position_size_usdt', getattr(config, 'ORDER_AMOUNT_USDT', 50.0))
        risk_u = t.get('risk_usd', 0.0)
        risk_p = t.get('risk_pct', 0.0)
        size_desc = f"${pos_sz:,.2f} USDT (Rủi ro: ${risk_u:,.2f} ~ {risk_p:.1f}%)" if risk_u > 0 else f"${pos_sz:,.2f} USDT"

        if t.get("strategy_type") == "SIDEWAY_RANGE":
            return (
                f"• {strat_icon} *{t['symbol']}* `[{strat_label}]` (AI: `{t.get('ai_score', 'N/A')}/10`)\n"
                f"  ├─ Khối lượng vào: `{size_desc}`\n"
                f"  ├─ Giá vào (Entry): `${t['entry_price']:,.2f}`\n"
                f"  ├─ TP: `${t.get('take_profit', 0):,.2f}` (+{t.get('tp_pct', 0):.1f}%)\n"
                f"  ├─ Cắt lỗ SL: `${t.get('stop_loss', 0):,.2f}` (-{t.get('sl_pct', 0):.1f}%)\n"
                f"  └─ Mở lúc: `{t.get('opened_at', 'N/A')}`\n"
            )
        else:
            tp1_share_pct = int(t.get('tp1_share', 0.3) * 100)
            tp2_share_pct = int(t.get('tp2_share', 0.7) * 100)
            tp1_status = f"✅ ĐÃ CHỐT {tp1_share_pct}%" if t.get("tp1_hit") else f"${t.get('take_profit_1', t.get('take_profit', 0)):,.2f} (+{t.get('tp1_pct', 0):.1f}%)"
            sl_desc = f"${t.get('stop_loss', 0):,.2f} (🛡️ Hòa vốn Entry)" if t.get("tp1_hit") else f"${t.get('stop_loss', 0):,.2f} (-{t.get('sl_pct', 0):.1f}%)"
            return (
                f"• {strat_icon} *{t['symbol']}* `[{strat_label}]` (AI: `{t.get('ai_score', 'N/A')}/10`)\n"
                f"  ├─ Khối lượng vào: `{size_desc}`\n"
                f"  ├─ Giá vào (Entry): `${t['entry_price']:,.2f}`\n"
                f"  ├─ TP1 (Chốt {tp1_share_pct}%): `{tp1_status}`\n"
                f"  ├─ TP2 (Gồng {tp2_share_pct}%): `${t.get('take_profit_2', t.get('take_profit', 0)):,.2f}` (+{t.get('tp2_pct', t.get('tp_pct', 0)):.1f}%)\n"
                f"  ├─ Cắt lỗ SL: `{sl_desc}`\n"
                f"  └─ Mở lúc: `{t.get('opened_at', 'N/A')}`\n"
            )

    msg += f"🏦 *SÀN BINANCE ({len(open_binance)} vị thế OPEN):*\n"
    if open_binance:
        for t in open_binance:
            msg += format_open_trade(t)
    else:
        msg += "• _Hiện không có vị thế nào đang mở trên Binance._\n"

    msg += f"\n🏦 *SÀN BYBIT ({len(open_bybit)} vị thế OPEN):*\n"
    if open_bybit:
        for t in open_bybit:
            msg += format_open_trade(t)
    else:
        msg += "• _Hiện không có vị thế nào đang mở trên Bybit._\n"

    msg += f"\n🏁 *6 LỆNH ĐÃ ĐÓNG GẦN NHẤT:*\n"
    if closed_trades:
        for t in closed_trades[-6:]:
            ex_tag = t.get('exchange', 'binance').upper()
            status_icon = "🟢" if "TP" in t.get("status", "") or "BE" in t.get("status", "") else "🔴"
            pnl = t.get("pnl_pct", 0)
            pnl_sign = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
            pnl_usd_val = t.get("pnl_usd")
            usd_sign = f" (+${pnl_usd_val:,.2f})" if (pnl_usd_val is not None and pnl_usd_val >= 0) else (f" (-${abs(pnl_usd_val):,.2f})" if pnl_usd_val is not None else "")
            s_type = "🎯 Trend" if t.get("strategy_type") == "SNIPER_TREND" else "📦 Sideway"
            msg += (
                f"{status_icon} `[{ex_tag}]` *{t['symbol']}* ({s_type}) | `{t.get('status')}`\n"
                f"  ├─ PnL: *{pnl_sign}*{usd_sign} | Entry: `${t['entry_price']:,.2f}` -> Đóng: `${t.get('close_price', 0):,.2f}`\n"
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

    status_str = "🟢 AN TOÀN VÀO LỆNH (DUAL)" if market_health.can_open_trades else "🔴 KHÓA LỆNH MUA (RỦI RO CAO)"
    msg = (
        "🌐 *BÁO CÁO MACRO GATEKEEPER* 🌐\n\n"
        f"• *Trạng thái:* *{status_str}*\n"
        f"• *Chế độ thị trường:* `{market_health.market_regime}`\n"
        f"• *Tâm lý F&G:* {market_health.fng_summary}\n"
        f"• *Điểm AI tối thiểu:* `{market_health.min_confidence_score}/10`\n\n"
        f"🧠 *Nhận định BTC:* {market_health.summary}"
    )
    reply_telegram(chat_id, msg)

def update_env_variable(key: str, value: str):
    """Cập nhật hoặc thêm biến môi trường vào file .env để lưu vĩnh viễn trên Server"""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"{key}={value}\n")
        except Exception as e:
            print(f"❌ Lỗi ghi file .env: {e}")
        return

    lines = []
    found = False
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        print(f"❌ Lỗi cập nhật file .env: {e}")

def handle_risk_command(chat_id: str, tokens: list):
    """Xử lý lệnh xem và điều chỉnh % rủi ro mỗi lệnh theo ATR"""
    current_mode = getattr(config, "POSITION_SIZING_MODE", "ATR_RISK")
    current_risk_pct = getattr(config, "RISK_PER_TRADE_PCT", 0.015) * 100
    max_cap = getattr(config, "MAX_POSITION_CAP_PCT", 0.25) * 100

    if len(tokens) == 1:
        msg = (
            "🎯 *QUẢN TRỊ RỦI RO POSITION SIZING (ATR RISK)* 🎯\n\n"
            f"• *Chế độ hiện tại:* `{current_mode}`\n"
            f"• *Mức rủi ro mỗi lệnh:* `{current_risk_pct:.1f}%` tài khoản\n"
            f"• *Khống chế trần tối đa:* `{max_cap:.0f}%` tài khoản / lệnh\n\n"
            "💡 *Cách hoạt động:*\n"
            "Khối lượng vào lệnh sẽ tự động tính theo công thức:\n"
            "`Khối lượng = (Tài khoản * Risk %) / SL %`\n"
            "Nếu dính SL, bạn luôn chỉ mất đúng mức rủi ro đã định.\n\n"
            "👉 *Cách đổi:* Gõ `/risk <số_%>` (Ví dụ: `/risk 1.5` hoặc `/risk 2.0`)"
        )
        reply_telegram(chat_id, msg)
        return

    try:
        val_str = tokens[1].replace("%", "").strip()
        val = float(val_str)
        if val < 0.1 or val > 10.0:
            reply_telegram(chat_id, "⚠️ Mức rủi ro mỗi lệnh hợp lệ từ 0.1% đến 10.0% tài khoản.")
            return

        risk_decimal = val / 100.0
        config.POSITION_SIZING_MODE = "ATR_RISK"
        config.RISK_PER_TRADE_PCT = risk_decimal

        update_env_variable("POSITION_SIZING_MODE", "ATR_RISK")
        update_env_variable("RISK_PER_TRADE_PCT", str(risk_decimal))

        msg = (
            "✅ *CẬP NHẬT MỨC RỦI RO ATR THÀNH CÔNG!* ✅\n\n"
            f"• *Chế độ:* `ATR_RISK (Động theo biến động)`\n"
            f"• *Mức rủi ro mới:* `{val:.1f}% tài khoản / lệnh`\n"
            f"• *Trần an toàn:* Tối đa 25% vốn / lệnh\n\n"
            "🎯 Mọi vị thế mới sẽ tự động tính toán khối lượng theo mức rủi ro này!"
        )
        reply_telegram(chat_id, msg)
    except ValueError:
        reply_telegram(chat_id, f"❌ Giá trị `{tokens[1]}` không hợp lệ. Vui lòng nhập số, ví dụ: `/risk 1.5`.")

def handle_amount_command(chat_id: str, tokens: list):
    current_mode = getattr(config, "POSITION_SIZING_MODE", "ATR_RISK")
    current_amt = getattr(config, "ORDER_AMOUNT_USDT", 50.0)

    if len(tokens) == 1:
        mode_desc = f"`ATR_RISK ({getattr(config, 'RISK_PER_TRADE_PCT', 0.015)*100:.1f}% vốn/lệnh)`" if current_mode == "ATR_RISK" else f"`FIXED (${current_amt:,.2f} USDT/lệnh)`"
        msg = (
            "💵 *CẤU HÌNH VỐN ĐI LỆNH (POSITION SIZING)* 💵\n\n"
            f"• *Chế độ hiện tại:* {mode_desc}\n"
            f"• *Số tiền cố định dự phòng:* `${current_amt:,.2f} USDT`\n\n"
            "💡 *Cách thay đổi:*\n"
            "• Gõ `/risk <số_%>` để dùng Quản trị rủi ro ATR (Khuyên dùng: `/risk 1.5`)\n"
            "• Gõ `/amount <số_tiền>` để chuyển sang đi tiền cố định (VD: `/amount 100`)"
        )
        reply_telegram(chat_id, msg)
        return

    try:
        new_amt_str = tokens[1].replace("$", "").replace(",", "").strip()
        new_amt = float(new_amt_str)
        if new_amt <= 0:
            reply_telegram(chat_id, "❌ Số tiền vào lệnh phải lớn hơn 0 USDT.")
            return
        if new_amt > 100000:
            reply_telegram(chat_id, "⚠️ Số tiền vào lệnh quá lớn (> $100,000). Vui lòng kiểm tra lại.")
            return

        config.POSITION_SIZING_MODE = "FIXED"
        config.ORDER_AMOUNT_USDT = new_amt

        update_env_variable("POSITION_SIZING_MODE", "FIXED")
        update_env_variable("ORDER_AMOUNT_USDT", str(new_amt))

        msg = (
            "✅ *CHUYỂN SANG ĐI VỐN CỐ ĐỊNH THÀNH CÔNG!* ✅\n\n"
            f"• *Chế độ:* `FIXED (Cố định)`\n"
            f"• *Số tiền mới:* `${new_amt:,.2f} USDT / lệnh`\n\n"
            "🎯 Từ chu kỳ tới, bot sẽ vào đúng số tiền cố định này cho mỗi lệnh."
        )
        reply_telegram(chat_id, msg)
    except ValueError:
        reply_telegram(chat_id, f"❌ Giá trị `{tokens[1]}` không hợp lệ. Vui lòng nhập số, ví dụ: `/amount 100`.")

def handle_status_command(chat_id: str):
    uptime_delta = datetime.now() - _start_time
    hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    model_name = getattr(config, 'GEMINI_PRIMARY_MODEL', 'gemini-3.6-flash')
    fallback_name = getattr(config, 'GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')
    dual_mode = "BẬT (Trend + Sideway)" if getattr(config, 'ENABLE_DUAL_REGIME', True) else "TẮT (Chỉ Trend)"
    sizing_mode = getattr(config, 'POSITION_SIZING_MODE', 'ATR_RISK')
    if sizing_mode == "ATR_RISK":
        sizing_desc = f"ATR_RISK ({getattr(config, 'RISK_PER_TRADE_PCT', 0.015)*100:.1f}%/lệnh | Trần {getattr(config, 'MAX_POSITION_CAP_PCT', 0.25)*100:.0f}%)"
    else:
        sizing_desc = f"FIXED (${getattr(config, 'ORDER_AMOUNT_USDT', 50.0):,.2f} USDT/lệnh)"

    exchanges_str = ", ".join([e.upper() for e in getattr(config, 'PAPER_EXCHANGES', ['binance', 'bybit'])])
    cap_per_ex = getattr(config, 'INITIAL_PAPER_BALANCE_PER_EXCHANGE', 500.0)

    msg = (
        "📊 *THÔNG TIN HỆ THỐNG BOT (DUAL-EXCHANGE)* 📊\n\n"
        f"• *Chế độ giao dịch:* `Dual-Exchange Parallel Paper Trading`\n"
        f"  ├─ 🏦 *Sàn chạy song song:* `{exchanges_str}`\n"
        f"  └─ 💵 *Vốn giả lập:* `${cap_per_ex:,.0f} USDT / sàn` (Tổng `$1,000 USDT`)\n"
        f"• *Chiến lược:* `DUAL REGIME: {dual_mode}`\n"
        f"  ├─ 🎯 *Trend:* `30% TP1 / 70% TP2 (SL ATR tối ưu)`\n"
        f"  └─ 📦 *Sideway:* `Bắt đáy Lower BB + RSI <= 38 (TP SMA20)`\n"
        f"• *Quản trị Vốn:* `{sizing_desc}`\n"
        f"• *Thời gian chạy (Uptime):* `{hours}h {minutes}m {seconds}s`\n"
        f"• *Chu kỳ quét:* Mỗi `{config.SLEEP_INTERVAL_SECONDS // 60} phút`\n"
        f"• *Danh mục theo dõi:* `{', '.join(config.SYMBOLS)}`\n"
        f"• *Ngưỡng duyệt Gemini AI:* `>= {getattr(config, 'MIN_AI_CONFIDENCE_SCORE', 8)}/10 điểm`\n"
        f"• *Model AI:* `{model_name}` (Dự phòng: `{fallback_name}`)\n\n"
        "✅ *Trạng thái: Hoạt động bình thường 24/7!*"
    )
    reply_telegram(chat_id, msg)

def handle_report_command(chat_id: str):
    trades = load_trades()
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    closed_trades = [t for t in trades if t.get("status") != "OPEN"]

    if not closed_trades:
        info = "📊 *BÁO CÁO HIỆU SUẤT PAPER TRADING (DUAL-EXCHANGE)* 📊\n\n"
        if open_trades:
            info += (
                f"• _Chưa có lệnh nào đóng (TP/SL) để tính toán thống kê PnL._\n"
                f"• Hiện đang có *{len(open_trades)} vị thế đang mở* trên Binance & Bybit.\n\n"
                f"👉 Gõ `/orders` để theo dõi các lệnh đang chạy!"
            )
        else:
            info += (
                "• _Chưa có lịch sử giao dịch nào được ghi nhận._\n"
                "• Bot đang theo dõi và quét thị trường song song cả Binance & Bybit.\n\n"
                "👉 Gõ `/scan` để yêu cầu bot quét thị trường ngay lập tức!"
            )
        reply_telegram(chat_id, info)
        return

    def calc_stats(trade_list):
        if not trade_list:
            return {
                "count": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "total_pnl": 0.0, "total_usd": 0.0, "avg_win": 0.0, "avg_loss": 0.0
            }
        wins = [t for t in trade_list if float(t.get("pnl_pct", 0)) > 0]
        losses = [t for t in trade_list if float(t.get("pnl_pct", 0)) <= 0]
        count = len(trade_list)
        win_rate = (len(wins) / count) * 100.0 if count > 0 else 0.0
        total_pnl = sum(float(t.get("pnl_pct", 0)) for t in trade_list)
        total_usd = sum(float(t.get("pnl_usd", 0.0)) for t in trade_list)
        avg_win = sum(float(t.get("pnl_pct", 0)) for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(float(t.get("pnl_pct", 0)) for t in losses) / len(losses) if losses else 0.0
        return {
            "count": count, "wins": len(wins), "losses": len(losses), "win_rate": win_rate,
            "total_pnl": total_pnl, "total_usd": total_usd, "avg_win": avg_win, "avg_loss": avg_loss
        }

    binance_trades = [t for t in closed_trades if t.get("exchange", "binance") == "binance"]
    bybit_trades = [t for t in closed_trades if t.get("exchange", "binance") == "bybit"]

    b_stat = calc_stats(binance_trades)
    by_stat = calc_stats(bybit_trades)
    tot_stat = calc_stats(closed_trades)

    msg = (
        "📊 *BÁO CÁO TỔNG HỢP HIỆU SUẤT (DUAL-EXCHANGE)* 📊\n\n"
        "🏦 *SÀN BINANCE ($500 khởi điểm):*\n"
        f"• *Lệnh đã đóng:* `{b_stat['count']} lệnh` | *Thắng:* `{b_stat['wins']}` | *Thua:* `{b_stat['losses']}`\n"
        f"• *Tỷ lệ thắng (Win Rate):* `🏆 {b_stat['win_rate']:.1f}%`\n"
        f"• *Realized PnL:* *{b_stat['total_pnl']:+.2f}%* (*{b_stat['total_usd']:+,.2f} USDT*)\n"
        f"• *Lãi TB/WIN:* `+{b_stat['avg_win']:.2f}%` | *Lỗ TB/LOSS:* `{b_stat['avg_loss']:.2f}%`\n\n"
        "🏦 *SÀN BYBIT ($500 khởi điểm):*\n"
        f"• *Lệnh đã đóng:* `{by_stat['count']} lệnh` | *Thắng:* `{by_stat['wins']}` | *Thua:* `{by_stat['losses']}`\n"
        f"• *Tỷ lệ thắng (Win Rate):* `🏆 {by_stat['win_rate']:.1f}%`\n"
        f"• *Realized PnL:* *{by_stat['total_pnl']:+.2f}%* (*{by_stat['total_usd']:+,.2f} USDT*)\n"
        f"• *Lãi TB/WIN:* `+{by_stat['avg_win']:.2f}%` | *Lỗ TB/LOSS:* `{by_stat['avg_loss']:.2f}%`\n\n"
        "💼 *TỔNG DANH MỤC TOÀN HỆ THỐNG ($1,000 khởi điểm):*\n"
        f"• *Tổng số lệnh đã đóng:* `{tot_stat['count']} lệnh`\n"
        f"• *Win Rate tổng:* `🏆 {tot_stat['win_rate']:.1f}%` ({tot_stat['wins']}W / {tot_stat['losses']}L)\n"
        f"• *Tổng Lợi nhuận:* *{tot_stat['total_usd']:+,.2f} USDT* (*{tot_stat['total_pnl']:+.2f}%*)\n\n"
        "📁 _Toàn bộ dữ liệu được cập nhật thời gian thực từ Binance & Bybit._"
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

    elif cmd in ['/risk', '/ruiro', 'risk', 'ruiro']:
        handle_risk_command(chat_id, tokens)

    elif cmd in ['/amount', '/setamount', '/tien', '/von', 'amount', 'setamount', 'tien', 'von']:
        handle_amount_command(chat_id, tokens)

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

    print("🎮 [Telegram Commander] Đã kích hoạt bộ lắng nghe lệnh (Tối ưu RAM ThreadPool)!")
    offset = None
    poll_count = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"timeout": 20}
            if offset:
                params["offset"] = offset

            res = _http_session.get(url, params=params, timeout=25)
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

                        # Xử lý lệnh qua ThreadPool thay vì spawn thread mới
                        _thread_pool.submit(process_message, sender_chat_id, msg_text, scan_callback)

            # Cứ mỗi 50 chu kỳ polling (~15 phút), thu hồi RAM arena của thread
            poll_count += 1
            if poll_count >= 50:
                poll_count = 0
                try:
                    libc = ctypes.CDLL("libc.so.6")
                    libc.malloc_trim(0)
                except Exception:
                    pass

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
