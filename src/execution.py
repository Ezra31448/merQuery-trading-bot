from src.news_filter import get_imminent_news

"""
Execution module for the trading bot.
Handles trade execution, trailing stop, and risk management.
"""

import MetaTrader5 as mt5
from datetime import datetime
from src.config import (
    SYMBOL, LOT_SIZE, MAX_SL_POINTS, TRAILING_ENABLE,
    TRAILING_MIN_PROFIT_ATR, TRAILING_DISTANCE_ATR,
    MAGIC_NUMBER, ACTIVE_AI, logger
)
from src.mt5_client import mt5_lock, ensure_mt5_connected
from src.analysis import get_market_data
from src.database import log_trade


def execute_trade(decision_data, current_atr):
    """Execute a trade based on AI decision."""
    action = decision_data.get("decision", "HOLD").upper()
    reason = decision_data.get("reason", "No reason provided")
    logger.info("AI Decision: %s | Reason: %s", action, reason)

    if action not in ["BUY", "SELL"]:
        logger.info("No trade action (HOLD).")
        return

    # Check open positions for this bot
    from src.mt5_client import has_open_position
    if has_open_position(SYMBOL):
        logger.info("Existing bot position found. Skipping new order.")
        return

    # get tick (thread-safe)
    with mt5_lock:
        tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logger.error("Failed to get tick for symbol %s", SYMBOL)
        return

    price = float(tick.ask) if action == "BUY" else float(tick.bid)

    # get symbol point
    with mt5_lock:
        s_info = mt5.symbol_info(SYMBOL)
    if s_info is None:
        logger.error("Failed to read symbol info for %s", SYMBOL)
        return
    point = s_info.point

    # Convert ATR (price units) to points correctly: atr_points = current_atr / point
    atr_points = current_atr / point if point and point != 0 else current_atr
    sl_distance_points = min(atr_points * 1.5, MAX_SL_POINTS)
    tp_distance_points = sl_distance_points * 1.5  # Risk:Reward 1:1.5

    if action == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        sl_price = price - (sl_distance_points * point)
        tp_price = price + (tp_distance_points * point)
    else:
        order_type = mt5.ORDER_TYPE_SELL
        sl_price = price + (sl_distance_points * point)
        tp_price = price - (tp_distance_points * point)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": price,
        "sl": round(sl_price, 2),
        "tp": round(tp_price, 2),
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": f"{ACTIVE_AI}_M15_Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    logger.info("Placing %s order at %.2f (SL: %.2f TP: %.2f)", action, price, sl_price, tp_price)
    try:
        with mt5_lock:
            result = mt5.order_send(request)
        if result is None:
            logger.error("order_send returned None")
            return
        if getattr(result, "retcode", None) != mt5.TRADE_RETCODE_DONE:
            logger.error("Order failed retcode=%s", getattr(result, "retcode", None))
            return
        logger.info("Order placed successfully. order=%s", getattr(result, "order", "N/A"))
        log_trade(SYMBOL, action, price, sl_price, tp_price, reason)
    except Exception as e:
        logger.exception("Exception during order_send: %s", e)


def apply_trailing_stop_sync():
    """
    Synchronous trailing stop logic. Uses mt5_lock for all MT5 API calls.
    Moves SL only to tighten (never widen) and applies small hysteresis to avoid frequent micro updates.
    Uses ATR-based trailing distance (TRAILING_DISTANCE_ATR * ATR).
    """
    if not TRAILING_ENABLE:
        return

    if not ensure_mt5_connected():
        return

    try:
        with mt5_lock:
            positions = mt5.positions_get(symbol=SYMBOL)
        if not positions:
            return

        # read symbol point
        with mt5_lock:
            s_info = mt5.symbol_info(SYMBOL)
        if s_info is None:
            logger.error("Symbol info missing during trailing stop")
            return
        point = s_info.point

        # read ATR once (price units)
        _, current_atr = get_market_data(bars=150)
        if current_atr is None:
            logger.debug("ATR missing for trailing stop; skipping")
            return

        # hysteresis in price units to prevent tiny adjust: 10 pips (0.10 USD for XAUUSD)
        # FIX: Increased from 0.5 to 10 to prevent spamming broker with frequent SL modifications
        hysteresis_price = point * 10

        for p in positions:
            # identify bot positions
            mag = getattr(p, "magic", None)
            comment = getattr(p, "comment", "") or ""
            if mag != MAGIC_NUMBER and (ACTIVE_AI not in comment):
                continue

            ticket = int(getattr(p, "ticket", 0))
            price_open = float(getattr(p, "price_open", getattr(p, "open_price", 0.0)))
            existing_sl = float(getattr(p, "sl", 0.0) or 0.0)
            existing_tp = float(getattr(p, "tp", 0.0) or 0.0)
            p_type = int(getattr(p, "type", 0))  # mt5.POSITION_TYPE_BUY / SELL

            # current tick (thread-safe)
            with mt5_lock:
                tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                logger.debug("No tick for trailing on ticket %s", ticket)
                continue
            current_price = float(tick.ask) if p_type == mt5.POSITION_TYPE_BUY else float(tick.bid)

            # profit in price units
            if p_type == mt5.POSITION_TYPE_BUY:
                profit_price = current_price - price_open
            else:
                profit_price = price_open - current_price

            # if profit not enough, skip
            if profit_price < (TRAILING_MIN_PROFIT_ATR * current_atr):
                continue

            trailing_dist_price = TRAILING_DISTANCE_ATR * current_atr

            if p_type == mt5.POSITION_TYPE_BUY:
                # new SL should be current_price - trailing_dist
                new_sl = current_price - trailing_dist_price
                # only tighten (move SL up) and by more than hysteresis
                if new_sl > existing_sl + hysteresis_price:
                    modify_request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "sl": round(new_sl, 2),
                        "tp": existing_tp
                    }
                    try:
                        with mt5_lock:
                            res = mt5.order_send(modify_request)
                        logger.info("BUY ticket %s: moved SL %.2f -> %.2f result=%s", ticket, existing_sl, new_sl, res)
                    except Exception:
                        logger.exception("Exception modifying SL for BUY ticket %s", ticket)
            else:
                # SELL: new SL should be current_price + trailing_dist
                new_sl = current_price + trailing_dist_price
                # only tighten (move SL down for SELL) and by more than hysteresis
                # existing_sl==0 means no SL set
                if existing_sl == 0 or new_sl < existing_sl - hysteresis_price:
                    modify_request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "sl": round(new_sl, 2),
                        "tp": existing_tp
                    }
                    try:
                        with mt5_lock:
                            res = mt5.order_send(modify_request)
                        logger.info("SELL ticket %s: moved SL %.2f -> %.2f result=%s", ticket, existing_sl, new_sl, res)
                    except Exception:
                        logger.exception("Exception modifying SL for SELL ticket %s", ticket)

    except Exception as e:
        logger.exception("apply_trailing_stop_sync exception: %s", e)


