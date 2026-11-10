"""
now_page.py
子機用のページ（設定画面と同じウェブサーバーの /now）に出す「今の天気」のデータを作って書き出す（2026-11-03）。

使っていないスマホ・タブレットのブラウザで /now を開いておくと、事務所の出入口などで
「今」（空港の観測・雨雲レーダー）と、この先の 3 時間ごとの予報・警報・雷を見られる。
表示プログラムが画面を描くたびに、メモリ上の /run に小さな JSON を書く（SD には書かない）。
ページはそれを 1 分ごとに読み直すだけなので、天気を取りに行く回数は増えない。
色（風速・気温・降水量）は今のサイネージと同じ決まりで、ここで決めて渡す（ページ側を簡単にする）。
"""

import datetime
import json
import os

NOW_FILE = "/run/raspi-weather/now.json"
AHEAD_COLS = 4                    # 「今」のあとに出す列の数


def _rgb(c):
    return "#%02x%02x%02x" % tuple(c[:3])


def _temp_color(t):
    if not isinstance(t, (int, float)):
        return "#000000"
    if t >= 34:
        return "#800080"
    if t >= 30:
        return "#ff0000"
    if t < 0:
        return "#0000b4"
    if t <= 5:
        return "#64b4ff"
    return "#000000"


def _pop_value(pop):
    try:
        return float(str(pop).replace("mm", ""))
    except (TypeError, ValueError):
        return None


def _icon(item):
    """天気のアイコンの番号（夜の晴れ系は月、晴れの高温は 1000・1000A。画面と同じ決まり）"""
    import weather_draw
    code = str(item.get("code") or "999")
    if weather_draw._is_night_item(item) and code.startswith("1") and len(code) == 3:
        return str(int(code) + 600)
    if code == "100":
        t = item.get("temp_val") or 0
        if t >= 34:
            return "1000A"
        if t >= 30:
            return "1000"
    return code


def _day(item):
    """列の日付（11/4）と曜日。日付が変わる列が分かるように"""
    dt = item.get("datetime")
    if isinstance(dt, str):
        try:
            dt = datetime.datetime.fromisoformat(dt)
        except ValueError:
            dt = None
    if not isinstance(dt, datetime.datetime):
        return "", "", ""
    wd = "月火水木金土日"[dt.weekday()]
    return dt.date().isoformat(), f"{dt.month}/{dt.day}", wd


def column(item):
    import weather_draw
    v = item.get("wind_val")
    day_iso, day_label, weekday = _day(item)
    pop = _pop_value(item.get("pop"))
    wd = item.get("wind_dir")
    return {
        "label": item.get("hour", ""),
        "day": day_iso, "day_label": day_label, "weekday": weekday,
        "date": item.get("date", ""),
        "is_now": bool(item.get("is_now")),
        "icon": _icon(item),
        "pop": None if pop is None else round(pop, 1),
        "pop_strong": pop is not None and pop >= 3.0,
        "temp": item.get("temp_val"),
        "temp_color": _temp_color(item.get("temp_val")),
        "wind": v,
        "wind_color": _rgb(weather_draw.wind_text_color(v)) if isinstance(v, (int, float)) else "#000000",
        "arrow_color": _rgb(weather_draw.wind_arrow_color(v)) if isinstance(v, (int, float)) else "#888888",
        "wind_dir": wd if isinstance(wd, (int, float)) else None,
        "calm": isinstance(v, (int, float)) and (int(v) == 0 or bool(item.get("wind_variable"))),
    }


WEEK_DAYS = 7                     # 週間天気の日数（土日の作業の予定を立てられるよう、1 週間先まで）
WEEKDAYS = "月火水木金土日"


def _max_temp_color(t):
    """週間の最高気温の色（サイネージの１週間の天気と同じ）"""
    if not isinstance(t, int):
        return "#000000"
    if t >= 34:
        return "#800080"
    if t >= 30:
        return "#ff0000"
    if t >= 28:
        return "#ffa500"
    return "#000000"


