"""
fetch_thunder.py
気象庁「雷ナウキャスト」の解析（実況）から、空港の近くの雷を調べる。

データソース: 気象庁ホームページ（ナウキャスト）が地図表示に使っている画像タイル
  時刻一覧: https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N3.json
  タイル  : https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/thns/{z}/{x}/{y}.png
  （10 分ごとに更新・1km 格子。公式の API ではないので、仕様が変わったら tools/thunder_probe.py で確かめる）

雷の活動度（凡例の色）
  1: 雷可能性あり  2: 雷あり  3: やや激しい雷  4: 激しい雷
活動度 2 以上（実際に雷がある）だけを数え、空港からいちばん近い位置の距離と方向を返す。
"""

import datetime
import io
import logging
import math
import threading

import requests

from utils import JST

TIMES_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N3.json"
TILE_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/{base}/none/{valid}/surf/thns/{z}/{x}/{y}.png"
ZOOM = 8                  # 1 画素 ≒ 0.5km（北緯 35 度）。半径 20km ならタイル 1〜4 枚
SEARCH_KM = 20            # これより遠い雷は数えない
NEAR_KM = 10              # 「雷接近」（赤）
MIN_LEVEL = 2             # 活動度 2（雷あり）以上
TIMEOUT = 15
_HEADERS = {"User-Agent": "raspi-weather-lite (airport weather signage)"}

# 凡例の色（気象庁の雨量と同じ系統の色）。実際の画素は一番近い色で活動度を決める
LEVEL_COLORS = {
    1: (242, 242, 0),     # 黄
    2: (255, 153, 0),     # 橙
    3: (255, 40, 0),      # 赤
    4: (180, 0, 104),     # 紫
}

DIRECTIONS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]


def level_for_color(rgb) -> int:
    """画素の色 → 活動度（1〜4）。凡例の色の中で一番近いもの"""
    r, g, b = rgb[:3]
    return min(LEVEL_COLORS, key=lambda lv: (LEVEL_COLORS[lv][0] - r) ** 2
               + (LEVEL_COLORS[lv][1] - g) ** 2 + (LEVEL_COLORS[lv][2] - b) ** 2)


def latest_analysis(times: list):
    """targetTimes_N3.json から、雷（thns）の最新の解析（basetime == validtime）を (basetime, validtime) で返す"""
    obs = [t for t in times
           if t.get("basetime") == t.get("validtime") and "thns" in (t.get("elements") or [])]
    if not obs:
        return None
    t = max(obs, key=lambda t: t["basetime"])
    return t["basetime"], t["validtime"]


def to_global_px(lat: float, lon: float, z: int):
    """緯度経度 → 地図（Web メルカトル）全体での画素位置"""
    n = 256 * (2 ** z)
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def from_global_px(x: float, y: float, z: int):
    n = 256 * (2 ** z)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def distance_bearing(lat1, lon1, lat2, lon2):
    """(km, 方位角 0〜360 度。北 0・東 90)。近距離なので平面近似で十分"""
    ky = 111.32
    kx = 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    dx = (lon2 - lon1) * kx
    dy = (lat2 - lat1) * ky
    return math.hypot(dx, dy), (math.degrees(math.atan2(dx, dy)) + 360) % 360


