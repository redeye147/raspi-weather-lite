"""
fetch_weather.py
E61c 完全互換データ取得モジュール
ロジックは一切変更しない
"""

import os
import json
import datetime
import logging
import threading
import time
from collections import defaultdict

from config import (
    LATITUDE,
    LONGITUDE,
    CACHE_FILE,
    CODE_MAPPING,
    WEEKDAY_JP
)


from utils import (
    JST,
    session_with_retry,
    iso_dump_default,
    iso_parse_datetime,
    get_target_datetimes
)

SESS = session_with_retry()


# =====================================================
# Open-Meteo取得（E61cそのまま）
# =====================================================
# 同じ種類の中の強さ（1 弱・2 並・3 強）。コードの大小は強さの順になっていない（例：にわか雨 80 は弱いのに強い雨 65 より大きい）
_INTENSITY = {
    51: 1, 53: 2, 55: 3, 56: 1, 57: 3,                     # 霧雨・凍る霧雨
    61: 1, 63: 2, 65: 3, 66: 1, 67: 3, 80: 1, 81: 2, 82: 3,  # 雨・凍る雨・にわか雨
    71: 1, 73: 2, 75: 3, 77: 1, 85: 1, 86: 3,              # 雪・霧雪・にわか雪
    95: 1, 96: 2, 99: 3,                                   # 雷雨（96・99 はひょう）
}


def weather_severity(code):
    """WMO の天気コードの悪さ（大きいほど悪い）：雷 > 雪 > 雨 > 霧雨 > 霧 > 曇り > 晴れ。同じ種類なら強い方
    （3 時間のうち強い雨・強い雪があれば、大雨・大雪のアイコンになるように）"""
    if code is None:
        return (-1, -1, -1)
    if code >= 95:
        rank = 6                                   # 雷
    elif 71 <= code <= 77 or code in (85, 86):
        rank = 5                                   # 雪
    elif 61 <= code <= 67 or 80 <= code <= 82:
        rank = 4                                   # 雨・にわか雨
    elif 51 <= code <= 57:
        rank = 3                                   # 霧雨
    elif code in (45, 48):
        rank = 2                                   # 霧
    else:
        rank = 1 if code > 0 else 0                # 曇り〜晴れ（0 快晴・1〜3 晴れ時々曇り〜曇り）
    return (rank, _INTENSITY.get(code, 0), code)


