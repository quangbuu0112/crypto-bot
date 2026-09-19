"""
Module điều phối giao dịch đa sàn (Multi-Exchange Trader).
Cho phép bot kết nối và đặt lệnh song song trên nhiều sàn cùng lúc (Binance, Bybit).
"""

import ccxt
import config

def get_exchange_client(exchange_name: str):
    """Khởi tạo CCXT client cho sàn tương ứng ở chế độ Testnet/Sandbox"""
    name = exchange_name.lower().strip()

    if name == 'binance':
        client = ccxt.binance({
            'apiKey': config.BINANCE_TESTNET_API_KEY,
            'secret': config.BINANCE_TESTNET_SECRET,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
            }
        })
        client.set_sandbox_mode(True)
        return client

    elif name == 'bybit':
        client = ccxt.bybit({
            'apiKey': config.BYBIT_TESTNET_API_KEY,
            'secret': config.BYBIT_TESTNET_SECRET,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })
        client.set_sandbox_mode(True)
        return client

    else:
        raise ValueError(f"Sàn {exchange_name} chưa được hỗ trợ.")

def check_all_testnet_balances() -> dict:
    """Kiểm tra số dư trên toàn bộ các sàn đang kích hoạt"""
    results = {}
    active_exchanges = getattr(config, 'ACTIVE_TESTNET_EXCHANGES', ['binance', 'bybit'])

    for name in active_exchanges:
        try:
            client = get_exchange_client(name)
            balance = client.fetch_balance()
            assets = {}
            for curr, val in balance['total'].items():
                if val and val > 0:
                    assets[curr] = {
                        'free': balance['free'].get(curr, 0),
                        'total': val
                    }
            results[name] = {"success": True, "assets": assets}
        except Exception as e:
            results[name] = {"success": False, "error": str(e)}

    return results

def place_multi_market_buy(symbol: str, usdt_amount: float = None) -> dict:
    """
    Gửi lệnh MUA MARKET đồng thời lên tất cả các sàn được kích hoạt
    """
    amount_to_spend = usdt_amount if usdt_amount else getattr(config, 'ORDER_AMOUNT_USDT', 50.0)
    active_exchanges = getattr(config, 'ACTIVE_TESTNET_EXCHANGES', ['binance', 'bybit'])
    results = {}

    for name in active_exchanges:
        try:
            client = get_exchange_client(name)
            client.load_markets()

            ticker = client.fetch_ticker(symbol)
            price = ticker['last']
            raw_amount = amount_to_spend / price
            amount = float(client.amount_to_precision(symbol, raw_amount))

            print(f"🚀 [{name.upper()} TESTNET] Gửi lệnh MUA MARKET {amount} {symbol} (~${amount_to_spend:.1f} USDT)...")
            order = client.create_market_buy_order(symbol, amount)

            results[name] = {
                "success": True,
                "order_id": order.get('id'),
                "amount": amount,
                "price": price,
                "cost": round(amount * price, 2),
                "status": order.get('status')
            }
            print(f"✅ [{name.upper()} TESTNET] Khớp MUA thành công! Order ID: {order.get('id')}")
        except Exception as e:
            print(f"❌ [{name.upper()} TESTNET] Lỗi đặt lệnh Mua: {e}")
            results[name] = {"success": False, "error": str(e)}

    return results

def place_multi_market_sell(symbol: str) -> dict:
    """
    Gửi lệnh BÁN MARKET trên tất cả các sàn để chốt lời / cắt lỗ
    """
    active_exchanges = getattr(config, 'ACTIVE_TESTNET_EXCHANGES', ['binance', 'bybit'])
    results = {}
    base_asset = symbol.split('/')[0]

    for name in active_exchanges:
        try:
            client = get_exchange_client(name)
            client.load_markets()

            balance = client.fetch_balance()
            free_amount = balance['free'].get(base_asset, 0)
            formatted_amount = float(client.amount_to_precision(symbol, free_amount))

            if formatted_amount <= 0:
                results[name] = {"success": False, "error": f"Số dư {base_asset} = 0"}
                continue

            print(f"🔻 [{name.upper()} TESTNET] Gửi lệnh BÁN MARKET {formatted_amount} {symbol}...")
            order = client.create_market_sell_order(symbol, formatted_amount)

            results[name] = {
                "success": True,
                "order_id": order.get('id'),
                "amount": formatted_amount,
                "status": order.get('status')
            }
            print(f"✅ [{name.upper()} TESTNET] Khớp BÁN thành công! Order ID: {order.get('id')}")
        except Exception as e:
            print(f"❌ [{name.upper()} TESTNET] Lỗi đặt lệnh Bán: {e}")
            results[name] = {"success": False, "error": str(e)}

    return results

if __name__ == "__main__":
    print("==================================================")
    print("🌐 KIỂM TRA SỐ DƯ TOÀN BỘ CÁC SÀN ĐANG KÍCH HOẠT")
    print("==================================================")
    balances = check_all_testnet_balances()
    for ex, data in balances.items():
        print(f"\n📌 SÀN: {ex.upper()} TESTNET")
        if data['success']:
            if not data['assets']:
                print("   (Ví trống hoặc chưa nạp Testnet USDT)")
            for c in ['USDT', 'BTC', 'ETH', 'SOL', 'BNB', 'XRP']:
                if c in data['assets']:
                    info = data['assets'][c]
                    print(f"   • {c:<5}: {info['free']:>12.4f} khả dụng")
        else:
            print(f"   ❌ Lỗi: {data['error']}")
