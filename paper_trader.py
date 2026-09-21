import json
import os
import time
from datetime import datetime, timezone
import ccxt
import config
import multi_exchange_trader

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

def open_paper_trade(symbol: str, entry_price: float, sl_pct: float = None, tp_pct: float = None,
                     ai_score: int = 0, stop_loss: float = None, take_profit: float = None,
                     macro_regime: str = None, fng_summary: str = None, ai_reasoning: str = None):
    """Mở một lệnh mua mô phỏng mới với SL/TP động theo ATR hoặc % và lưu đầy đủ thông số"""
    trades = load_trades()

    # Kiểm tra xem coin này đã có lệnh nào đang chạy chưa (tránh trùng lệnh)
    for t in trades:
        if t['symbol'] == symbol and t['status'] == 'OPEN':
            return None # Đã có lệnh đang mở, không vào thêm

    # Xác định mức giá Cắt lỗ và Chốt lời
    calculated_sl = stop_loss if stop_loss is not None else entry_price * (1 - (sl_pct if sl_pct is not None else config.STOP_LOSS_PCT))
    calculated_tp = take_profit if take_profit is not None else entry_price * (1 + (tp_pct if tp_pct is not None else config.TAKE_PROFIT_PCT))
    actual_sl_pct = (entry_price - calculated_sl) / entry_price * 100
    actual_tp_pct = (calculated_tp - entry_price) / entry_price * 100

    trade_id = f"{symbol.replace('/', '_')}_{int(time.time())}"
    opened_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    # Đặt lệnh Mua song song lên tất cả các sàn Testnet được kích hoạt (nếu bật USE_TESTNET)
    exchange_orders = {}
    if getattr(config, "USE_TESTNET", False):
        usdt_amt = getattr(config, "ORDER_AMOUNT_USDT", 50.0)
        multi_res = multi_exchange_trader.place_multi_market_buy(symbol, usdt_amount=usdt_amt)
        for ex_name, o_data in multi_res.items():
            if o_data.get('success'):
                exchange_orders[ex_name] = o_data.get('order_id')

    new_trade = {
        "id": trade_id,
        "symbol": symbol,
        "entry_price": round(entry_price, 4),
        "stop_loss": round(calculated_sl, 4),
        "take_profit": round(calculated_tp, 4),
        "sl_pct": round(actual_sl_pct, 2),
        "tp_pct": round(actual_tp_pct, 2),
        "ai_score": ai_score,
        "macro_regime": macro_regime or "N/A",
        "fng_summary": fng_summary or "N/A",
        "ai_reasoning": ai_reasoning or "N/A",
        "status": "OPEN",
        "opened_at": opened_at,
        "exchange_orders": exchange_orders
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
                pnl_pct = (current_price - t['entry_price']) / t['entry_price'] * 100
                t['pnl_pct'] = round(pnl_pct, 2)
                t['closed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

                # Bán coin trên tất cả các sàn Testnet được kích hoạt
                if getattr(config, "USE_TESTNET", True):
                    sell_results = multi_exchange_trader.place_multi_market_sell(symbol)
                    t['exchange_close_orders'] = {
                        k: v.get('order_id') for k, v in sell_results.items() if v.get('success')
                    }

                closed_events.append((t, "✅ CHỐT LỜI (TAKE PROFIT)"))

            # Kiểm tra dính Stop Loss
            elif current_price <= t['stop_loss']:
                t['status'] = 'CLOSED_SL'
                t['close_price'] = current_price
                pnl_pct = (current_price - t['entry_price']) / t['entry_price'] * 100
                t['pnl_pct'] = round(pnl_pct, 2)
                t['closed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

                # Bán coin trên tất cả các sàn Testnet được kích hoạt
                if getattr(config, "USE_TESTNET", True):
                    sell_results = multi_exchange_trader.place_multi_market_sell(symbol)
                    t['exchange_close_orders'] = {
                        k: v.get('order_id') for k, v in sell_results.items() if v.get('success')
                    }

                closed_events.append((t, "❌ CẮT LỖ (STOP LOSS)"))

        except Exception as e:
            print(f"❌ Lỗi lấy giá {symbol}: {e}")

    if closed_events:
        save_trades(trades)

    return closed_events