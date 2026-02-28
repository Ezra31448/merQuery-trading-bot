"""
Configuration module for the trading bot.
Loads environment variables, defines constants, and sets up logging.
"""

import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==========================================
# Configuration Constants
# ==========================================

# Trading parameters
SYMBOL = "XAUUSD"
LOT_SIZE = 0.01
MAX_SL_POINTS = 500
DB_NAME = "trading_bot.db"

# AI Configuration
ACTIVE_AI = os.getenv("ACTIVE_AI", "GLM")  # "DEEPSEEK" or "GLM"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GLM_API_KEY = os.getenv("GLM_API_KEY")

# Decision Mode: "AI" or "RULE_BASED"
# RULE_BASED is faster, more reliable, and has zero API cost
DECISION_MODE = os.getenv("DECISION_MODE", "AI")  # "AI" or "RULE_BASED"

# Risk Management
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "50"))
MAGIC_NUMBER = int(os.getenv("MAGIC_NUMBER", "100100"))

# Trailing Stop Configuration
TRAILING_ENABLE = True
TRAILING_MIN_PROFIT_ATR = float(os.getenv("TRAILING_MIN_PROFIT_ATR", "0.5"))   # start trailing when profit >= 0.5 ATR
TRAILING_DISTANCE_ATR = float(os.getenv("TRAILING_DISTANCE_ATR", "0.4"))     # trailing distance = ATR * factor

# Worker Intervals
BAR_WATCHER_POLL_S = float(os.getenv("BAR_WATCHER_POLL_S", "1.0"))
TRAILING_INTERVAL_S = float(os.getenv("TRAILING_INTERVAL_S", "2.0"))

# ==========================================
# Logging Setup
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
