"""
Full async trading bot for XAUUSD (M15) on MetaTrader5 with:
- asyncio.Semaphore(1) trading_semaphore to prevent overlapping business logic
- threading.Lock mt5_lock for all raw MT5 API calls
- apply_trailing_stop_sync() fully implemented (ATR-based + hysteresis)
- bar_watcher_worker + trailing_stop_worker as asyncio tasks
- bot_routine() synchronous (called under semaphore)
- OpenAI wrapper support for DEEPSEEK and GLM
- SQLite logging
- dotenv for API keys and config constants at top

IMPORTANT: Test on demo account first. Confirm MT5 API modify format with your broker MT5 build.
"""

import os
import time
import json
import sqlite3
import logging
import threading
import asyncio
import signal
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta
from openai import OpenAI
from dotenv import load_dotenv

# ==========================================
# Configuration 
# ==========================================
load_dotenv()

SYMBOL = "XAUUSD"
LOT_SIZE = 0.01
MAX_SL_POINTS = 500
DB_NAME = "trading_bot.db"
ACTIVE_AI = os.getenv("ACTIVE_AI", "GLM")  # "DEEPSEEK" or "GLM"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GLM_API_KEY = os.getenv("GLM_API_KEY")

MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "50"))
MAGIC_NUMBER = int(os.getenv("MAGIC_NUMBER", "100100"))

TRAILING_ENABLE = True
TRAILING_MIN_PROFIT_ATR = float(os.getenv("TRAILING_MIN_PROFIT_ATR", "0.5"))   # start trailing when profit >= 0.5 ATR
TRAILING_DISTANCE_ATR = float(os.getenv("TRAILING_DISTANCE_ATR", "0.4"))     # trailing distance = ATR * factor

BAR_WATCHER_POLL_S = float(os.getenv("BAR_WATCHER_POLL_S", "1.0"))
TRAILING_INTERVAL_S = float(os.getenv("TRAILING_INTERVAL_S", "15.0"))

# ==========================================
# Logging
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==========================================
# Concurrency primitives
# ==========================================
# mt5_lock: protects raw MT5 API calls (socket/connection level). Use around mt5.order_send, mt5.positions_get, mt5.copy_rates_from_pos, mt5.symbol_info_tick, mt5.history_deals_get, mt5.symbol_info
mt5_lock = threading.Lock()

# trading_semaphore: protects high-level business logic to prevent overlapping workflows.
# NOTE: trading_semaphore is created in main_async() and assigned to this global.
# Reason for separation: mt5_lock protects the API call concurrency and ensures thread-safety
# at the transport level. trading_semaphore protects business logic (e.g., ensuring we don't
# simultaneously open orders and modify SL/TP or allow two routines to decide and open orders
# at the same time). Both are necessary because they operate at different layers.
trading_semaphore = None  # set in main_async()

