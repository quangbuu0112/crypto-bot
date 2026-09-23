import json
import os
import time
from datetime import datetime, timezone
import ccxt
import config
import multi_exchange_trader

TRADES_FILE = "paper_trades.json"

# Khởi tạo Singleton CCXT clients cho cả 2 sàn Binance & Bybit
_binance_client = ccxt.binance({'enableRateLimit': True})
_bybit_client = ccxt.bybit({'enableRateLimit': True})

def _get_exchange_client(exchange_name: str = 'binance'):
    name = (exchange_name or 'binance').lower().strip()
    return _bybit_client if name == 'bybit' else _binance_client

def get_live_exchange_price(symbol: str, exchange_name: str = 'binance') -> float:
    """Lấy giá thị trường hiện tại (ticker last) theo từng sàn"""
    try:
        client = _get_exchange_client(exchange_name)
        ticker = client.fetch_ticker(symbol)
        return float(ticker['last'])
    except Exception as e:
        print(f"❌ Lỗi lấy giá {symbol} trên {exchange_name}: {e}")
        return None

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

def get_current_paper_balance(exchange_name: str = None):
    """
    Tính số dư khả dụng thực tế của tài khoản Paper Trading:
    - Nếu truyền exchange_name ('binance' hoặc 'bybit'): Trả về số dư của sàn đó ($500 + Realized PnL sàn đó).
    - Nếu exchange_name = None: Trả về dict {'binance': ..., 'bybit': ..., 'total': ...}
    """
    trades = load_trades()
    initial_cap_per_ex = float(getattr(config, 'INITIAL_PAPER_BALANCE_PER_EXCHANGE', 500.0))

    if exchange_name:
        ex_name = exchange_name.lower().strip()
        realized_pnl = sum(
            float(t.get('pnl_usd', 0.0))
            for t in trades
            if t.get('exchange', 'binance').lower() == ex_name and str(t.get('status', '')).startswith('CLOSED')
        )
        return round(initial_cap_per_ex + realized_pnl, 2)

    # Tính toán cho cả 2 sàn
    bal_binance = initial_cap_per_ex + sum(
        float(t.get('pnl_usd', 0.0))
        for t in trades
        if t.get('exchange', 'binance').lower() == 'binance' and str(t.get('status', '')).startswith('CLOSED')
    )
    bal_bybit = initial_cap_per_ex + sum(
        float(t.get('pnl_usd', 0.0))
        for t in trades
        if t.get('exchange', 'binance').lower() == 'bybit' and str(t.get('status', '')).startswith('CLOSED')
    )

    return {
        "binance": round(bal_binance, 2),
        "bybit": round(bal_bybit, 2),
        "total": round(bal_binance + bal_bybit, 2)
    }

