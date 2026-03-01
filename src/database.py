"""
Database module for the trading bot.
Handles SQLite database operations for logging trades.
"""

import sqlite3
from datetime import datetime
from src.config import DB_NAME, logger


def setup_database():
    """Initialize the database and create the trade_logs table if it doesn't exist."""
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
    """Log a trade to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO trade_logs (timestamp, symbol, action, price, sl, tp, ai_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (current_time_str, symbol, action, price, sl, tp, reason))
    conn.commit()
    conn.close()

def setup_news_database():
    """Create table for logging news events."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_time DATETIME,
            currency TEXT,
            impact TEXT,
            title TEXT,
            UNIQUE(news_time, title) 
        )
    ''')
    conn.commit()
    conn.close()

def log_news_event(news_time, currency, impact, title):
    """Log a fetched news event into the database. IGNORE if already exists."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO news_logs (news_time, currency, impact, title)
            VALUES (?, ?, ?, ?)
        ''', (news_time.strftime("%Y-%m-%d %H:%M:%S"), currency, impact, title))
        conn.commit()
    except Exception as e:
        logger.error("Failed to log news to DB: %s", e)
    finally:
        conn.close()
