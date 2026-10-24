"""
fetch_rainnow.py
気象庁「高解像度降水ナウキャスト」（雨雲レーダーの実測と 1 時間先までの予測）から、空港の雨の強さを読む。

データソース: 気象庁ホームページ（ナウキャスト）が地図表示に使っている画像タイル
  時刻一覧: https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json（実況）・targetTimes_N2.json（予測）
  タイル  : https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png
  （5 分ごとに更新・250m〜1km 格子。公式の API ではないので、仕様が変わったら tools/rain_probe.py で確かめる）

画素の色が雨の強さ（mm/h）の区分。空港のまわり（半径 RADIUS_KM）でいちばん強い区分を読み、
区分の真ん中の値（例 1〜5mm/h → 3mm/h）を「1 時間あたりの雨の量」とする。
"""

import datetime
import math
import threading

import requests

import fetch_thunder as ft
from netretry import FailureLog, get_with_retry
from utils import JST

TIMES_URLS = ("https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json",
              "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json")
TILE_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/{base}/none/{valid}/surf/hrpns/{z}/{x}/{y}.png"
ELEMENT = "hrpns"
ZOOM = 10                    # 1 画素 ≒ 125m（北緯 35 度）。空港のまわりはタイル 1〜2 枚
RADIUS_KM = 1.5              # 空港の敷地くらいの範囲
AHEAD_MIN = 60               # 何分先までの予測を見るか
AHEAD_STEP_MIN = 15          # 予測は 15 分おき（+15・+30・+45・+60）に見る（取りに行く数を減らす）
FETCH_INTERVAL_MIN = 10      # 気象庁の更新は 5 分ごと。通信を控えめに 10 分ごと
FRESH_MIN = 20               # 解析がこれより古ければ使わない
TIMEOUT = 15
_HEADERS = {"User-Agent": "raspi-weather-lite (airport weather signage)"}

# 凡例の色（気象庁の雨量の配色）と、その区分の代表値（mm/h）
RAIN_LEVELS = [
    ((242, 242, 255), 0.5),     # 1 未満
    ((160, 210, 255), 3.0),     # 1〜5
    ((33, 140, 255), 7.5),      # 5〜10
    ((0, 65, 255), 15.0),       # 10〜20
    ((250, 245, 0), 25.0),      # 20〜30
    ((255, 153, 0), 40.0),      # 30〜50
    ((255, 40, 0), 65.0),       # 50〜80
    ((180, 0, 104), 80.0),      # 80 以上
]


def mmh_for_color(rgb):
    r, g, b = rgb[:3]
    return min(RAIN_LEVELS, key=lambda lv: (lv[0][0] - r) ** 2 + (lv[0][1] - g) ** 2 + (lv[0][2] - b) ** 2)[1]


def analysis_and_forecasts(times_lists):
    """時刻一覧（N1・N2 をまとめたもの）から、最新の解析 (basetime, validtime) と、
    同じ basetime の予測の validtime の並び（AHEAD_MIN 分先まで）を返す"""
    entries = [t for times in times_lists for t in times if ELEMENT in (t.get("elements") or [])]
    obs = [t for t in entries if t.get("basetime") == t.get("validtime")]
    if not obs:
        return None, []
    base = max(t["basetime"] for t in obs)
    limit = (_utc(base) + datetime.timedelta(minutes=AHEAD_MIN)).strftime("%Y%m%d%H%M%S")
    fcs = sorted({t["validtime"] for t in entries if t.get("basetime") == base and base < t["validtime"] <= limit})
    step = [v for v in fcs if (_utc(v) - _utc(base)).total_seconds() % (AHEAD_STEP_MIN * 60) == 0]
    return (base, base), step


def _utc(s):
    return datetime.datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)


def max_mmh_near(lat, lon, tiles, z=ZOOM, km=RADIUS_KM):
    """空港から半径 km の中で、いちばん強い雨（mm/h）。雨が無ければ 0"""
    cx, cy = ft.to_global_px(lat, lon, z)
    px_km = 40075.0 * math.cos(math.radians(lat)) / (256 * 2 ** z)
    r = int(km / px_km) + 1
    best = 0.0
    for gy in range(int(cy) - r, int(cy) + r + 1):
        for gx in range(int(cx) - r, int(cx) + r + 1):
            if (gx - cx) ** 2 + (gy - cy) ** 2 > r * r:
                continue
            img = tiles.get((gx // 256, gy // 256))
            if img is None:
                continue
            c = img.get_at((gx % 256, gy % 256))
            if len(c) > 3 and c[3] < 128:           # 透明 = 雨なし
                continue
            best = max(best, mmh_for_color(c))
    return best


def _tiles_at(base, valid, lat, lon, session, z=ZOOM):
    tiles = {}
    for tx, ty in ft.tiles_for(lat, lon, RADIUS_KM, z):
        tr = get_with_retry(TILE_URL.format(base=base, valid=valid, z=z, x=tx, y=ty),
                            session=session, headers=_HEADERS, timeout=TIMEOUT)
        if tr.status_code == 404:                   # 雨の無い範囲はタイルが無いことがある
            continue
        tr.raise_for_status()
        tiles[(tx, ty)] = ft._load_png(tr.content)
    return tiles


def fetch_rainnow(lat, lon, session=requests):
    """{"status": "ok", "at": 解析時刻(JST), "now_mmh": 今の雨, "max_mmh": 1 時間先までのいちばん強い雨}
    取得できないときは {"status": "error", "error": "..."}"""
    times_lists = []
    for url in TIMES_URLS:
        r = get_with_retry(url, session=session, headers=_HEADERS, timeout=TIMEOUT)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        times_lists.append(r.json())
    latest, fcs = analysis_and_forecasts(times_lists)
    if latest is None:
        return {"status": "error", "error": "降水ナウキャストの解析時刻が見つからない"}
    base, valid = latest
    now_mmh = max_mmh_near(lat, lon, _tiles_at(base, valid, lat, lon, session))
    max_mmh = now_mmh
    for v in fcs:
        max_mmh = max(max_mmh, max_mmh_near(lat, lon, _tiles_at(base, v, lat, lon, session)))
    return {"status": "ok", "at": ft.jst_of(valid), "now_mmh": now_mmh, "max_mmh": max_mmh}


_FAILURES = FailureLog("降水ナウキャスト")


def start_fetch_in_background(lat, lon, holder):
    def run():
        try:
            result = fetch_rainnow(lat, lon)
        except Exception as e:
            result = {"status": "error", "error": str(e)}
        if result.get("status") == "ok":
            _FAILURES.ok()
        else:
            _FAILURES.failed(result.get("error"))
        holder["result"] = result
    holder.pop("result", None)
    threading.Thread(target=run, daemon=True).start()


def is_fresh(result, now):
    return bool(result and result.get("status") == "ok"
                and now - result["at"] <= datetime.timedelta(minutes=FRESH_MIN))
