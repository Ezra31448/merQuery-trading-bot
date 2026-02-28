"""
MT5 Client module for the trading bot.
Provides thread-safe wrappers for MetaTrader5 API calls.
"""

import threading
import MetaTrader5 as mt5
from src.config import MAGIC_NUMBER, ACTIVE_AI, logger


# ==========================================
# Concurrency primitives
# ==========================================
# mt5_lock: protects raw MT5 API calls (socket/connection level). 
# Use around mt5.order_send, mt5.positions_get, mt5.copy_rates_from_pos, 
# mt5.symbol_info_tick, mt5.history_deals_get, mt5.symbol_info
mt5_lock = threading.Lock()


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
    """Get the point value for a given symbol."""
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
