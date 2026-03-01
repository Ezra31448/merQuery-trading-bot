"""
Bot module for the trading bot.
Contains the main bot routine and async workers.
"""

import asyncio
import MetaTrader5 as mt5
from datetime import datetime
from src.config import SYMBOL, BAR_WATCHER_POLL_S, TRAILING_INTERVAL_S, MAX_DAILY_LOSS_USD, DECISION_MODE, logger
from src.mt5_client import ensure_mt5_connected
from src.analysis import get_market_data, get_ai_decision, get_rule_based_decision
from src.execution import execute_trade, apply_trailing_stop_sync, get_daily_pnl ,tighten_sl_for_news_sync
from src.news_filter import get_imminent_news


def bot_routine(ai_decision, current_atr):
    """Main bot routine - performs analysis and executes trades.
    
    Args:
        ai_decision: Pre-computed AI decision dict
        current_atr: Current ATR value in price units
    """
    logger.info("Starting analysis cycle (bot_routine)")

    imminent_news, time_diff = get_imminent_news()
    if imminent_news:
        logger.warning("🚨 NEWS BLACKOUT ACTIVE! News '%s' is approaching/passed (%.0f mins). Skipping new trades.", 
                       imminent_news['title'], time_diff)
        return # หยุดการเปิดออเดอร์ใหม่ทันที

    # daily loss check
    daily_pnl = get_daily_pnl()
    if daily_pnl <= -MAX_DAILY_LOSS_USD:
        logger.warning("Daily loss limit reached (%.2f). Skipping trading for this cycle.", daily_pnl)
        return

    execute_trade(ai_decision, current_atr)

    # apply trailing after potential new position (caller already holds trading_semaphore)
    apply_trailing_stop_sync()


async def bar_watcher_worker(poll_interval: float, stop_event: asyncio.Event, trading_semaphore: asyncio.Semaphore):
    """
    Worker that watches for new closed M15 bars and triggers bot_routine.
    
    Args:
        poll_interval: How often to poll for new bars (seconds)
        stop_event: Event to signal shutdown
        trading_semaphore: Semaphore to control business logic concurrency
    """
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
                    
                    # FIX: Move AI call OUTSIDE semaphore to avoid blocking trailing_stop_worker
                    market_context, current_atr = await asyncio.to_thread(get_market_data, bars=200)
                    if market_context is None or current_atr is None:
                        logger.error("Market data not available - skipping cycle")
                        last_bar_time = current_bar_time
                        continue
                    
                    # Use AI or Rule-based decision based on DECISION_MODE
                    if DECISION_MODE == "RULE_BASED":
                        logger.info("Using RULE_BASED decision mode")
                        decision = await asyncio.to_thread(get_rule_based_decision, market_context)
                    else:
                        logger.info("Using AI decision mode (%s)", DECISION_MODE)
                        decision = await asyncio.to_thread(get_ai_decision, market_context)
                    
                    # acquire business logic semaphore only for execution (not AI call)
                    async with trading_semaphore:
                        # run synchronous bot_routine in thread to avoid blocking loop
                        await asyncio.to_thread(bot_routine, decision, current_atr)
                    last_bar_time = current_bar_time
        except Exception:
            logger.exception("Error in bar_watcher_worker")
        await asyncio.sleep(poll_interval)
    logger.info("Bar watcher stopped")


async def trailing_stop_worker(interval_seconds: float, stop_event: asyncio.Event, trading_semaphore: asyncio.Semaphore):
    """
    Worker that periodically applies trailing stop to open positions.
    
    Args:
        interval_seconds: How often to check trailing stop (seconds)
        stop_event: Event to signal shutdown
        trading_semaphore: Semaphore to control business logic concurrency
    """
    logger.info("Trailing stop worker started (interval=%s seconds)", interval_seconds)
    while not stop_event.is_set():
        try:
            # acquire business logic semaphore to avoid overlap with bot_routine
            async with trading_semaphore:
                # 1. ดึงค่า ATR มาก่อน
                _, current_atr = await asyncio.to_thread(get_market_data, bars=150)
                if current_atr:
                    # 2. เช็คบีบ SL หนีข่าว (Option C)
                    await asyncio.to_thread(tighten_sl_for_news_sync, current_atr)
                
                # 3. รัน Trailing stop ปกติ
                await asyncio.to_thread(apply_trailing_stop_sync)# 1. ดึงค่า ATR มาก่อน
                _, current_atr = await asyncio.to_thread(get_market_data, bars=150)
                if current_atr:
                    # 2. เช็คบีบ SL หนีข่าว (Option C)
                    await asyncio.to_thread(tighten_sl_for_news_sync, current_atr)
                
                # 3. รัน Trailing stop ปกติ
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