# ==========================================
# Database helpers
# ==========================================
def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            symbol TEXT,
            action TEXT,
            price REAL,
            sl REAL,
            tp REAL,
            ai_reason TEXT
        )
    ''')
    conn.commit()
    conn.close()

def log_trade(symbol, action, price, sl, tp, reason):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO trade_logs (timestamp, symbol, action, price, sl, tp, ai_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (current_time_str, symbol, action, price, sl, tp, reason))
    conn.commit()
    conn.close()

# ==========================================
# MT5 helpers (all raw calls wrapped with mt5_lock)
# ==========================================
def ensure_mt5_connected():
    """Check terminal_info and try to reinitialize if disconnected."""
    try:
        with mt5_lock:
            info = mt5.terminal_info()
        if info is None:
            logger.warning("MT5 terminal not connected. Attempting to initialize...")
            with mt5_lock:
                mt5.shutdown()
                ok = mt5.initialize()
            if ok:
                logger.info("MT5 reinitialized successfully.")
                return True
            else:
                logger.error("MT5 initialize() failed.")
                return False
        return True
    except Exception as e:
        logger.exception("Error while checking/reinitializing MT5: %s", e)
        return False

def symbol_point(symbol):
    with mt5_lock:
        s = mt5.symbol_info(symbol)
    if s is None:
        return None
    return s.point

def has_open_position(symbol):
    """Return True if any position belonging to this bot exists for the symbol."""
    try:
        with mt5_lock:
            positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return False
        for p in positions:
            mag = getattr(p, "magic", None)
            comment = getattr(p, "comment", "") or ""
            if mag == MAGIC_NUMBER or (ACTIVE_AI in comment):
                return True
        return False
    except Exception as e:
        logger.exception("has_open_position error: %s", e)
        return False

# ==========================================
# Market data & indicators
# ==========================================
def get_market_data(bars=200):
    """
    Return (context, current_atr_price_units)
    context contains last 3 closed candles (close, RSI, EMA20)
    current_atr is price units (e.g., USD)
    """
    if not ensure_mt5_connected():
        return None, None

    # ensure symbol is selected
    with mt5_lock:
        ok_select = mt5.symbol_select(SYMBOL, True)
    if not ok_select:
        logger.error("Symbol %s not available in Market Watch", SYMBOL)
        return None, None

    with mt5_lock:
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, bars)
    if rates is None or len(rates) < 50:
        logger.error("Not enough bars returned (%s)", None if rates is None else len(rates))
        return None, None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    # indicators
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['RSI14'] = ta.rsi(df['close'], length=14)
    df['ATR14'] = ta.atr(high=df['high'], low=df['low'], close=df['close'], length=14)
    df.dropna(inplace=True)
    if len(df) < 10:
        logger.error("Not enough data after indicator calculations")
        return None, None

    recent_candles = df.iloc[-4:-1].copy()  # last 3 closed candles
    try:
        current_atr = float(df.iloc[-2]['ATR14'])  # ATR as price units
    except Exception:
        current_atr = float(df['ATR14'].dropna().iloc[-1])

    context = {"symbol": SYMBOL, "timeframe": "M15", "data": []}
    for _, row in recent_candles.iterrows():
        context["data"].append({
            "time": row['time'].strftime("%Y-%m-%d %H:%M:%S"),
            "close": round(float(row['close']), 2),
            "RSI": round(float(row['RSI14']), 2),
            "EMA20": round(float(row['EMA20']), 2)
        })

    return context, current_atr

# ==========================================
# AI decision (OpenAI wrapper)
# ==========================================
def get_ai_decision(market_context):
    logger.info("Sending market context to AI (%s)", ACTIVE_AI)
    prompt = f"""
You are an expert Gold (XAUUSD) day trader. Analyze the following M15 market data which contains the last 3 closed candles:
{json.dumps(market_context)}
Based on RSI and EMA20 trend, decide the next action.
Rule: Only Buy when RSI is oversold and bouncing, or Sell when RSI is overbought and rejecting. If no clear signal, choose HOLD.
Respond ONLY in valid JSON format like this exactly, do not add markdown:
{{"decision": "BUY", "reason": "Short reason here"}}
(decision must be "BUY", "SELL", or "HOLD")
"""
    try:
        if ACTIVE_AI == "DEEPSEEK":
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
            model_name = "deepseek-chat"
        elif ACTIVE_AI == "GLM":
            client = OpenAI(api_key=GLM_API_KEY, base_url="https://api.z.ai/api/paas/v4/")
            model_name = "glm-4.7"
        else:
            logger.error("Unknown ACTIVE_AI: %s", ACTIVE_AI)
            return {"decision": "HOLD", "reason": "Config Error: Unknown AI"}

        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=150
        )
        ai_reply = response.choices[0].message.content
        ai_reply = ai_reply.replace('```json', '').replace('```', '').strip()
        result = json.loads(ai_reply)
        return result
    except Exception as e:
        logger.exception("AI API error: %s", e)
        return {"decision": "HOLD", "reason": f"API Error: {str(e)}"}

# ==========================================
# Trade execution (thread-safe)
# ==========================================
def execute_trade(decision_data, current_atr):
    action = decision_data.get("decision", "HOLD").upper()
    reason = decision_data.get("reason", "No reason provided")
    logger.info("AI Decision: %s | Reason: %s", action, reason)

    if action not in ["BUY", "SELL"]:
        logger.info("No trade action (HOLD).")
        return

    # Check open positions for this bot
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

# ==========================================
# Trailing stop (synchronous)
# ==========================================
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

        # hysteresis in price units to prevent tiny adjust: half a point
        hysteresis_price = point * 0.5

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

# ==========================================
# Risk controls
# ==========================================
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
        pnl = sum(float(deal.profit) for deal in deals)
        return pnl
    except Exception as e:
        logger.exception("get_daily_pnl error: %s", e)
        return 0.0

# ==========================================
# Bot routine (synchronous) - caller must hold trading_semaphore when required
# ==========================================
def bot_routine():
    logger.info("Starting analysis cycle (bot_routine)")
    market_context, current_atr = get_market_data(bars=200)
    if market_context is None or current_atr is None:
        logger.error("Market data not available - skipping cycle")
        return

    # daily loss check
    daily_pnl = get_daily_pnl()
    if daily_pnl <= -MAX_DAILY_LOSS_USD:
        logger.warning("Daily loss limit reached (%.2f). Skipping trading for this cycle.", daily_pnl)
        return

    ai_decision = get_ai_decision(market_context)
    execute_trade(ai_decision, current_atr)

    # apply trailing after potential new position (caller already holds trading_semaphore)
    apply_trailing_stop_sync()

# ==========================================
# Async workers
# ==========================================
async def bar_watcher_worker(poll_interval: float, stop_event: asyncio.Event):
    global trading_semaphore
    logger.info("Bar watcher started (poll_interval=%ss)", poll_interval)
    last_bar_time = None
    while not stop_event.is_set():
        try:
            # raw MT5 call in thread
            rates = await asyncio.to_thread(lambda: mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 1))
            if rates and len(rates) > 0:
                current_bar_time = rates[0]['time']
                if last_bar_time is None:
                    last_bar_time = current_bar_time
                elif current_bar_time != last_bar_time:
                    logger.info("New closed M15 bar detected at %s", datetime.fromtimestamp(current_bar_time))
                    # small wait to ensure indicators/ticks stable
                    await asyncio.sleep(2)
                    # acquire business logic semaphore before executing bot routine
                    async with trading_semaphore:
                        # run synchronous bot_routine in thread to avoid blocking loop
                        await asyncio.to_thread(bot_routine)
                    last_bar_time = current_bar_time
        except Exception:
            logger.exception("Error in bar_watcher_worker")
        await asyncio.sleep(poll_interval)
    logger.info("Bar watcher stopped")

async def trailing_stop_worker(interval_seconds: float, stop_event: asyncio.Event):
    global trading_semaphore
    logger.info("Trailing stop worker started (interval=%s seconds)", interval_seconds)
    while not stop_event.is_set():
        try:
            # acquire business logic semaphore to avoid overlap with bot_routine
            async with trading_semaphore:
                await asyncio.to_thread(apply_trailing_stop_sync)
        except Exception:
            logger.exception("Error in trailing_stop_worker")
        # cancellable sleep
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            # timed out, continue loop
            pass
    logger.info("Trailing stop worker stopped")

# ==========================================
# Async main and graceful shutdown
# ==========================================
async def main_async():
    global trading_semaphore
    # initialize MT5 and DB in thread
    ok_init = await asyncio.to_thread(mt5.initialize)
    if not ok_init:
        logger.error("MT5 initialize failed. Exiting.")
        return
    await asyncio.to_thread(setup_database)

    # create semaphore for business logic concurrency control
    trading_semaphore = asyncio.Semaphore(1)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("Signal received: requesting shutdown")
        stop_event.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _signal_handler)
        except NotImplementedError:
            # Not supported on some platforms
            pass

    # start workers
    bar_task = asyncio.create_task(bar_watcher_worker(BAR_WATCHER_POLL_S, stop_event))
    trailing_task = asyncio.create_task(trailing_stop_worker(TRAILING_INTERVAL_S, stop_event))

    logger.info("Async workers started. Press Ctrl-C to stop.")
    try:
        await stop_event.wait()
    finally:
        logger.info("Shutdown initiated: cancelling workers...")
        bar_task.cancel()
        trailing_task.cancel()
        await asyncio.gather(bar_task, trailing_task, return_exceptions=True)
        logger.info("Workers cancelled. Shutting down MT5...")
        await asyncio.to_thread(mt5.shutdown)
        logger.info("MT5 shutdown complete. Exiting.")

# ==========================================
# Entry point
# ==========================================
if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; exiting.")
    except Exception:
        logger.exception("Unexpected exception in main")