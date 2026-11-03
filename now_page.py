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


def column(item):
    import weather_draw
    v = item.get("wind_val")
    pop = _pop_value(item.get("pop"))
    wd = item.get("wind_dir")
    return {
        "label": item.get("hour", ""),
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


def build_payload(cols, now, airport_label, icao="", warning_text="", headline_text="",
                  thunder=None, wbgt=None, sunrise="", sunset="", weather_updated=""):
    """cols：「今」から並んだ列（table_cols.build の結果）"""
    cols = list(cols or [])
    th = None
    if thunder:
        th = {"kind": thunder.get("kind"), "km": round(float(thunder.get("km", 0))), "dir": thunder.get("dir", ""),
              "at": thunder["at"].strftime("%H:%M") if isinstance(thunder.get("at"), datetime.datetime) else ""}
    active = bool(warning_text) and "なし" not in warning_text and "失敗" not in warning_text
    return {
        "written_at": now.timestamp(),
        "time": now.strftime("%-m/%-d %H:%M"),
        "airport": airport_label, "icao": icao or "",
        "sunrise": sunrise, "sunset": sunset, "weather_updated": weather_updated,
        "now": column(cols[0]) if cols else None,
        "ahead": [column(c) for c in cols[1:1 + AHEAD_COLS]],
        "warning": warning_text if active else "発表なし",
        "warning_level": ("warning" if active and "警報" in warning_text else "advisory" if active else "none"),
        "headline": headline_text if active else "",
        "thunder": th,
        "wbgt": ({"label": wbgt.get("label"), "value": wbgt.get("value")} if wbgt else None),
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