def get_daily_pnl():
    """Estimate realized PnL since start of local day (uses history_deals_get)."""
    if not ensure_mt5_connected():
        return 0.0
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with mt5_lock:
            deals = mt5.history_deals_get(today, datetime.now())
        if not deals:
            return 0.0
        # FIX: Filter by MAGIC_NUMBER and comment to only count this bot's trades
        pnl = sum(
            float(deal.profit)
            for deal in deals
            if getattr(deal, "magic", None) == MAGIC_NUMBER
            or (ACTIVE_AI in getattr(deal, "comment", ""))
        )
        return pnl
    except Exception as e:
        logger.exception("get_daily_pnl error: %s", e)
        return 0.0
    
def tighten_sl_for_news_sync(current_atr):
    """
    ถ้าใกล้ข่าวออก (Option C): บีบ SL ให้แคบลงเพื่อลดความเสี่ยง
    """
    if not ensure_mt5_connected():
        return

    # เช็คว่าอยู่ในช่วงใกล้ข่าวหรือเปล่า
    imminent_news, time_diff = get_imminent_news()
    if not imminent_news:
        return # ไม่มีข่าว ไม่ต้องทำอะไร

    # ถ้าข่าวเพิ่งผ่านไปแล้ว (time_diff ติดลบ) ก็ปล่อย Trailing stop ปกติจัดการไป
    if time_diff < 0: 
        return

    try:
        with mt5_lock:
            positions = mt5.positions_get(symbol=SYMBOL)
        if not positions:
            return

        with mt5_lock:
            s_info = mt5.symbol_info(SYMBOL)
        point = s_info.point
        
        # บีบความเสี่ยง: ปกติเราตั้ง SL ที่ 1.5 ATR ตอนมีข่าวเราบีบเหลือแค่ 0.3 ATR เลย!
        tight_distance_price = 0.3 * current_atr 

        for p in positions:
            mag = getattr(p, "magic", None)
            comment = getattr(p, "comment", "") or ""
            if mag != MAGIC_NUMBER and (ACTIVE_AI not in comment):
                continue

            ticket = int(getattr(p, "ticket", 0))
            existing_sl = float(getattr(p, "sl", 0.0) or 0.0)
            existing_tp = float(getattr(p, "tp", 0.0) or 0.0)
            p_type = int(getattr(p, "type", 0))

            with mt5_lock:
                tick = mt5.symbol_info_tick(SYMBOL)
            current_price = float(tick.ask) if p_type == mt5.POSITION_TYPE_BUY else float(tick.bid)

            modify_request = None
            if p_type == mt5.POSITION_TYPE_BUY:
                new_sl = current_price - tight_distance_price
                # ถ้าจุดตัดขาดทุนใหม่ (new_sl) อยู่สูงกว่าของเดิม (แปลว่าแคบลง ปลอดภัยขึ้น)
                if new_sl > existing_sl:
                    modify_request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": round(new_sl, 2), "tp": existing_tp}
            else:
                new_sl = current_price + tight_distance_price
                if existing_sl == 0 or new_sl < existing_sl:
                    modify_request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": round(new_sl, 2), "tp": existing_tp}

            if modify_request:
                with mt5_lock:
                    res = mt5.order_send(modify_request)
                logger.warning("🚨 NEWS TIGHTEN SL! Ticket %s: moved SL to %.2f due to %s", ticket, new_sl, imminent_news['title'])

    except Exception as e:
        logger.exception("tighten_sl_for_news_sync exception: %s", e)
