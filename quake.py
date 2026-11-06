"""
quake.py
空港のある市区町村で震度 5 弱以上の地震があったら、帯で知らせる（2026-11-06）。

データ：気象庁の地震情報の一覧 bosai/quake/data/list.json（警報と同じ気象庁のサイト）。
揺れてから 1.5〜数分で載る（緊急地震速報のように揺れる前ではない）。
  - 震度速報：揺れから約 1.5 分。震度 3 以上の「地域」（例 愛知県西部）だけで、市区町村の震度は無い
  - 震源・震度情報：揺れから数分。市区町村ごとの震度・震源・深さ・マグニチュード
空港のある市区町村（config の quake_city）の震度で判断するので、帯が出るのは「震源・震度情報」が載ってから。
一覧の 1 件（list.json の要素）の形（2026-11-06 時点の理解。tools/quake_probe.py で確かめる）：
  {"eid": 地震の番号, "rdt": 発表時刻, "at": 発生時刻, "ttl": 情報の名前, "anm": 震源の地名,
   "cod": "+35.0+136.9-10000/"（緯度・経度・深さ m）, "mag": "5.8", "maxi": 最大震度,
   "int": [{"code": 県, "maxi": .., "city": [{"code": "2321600", "maxi": "5+"}, ...]}, ...]}
震度の書き方は "1"〜"4"・"5-"（5 弱）・"5+"（5 強）・"6-"・"6+"・"7"。
"""

import datetime
import logging
import re

import requests

from utils import JST

LIST_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"
FETCH_INTERVAL_S = 60          # 1 分ごと（変わっていなければ 304 で中身は届かない）
SHOW_HOURS = 3                 # 地震の発生から 3 時間、帯を出す
MIN_INTENSITY = "5-"           # 震度 5 弱以上
TIMEOUT = 15
_HEADERS = {"User-Agent": "raspi-weather-lite (airport weather signage)"}

_ORDER = ["1", "2", "3", "4", "5-", "5+", "6-", "6+", "7"]
_NAMES = {"5-": "5弱", "5+": "5強", "6-": "6弱", "6+": "6強"}


def intensity_rank(s) -> int:
    """震度の大きさの順番（分からない値は -1）"""
    try:
        return _ORDER.index(str(s).strip())
    except ValueError:
        return -1


def intensity_name(s) -> str:
    s = str(s).strip()
    return _NAMES.get(s, s)


def _parse_time(s):
    try:
        return datetime.datetime.fromisoformat(str(s)).astimezone(JST)
    except (TypeError, ValueError):
        return None


def depth_km(cod):
    """"+35.0+136.9-10000/" → 10（km）。分からなければ None"""
    m = re.match(r"^[+-][\d.]+[+-][\d.]+([+-]\d+)", str(cod or ""))
    if not m:
        return None
    try:
        return round(abs(int(m.group(1))) / 1000)
    except ValueError:
        return None


def city_intensity(entry, city_code):
    """1 件の情報の中の、その市区町村の震度（無ければ None）"""
    for pref in entry.get("int") or []:
        for city in pref.get("city") or []:
            if str(city.get("code")) == str(city_code):
                return city.get("maxi")
    return None


def find_quake(entries, city_code, now, min_intensity=MIN_INTENSITY, hours=SHOW_HOURS):
    """一覧から、hours 時間以内に発生し、city_code の市区町村で min_intensity 以上だった地震を探す。
    同じ地震（eid）の情報が何回か出たら、いちばん新しい発表を使う（震源や震度が直る）。
    戻り値 {"eid", "at", "intensity", "epicenter", "depth_km", "mag"}（無ければ None）"""
    if not city_code:
        return None
    latest = {}
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("eid"):
            continue
        rdt = str(e.get("rdt") or e.get("ctt") or "")
        if e["eid"] not in latest or rdt >= latest[e["eid"]][0]:
            latest[e["eid"]] = (rdt, e)
    best = None
    for _, e in latest.values():
        at = _parse_time(e.get("at"))
        if at is None or not (datetime.timedelta(0) <= now - at <= datetime.timedelta(hours=hours)):
            continue
        it = city_intensity(e, city_code)
        if intensity_rank(it) < intensity_rank(min_intensity):
            continue
        q = {"eid": e["eid"], "at": at, "intensity": it,
             "epicenter": (e.get("anm") or "").strip(), "depth_km": depth_km(e.get("cod")),
             "mag": (str(e.get("mag") or "").strip() or None)}
        if best is None or q["at"] > best["at"]:
            best = q
    return best


def banner_text(q, city_name=""):
    """帯の (見出し, 本文)。例 ("地震 震度5強", "常滑市（11/6 10:23 発生・震源 愛知県西部 深さ 10km・M5.8）")"""
    title = f"地震 震度{intensity_name(q['intensity'])}"
    parts = [f"{q['at']:%-m/%-d %H:%M} 発生"]
    if q.get("epicenter"):
        src = f"震源 {q['epicenter']}"
        if q.get("depth_km") is not None:
            src += " ごく浅い" if q["depth_km"] == 0 else f" 深さ {q['depth_km']}km"
        if q.get("mag") and re.match(r"^\d+(\.\d+)?$", q["mag"]):
            src += f"・M{q['mag']}"
        parts.append(src)
    else:
        parts.append("震源 調査中")
    return title, f"{city_name}（{'・'.join(parts)}）"


def fetch_list(session=requests, etag=None):
    """一覧を取る。戻り値 (status, entries, etag)。status は "ok" / "same"（変わっていない）/ "error: ..." """
    headers = dict(_HEADERS)
    if etag:
        headers["If-None-Match"] = etag
    try:
        r = session.get(LIST_URL, headers=headers, timeout=TIMEOUT)
    except Exception as e:
        return f"error: {e}", None, etag
    if r.status_code == 304:
        return "same", None, etag
    if r.status_code != 200:
        return f"error: HTTP {r.status_code}", None, etag
    try:
        data = r.json()
    except ValueError:
        return "error: 一覧が読めない", None, etag
    if not isinstance(data, list):
        return "error: 一覧の形が違う", None, etag
    return "ok", data, r.headers.get("ETag")


class QuakeState:
    """一覧を覚えておき、今出す地震（find_quake の結果）を決める。
    一覧が変わらないとき（304）は前の一覧で判断する（3 時間たったら消えるように、時刻は毎回見る）"""

    def __init__(self, city_code):
        self.city_code = city_code
        self.entries = []
        self.etag = None
        self.status = None
        self.ok_at = None

    def update(self, status, entries, etag, now_ts=None):
        self.status = status
        if status == "ok":
            self.entries, self.etag = entries, etag
        if status in ("ok", "same"):
            self.ok_at = now_ts

    def current(self, now):
        try:
            return find_quake(self.entries, self.city_code, now)
        except Exception as e:                     # 形が違っても表示は止めない
            logging.info(f"地震の一覧の読み取りに失敗: {e}")
            return None


def start_fetch_in_background(holder: dict, etag=None, session=requests) -> None:
    import threading

    def run():
        holder["result"] = fetch_list(session=session, etag=etag)

    threading.Thread(target=run, daemon=True).start()
