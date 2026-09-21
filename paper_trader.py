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
                     take_profit_1: float = None, take_profit_2: float = None,
                     tp1_pct: float = None, tp2_pct: float = None,
                     macro_regime: str = None, fng_summary: str = None, ai_reasoning: str = None):
    """Mở một lệnh mua mô phỏng mới theo chuẩn Sniper Quality với Partial TP1 & TP2"""
    trades = load_trades()

    # Kiểm tra xem coin này đã có lệnh nào đang chạy chưa (tránh trùng lệnh)
    for t in trades:
        if t['symbol'] == symbol and t['status'] == 'OPEN':
            return None

    calculated_sl = stop_loss if stop_loss is not None else entry_price * (1 - (sl_pct if sl_pct is not None else config.STOP_LOSS_PCT))
    calculated_tp2 = take_profit_2 if take_profit_2 is not None else (take_profit if take_profit is not None else entry_price * (1 + config.TAKE_PROFIT_PCT))
    calculated_tp1 = take_profit_1 if take_profit_1 is not None else entry_price + (calculated_tp2 - entry_price) * 0.4

    actual_sl_pct = (entry_price - calculated_sl) / entry_price * 100
    actual_tp1_pct = (calculated_tp1 - entry_price) / entry_price * 100
    actual_tp2_pct = (calculated_tp2 - entry_price) / entry_price * 100

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
        "initial_sl": round(calculated_sl, 4),
        "stop_loss": round(calculated_sl, 4),
        "take_profit_1": round(calculated_tp1, 4),
        "take_profit_2": round(calculated_tp2, 4),
        "take_profit": round(calculated_tp2, 4), # TP tối đa
        "sl_pct": round(actual_sl_pct, 2),
        "tp1_pct": round(actual_tp1_pct, 2),
        "tp2_pct": round(actual_tp2_pct, 2),
        "tp_pct": round(actual_tp2_pct, 2),
        "tp1_hit": False,
        "tp1_hit_at": None,
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
    """
    Quét giá Binance thực tế để xử lý quy trình Sniper Quality:
    1. Chạm TP1: Chốt lời 50% khối lượng, kéo Stop Loss về Entry hòa vốn.
    2. Chạm TP2: Chốt lời toàn bộ 50% còn lại.
    3. Đã chạm TP1 mà quay đầu về Entry: Đóng lệnh hòa vốn (giữ nguyên 50% lãi TP1).
    4. Chưa chạm TP1 mà chạm Stop Loss: Cắt lỗ ban đầu.
    """
    trades = load_trades()
    open_trades = [t for t in trades if t['status'] == 'OPEN']
    
    if not open_trades:
        return []

    events = []

    for t in open_trades:
        symbol = t['symbol']
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            entry_price = t['entry_price']
            now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            tp1_target = t.get('take_profit_1', t.get('take_profit', entry_price * 1.02))
            tp2_target = t.get('take_profit_2', t.get('take_profit', entry_price * 1.04))

            # TRƯỜNG HỢP 1: CHƯA CHẠM TP1
            if not t.get('tp1_hit', False):
                # 1A. Chạm TP1 -> Chốt 50% & Kéo SL về Entry
                if current_price >= tp1_target:
                    t['tp1_hit'] = True
                    t['tp1_hit_at'] = now_str
                    t['tp1_price'] = current_price
                    t['stop_loss'] = entry_price # Dời SL về hòa vốn

                    events.append((
                        t,
                        f"🎯 CHỐT LỜI 50% VỊ THẾ (TP1: +{t.get('tp1_pct', 0):.1f}%)\n🛡️ ĐÃ TỰ ĐỘNG DỜI STOP LOSS VỀ GIÁ VÀO LỆNH (${entry_price:,.2f}) - RỦI RO = 0%!"
                    ))

                # 1B. Chưa chạm TP1 mà chạm Stop Loss ban đầu
                elif current_price <= t['stop_loss']:
                    t['status'] = 'CLOSED_SL'
                    t['close_price'] = current_price
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    t['pnl_pct'] = round(pnl_pct, 2)
                    t['closed_at'] = now_str
                    events.append((t, f"🔴 CẮT LỖ STOP LOSS (-{abs(t['pnl_pct']):.1f}%)"))

            # TRƯỜNG HỢP 2: ĐÃ CHỐT 50% TP1 (GỒNG 50% CÒN LẠI VỚI SL VỀ ENTRY)
            else:
                # 2A. Tiếp tục bay lên chạm TP2 -> Chốt trọn vẹn
                if current_price >= tp2_target:
                    t['status'] = 'CLOSED_TP2'
                    t['close_price'] = current_price
                    tp1_pnl = t.get('tp1_pct', 0)
                    tp2_pnl = (current_price - entry_price) / entry_price * 100
                    t['pnl_pct'] = round(0.5 * tp1_pnl + 0.5 * tp2_pnl, 2)
                    t['closed_at'] = now_str
                    events.append((t, f"🏆 CHỐT LỜI TOÀN BỘ TP2 (+{t['pnl_pct']:.1f}% TỔNG LÃI)"))

                # 2B. Quay đầu cắn Entry hòa vốn -> Lệnh vẫn kết thúc có lãi (lãi 50% của TP1)
                elif current_price <= t['stop_loss']:
                    t['status'] = 'CLOSED_BE'
                    t['close_price'] = current_price
                    tp1_pnl = t.get('tp1_pct', 0)
                    t['pnl_pct'] = round(0.5 * tp1_pnl, 2)
                    t['closed_at'] = now_str
                    events.append((t, f"🛡️ QUAY ĐẦU CHẠM HÒA VỐN ENTRY (LÃI TRỌN 50% TP1: +{t['pnl_pct']:.1f}%)"))

        except Exception as e:
            print(f"❌ Lỗi lấy giá {symbol}: {e}")

    if events:
        save_trades(trades)

    return events