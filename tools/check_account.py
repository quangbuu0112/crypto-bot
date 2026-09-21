"""
Script kiểm tra Số dư (Balance) và Lịch sử giao dịch (Trade History)
trên cả Binance Testnet, Bybit Testnet và nhật ký Paper Trading.

Cách dùng:
    python tools/check_account.py
"""

import os
import sys
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
import ccxt

def print_header(title: str):
    print("\n" + "=" * 65)
    print(f"📊 {title}")
    print("=" * 65)

def check_binance_testnet():
    print_header("1. BINANCE SPOT TESTNET")
    api_key = str(config.BINANCE_TESTNET_API_KEY or "").strip()
    secret = str(config.BINANCE_TESTNET_SECRET or "").strip()

    if not api_key or not secret:
        print("⚠️ Chưa cấu hình BINANCE_TESTNET_API_KEY / SECRET trong .env")
        return

    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot', 'adjustForTimeDifference': True}
        })
        exchange.set_sandbox_mode(True)

        # 1. Số dư ví
        balance = exchange.fetch_balance()
        print("💰 SỐ DƯ TÀI KHOẢN:")
        has_asset = False
        for curr, total in balance['total'].items():
            if total > 0.0001:
                has_asset = True
                free = balance['free'].get(curr, 0)
                used = balance['used'].get(curr, 0)
                print(f"   • {curr:8s}: Tổng = {total:14.4f} | Khả dụng = {free:14.4f} | Đang khóa = {used:10.4f}")
        if not has_asset:
            print("   (Ví trống hoặc chưa có số dư)")

        # 2. Lịch sử lệnh gần nhất
        print("\n📜 LỊCH SỬ LỆNH KHỚP GẦN NHẤT (5 coin theo dõi):")
        has_trades = False
        for symbol in config.SYMBOLS:
            try:
                orders = exchange.fetch_orders(symbol, limit=5)
                for o in orders:
                    has_trades = True
                    t_str = datetime.fromtimestamp(o['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S') if o.get('timestamp') else "N/A"
                    side = o.get('side', '').upper()
                    status = o.get('status', '').upper()
                    price = o.get('price') or o.get('average') or 0.0
                    amount = o.get('amount') or 0.0
                    cost = o.get('cost') or (price * amount)
                    print(f"   [{t_str}] {symbol:10s} | {side:4s} | Trạng thái: {status:8s} | SL: {amount:.4f} | Giá: ${price:,.2f} | Tổng: ${cost:,.2f}")
            except Exception:
                pass
        if not has_trades:
            print("   (Chưa có lệnh nào được khớp trên sàn)")

    except Exception as e:
        print(f"❌ Lỗi kết nối Binance Testnet: {e}")

def check_bybit_testnet():
    print_header("2. BYBIT SPOT TESTNET")
    api_key = str(config.BYBIT_TESTNET_API_KEY or "").strip()
    secret = str(config.BYBIT_TESTNET_SECRET or "").strip()

    if not api_key or not secret:
        print("⚠️ Chưa cấu hình BYBIT_TESTNET_API_KEY / SECRET trong .env")
        return

    try:
        exchange = ccxt.bybit({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot', 'adjustForTimeDifference': True}
        })
        exchange.set_sandbox_mode(True)

        balance = exchange.fetch_balance()
        print("💰 SỐ DƯ TÀI KHOẢN:")
        has_asset = False
        for curr, total in balance['total'].items():
            if total > 0.0001:
                has_asset = True
                free = balance['free'].get(curr, 0)
                used = balance['used'].get(curr, 0)
                print(f"   • {curr:8s}: Tổng = {total:14.4f} | Khả dụng = {free:14.4f} | Đang khóa = {used:10.4f}")
        if not has_asset:
            print("   (Ví trống hoặc chưa có số dư)")

    except Exception as e:
        print(f"❌ Lỗi kết nối Bybit Testnet: {e}")

def check_paper_trades():
    print_header("3. NHẬT KÝ LỆNH BOT (paper_trades.json)")
    path = os.path.join(BASE_DIR, "paper_trades.json")
    if not os.path.exists(path):
        print("📁 Chưa có file paper_trades.json")
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            trades = json.load(f)

        if not trades:
            print("📭 Chưa có lệnh nào trong lịch sử.")
            return

        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        closed_trades = [t for t in trades if t.get("status") != "OPEN"]

        print(f"📌 ĐANG CHẠY ({len(open_trades)} lệnh):")
        for t in open_trades:
            print(f"   • [{t.get('opened_at', 'N/A')}] {t['symbol']} | Entry: ${t['entry_price']:,.2f} | TP: ${t.get('take_profit', 0):,.2f} | SL: ${t.get('stop_loss', 0):,.2f} | AI Score: {t.get('ai_score', 'N/A')}/10")

        print(f"\n🏁 ĐÃ ĐÓNG ({len(closed_trades)} lệnh gần nhất):")
        for t in closed_trades[-10:]:
            status = t.get("status")
            pnl = t.get("pnl_pct", 0)
            pnl_str = f"+{pnl:.2f}%" if pnl >= 0 else f"{pnl:.2f}%"
            print(f"   • [{t.get('closed_at', t.get('opened_at', 'N/A'))}] {t['symbol']:10s} | {status:10s} | Entry: ${t['entry_price']:,.2f} | Close: ${t.get('close_price', 0):,.2f} | PnL: {pnl_str}")

    except Exception as e:
        print(f"❌ Lỗi đọc paper_trades.json: {e}")

if __name__ == "__main__":
    print(f"⏰ Thời gian kiểm tra: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    check_binance_testnet()
    check_bybit_testnet()
    check_paper_trades()
    print("\n" + "=" * 65 + "\n")
