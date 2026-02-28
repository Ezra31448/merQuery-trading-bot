"""
Analysis module for the trading bot.
Handles market data retrieval, indicator calculations, and AI decision making.
"""

import json
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
from openai import OpenAI
from src.config import SYMBOL, ACTIVE_AI, DEEPSEEK_API_KEY, GLM_API_KEY, logger
from src.mt5_client import mt5_lock, ensure_mt5_connected


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


def get_ai_decision(market_context):
    """Get trading decision from AI (DEEPSEEK or GLM)."""
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