def week_day(d, today=None):
    """１週間の天気の 1 日（fetch_weather の daily の 1 件）を、ページで使う形に"""
    try:
        day = datetime.date.fromisoformat(d.get("date", ""))
    except (TypeError, ValueError):
        return None
    tmax = tmin = None
    try:
        a, b = str(d.get("temp", "")).split("/")
        tmax, tmin = int(a), int(b)
    except ValueError:
        pass
    pop = str(d.get("pop", "")).replace("%", "")
    wd = WEEKDAYS[day.weekday()]
    return {
        "date": day.isoformat(),
        "label": f"{day.month}/{day.day}",
        "weekday": wd,
        "weekend": "sat" if wd == "土" else "sun" if wd == "日" else "",
        "today": today is not None and day == today,
        "icon": str(d.get("code") or "999"),
        "pop": int(pop) if pop.isdigit() else None,
        "tmax": tmax, "tmin": tmin, "tmax_color": _max_temp_color(tmax),
        "rel": d.get("rel", "") if d.get("rel") in ("A", "B", "C") else "",
    }


# ------------------------------------------------------------------ カード表示（2026-11-11）
CARD_SWITCH_HOUR = 18          # 18 時からは翌日のカードを出す
PERIODS = [("朝", "6〜12時", 6, 12), ("昼", "12〜18時", 12, 18), ("夕", "18〜24時", 18, 24), ("夜", "0〜6時（翌日）", 24, 30)]
UMBRELLA_POP = 50              # 降水確率がこれ以上の区切りがあれば「傘 いる」
UMBRELLA_MM = 1.0              # 降水短時間予報（無い区切りは 1 時間ごとの予報）でこれ以上の雨があれば「いる」
_DIRS16 = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
           "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
KT_TO_MS = 0.514444