OPENMETEO_MODEL = "jma_seamless"   # 今日の天気（3 時間ごと）は気象庁の数値予報モデルを使う
def fetch_weather_openmeteo(latitude=LATITUDE, longitude=LONGITUDE):

    # 既存キャッシュを読む（あれば）
    cached_hourly = {}
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
                for ch in cache.get("hourly", []):
                    # key: "YYYY-MM-DDTHH:00"
                    dt = ch.get("datetime")
                    if isinstance(dt, str):
                        key = dt[:13] + ":00"  # "YYYY-MM-DDTHH:00"
                        cached_hourly[key] = ch
    except Exception:
        cached_hourly = {}

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={latitude}&longitude={longitude}"
        "&hourly=weathercode,precipitation,temperature_2m,windspeed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"
        "&timezone=Asia/Tokyo"
    )

    # 気象庁の数値予報モデル（日本付近は約 5km・1 時間ごとの MSM、その先は GSM）を指定して取得。
    # 使えなかったとき（Open-Meteo 側の障害・仕様変更）は、指定なし（Open-Meteo の自動選択）で取り直す
    try:
        r = SESS.get(url + f"&models={OPENMETEO_MODEL}", timeout=10)
        r.raise_for_status()
        data = r.json()
        if not (data.get("hourly") or {}).get("time"):
            raise ValueError("時間ごとのデータが空")
    except Exception as e:
        logging.warning(f"Open-Meteo: {OPENMETEO_MODEL} で取得できず → 標準のモデルで取り直し: {e}")
        r = SESS.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

    # -------- hourly ----------
    ht = data.get("hourly", {}) or {}
    h_times = ht.get("time", []) or []

    def mkm(hkey):
        vals = ht.get(hkey, []) or []
        return {
            t: vals[i]
            for i, t in enumerate(h_times)
            if i < len(vals)
        }

    H_WC   = mkm("weathercode")
    H_PREC = mkm("precipitation")
    H_TMP  = mkm("temperature_2m")
    H_WND  = mkm("windspeed_10m")

    targets = get_target_datetimes()

    hourly = []

    for dt in targets:
        ts = dt.astimezone(JST).strftime("%Y-%m-%dT%H:00")

        if ts in H_WC:
            # 列は 3 時間（例 09 → 09〜12 時）。現場の安全のため、途中の雨・強風を見落とさないよう
            # 天気は 3 時間のうちいちばん悪い天気、降水量はいちばん多い 1 時間の量（1 時間あたり。合計しない）、
            # 風速はいちばん強い値。気温は真ん中（10:00 と 11:00 の平均＝ 10:30 ごろ）。
            # Open-Meteo の降水量・天気は「その時刻までの 1 時間」なので 10:00・11:00・12:00 の値が 09〜12 時を表す。
            # 気温・風速は「その時刻の値」なので 09:00・10:00・11:00。データが無い時刻は除き、全部無ければ列の時刻の値
            def at(h):
                return (dt + datetime.timedelta(hours=h)).astimezone(JST).strftime("%Y-%m-%dT%H:00")

            def pick(table, hours):
                return [table[k] for k in map(at, hours) if table.get(k) is not None]

            wcs = pick(H_WC, (1, 2, 3)) or [H_WC[ts]]
            wcode = CODE_MAPPING.get(max(wcs, key=weather_severity), "999")
            precs = pick(H_PREC, (1, 2, 3))
            prec = max(precs) if precs else H_PREC.get(ts, 0)
            winds = pick(H_WND, (0, 1, 2))
            windkph = max(winds) if winds else H_WND.get(ts, 0)
            temps = pick(H_TMP, (1, 2))
            tempC = sum(temps) / len(temps) if temps else H_TMP.get(ts, 0)

            hourly.append({
                "datetime": dt,
                "date": dt.strftime("%-m/%-d"),
                "hour": dt.strftime("%H"),
                "code": wcode,
                "pop": f"{prec:.1f}mm" if prec is not None else "--",
                "temp_val": round(tempC) if tempC is not None else None,
                "temp": f"{round(tempC)}℃" if tempC is not None else "--",
                "wind_val": round(windkph / 3.6) if windkph is not None else None,
                "wind": f"{round(windkph / 3.6)}m" if windkph is not None else "--",
            })

        elif ts in cached_hourly:
            # ★ API未更新ならキャッシュを使用
            ch = cached_hourly[ts]
            hourly.append({
                "datetime": dt,
                "date": dt.strftime("%-m/%-d"),
                "hour": dt.strftime("%H"),
                "code": ch.get("code", "999"),
                "pop": ch.get("pop", "--"),
                "temp_val": ch.get("temp_val"),
                "temp": ch.get("temp", "--"),
                "wind_val": ch.get("wind_val"),
                "wind": ch.get("wind", "--"),
            })

        else:
            # ★ 本当に無い場合のみダミー
            hourly.append({
                "datetime": dt,
                "date": dt.strftime("%-m/%-d"),
                "hour": dt.strftime("%H"),
                "code": "999",
                "pop": "--",
                "temp_val": None,
                "temp": "--",
                "wind_val": None,
                "wind": "--",
            })

        # -------- daily ----------
    dd = data.get("daily", {}) or {}
    d_times = dd.get("time", []) or []

    daily = []

    for i, t in enumerate(d_times):

        def val(key):
            v = dd.get(key) or []
            return v[i] if i < len(v) else None

        # 気象庁モデルは降水確率を出さない（null）。値が無い項目は「-」にして、その日は捨てない
        wc, pop = val("weathercode"), val("precipitation_probability_max")
        tmax, tmin = val("temperature_2m_max"), val("temperature_2m_min")

        d = datetime.datetime.strptime(t, "%Y-%m-%d").date()

        weekday = WEEKDAY_JP[d.weekday()]

        daily.append({
            "date": d.isoformat(),
            "day": f"{d.day}（{weekday}）",
            "code": CODE_MAPPING.get(wc, "999"),
            "pop": f"{pop}%" if pop is not None else "-%",
            "temp": f"{round(tmax)}/{round(tmin)}" if tmax is not None and tmin is not None else "-/-",
        })

        if len(daily) >= 7:      # 今日から 7 日分。JMA（明日から 5 日分）の補完に 6 日目まで要る。表示は 5 日（呼び出し側）
            break

    # -------- キャッシュ保存 ----------
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)

        with open(CACHE_FILE, "w") as f:
            json.dump(
                {"hourly": hourly, "daily": daily[:5]},
                f,
                default=iso_dump_default,
                ensure_ascii=False
            )
    except:
        pass
    return hourly, daily


