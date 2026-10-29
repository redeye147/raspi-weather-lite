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
# スクリーンショットの依頼ファイル（tools/screenshot.py が保存先を書き、表示プログラムが画面を保存して消す）
SCREENSHOT_REQUEST = os.path.join(BASE_DIR, "cache", "screenshot_request")
BASE_FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"

AIRPORT_CONFIG = {
        "narita": {
            "runway": {"ends": ("16", "34"), "deg": 337},   # 風の矢印の下に描く滑走路（2 つ目の番号の向き・真方位のおおよそ）
            "icao": "RJAA",          # 航空気象（METAR/TAF）の空港コード
            "office_code": "120000",
            "area_codes": ("1221100", "120010"),   # 成田市 + 千葉県北西部（warning用）
            "latitude": 35.7651,
            "longitude": 140.3854,
            "name": "成田空港"
        },

        "haneda": {
            "runway": {"ends": ("16", "34"), "deg": 337},   # 風の矢印の下に描く滑走路（2 つ目の番号の向き・真方位のおおよそ）
            "icao": "RJTT",          # 航空気象（METAR/TAF）の空港コード
            "office_code": "130000",
            # 大田区 + 東京地方
            "area_codes": ("1311100", "130010"),
            "latitude": 35.5494,
            "longitude": 139.7798,
            "name": "羽田空港"
        },

        "centrair": {
            "runway": {"ends": ("18", "36"), "deg": 356},   # 風の矢印の下に描く滑走路（2 つ目の番号の向き・真方位のおおよそ）
            "icao": "RJGG",          # 航空気象（METAR/TAF）の空港コード
            "office_code": "230000",
            # 常滑市 + 愛知県西部
            "area_codes": ("2321600", "230010"),
            "latitude": 34.8583,
            "longitude": 136.8053,
            "name": "中部国際空港"
        },

        "kanku": {
            "runway": {"ends": ("06", "24"), "deg": 238},   # 風の矢印の下に描く滑走路（2 つ目の番号の向き・真方位のおおよそ）
            "icao": "RJBB",          # 航空気象（METAR/TAF）の空港コード
            "name": "関西国際空港",
            "latitude": 34.4347,
            "longitude": 135.2440,
            "office_code": "270000",
            "area_codes": ["270010"]
        },

        "chitose": {
            "runway": {"ends": ("18", "36"), "deg": 351},   # 風の矢印の下に描く滑走路（2 つ目の番号の向き・真方位のおおよそ）
            "icao": "RJCC",          # 航空気象（METAR/TAF）の空港コード
            "name": "新千歳空港",
            "latitude": 42.7752,
            "longitude": 141.6922,
            "office_code": "016000",
            "area_codes": ["016010"]   # 石狩地方
        },

        "fukuoka": {
            "runway": {"ends": ("16", "34"), "deg": 337},   # 風の矢印の下に描く滑走路（2 つ目の番号の向き・真方位のおおよそ）
            "icao": "RJFF",          # 航空気象（METAR/TAF）の空港コード
            "name": "福岡空港",
            "latitude": 33.5859,
            "longitude": 130.4511,
            "office_code": "400000",
            "area_codes": ["400010"]   # 福岡地方
        },

        "naha": {
            "runway": {"ends": ("18", "36"), "deg": 356},   # 風の矢印の下に描く滑走路（2 つ目の番号の向き・真方位のおおよそ）
            "icao": "ROAH",          # 航空気象（METAR/TAF）の空港コード
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

ROW_LABELS = ["日付", "時刻", "天気", "降水量", "気　温", "風　速"]
WEEK_ROW_LABELS = ["日付", "天気", "降水確率", "気温"]

JST = pytz.timezone("Asia/Tokyo")

AIRPORT_NAME = "中部国際空港"

# Open-Meteo（WMO）の天気コード → 気象庁の天気コード（アイコン weather_icons/{コード}.png）
# 表示プログラムの CPU 使用率（直近 1 分の平均）を診断ページへ渡すファイル。/run はメモリ上（SD に書かない・再起動で消える）
STATUS_FILE = "/run/raspi-weather/status.json"

CODE_MAPPING = {
    0: "100", 1: "100", 2: "101", 3: "200",       # 快晴・晴れ・晴れ時々曇り・曇り
    45: "209", 48: "209",                         # 霧
    51: "202", 53: "202", 55: "202",              # 霧雨
    56: "202", 57: "202",                         # 凍る霧雨（以前は抜けていて「?」になっていた）
    61: "300", 63: "302", 65: "306",              # 雨（弱・並・強 → 強は大雨）
    66: "300", 67: "306",                         # 凍る雨（以前は抜けていて「?」になっていた）
    71: "400", 73: "400", 75: "405", 77: "400",   # 雪（強 → 大雪）・霧雪
    80: "302", 81: "302", 82: "306",              # にわか雨（激しい → 大雨）
    85: "400", 86: "405",                         # にわか雪（強 → 大雪）
    95: "350", 96: "350", 99: "350",              # 雷雨（96・99 はひょうを伴う）→ 雨で雷
}
