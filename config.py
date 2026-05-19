"""
config.py
E61c設定値
"""

import os
import pytz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ICON_DIR = os.path.join(BASE_DIR, "weather_icons")
LOG_FILE = os.path.join(BASE_DIR, "displayraspi_log.txt")
CACHE_FILE = os.path.join(BASE_DIR, "weather_cache.json")

AIRPORT_CONFIG = {
        "narita": {
            "office_code": "120000",
            "area_codes": ("1221100", "120010"),   # 成田市 + 千葉県北西部（warning用）
            "latitude": 35.7651,
            "longitude": 140.3854,
            "name": "成田空港"
        },

        "haneda": {
            "office_code": "130000",
            # 大田区 + 東京地方
            "area_codes": ("1311100", "130010"),
            "latitude": 35.5494,
            "longitude": 139.7798,
            "name": "羽田空港"
        },

        "centrair": {
            "office_code": "230000",
            # 常滑市 + 愛知県西部
            "area_codes": ("2321600", "230010"),
            "latitude": 34.8583,
            "longitude": 136.8053,
            "name": "中部国際空港"
        },

        "kanku": {
            "name": "関西国際空港",
            "latitude": 34.4347,
            "longitude": 135.2440,
            "office_code": "270000",
            "area_codes": ["270010"]
        },

        "chitose": {
            "name": "新千歳空港",
            "latitude": 42.7752,
            "longitude": 141.6922,
            "office_code": "016000",
            "area_codes": ["016010"]   # 石狩地方
        },

        "fukuoka": {
            "name": "福岡空港",
            "latitude": 33.5859,
            "longitude": 130.4511,
            "office_code": "400000",
            "area_codes": ["400010"]   # 福岡地方
        },

        "naha": {
            "name": "那覇空港",
            "latitude": 26.1958,
            "longitude": 127.6458,
            "office_code": "471000",
            "area_codes": ["471010"]   # 沖縄本島中南部
        },
}

LATITUDE  = 34.8583
LONGITUDE = 136.8053

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

ROW_LABELS = ["日付", "時刻", "天気", "降水量", "気温", "風速"]
WEEK_ROW_LABELS = ["日付", "天気", "降水確率", "気温"]

JST = pytz.timezone("Asia/Tokyo")

AIRPORT_NAME = "中部国際空港"

CODE_MAPPING = {
    0: "100", 1: "100", 2: "101", 3: "200",
    45: "200", 48: "200",
    51: "202", 53: "202", 55: "202",
    61: "300", 63: "302", 65: "302",
    71: "400", 73: "400", 75: "400",
    77: "400", 80: "302", 81: "302",
    82: "302", 85: "400", 86: "400",
    95: "302", 96: "400", 99: "400"
}