# =====================================================
# JMA取得（E61cそのまま）
# =====================================================
def fetch_weather_jma(office_code, target_area_codes):

    url = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{office_code}.json"

    r = SESS.get(url, timeout=10)
    r.raise_for_status()

    arr = r.json()

    daily_codes = {}
    daily_pops = defaultdict(list)
    daily_temps = defaultdict(list)

    def _pick_area_index(area_list):
        code_to_idx = {a["area"]["code"]: i for i, a in enumerate(area_list)}
        for ac in target_area_codes:
            if ac in code_to_idx:
                return code_to_idx[ac]
        return 0

    def _collect(block):
        """1 つの予報（短期 or 週間）の timeSeries を、中身のキーで見分けて集める。
        短期: [天気(weatherCodes)] [降水確率 6 時間ごと(pops)] [気温(temps)]
        週間: [天気と降水確率(weatherCodes・pops)] [最高・最低気温(tempsMax・tempsMin)]
        （以前は「2 番目は降水確率・3 番目は気温」と決め打ちしていて、週間の降水確率と気温を読めていなかった）"""
        for ts in block.get("timeSeries", []):
            areas = ts.get("areas", [])
            if not areas:
                continue
            area = areas[_pick_area_index(areas)]
            days = [iso_parse_datetime(t).astimezone(JST).date() for t in ts.get("timeDefines", [])]

            def values(key):
                for d, v in zip(days, area.get(key, [])):
                    if v not in (None, "", "-"):
                        yield d, v

            for d, v in values("weatherCodes"):
                daily_codes.setdefault(d, str(v))          # 短期（先に来る）を優先
            for d, v in values("pops"):
                daily_pops[d].append(int(v))
            for key in ("temps", "tempsMax", "tempsMin"):
                for d, v in values(key):
                    daily_temps[d].append(int(v))

    for block in arr:
        _collect(block)

    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)

    candidate_days = sorted(set(
        list(daily_codes.keys()) +
        list(daily_pops.keys()) +
        list(daily_temps.keys())
    ))

    candidate_days = [
        d for d in candidate_days
        if d >= tomorrow
    ][:5]

    daily = []

    for d in candidate_days:

        weekday = WEEKDAY_JP[d.weekday()]

        code = daily_codes.get(d, "100")
        pop_str = (
            f"{max(daily_pops[d])}%"
            if daily_pops.get(d)
            else "-%"
        )

        if daily_temps.get(d):
            tmin = min(daily_temps[d])
            tmax = max(daily_temps[d])
            temp_str = f"{tmax}/{tmin}"
        else:
            temp_str = "-/-"

        daily.append({
            "date": d.isoformat(),
            "day": f"{d.day}（{weekday}）",
            "code": str(code),
            "pop": pop_str,
            "temp": temp_str
        })

    return [], daily


# =====================================================
# キャッシュ読込
# =====================================================
def load_cached_weather():

    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)

        for item in data.get("hourly", []):
            if isinstance(item.get("datetime"), str):
                item["datetime"] = iso_parse_datetime(item["datetime"])

        return data.get("hourly", []), data.get("daily", [])

    except:
        return [], []


# ==========================================================
# バックグラウンド天気取得クラス（main01.py から移動。中身は変更なし）
# ==========================================================
FETCH_TIMEOUT = 60   # Pi Zero W は天気 2 か所の取得・読み込みに 30 秒を超えることがあった（2026-10-13 の 115）


# ==========================================================
# バックグラウンド天気取得クラス
# ==========================================================
class WeatherFetcher:
    def __init__(self, cfg, args):
        self._cfg = cfg
        self._args = args
        self._thread = None
        self._result = None
        self._ok = False
        self._event = threading.Event()
        self._started_at = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._result = None
        self._ok = False
        self._event.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            cfg, args = self._cfg, self._args
            if args.jma:
                hourly, om_daily = fetch_weather_openmeteo(cfg["latitude"], cfg["longitude"])
                _, jma_daily = fetch_weather_jma(cfg["office_code"], cfg["area_codes"])
                om_map = {d["date"]: d for d in om_daily}
                daily = []
                for d in jma_daily[:5]:
                    od = om_map.get(d.get("date"))
                    if od:
                        if d.get("pop") in ("-%", "", None):
                            d["pop"] = od.get("pop")
                        if d.get("temp") in ("-/-", "", None):
                            d["temp"] = od.get("temp")
                    daily.append(d)
            else:
                hourly, daily = fetch_weather_openmeteo(cfg["latitude"], cfg["longitude"])
                daily = daily[:5]
            self._result = (hourly, daily)
            self._ok = True
        except Exception as e:
            logging.error(f"WeatherFetcher error: {e}")
            self._ok = False
        finally:
            self._event.set()

    def poll(self):
        if self._thread is None:
            return False, None, None, None
        if self._event.is_set():
            self._thread = None
            if self._ok and self._result:
                return True, self._result[0], self._result[1], True
            return True, None, None, False
        if time.time() - self._started_at > FETCH_TIMEOUT:
            logging.error(f"WeatherFetcher: タイムアウト ({FETCH_TIMEOUT}秒) スレッドを放棄")
            self._thread = None
            return True, None, None, False
        return False, None, None, None

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()