def is_symbol_in_cooldown(symbol: str, exchange_name: str = None) -> dict:
    """
    🛡️ GIÁP 3: MẠCH NGẮT CHUỖI THUA (CONSECUTIVE LOSS COOLDOWN)
    Nếu 1 coin dính 2 lệnh SL liên tiếp trong vòng 72 giờ -> Tạm khóa 72h để bảo toàn vốn.
    """
    if not getattr(config, 'ENABLE_CONSECUTIVE_LOSS_COOLDOWN', True):
        return {"in_cooldown": False}

    trades = load_trades()
    closed_sym_trades = [
        t for t in trades 
        if t.get('symbol') == symbol 
        and (exchange_name is None or t.get('exchange', 'binance').lower() == exchange_name.lower())
        and t.get('status') in ['CLOSED_SL', 'CLOSED_TP', 'CLOSED_TP2', 'CLOSED_BE', 'CLOSED_TIMEOUT']
    ]
    if len(closed_sym_trades) < 2:
        return {"in_cooldown": False}

    last_two = closed_sym_trades[-2:]
    if all(t.get('status') == 'CLOSED_SL' for t in last_two):
        try:
            last_closed_at = last_two[-1].get('closed_at')
            if last_closed_at:
                clean_time_str = last_closed_at.replace(' UTC', '').strip()
                last_dt = datetime.strptime(clean_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                hours_passed = (now_dt - last_dt).total_seconds() / 3600.0
                cooldown_limit = getattr(config, 'COOLDOWN_HOURS', 72)
                if hours_passed < cooldown_limit:
                    remaining_h = round(cooldown_limit - hours_passed, 1)
                    return {
                        "in_cooldown": True,
                        "remaining_hours": remaining_h,
                        "detail": f"🛡️ [GIÁP 3: COOLDOWN] {symbol} ({exchange_name or 'All'}) dính 2 SL liên tiếp. Tạm khóa còn {remaining_h}h."
                    }
        except Exception:
            pass

    return {"in_cooldown": False}

def open_paper_trade(symbol: str, entry_price: float, sl_pct: float = None, tp_pct: float = None,
                      ai_score: int = 0, stop_loss: float = None, take_profit: float = None,
                      take_profit_1: float = None, take_profit_2: float = None,
                      tp1_pct: float = None, tp2_pct: float = None,
                      tp1_share: float = None, tp2_share: float = None,
                      macro_regime: str = None, fng_summary: str = None, ai_reasoning: str = None,
                      strategy_type: str = "SNIPER_TREND", strategy_desc: str = None,
                      exchange_name: str = 'binance'):
    """
    Mở một lệnh mua mô phỏng mới theo chuẩn DUAL Regime và Position Sizing Động cho từng sàn (Binance / Bybit).
    """
    ex_name = (exchange_name or 'binance').lower().strip()
    trades = load_trades()

    # Kiểm tra xem coin này đã có lệnh nào đang chạy trên sàn này chưa
    for t in trades:
        if t['symbol'] == symbol and t.get('exchange', 'binance').lower() == ex_name and t['status'] == 'OPEN':
            return None

    # Lấy giá thực tế của sàn tương ứng nếu có
    actual_entry_price = entry_price
    live_price = get_live_exchange_price(symbol, ex_name)
    if live_price and live_price > 0:
        actual_entry_price = live_price

    # Tính toán lại các mốc TP/SL theo giá vào lệnh thực tế của sàn
    if sl_pct is not None:
        calculated_sl = actual_entry_price * (1.0 - (sl_pct / 100.0 if sl_pct > 1.0 else sl_pct))
    else:
        calculated_sl = stop_loss if stop_loss is not None else actual_entry_price * 0.98

    if tp2_pct is not None:
        calculated_tp2 = actual_entry_price * (1.0 + (tp2_pct / 100.0 if tp2_pct > 1.0 else tp2_pct))
    else:
        calculated_tp2 = take_profit_2 if take_profit_2 is not None else (take_profit if take_profit is not None else actual_entry_price * 1.06)

    if tp1_pct is not None:
        calculated_tp1 = actual_entry_price * (1.0 + (tp1_pct / 100.0 if tp1_pct > 1.0 else tp1_pct))
    else:
        calculated_tp1 = take_profit_1 if take_profit_1 is not None else (calculated_tp2 if strategy_type == "SIDEWAY_RANGE" else actual_entry_price + (calculated_tp2 - actual_entry_price) * 0.35)

    actual_sl_pct = (actual_entry_price - calculated_sl) / actual_entry_price * 100.0
    actual_tp1_pct = (calculated_tp1 - actual_entry_price) / actual_entry_price * 100.0
    actual_tp2_pct = (calculated_tp2 - actual_entry_price) / actual_entry_price * 100.0

    # Tính toán Position Sizing dựa trên số dư riêng của sàn đó
    current_bal = get_current_paper_balance(ex_name)
    sl_decimal = (actual_entry_price - calculated_sl) / actual_entry_price if actual_entry_price > 0 else 0.02
    sizing_info = config.calculate_position_size(current_bal, sl_decimal)
    position_size_usdt = sizing_info["position_size_usdt"]

    trade_id = f"{ex_name.upper()}_{symbol.replace('/', '_')}_{int(time.time())}"
    opened_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    # Đặt lệnh Mua song song lên sàn Testnet (nếu bật USE_TESTNET)
    exchange_orders = {}
    if getattr(config, "USE_TESTNET", False):
        try:
            multi_res = multi_exchange_trader.place_multi_market_buy(symbol, usdt_amount=position_size_usdt)
            for e_name, o_data in multi_res.items():
                if o_data.get('success'):
                    exchange_orders[e_name] = o_data.get('order_id')
        except Exception as e:
            print(f"⚠️ Lỗi đặt Testnet: {e}")

    new_trade = {
        "id": trade_id,
        "exchange": ex_name,
        "symbol": symbol,
        "strategy_type": strategy_type,
        "strategy_desc": strategy_desc or ("🎯 SNIPER TREND" if strategy_type == "SNIPER_TREND" else "📦 SIDEWAY RANGE"),
        "position_size_usdt": position_size_usdt,
        "risk_usd": sizing_info["risk_usd"],
        "risk_pct": sizing_info["risk_pct"],
        "sizing_mode": sizing_info["mode"],
        "account_balance_at_entry": current_bal,
        "entry_price": round(actual_entry_price, 4),
        "initial_sl": round(calculated_sl, 4),
        "stop_loss": round(calculated_sl, 4),
        "take_profit_1": round(calculated_tp1, 4),
        "take_profit_2": round(calculated_tp2, 4),
        "take_profit": round(calculated_tp2, 4),
        "sl_pct": round(actual_sl_pct, 2),
        "tp1_pct": round(actual_tp1_pct, 2),
        "tp2_pct": round(actual_tp2_pct, 2),
        "tp_pct": round(actual_tp2_pct, 2),
        "tp1_share": tp1_share if tp1_share is not None else getattr(config, 'TP1_SHARE', 0.35),
        "tp2_share": tp2_share if tp2_share is not None else getattr(config, 'TP2_SHARE', 0.65),
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
    Quét giá sàn Binance và Bybit thực tế để xử lý vị thế song song cho cả 2 sàn.
    """
    trades = load_trades()
    open_trades = [t for t in trades if t.get('status') == 'OPEN']
    
    if not open_trades:
        return []

    events = []

    for t in open_trades:
        symbol = t['symbol']
        ex_name = t.get('exchange', 'binance').lower().strip()
        client = _get_exchange_client(ex_name)

        try:
            ticker = client.fetch_ticker(symbol)
            current_price = float(ticker['last'])
            entry_price = float(t['entry_price'])
            now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            strat_type = t.get('strategy_type', 'SNIPER_TREND')
            pos_size = float(t.get('position_size_usdt', getattr(config, 'ORDER_AMOUNT_USDT', 50.0)))
            ex_tag = f"🏦 [{ex_name.upper()}]"

            # =========================================================
            # XỬ LÝ VỊ THẾ SIDEWAY RANGE
            # =========================================================
            if strat_type == "SIDEWAY_RANGE":
                tp_target = float(t.get('take_profit', entry_price * 1.022))
                sl_target = float(t.get('stop_loss', entry_price * 0.98))

                if current_price >= tp_target:
                    t['status'] = 'CLOSED_TP'
                    t['close_price'] = current_price
                    pnl_pct = (current_price - entry_price) / entry_price * 100.0
                    t['pnl_pct'] = round(pnl_pct, 2)
                    t['pnl_usd'] = round(pos_size * (pnl_pct / 100.0), 2)
                    t['closed_at'] = now_str
                    events.append((t, f"{ex_tag} 📦 [SIDEWAY] CHỐT LỜI BIÊN TRÊN (+{t['pnl_pct']:.1f}% | +${t['pnl_usd']:,.2f})"))

                elif current_price <= sl_target:
                    t['status'] = 'CLOSED_SL'
                    t['close_price'] = current_price
                    pnl_pct = (current_price - entry_price) / entry_price * 100.0
                    t['pnl_pct'] = round(pnl_pct, 2)
                    t['pnl_usd'] = round(pos_size * (pnl_pct / 100.0), 2)
                    t['closed_at'] = now_str
                    events.append((t, f"{ex_tag} 🔴 [SIDEWAY] CẮT LỖ THỦNG BIÊN (-{abs(t['pnl_pct']):.1f}% | -${abs(t['pnl_usd']):,.2f})"))

            # =========================================================
            # XỬ LÝ VỊ THẾ SNIPER TREND (TP1 35% + TP2 RUNNER 65%)
            # =========================================================
            else:
                tp1_target = float(t.get('take_profit_1', entry_price * 1.02))
                tp2_target = float(t.get('take_profit_2', entry_price * 1.06))
                tp1_share = float(t.get('tp1_share', getattr(config, 'TP1_SHARE', 0.35)))
                tp2_share = float(t.get('tp2_share', getattr(config, 'TP2_SHARE', 0.65)))

                if not t.get('tp1_hit', False):
                    # Chạm TP1 -> Chốt 35% & Kéo SL về Entry hòa vốn
                    if current_price >= tp1_target:
                        t['tp1_hit'] = True
                        t['tp1_hit_at'] = now_str
                        t['tp1_price'] = current_price
                        t['stop_loss'] = entry_price # Dời SL về hòa vốn
                        tp1_gain_usd = round(pos_size * tp1_share * (t.get('tp1_pct', 0) / 100.0), 2)

                        events.append((
                            t,
                            f"{ex_tag} 🎯 [SNIPER] CHỐT LỜI 35% VỊ THẾ (TP1: +{t.get('tp1_pct', 0):.1f}% | +${tp1_gain_usd:,.2f})\n🛡️ ĐÃ TỰ ĐỘNG DỜI STOP LOSS VỀ GIÁ ENTRY (${entry_price:,.2f}) - RỦI RO = 0%!"
                        ))

                    # Chưa chạm TP1 mà chạm Stop Loss ban đầu
                    elif current_price <= float(t['stop_loss']):
                        t['status'] = 'CLOSED_SL'
                        t['close_price'] = current_price
                        pnl_pct = (current_price - entry_price) / entry_price * 100.0
                        t['pnl_pct'] = round(pnl_pct, 2)
                        t['pnl_usd'] = round(pos_size * (pnl_pct / 100.0), 2)
                        t['closed_at'] = now_str
                        events.append((t, f"{ex_tag} 🔴 [SNIPER] CẮT LỖ STOP LOSS (-{abs(t['pnl_pct']):.1f}% | -${abs(t['pnl_usd']):,.2f})"))

                else:
                    # Đã chốt 35% TP1, tiếp tục chạm TP2 Runner
                    if current_price >= tp2_target:
                        t['status'] = 'CLOSED_TP2'
                        t['close_price'] = current_price
                        tp1_pnl = float(t.get('tp1_pct', 0))
                        tp2_pnl = (current_price - entry_price) / entry_price * 100.0
                        t['pnl_pct'] = round(tp1_share * tp1_pnl + tp2_share * tp2_pnl, 2)
                        t['pnl_usd'] = round(pos_size * (t['pnl_pct'] / 100.0), 2)
                        t['closed_at'] = now_str
                        events.append((t, f"{ex_tag} 🏆 [SNIPER RUNNER] CHỐT LỜI TOÀN BỘ TP2 (+{t['pnl_pct']:.1f}% | +${t['pnl_usd']:,.2f})"))

                    # Đã chốt 35% TP1, quay đầu về Entry hòa vốn
                    elif current_price <= float(t['stop_loss']):
                        t['status'] = 'CLOSED_BE'
                        t['close_price'] = current_price
                        tp1_pnl = float(t.get('tp1_pct', 0))
                        t['pnl_pct'] = round(tp1_share * tp1_pnl, 2)
                        t['pnl_usd'] = round(pos_size * (t['pnl_pct'] / 100.0), 2)
                        t['closed_at'] = now_str
                        events.append((t, f"{ex_tag} 🛡️ [SNIPER] QUAY ĐẦU CHẠM HÒA VỐN ENTRY (LÃI TRỌN 35% TP1: +{t['pnl_pct']:.1f}% | +${t['pnl_usd']:,.2f})"))

        except Exception as e:
            print(f"❌ Lỗi lấy giá {symbol} trên {ex_name}: {e}")

    if events:
        save_trades(trades)

    return events