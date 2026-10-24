"""
fetch_rainfcst.py
気象庁「降水短時間予報」（今後の雨）から、空港の 6 時間先までの 1 時間ごとの雨の量を読む。

雨雲レーダーの動きと数値予報を組み合わせた予報で、数時間先の雨は数値予報（Open-Meteo）より当たりやすい。
今日の天気の、今より先の列の降水量（とアイコンの雨のあり・なし）に使う（fc_blend.py）。

データソース: 気象庁ホームページ（今後の雨）が地図表示に使っている画像タイル
  時刻一覧: https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json
  タイル  : https://www.jma.go.jp/bosai/jmatile/data/rasrf/{basetime}/{member}/{validtime}/surf/{element}/{z}/{x}/{y}.png
  （公式の API ではない。member・要素の名前は時刻一覧に書いてあるものを使う。仕様が変わったら tools/rainfc_probe.py で確かめる）

画素の色は「その時刻までの 1 時間の雨の量」の区分（配色は降水ナウキャストと同じ）。
"""

import datetime
import threading

import requests

import fetch_rainnow as fr
from netretry import FailureLog, get_with_retry
from utils import JST

TIMES_URL = "https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json"
TILE_URL = ("https://www.jma.go.jp/bosai/jmatile/data/rasrf/{base}/{member}/{valid}"
            "/surf/{element}/{z}/{x}/{y}.png")
ELEMENT = "rasrf"
AHEAD_H = 6                  # 何時間先まで使うか（降水短時間予報の速報版の範囲）
ZOOMS = (10, 8)              # 細かい方から試す（細かいタイルが無ければ粗い方）
FETCH_INTERVAL_MIN = 30      # 気象庁の更新は 10〜30 分ごと
FRESH_MIN = 90               # 発表がこれより古ければ使わない


def _utc(s):
    return datetime.datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)


def hour_key(dt):
    """その 1 時間の終わりの時刻（JST）→ "2026-10-24T13:00"（予報の記録・列の 1 時間ごとの値と同じ書き方）"""
    return dt.astimezone(JST).strftime("%Y-%m-%dT%H:00")


def forecast_targets(times):
    """時刻一覧から、最新の発表 (basetime, member, element) と、その予報の時刻（AHEAD_H 時間先まで）の並び。
    一覧には別の要素（slmcs など）や、15 時間先まで（7 時間先から）の発表も混ざっているので、
    rasrf があって AHEAD_H 時間先までの予報がある発表のうち、いちばん新しいものを使う。
    速報版（immed）は 10 分ごとの発表で、予報の時刻も 13:10・14:10 のように正時からずれる"""
    by_base = {}
    for t in times:
        b, v = t.get("basetime"), t.get("validtime")
        if not b or not v or v <= b or ELEMENT not in (t.get("elements") or []):
            continue
        lead = (_utc(v) - _utc(b)).total_seconds()
        if lead > AHEAD_H * 3600 or lead % 3600:          # 発表から 1 時間おきの時刻だけ（1 時間の雨の区切り）
            continue
        by_base.setdefault((b, t.get("member") or "none"), set()).add(v)
    if not by_base:
        return None, []
    base, member = max(by_base, key=lambda k: (k[0], k[1] == "none"))   # 同じ時刻なら none（ふつうの発表）を
    return (base, member, ELEMENT), sorted(by_base[(base, member)])


def nearest_hour(dt):
    """13:10 → 13:00・13:40 → 14:00（その時刻までの 1 時間の雨を、いちばん重なる「正時までの 1 時間」とみなす）"""
    return (dt + datetime.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def fetch_rainfcst(lat, lon, session=requests):
    """{"status": "ok", "at": 発表時刻(JST), "hours": {"2026-10-24T13:00": その 1 時間の雨(mm/h)}}
    タイルが 1 枚も取れなかった時刻は hours に入れない（分からない時刻は予報のまま）。
    取得できないときは {"status": "error", "error": "..."}"""
    r = get_with_retry(TIMES_URL, session=session, headers=fr._HEADERS, timeout=fr.TIMEOUT)
    r.raise_for_status()
    latest, valids = forecast_targets(r.json())
    if latest is None or not valids:
        return {"status": "error", "error": "降水短時間予報の発表時刻が見つからない"}
    base, member, element = latest
    hours = {}
    zooms = list(ZOOMS)
    for v in valids:
        for z in list(zooms):
            tiles = fr._tiles_at(base, v, lat, lon, session, z=z, url=TILE_URL, member=member, element=element)
            if tiles:
                zooms = [z]                       # 取れた細かさを、あとの時刻にも使う
                hours[hour_key(nearest_hour(_utc(v)))] = fr.max_mmh_near(lat, lon, tiles, z=z)
                break
    return {"status": "ok", "at": _utc(base).astimezone(JST), "hours": hours}


_FAILURES = FailureLog("降水短時間予報")


def start_fetch_in_background(lat, lon, holder):
    def run():
        try:
            result = fetch_rainfcst(lat, lon)
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
