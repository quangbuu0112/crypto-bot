import json
import os
import ccxt

TRADES_FILE = "paper_trades.json"
exchange = ccxt.binance({'enableRateLimit': True})

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    try:
        with open(TRADES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_trades(trades):
    with open(TRADES_FILE, 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)

def open_paper_trade(symbol: str, entry_price: float, sl_pct: float = 0.01, tp_pct: float = 0.015, ai_score: int = 0):
    """Mở một lệnh mua mô phỏng mới"""
    trades = load_trades()
    
    # Kiểm tra xem coin này đã có lệnh nào đang chạy chưa (tránh trùng lệnh)
    for t in trades:
        if t['symbol'] == symbol and t['status'] == 'OPEN':
            return None # Đã có lệnh đang mở, không vào thêm
            
    trade_id = f"{symbol}_{int(os.times().elapsed)}"
    new_trade = {
        "id": trade_id,
        "symbol": symbol,
        "entry_price": entry_price,
        "stop_loss": entry_price * (1 - sl_pct),
        "take_profit": entry_price * (1 + tp_pct),
        "ai_score": ai_score,
        "status": "OPEN",
        "opened_at": os.popen('date').read().strip() if os.name != 'nt' else ""
    }
    trades.append(new_trade)
    save_trades(trades)
    return new_trade

def check_and_update_paper_trades():
    """Quét giá hiện tại từ Binance để đóng các lệnh đụng SL hoặc TP"""
    trades = load_trades()
    open_trades = [t for t in trades if t['status'] == 'OPEN']
    
    if not open_trades:
        return []

    closed_events = []

    for t in open_trades:
        symbol = t['symbol']
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']

            # Kiểm tra dính Take Profit
            if current_price >= t['take_profit']:
                t['status'] = 'CLOSED_TP'
                t['close_price'] = current_price
                t['pnl_pct'] = +1.5
                closed_events.append((t, "✅ CHỐT LỜI (TAKE PROFIT)"))

            # Kiểm tra dính Stop Loss
            elif current_price <= t['stop_loss']:
                t['status'] = 'CLOSED_SL'
                t['close_price'] = current_price
                t['pnl_pct'] = -1.0
                closed_events.append((t, "❌ CẮT LỖ (STOP LOSS)"))

        except Exception as e:
            print(f"❌ Lỗi lấy giá {symbol}: {e}")

    if closed_events:
        save_trades(trades)

    return closed_events