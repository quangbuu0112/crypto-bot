"""
Module quản lý giao dịch trực tiếp trên Binance Spot Testnet.
Hỗ trợ:
  - Kiểm tra số dư ví (Balance)
  - Lấy giá thị trường (Ticker)
  - Chuẩn hóa khối lượng theo quy chuẩn LOT_SIZE của sàn
  - Đặt lệnh Mua Market (Market Buy)
  - Đặt lệnh Bán Market (Market Sell)
  - Đặt lệnh Chốt lời (Limit TP) / Cắt lỗ (Stop Loss)
"""

import ccxt
import config

def get_testnet_exchange():
    """Khởi tạo CCXT kết nối tới Binance Spot Testnet"""
    api_key = str(config.BINANCE_TESTNET_API_KEY).strip() if config.BINANCE_TESTNET_API_KEY else ""
    secret = str(config.BINANCE_TESTNET_SECRET).strip() if config.BINANCE_TESTNET_SECRET else ""

    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
            'adjustForTimeDifference': True, # Tự động đồng bộ lệch giờ máy tính
        }
    })
    exchange.set_sandbox_mode(True) # Chuyển sang https://testnet.binance.vision
    return exchange

def check_testnet_balance():
    """Kiểm tra số dư trên Binance Spot Testnet"""
    exchange = get_testnet_exchange()
    try:
        balance = exchange.fetch_balance()
        assets = {}
        for curr, val in balance['total'].items():
            if val > 0:
                assets[curr] = {
                    'free': balance['free'].get(curr, 0),
                    'used': balance['used'].get(curr, 0),
                    'total': val
                }
        return {"success": True, "assets": assets}
    except Exception as e:
        return {"success": False, "error": str(e)}

def place_testnet_market_buy(symbol: str, usdt_amount: float = 20.0):
    """
    Đặt lệnh mua Market trên Binance Testnet với số tiền USDT chỉ định.
    Tự động chuẩn hóa khối lượng theo precision của sàn.
    """
    exchange = get_testnet_exchange()
    try:
        # 1. Tải thông tin thị trường để lấy quy chuẩn LOT_SIZE
        exchange.load_markets()
        market = exchange.market(symbol)

        # 2. Lấy giá hiện tại
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']

        # 3. Tính khối lượng coin cần mua
        raw_amount = usdt_amount / current_price

        # 4. Chuẩn hóa theo quy chuẩn của Binance
        amount = float(exchange.amount_to_precision(symbol, raw_amount))

        # Kiểm tra giá trị tối thiểu (Min Notional >= $10)
        notional = amount * current_price
        if notional < 10.0:
            return {"success": False, "error": f"Giá trị lệnh ${notional:.2f} nhỏ hơn mức tối thiểu 10 USDT của sàn."}

        print(f"🚀 Đang gửi lệnh MUA MARKET: {amount} {symbol} (~${notional:.2f} USDT)...")
        order = exchange.create_market_buy_order(symbol, amount)

        return {
            "success": True,
            "order_id": order.get('id'),
            "symbol": symbol,
            "amount": amount,
            "price": current_price,
            "cost": notional,
            "status": order.get('status')
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def place_testnet_market_sell(symbol: str, amount: float = None):
    """
    Bán toàn bộ hoặc một lượng coin nhất định theo giá Market trên Testnet.
    """
    exchange = get_testnet_exchange()
    try:
        exchange.load_markets()
        base_asset = symbol.split('/')[0]

        if amount is None:
            # Bán toàn bộ số dư khả dụng của coin đó
            balance = exchange.fetch_balance()
            amount = balance['free'].get(base_asset, 0)

        formatted_amount = float(exchange.amount_to_precision(symbol, amount))
        if formatted_amount <= 0:
            return {"success": False, "error": f"Không đủ số dư {base_asset} để bán."}

        print(f"🔻 Đang gửi lệnh BÁN MARKET: {formatted_amount} {symbol}...")
        order = exchange.create_market_sell_order(symbol, formatted_amount)
        return {
            "success": True,
            "order_id": order.get('id'),
            "symbol": symbol,
            "amount": formatted_amount,
            "status": order.get('status')
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import sys
    print("==================================================")
    print("🧪 KIỂM TRA KẾT NỐI BINANCE SPOT TESTNET")
    print("==================================================")
    res = check_testnet_balance()
    if res['success']:
        print("✅ Kết nối thành công!")
        print("💰 Số dư ví Testnet:")
        for coin, data in res['assets'].items():
            print(f"   • {coin:<6}: {data['free']:>12.4f} (Khả dụng) | Tổng: {data['total']:>12.4f}")
    else:
        print("❌ Kết nối thất bại:")
        print("   Lỗi:", res['error'])