def direction_name(deg: float) -> str:
    return DIRECTIONS[int((deg + 22.5) // 45) % 8]


def tiles_for(lat, lon, km, z=ZOOM):
    """空港から半径 km を覆うタイル (x, y) の一覧"""
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians(lat)))
    x0, y0 = to_global_px(lat + dlat, lon - dlon, z)
    x1, y1 = to_global_px(lat - dlat, lon + dlon, z)
    return [(tx, ty) for ty in range(int(y0) // 256, int(y1) // 256 + 1)
            for tx in range(int(x0) // 256, int(x1) // 256 + 1)]


def nearest_thunder(lat, lon, tiles: dict, z=ZOOM, km=SEARCH_KM, min_level=MIN_LEVEL):
    """tiles = {(tx, ty): get_at(px, py) → (r, g, b, a) を持つ画像}。
    半径 km 以内で活動度 min_level 以上の、いちばん近い画素を {km, deg, dir, level} で返す（無ければ None）"""
    cx, cy = to_global_px(lat, lon, z)
    px_km = 40075.0 * math.cos(math.radians(lat)) / (256 * 2 ** z)     # 1 画素の大きさ
    r_px = int(km / px_km) + 2
    best = None
    max_level = 0
    for gy in range(int(cy) - r_px, int(cy) + r_px + 1):
        for gx in range(int(cx) - r_px, int(cx) + r_px + 1):
            img = tiles.get((gx // 256, gy // 256))
            if img is None:
                continue
            c = img.get_at((gx % 256, gy % 256))
            if len(c) > 3 and c[3] < 128:          # 透明 = 雷なし
                continue
            lv = level_for_color(c)
            if lv < min_level:
                continue
            plat, plon = from_global_px(gx + 0.5, gy + 0.5, z)
            d, deg = distance_bearing(lat, lon, plat, plon)
            if d > km:
                continue
            max_level = max(max_level, lv)
            if best is None or d < best["km"]:
                best = {"km": d, "deg": deg, "dir": direction_name(deg), "level": lv}
    if best:
        best["max_level"] = max_level
    return best


def _load_png(data: bytes):
    import pygame
    return pygame.image.load(io.BytesIO(data), "tile.png")


def fetch_tiles(lat: float, lon: float, km=SEARCH_KM, z=ZOOM, session=requests):
    """最新の解析時刻と、空港から半径 km を覆うタイル {(tx, ty): 画像} を返す。((base, valid), tiles)"""
    r = session.get(TIMES_URL, headers=_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    latest = latest_analysis(r.json())
    if latest is None:
        return None, {}
    base, valid = latest
    tiles = {}
    for tx, ty in tiles_for(lat, lon, km, z):
        url = TILE_URL.format(base=base, valid=valid, z=z, x=tx, y=ty)
        tr = session.get(url, headers=_HEADERS, timeout=TIMEOUT)
        if tr.status_code == 404:              # 雷の無い範囲はタイルが無いことがある
            continue
        tr.raise_for_status()
        tiles[(tx, ty)] = _load_png(tr.content)
    return latest, tiles


def jst_of(valid: str) -> datetime.datetime:
    """"20260820011000"（UTC）→ JST の datetime"""
    return datetime.datetime.strptime(valid, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc).astimezone(JST)


def fetch_thunder(lat: float, lon: float, session=requests):
    """最新の雷の解析を調べる。
    戻り値 {"status": "ok", "at": datetime(JST), "hit": nearest_thunder の結果 or None}
    取得できないときは {"status": "error", "error": "..."}"""
    latest, tiles = fetch_tiles(lat, lon, session=session)
    if latest is None:
        return {"status": "error", "error": "雷の解析時刻が見つからない"}
    return {"status": "ok", "at": jst_of(latest[1]), "hit": nearest_thunder(lat, lon, tiles)}


def start_fetch_in_background(lat: float, lon: float, holder: dict) -> None:
    """裏で取得して holder["result"] に入れる（取得中も時計を止めない）"""
    def run():
        try:
            holder["result"] = fetch_thunder(lat, lon)
        except Exception as e:
            logging.warning(f"雷ナウキャスト取得失敗: {e}")
            holder["result"] = {"status": "error", "error": str(e)}
    holder.pop("result", None)
    threading.Thread(target=run, daemon=True).start()


# ── 表示の判断 ────────────────────────────────────────
HOLD_MIN = 20             # 範囲外になっても 20 分は出したまま（出たり消えたりしないように）
FETCH_INTERVAL_MIN = 5    # 気象庁の更新は 10 分ごと。遅れを小さくするため 5 分ごとに確かめる


class ThunderState:
    """直近の検出を覚えて、帯に出す内容（None / {"kind": "near"|"watch", km, dir, at}）を決める"""

    def __init__(self):
        self.near = None      # 10km 以内を最後に見た検出
        self.watch = None     # 20km 以内を最後に見た検出

    def update(self, result: dict):
        if not result or result.get("status") != "ok":
            return
        hit = result.get("hit")
        if not hit:
            return
        info = {"km": hit["km"], "dir": hit["dir"], "at": result["at"]}
        self.watch = info
        if hit["km"] <= NEAR_KM:
            self.near = info

    def current(self, now: datetime.datetime):
        hold = datetime.timedelta(minutes=HOLD_MIN)
        if self.near and now - self.near["at"] <= hold:
            # 10km 以内を見てから 20 分は「雷接近」。表示する距離・方向は最新の検出
            return {"kind": "near", **(self.watch if self.watch["at"] >= self.near["at"] else self.near)}
        if self.watch and now - self.watch["at"] <= hold:
            return {"kind": "watch", **self.watch}
        return None


def banner_text(info: dict):
    """帯の (見出し, 本文)"""
    km = max(1, round(info["km"]))
    at = info["at"].strftime("%H:%M")
    if info["kind"] == "near":
        return "雷接近", f"空港の{info['dir']} {km}km に雷（{at} 解析）　屋外作業を中止し、建物・車内へ避難"
    return "雷注意", f"空港の{info['dir']} {km}km に雷（{at} 解析）　接近に注意・作業中止の準備を"