def dir_name(deg):
    """風が吹いてくる方角（度）→「北北西」"""
    if not isinstance(deg, (int, float)):
        return ""
    return _DIRS16[int((deg % 360 + 11.25) // 22.5) % 16]


def _max_temp_of(daily, day):
    for d in daily or []:
        if d.get("date") == day.isoformat():
            try:
                a, b = str(d.get("temp", "")).split("/")
                return int(a), int(b)
            except ValueError:
                return None
    return None


def build_card(now, card, daily=None, taf=None, rain_hours=None):
    """子機用ページのカード表示のデータ。card = fetch_weather.card_data()（1 時間ごとの値と 6 時間ごとの降水確率）。
    18 時からは翌日の分。朝 6〜12・昼 12〜18・夕 18〜24・夜 0〜6（翌日）。
    風は空港の予報（TAF）が出ている時間は TAF（サイネージの表示と同じ。ふだんと「ときどき」の強い方）"""
    import weather_draw
    from table_cols import _worst
    from config import CODE_MAPPING
    hours = {h["t"]: h for h in (card or {}).get("hours") or [] if h.get("t")}
    pops6 = (card or {}).get("pops6") or {}
    if not hours:
        return None
    tomorrow = now.hour >= CARD_SWITCH_HOUR
    day = now.date() + datetime.timedelta(days=1 if tomorrow else 0)
    base = datetime.datetime.combine(day, datetime.time(0), tzinfo=now.tzinfo)

    def hour(h):
        t = base + datetime.timedelta(hours=h)
        v = dict(hours.get(t.strftime("%Y-%m-%dT%H:00")) or {})
        if not v:
            return None
        if taf is not None:
            try:
                import taf as taf_mod
                s = taf_mod.slot_summary(taf, t, hours=1)
            except Exception:
                s = None
            if s and s.get("wind_kt") is not None:
                v["wind"], v["dir"] = round(s["wind_kt"] * KT_TO_MS, 1), s.get("wind_dir")
        if rain_hours:
            mm = rain_hours.get((t + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:00"))
            if mm is not None:
                v["rainfc"] = mm
        return v

    periods, any_wet = [], False
    for name, label, h0, h1 in PERIODS:
        hs = [x for x in (hour(h) for h in range(h0, h1)) if x]
        temps = [x["temp"] for x in hs if isinstance(x.get("temp"), (int, float))]
        winds = [x for x in hs if isinstance(x.get("wind"), (int, float))]
        top = max(winds, key=lambda x: x["wind"]) if winds else None
        codes = [CODE_MAPPING.get(x.get("wmo"), "999") for x in hs if x.get("wmo") is not None]
        code = _worst(codes) if codes else "999"
        if name in ("夕", "夜") and code.startswith("1") and len(code) == 3:
            code = str(int(code) + 600)                      # 夜は晴れ系を月のアイコンに（サイネージと同じ）
        start = (base + datetime.timedelta(hours=h0)).strftime("%Y-%m-%dT%H")
        pop = pops6.get(start)
        rain = [x.get("rainfc") if x.get("rainfc") is not None else (x.get("prec") if pop is None else None)
                for x in hs]
        wet = (pop is not None and pop >= UMBRELLA_POP) or any(r is not None and r >= UMBRELLA_MM for r in rain)
        any_wet = any_wet or wet
        w = round(top["wind"]) if top else None
        periods.append({
            "name": name, "range": label, "icon": code, "pop": pop,
            "tmin": round(min(temps)) if temps else None, "tmax": round(max(temps)) if temps else None,
            "wind": w, "wind_dir": top.get("dir") if top else None,
            "wind_color": _rgb(weather_draw.wind_text_color(w)) if w is not None else "#000000",
            "arrow_color": _rgb(weather_draw.wind_arrow_color(w)) if w is not None else "#888888",
            "calm": w == 0,
        })

    def day_max(d0):
        ts = [x["temp"] for x in (hours.get((d0 + datetime.timedelta(hours=h)).strftime("%Y-%m-%dT%H:00"))
                                   for h in range(24)) if x and isinstance(x.get("temp"), (int, float))]
        return max(ts) if len(ts) >= 20 else None, min(ts) if len(ts) >= 20 else None

    hmax, hmin = day_max(base)
    pmax, _ = day_max(base - datetime.timedelta(days=1))
    official = _max_temp_of(daily, day)                      # 気象庁の最高・最低（明日以降は週間・短期予報）
    tmax = official[0] if official else (round(hmax) if hmax is not None else None)
    tmin = official[1] if official else (round(hmin) if hmin is not None else None)
    day_periods = [p for p in periods[:3] if p["wind"] is not None]
    wtop = max(day_periods, key=lambda p: p["wind"]) if day_periods else None
    return {
        "tomorrow": tomorrow,
        "date_label": f"{day.month}/{day.day}（{WEEKDAYS[day.weekday()]}）",
        "max": tmax, "min": tmin, "max_color": _max_temp_color(tmax),
        "diff": round(hmax - pmax) if hmax is not None and pmax is not None else None,
        "umbrella": any_wet,
        "wind_max": ({"ms": wtop["wind"], "dir": wtop["wind_dir"], "dir_name": dir_name(wtop["wind_dir"]),
                      "period": wtop["name"], "color": wtop["wind_color"], "arrow_color": wtop["arrow_color"]}
                     if wtop else None),
        "periods": periods,
    }


def build_payload(cols, now, airport_label, icao="", warning_text="", headline_text="",
                  thunder=None, wbgt=None, sunrise="", sunset="", weather_updated="", daily=None, card=None):
    """cols：「今」から並んだ列（table_cols.build の結果）。daily：１週間の天気（fetch_weather の daily）"""
    week = [w for w in (week_day(d, now.date()) for d in (daily or [])) if w][:WEEK_DAYS]
    cols = list(cols or [])
    th = None
    if thunder:
        th = {"kind": thunder.get("kind"), "km": round(float(thunder.get("km", 0))), "dir": thunder.get("dir", ""),
              "at": thunder["at"].strftime("%H:%M") if isinstance(thunder.get("at"), datetime.datetime) else ""}
    active = bool(warning_text) and "なし" not in warning_text and "失敗" not in warning_text
    return {
        "written_at": now.timestamp(),
        "time": now.strftime("%-m/%-d %H:%M"),
        "today": now.date().isoformat(),
        "airport": airport_label, "icao": icao or "",
        "sunrise": sunrise, "sunset": sunset, "weather_updated": weather_updated,
        "now": column(cols[0]) if cols else None,
        "ahead": [column(c) for c in cols[1:1 + AHEAD_COLS]],
        "warning": warning_text if active else "発表なし",
        "warning_level": ("warning" if active and "警報" in warning_text else "advisory" if active else "none"),
        "headline": headline_text if active else "",
        "thunder": th,
        "wbgt": ({"label": wbgt.get("label"), "value": wbgt.get("value")} if wbgt else None),
        "week": week,
        "card": card,
    }


def write(payload, path=None):
    path = path or NOW_FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def read(path=None):
    try:
        with open(path or NOW_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
