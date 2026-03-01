"""
News Filter module.
Handles fetching high-impact economic news and determining blackout windows.
"""

import requests
import json
from datetime import datetime, timedelta, timezone
from src.config import logger
from src.database import log_news_event

# Cache เพื่อไม่ให้ยิง API รัวๆ ทุก 1 วินาที (ดึงใหม่ทุก 4 ชั่วโมงก็พอ)
NEWS_CACHE = []
LAST_FETCH_TIME = None
CACHE_DURATION_HOURS = 4

# ตั้งค่า News Filter ตามสเปค
TARGET_CURRENCY = "USD"
TARGET_IMPACT = "High"
BLACKOUT_MINUTES_BEFORE = 30
BLACKOUT_MINUTES_AFTER = 30

def fetch_this_week_news():
    """Fetch JSON data from ForexFactory community API feed."""
    global NEWS_CACHE, LAST_FETCH_TIME
    
    now_utc = datetime.now(timezone.utc)
    
    # ถ้ามี Cache และยังไม่หมดอายุ ให้ใช้ของเดิม
    if LAST_FETCH_TIME and (now_utc - LAST_FETCH_TIME).total_seconds() < (CACHE_DURATION_HOURS * 3600):
        return NEWS_CACHE

    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    headers = {"User-Agent": "Mozilla/5.0"} # ใส่เพื่อป้องกันการโดนบล็อก

    try:
        logger.info("Fetching fresh economic calendar from ForexFactory...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        events = response.json()
        
        filtered_news = []
        for event in events:
            # กรองเฉพาะ USD และ High Impact
            if event.get("country") == TARGET_CURRENCY and event.get("impact") == TARGET_IMPACT:
                # แปลงเวลาข่าวที่เป็น string (เช่น "2026-03-01T10:00:00-05:00") เป็น UTC datetime object
                try:
                    event_time_utc = datetime.fromisoformat(event["date"]).astimezone(timezone.utc)
                    
                    news_item = {
                        "title": event.get("title"),
                        "time_utc": event_time_utc,
                        "impact": TARGET_IMPACT,
                        "currency": TARGET_CURRENCY
                    }
                    filtered_news.append(news_item)
                    
                    # บันทึกลง Database
                    log_news_event(event_time_utc, TARGET_CURRENCY, TARGET_IMPACT, event.get("title"))
                    
                except ValueError:
                    continue
        
        NEWS_CACHE = filtered_news
        LAST_FETCH_TIME = now_utc
        logger.info("Successfully fetched and cached %d High Impact %s news events.", len(filtered_news), TARGET_CURRENCY)
        return NEWS_CACHE

    except Exception as e:
        logger.error("Error fetching news: %s", e)
        return NEWS_CACHE # ถ้าดึงล้มเหลว ให้ใช้ของเก่าใน Cache ไปก่อน

def get_imminent_news():
    """เช็คว่ามีข่าวแรงกำลังจะมาในกรอบเวลา Blackout หรือพึ่งผ่านไปหรือไม่"""
    events = fetch_this_week_news()
    now_utc = datetime.now(timezone.utc)
    
    for event in events:
        news_time = event["time_utc"]
        time_diff_minutes = (news_time - now_utc).total_seconds() / 60.0
        
        # เช็คว่าอยู่ในช่วง 30 นาทีก่อนข่าวออก หรือ 30 นาทีหลังข่าวออก หรือไม่
        if -BLACKOUT_MINUTES_AFTER <= time_diff_minutes <= BLACKOUT_MINUTES_BEFORE:
            return event, time_diff_minutes
            
    return None, None