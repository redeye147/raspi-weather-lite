"""
utils.py
E61c 完全互換ユーティリティ
"""

import datetime
import pytz
import socket
import pygame
import requests
from requests.adapters import HTTPAdapter, Retry
from astral.sun import sun
from astral import LocationInfo
import datetime

# =========================
# JST
# =========================
#JST = pytz.timezone("Asia/Tokyo")
from zoneinfo import ZoneInfo
JST = ZoneInfo("Asia/Tokyo")

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


# =========================
# セッション（リトライ付き）
# =========================
def session_with_retry():

    s = requests.Session()

    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504]
    )

    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))

    s.headers.update({
        "User-Agent": "raspi-weather-display/1.0"
    })

    return s


# =========================
# IP取得
# =========================
def get_last_ip_octet():

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.split(".")[-1]
    except Exception:
        return "?"


# =========================
# ISO変換
# =========================
def iso_dump_default(o):

    if isinstance(o, datetime.datetime):
        if o.tzinfo is None:
            o = JST.localize(o)
        return o.astimezone(JST).isoformat()

    return o


def iso_parse_datetime(s):

    dt = datetime.datetime.fromisoformat(s)

    if dt.tzinfo is None:
        dt = JST.localize(dt)

    return dt


# =========================
# フォント検索
# =========================
def pick_font():

    candidates = [
        "NotoSansCJKjp",
        "Noto Sans C JK JP",
        "NotoSansCJK-Regular.ttc",
        "IPAGothic",
        "VL-Gothic-Regular",
        "TakaoPGothic",
        "DejaVuSans"
    ]

    return pygame.font.match_font(candidates)


# =========================
# 曜日取得
# =========================
def get_japanese_weekday(date_obj):

    return WEEKDAY_JP[date_obj.weekday()]


# =========================
# 表示対象時間生成
# =========================
def get_target_datetimes():

    now = datetime.datetime.now(JST).replace(minute=0, second=0, microsecond=0)

    # ★6時基準：6時未満なら「昨日」を基準日にする
    if now.hour >= 6:
        base_date = now.date()
    else:
        base_date = now.date() - datetime.timedelta(days=1)

    tlist = [
        datetime.datetime.combine(
            base_date,
            datetime.time(h, 0)
        )
        for h in [6, 9, 12, 15, 18, 21]
    ]

    next_day = base_date + datetime.timedelta(days=1)

    tlist += [
        datetime.datetime.combine(
            next_day,
            datetime.time(h, 0)
        )
        for h in [0, 3, 6, 9]
    ]

    return tlist

# =========================
# 06時日付表示制御
# =========================
def should_display_date(hour_str):

    if not hasattr(should_display_date, "seen_06"):
        should_display_date.seen_06 = False

    if hour_str == "06":
        if not should_display_date.seen_06:
            should_display_date.seen_06 = True
            return True
        return False

    return hour_str == "00"

# =========================
# 0７　今日の日の出/日の入り
# =========================
def get_sunrise_sunset_str(latitude: float, longitude: float, tz=JST):
    """
    今日の日の出/日の入り（HH:MM）を返す
    """
    loc = LocationInfo(name="Airport", region="JP", timezone=str(tz), latitude=latitude, longitude=longitude)
    s = sun(loc.observer, date=datetime.date.today(), tzinfo=tz)
    return s["sunrise"].strftime("%H:%M"), s["sunset"].strftime("%H:%M")

# =========================
# 0８　空港現場向け 改良版サマリー
# =========================
def build_work_summary(hourly):

    warnings = []

    for item in hourly[:6]:   # 直近4時間

        hour = item["hour"]
        wind = item.get("wind_val", 0)

        # --- 強風 ---
        try:
            wind = float(item.get("wind_val", 0))
        except(TypeError, ValueError):
            wind = 0

        if wind >= 14:
            warnings.append(f"{hour}時 強風({int(wind)}m) 高所注意")
        elif wind >= 10:
            warnings.append(f"{hour}時 風強({int(wind)}m)")


        # --- 雨 ---
        try:
            rain = float(str(item["pop"]).replace("mm",""))
            if rain >= 5:
                warnings.append(f"{hour}時 強雨({rain}mm)")
            elif rain >= 3:
                warnings.append(f"{hour}時 雨({rain}mm)")
        except:
            pass

        # --- 高温 ---
        temp = item.get("temp_val")

        if not isinstance(temp, (int, float)):
            temp = None

        if temp is not None:
            if temp >= 34:
                warnings.append(f"{hour}時 熱中症警戒({temp}℃)")
            elif temp >= 30:
                warnings.append(f"{hour}時 高温({temp}℃)")

            # --- 凍結 ---
            if temp <= 0:
                warnings.append(f"{hour}時 凍結注意({temp}℃)")

    if not warnings:
        return "特記事項なし"

    return " / ".join(warnings)
