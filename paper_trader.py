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

def get_current_paper_balance(initial_balance: float = 500.0) -> float:
    """Tính toán số dư tài khoản Paper Trading hiện tại từ lịch sử giao dịch"""
    trades = load_trades()
    balance = initial_balance
    for t in trades:
        if t.get("status") != "OPEN":
            if "pnl_usd" in t:
                balance += float(t.get("pnl_usd", 0.0))
            elif "pnl_pct" in t:
                pos_sz = float(t.get("position_size_usdt", getattr(config, "ORDER_AMOUNT_USDT", 50.0)))
                balance += pos_sz * (float(t.get("pnl_pct", 0.0)) / 100.0)
    return max(round(balance, 2), 50.0)

def open_paper_trade(symbol: str, entry_price: float, sl_pct: float = None, tp_pct: float = None,
                     ai_score: int = 0, stop_loss: float = None, take_profit: float = None,
                     take_profit_1: float = None, take_profit_2: float = None,
                     tp1_pct: float = None, tp2_pct: float = None,
                     tp1_share: float = None, tp2_share: float = None,
                     macro_regime: str = None, fng_summary: str = None, ai_reasoning: str = None,
                     strategy_type: str = "SNIPER_TREND", strategy_desc: str = None):
    """Mở một lệnh mua mô phỏng mới theo chuẩn DUAL Regime và Position Sizing Động"""
    trades = load_trades()

    # Kiểm tra xem coin này đã có lệnh nào đang chạy chưa (tránh trùng lệnh)
    for t in trades:
        if t['symbol'] == symbol and t['status'] == 'OPEN':
            return None

    calculated_sl = stop_loss if stop_loss is not None else entry_price * (1 - (sl_pct if sl_pct is not None else config.STOP_LOSS_PCT))
    calculated_tp2 = take_profit_2 if take_profit_2 is not None else (take_profit if take_profit is not None else entry_price * (1 + config.TAKE_PROFIT_PCT))
    calculated_tp1 = take_profit_1 if take_profit_1 is not None else (calculated_tp2 if strategy_type == "SIDEWAY_RANGE" else entry_price + (calculated_tp2 - entry_price) * 0.4)

    actual_sl_pct = (entry_price - calculated_sl) / entry_price * 100
    actual_tp1_pct = (calculated_tp1 - entry_price) / entry_price * 100
    actual_tp2_pct = (calculated_tp2 - entry_price) / entry_price * 100

    # Tính toán khối lượng vào lệnh theo công thức Position Sizing
    current_bal = get_current_paper_balance()
    sl_decimal = (entry_price - calculated_sl) / entry_price if entry_price > 0 else 0.02
    sizing_info = config.calculate_position_size(current_bal, sl_decimal)
    position_size_usdt = sizing_info["position_size_usdt"]

    trade_id = f"{symbol.replace('/', '_')}_{int(time.time())}"
    opened_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    # Đặt lệnh Mua song song lên tất cả các sàn Testnet được kích hoạt (nếu bật USE_TESTNET)
    exchange_orders = {}
    if getattr(config, "USE_TESTNET", False):
        multi_res = multi_exchange_trader.place_multi_market_buy(symbol, usdt_amount=position_size_usdt)
        for ex_name, o_data in multi_res.items():
            if o_data.get('success'):
                exchange_orders[ex_name] = o_data.get('order_id')

    new_trade = {
        "id": trade_id,
        "symbol": symbol,
        "strategy_type": strategy_type,
        "strategy_desc": strategy_desc or ("🎯 SNIPER TREND" if strategy_type == "SNIPER_TREND" else "📦 SIDEWAY RANGE"),
        "position_size_usdt": position_size_usdt,
        "risk_usd": sizing_info["risk_usd"],
        "risk_pct": sizing_info["risk_pct"],
        "sizing_mode": sizing_info["mode"],
        "account_balance_at_entry": current_bal,
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
        "tp1_share": tp1_share if tp1_share is not None else getattr(config, 'TP1_SHARE', 0.3),
        "tp2_share": tp2_share if tp2_share is not None else getattr(config, 'TP2_SHARE', 0.7),
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
    Quét giá Binance thực tế để xử lý vị thế cho cả 2 chế độ:
    - SIDEWAY_RANGE: Chốt lời tại SMA20 / +2.2%, Cắt lỗ 1.2x ATR.
    - SNIPER_TREND : Quy trình 2 giai đoạn (TP1 30% dời SL về Entry, TP2 70% gồng dài).
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
            strat_type = t.get('strategy_type', 'SNIPER_TREND')
            pos_size = float(t.get('position_size_usdt', getattr(config, 'ORDER_AMOUNT_USDT', 50.0)))

            # =========================================================
            # XỬ LÝ VỊ THẾ SIDEWAY RANGE (BẮT ĐÁY BIÊN HỘP)
            # =========================================================
            if strat_type == "SIDEWAY_RANGE":
                tp_target = t.get('take_profit', entry_price * 1.022)
                sl_target = t.get('stop_loss', entry_price * 0.98)

                if current_price >= tp_target:
                    t['status'] = 'CLOSED_TP'
                    t['close_price'] = current_price
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    t['pnl_pct'] = round(pnl_pct, 2)
                    t['pnl_usd'] = round(pos_size * (pnl_pct / 100.0), 2)
                    t['closed_at'] = now_str
                    events.append((t, f"📦 [SIDEWAY] CHỐT LỜI BIÊN TRÊN (+{t['pnl_pct']:.1f}% | +${t['pnl_usd']:,.2f})"))

                elif current_price <= sl_target:
                    t['status'] = 'CLOSED_SL'
                    t['close_price'] = current_price
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    t['pnl_pct'] = round(pnl_pct, 2)
                    t['pnl_usd'] = round(pos_size * (pnl_pct / 100.0), 2)
                    t['closed_at'] = now_str
                    events.append((t, f"🔴 [SIDEWAY] CẮT LỖ THỦNG BIÊN (-{abs(t['pnl_pct']):.1f}% | -${abs(t['pnl_usd']):,.2f})"))

            # =========================================================
            # XỬ LÝ VỊ THẾ SNIPER TREND (2 GIAI ĐOẠN TP1 + TP2)
            # =========================================================
            else:
                tp1_target = t.get('take_profit_1', t.get('take_profit', entry_price * 1.02))
                tp2_target = t.get('take_profit_2', t.get('take_profit', entry_price * 1.04))
                tp1_share = t.get('tp1_share', getattr(config, 'TP1_SHARE', 0.3))
                tp2_share = t.get('tp2_share', getattr(config, 'TP2_SHARE', 0.7))

                if not t.get('tp1_hit', False):
                    # Chạm TP1 -> Chốt 30% & Kéo SL về Entry hòa vốn
                    if current_price >= tp1_target:
                        t['tp1_hit'] = True
                        t['tp1_hit_at'] = now_str
                        t['tp1_price'] = current_price
                        t['stop_loss'] = entry_price # Dời SL về hòa vốn
                        tp1_gain_usd = round(pos_size * tp1_share * (t.get('tp1_pct', 0) / 100.0), 2)

                        events.append((
                            t,
                            f"🎯 [SNIPER] CHỐT LỜI 30% VỊ THẾ (TP1: +{t.get('tp1_pct', 0):.1f}% | +${tp1_gain_usd:,.2f})\n🛡️ ĐÃ TỰ ĐỘNG DỜI STOP LOSS VỀ GIÁ VÀO LỆNH (${entry_price:,.2f}) - RỦI RO = 0%!"
                        ))

                    # Chưa chạm TP1 mà chạm Stop Loss ban đầu
                    elif current_price <= t['stop_loss']:
                        t['status'] = 'CLOSED_SL'
                        t['close_price'] = current_price
                        pnl_pct = (current_price - entry_price) / entry_price * 100
                        t['pnl_pct'] = round(pnl_pct, 2)
                        t['pnl_usd'] = round(pos_size * (pnl_pct / 100.0), 2)
                        t['closed_at'] = now_str
                        events.append((t, f"🔴 [SNIPER] CẮT LỖ STOP LOSS (-{abs(t['pnl_pct']):.1f}% | -${abs(t['pnl_usd']):,.2f})"))

                else:
                    # Đã chốt 30% TP1, tiếp tục chạm TP2
                    if current_price >= tp2_target:
                        t['status'] = 'CLOSED_TP2'
                        t['close_price'] = current_price
                        tp1_pnl = t.get('tp1_pct', 0)
                        tp2_pnl = (current_price - entry_price) / entry_price * 100
                        t['pnl_pct'] = round(tp1_share * tp1_pnl + tp2_share * tp2_pnl, 2)
                        t['pnl_usd'] = round(pos_size * (t['pnl_pct'] / 100.0), 2)
                        t['closed_at'] = now_str
                        events.append((t, f"🏆 [SNIPER] CHỐT LỜI TOÀN BỘ TP2 (+{t['pnl_pct']:.1f}% | +${t['pnl_usd']:,.2f})"))

                    # Đã chốt 30% TP1, quay đầu về Entry hòa vốn
                    elif current_price <= t['stop_loss']:
                        t['status'] = 'CLOSED_BE'
                        t['close_price'] = current_price
                        tp1_pnl = t.get('tp1_pct', 0)
                        t['pnl_pct'] = round(tp1_share * tp1_pnl, 2)
                        t['pnl_usd'] = round(pos_size * (t['pnl_pct'] / 100.0), 2)
                        t['closed_at'] = now_str
                        events.append((t, f"🛡️ [SNIPER] QUAY ĐẦU CHẠM HÒA VỐN ENTRY (LÃI TRỌN 30% TP1: +{t['pnl_pct']:.1f}% | +${t['pnl_usd']:,.2f})"))

        except Exception as e:
            print(f"❌ Lỗi lấy giá {symbol}: {e}")

    if events:
        save_trades(trades)

    return events