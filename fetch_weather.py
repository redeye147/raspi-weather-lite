"""
fetch_weather.py
E61c 完全互換データ取得モジュール
ロジックは一切変更しない
"""

import os
import json
import datetime
import logging
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
def fetch_weather_openmeteo(latitude=LATITUDE, longitude=LONGITUDE):
    
    print("=== FETCH START ===", flush=True)

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
            wcode = CODE_MAPPING.get(H_WC[ts], "999")

            tempC = H_TMP.get(ts, 0)
            windkph = H_WND.get(ts, 0)
            prec = H_PREC.get(ts ,0)   # ← これが必要

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

        #======================


    # -------- daily ----------
    dd = data.get("daily", {}) or {}
    d_times = dd.get("time", []) or []

    daily = []

    for i, t in enumerate(d_times):

        try:
            wc   = dd["weathercode"][i]
            pop  = dd["precipitation_probability_max"][i]
            tmax = dd["temperature_2m_max"][i]
            tmin = dd["temperature_2m_min"][i]
        except:
            continue

        d = datetime.datetime.strptime(t, "%Y-%m-%d").date()

        weekday = WEEKDAY_JP[d.weekday()]

        daily.append({
            "date": d.isoformat(),
            "day": f"{d.day}（{weekday}）",
            "code": CODE_MAPPING.get(wc, "999"),
            "pop": f"{pop}%",
            "temp": f"{round(tmax)}/{round(tmin)}",
        })

        if len(daily) >= 5:
            break

    # -------- キャッシュ保存 ----------
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)

        with open(CACHE_FILE, "w") as f:
            json.dump(
                {"hourly": hourly, "daily": daily},
                f,
                default=iso_dump_default,
                ensure_ascii=False
            )
    except:
        pass
    #fetch_weather_openmeteo() の最後あたりに一時的に：
    print("NOW:", datetime.datetime.now(JST), "FIRST:", hourly[0]["date"], hourly[0]["hour"], flush=True)
    for h in hourly:
        print(h["date"], h["hour"])

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

        ts_list = block.get("timeSeries", [])

        # weatherCodes
        if len(ts_list) >= 1:
            areas = ts_list[0].get("areas", [])
            if areas:
                ai = _pick_area_index(areas)
                time_def = ts_list[0].get("timeDefines", [])
                wcodes = areas[ai].get("weatherCodes", [])

                for i, t in enumerate(time_def[:len(wcodes)]):
                    d = iso_parse_datetime(t).astimezone(JST).date()
                    daily_codes[d] = str(wcodes[i])

        # pops
        if len(ts_list) >= 2:
            areas = ts_list[1].get("areas", [])
            if areas and "pops" in areas[0]:
                ai = _pick_area_index(areas)
                time_def = ts_list[1].get("timeDefines", [])
                pops = areas[ai].get("pops", [])

                for i, t in enumerate(time_def[:len(pops)]):
                    v = pops[i]
                    if v in (None, "", "-"):
                        continue
                    d = iso_parse_datetime(t).astimezone(JST).date()
                    daily_pops[d].append(int(v))

        # temps
        if len(ts_list) >= 3:
            areas = ts_list[2].get("areas", [])
            ai = _pick_area_index(areas)
            time_def = ts_list[2].get("timeDefines", [])
            temps = areas[ai].get("temps", [])

            for i, t in enumerate(time_def[:len(temps)]):
                v = temps[i]
                if v in (None, "", "-"):
                    continue
                d = iso_parse_datetime(t).astimezone(JST).date()
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
        print("JMA RAW CODE:", d, code) 
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
