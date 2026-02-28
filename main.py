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

import asyncio
import signal
import MetaTrader5 as mt5
from src.config import BAR_WATCHER_POLL_S, TRAILING_INTERVAL_S, logger
from src.database import setup_database
from src.bot import bar_watcher_worker, trailing_stop_worker


async def main_async():
    """
    Main async function that initializes the bot and manages workers.
    Creates trading_semaphore for business logic concurrency control.
    """
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
    bar_task = asyncio.create_task(bar_watcher_worker(BAR_WATCHER_POLL_S, stop_event, trading_semaphore))
    trailing_task = asyncio.create_task(trailing_stop_worker(TRAILING_INTERVAL_S, stop_event, trading_semaphore))

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
