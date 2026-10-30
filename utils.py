"""
utils.py
E61c 完全互換ユーティリティ
"""

import datetime
import functools
import time
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
# フォントキャッシュ（Pi Zero W 向け最適化）
# =========================
_font_cache: dict = {}

def get_font(path: str, size: int, bold: bool = False) -> pygame.font.Font:
    """フォントオブジェクトをキャッシュして返す。毎フレーム生成を防ぐ。"""
    key = (path, size, bold)
    if key not in _font_cache:
        f = pygame.font.Font(path, size)
        if bold:
            f.set_bold(True)
        _font_cache[key] = f
    return _font_cache[key]


def clear_font_cache() -> None:
    """pygame.quit() のあとに古いフォントを使うと落ちる（Segmentation fault）ので、作り直す前に捨てる"""
    _font_cache.clear()


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
def get_cpu_temp():
    """本体（CPU）温度 ℃。読めなければ None（Pi 以外など）"""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000
    except (OSError, ValueError):
        return None


def format_cpu_status(cpu, temp):
    """画面右上の CPU 使用率と本体温度（例「3% / 52℃」）。温度が読めなければ使用率だけ"""
    return f"{cpu:.0f}%" + (f" / {temp:.0f}℃" if temp is not None else "")


def get_last_ip_octet():

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.split(".")[-1]
    except Exception:
        return "?"


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def make_qr_surface(url: str, max_size: int = 54):
    """QRコードをpygame.Surfaceとして生成する（Pillowなし）。失敗時はNoneを返す。"""
    try:
        import qrcode as _qrcode
        qr = _qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        n = len(matrix)
        pixel = max(1, max_size // n)
        size = n * pixel
        surf = pygame.Surface((size, size))
        surf.fill((255, 255, 255))
        for row_i, row in enumerate(matrix):
            for col_i, val in enumerate(row):
                if val:
                    pygame.draw.rect(
                        surf, (0, 0, 0),
                        (col_i * pixel, row_i * pixel, pixel, pixel)
                    )
        return surf
    except Exception:
        return None


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
        dt = dt.replace(tzinfo=JST)

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
TABLE_LAYOUT = "fixed"     # 今日の天気の表の形（main01 が config.json の table_layout で設定。table_cols.py）


def get_target_datetimes(now=None, layout=None):
    """今日の天気の表のもとになる 3 時間ごとの時刻（日本時間）。表の形（table_cols.LAYOUTS）ごとに
      fixed  : 朝 6 時〜翌朝 9 時の 10 個（6 時より前は前の日の 6 時から）。今までの表
      insert : 6:00〜23:59 は今日の 6 時から、0:00〜5:59 は今日の 0 時から 9 個（「今」の列を割り込ませる）
      now    : 今の 3 時間帯の始まりから 12 個（取得から次の取得までたっても 10 列が足りるよう多めに）"""
    layout = layout or TABLE_LAYOUT
    now = (now or datetime.datetime.now(JST)).astimezone(JST).replace(minute=0, second=0, microsecond=0)
    if layout == "now":
        start, n = now.replace(hour=now.hour // 3 * 3), 12
    elif layout == "insert":
        start, n = now.replace(hour=6 if now.hour >= 6 else 0), 9
    else:
        start, n = now.replace(hour=6) - datetime.timedelta(days=0 if now.hour >= 6 else 1), 10
    return [start + datetime.timedelta(hours=3 * i) for i in range(n)]


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


@functools.lru_cache(maxsize=32)
def sun_times(date: datetime.date, latitude: float, longitude: float):
    loc = LocationInfo(name="Airport", region="JP", timezone="Asia/Tokyo", latitude=latitude, longitude=longitude)
    s = sun(loc.observer, date=date, tzinfo=JST)
    return s["sunrise"], s["sunset"]


def is_night(dt: datetime.datetime, latitude: float, longitude: float) -> bool:
    """dt がその日の日の出前 or 日の入り以降なら True"""
    dt = dt.replace(tzinfo=JST) if dt.tzinfo is None else dt.astimezone(JST)
    sunrise, sunset = sun_times(dt.date(), latitude, longitude)
    return dt < sunrise or dt >= sunset

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


def wait_ms(ms: int) -> None:
    """待機。pygame.time.wait（SDL_Delay）は C の中で眠るため SIGTERM の処理が待機明けまで遅れる。
    time.sleep ならシグナルで即座に起きてハンドラが動く（停止が最大 10 秒遅れるのを防ぐ）。"""
    time.sleep(max(0, ms) / 1000)
