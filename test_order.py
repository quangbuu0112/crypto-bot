import testnet_trader

print("==================================================")
print("💰 KIỂM TRA SỐ DƯ CÁC ĐỒNG COIN CHÍNH TRÊN TESTNET")
print("==================================================")
res = testnet_trader.check_testnet_balance()
if res['success']:
    for c in ['USDT', 'BTC', 'ETH', 'SOL', 'BNB', 'XRP']:
        info = res['assets'].get(c, {'free': 0, 'total': 0})
        print(f"  • {c:<5}: {info['free']:>12.4f} khả dụng (Tổng: {info['total']:>12.4f})")
else:
    print("Lỗi:", res['error'])

print("\n==================================================")
print("🚀 TIẾN HÀNH THỬ ĐẶT LỆNH MUA MARKET (15 USDT BTC/USDT)")
print("==================================================")
buy_res = testnet_trader.place_testnet_market_buy('BTC/USDT', usdt_amount=15.0)
print("Kết quả đặt lệnh Mua:", buy_res)

print("\n==================================================")
print("💰 KIỂM TRA LẠI SỐ DƯ SAU KHI KHỚP LỆNH")
print("==================================================")
res2 = testnet_trader.check_testnet_balance()
if res2['success']:
    for c in ['USDT', 'BTC']:
        info = res2['assets'].get(c, {'free': 0, 'total': 0})
        print(f"  • {c:<5}: {info['free']:>12.6f} khả dụng")
