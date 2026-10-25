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

凡例の色はまだ雷の日の実物で確かめていない（2026-10-22 17:10 の 118 で、空港の観測は晴れ・雷なしなのに
「雷接近 9.2km」が出た）。確かめるため、雷を見つけたときは
  - 見つけた画素の色・活動度と、半径 20km の中の色の数をログに残す
  - その解析のタイル画像（PNG）と中身のまとめを cache/thunder/ に保存する（最新 EVIDENCE_KEEP 回分）
"""

import datetime
import io
import logging
import json
import math
import os
import threading

import requests

from netretry import FailureLog, get_with_retry
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

EVIDENCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "thunder")
EVIDENCE_KEEP = 10        # 雷を見つけた解析の画像を何回分残すか（1 回 数 KB〜数十 KB）

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
    colors = {}                                    # 半径の中の色ごとの画素数（色と活動度の対応を確かめる用）
    for gy in range(int(cy) - r_px, int(cy) + r_px + 1):
        for gx in range(int(cx) - r_px, int(cx) + r_px + 1):
            img = tiles.get((gx // 256, gy // 256))
            if img is None:
                continue
            c = img.get_at((gx % 256, gy % 256))
            if len(c) > 3 and c[3] < 128:          # 透明 = 雷なし
                continue
            lv = level_for_color(c)
            plat, plon = from_global_px(gx + 0.5, gy + 0.5, z)
            d, deg = distance_bearing(lat, lon, plat, plon)
            if d > km:
                continue
            rgba = tuple(c[:4]) if len(c) > 3 else (*tuple(c[:3]), 255)
            colors[rgba] = colors.get(rgba, 0) + 1
            if lv < min_level:
                continue
            max_level = max(max_level, lv)
            if best is None or d < best["km"]:
                best = {"km": d, "deg": deg, "dir": direction_name(deg), "level": lv, "rgba": rgba}
    if best:
        best["max_level"] = max_level
        best["colors"] = sorted(([list(k), n, level_for_color(k)] for k, n in colors.items()),
                                key=lambda x: -x[1])[:8]
    return best


def describe_hit(hit):
    """ログ用：見つけた画素の色と、半径の中の色（多い順）"""
    cs = "・".join(f"RGBA{tuple(c)}×{n}→{lv}" for c, n, lv in hit.get("colors", []))
    return f"活動度 {hit['level']}（RGBA{tuple(hit['rgba'])}）・半径内の色 {cs}"


def save_evidence(valid, raw_tiles, hit, base_dir=None, keep=None):
    """雷を見つけた解析のタイル画像と、まとめ（json）を残す。同じ解析は 1 回だけ。古いものから消す"""
    base_dir = base_dir or EVIDENCE_DIR
    keep = keep or EVIDENCE_KEEP
    stamp = jst_of(valid).strftime("%Y%m%d_%H%M")
    summary = os.path.join(base_dir, f"thns_{stamp}.json")
    if os.path.exists(summary):
        return False
    os.makedirs(base_dir, exist_ok=True)
    for (tx, ty), data in raw_tiles.items():
        with open(os.path.join(base_dir, f"thns_{stamp}_{tx}_{ty}.png"), "wb") as f:
            f.write(data)
    with open(summary, "w", encoding="utf-8") as f:
        json.dump({"valid": valid, "hit": {k: v for k, v in hit.items()}, "tiles": [list(t) for t in raw_tiles]},
                  f, ensure_ascii=False, indent=1)
    stamps = sorted({n[5:18] for n in os.listdir(base_dir) if n.startswith("thns_")})
    for old in stamps[:-keep]:
        for n in os.listdir(base_dir):
            if n.startswith(f"thns_{old}"):
                try:
                    os.remove(os.path.join(base_dir, n))
                except OSError:
                    pass
    return True


def _load_png(data: bytes):
    import pygame
    return pygame.image.load(io.BytesIO(data), "tile.png")


def fetch_tiles(lat: float, lon: float, km=SEARCH_KM, z=ZOOM, session=requests, raw=None):
    """最新の解析時刻と、空港から半径 km を覆うタイル {(tx, ty): 画像} を返す。((base, valid), tiles)
    raw に辞書を渡すと、元の PNG のバイト列も {(tx, ty): bytes} で入れる"""
    r = get_with_retry(TIMES_URL, session=session, headers=_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    latest = latest_analysis(r.json())
    if latest is None:
        return None, {}
    base, valid = latest
    tiles = {}
    for tx, ty in tiles_for(lat, lon, km, z):
        url = TILE_URL.format(base=base, valid=valid, z=z, x=tx, y=ty)
        tr = get_with_retry(url, session=session, headers=_HEADERS, timeout=TIMEOUT)
        if tr.status_code == 404:              # 雷の無い範囲はタイルが無いことがある
            continue
        tr.raise_for_status()
        tiles[(tx, ty)] = _load_png(tr.content)
        if raw is not None:
            raw[(tx, ty)] = tr.content
    return latest, tiles


def jst_of(valid: str) -> datetime.datetime:
    """"20260820011000"（UTC）→ JST の datetime"""
    return datetime.datetime.strptime(valid, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc).astimezone(JST)


def fetch_thunder(lat: float, lon: float, session=requests):
    """最新の雷の解析を調べる。
    戻り値 {"status": "ok", "at": datetime(JST), "hit": nearest_thunder の結果 or None}
    取得できないときは {"status": "error", "error": "..."}"""
    raw = {}
    latest, tiles = fetch_tiles(lat, lon, session=session, raw=raw)
    if latest is None:
        return {"status": "error", "error": "雷の解析時刻が見つからない"}
    hit = nearest_thunder(lat, lon, tiles)
    if hit:
        try:
            if save_evidence(latest[1], raw, hit):
                logging.info(f"[thunder] {jst_of(latest[1]):%H:%M} 解析 {hit['dir']} {hit['km']:.1f}km "
                             f"{describe_hit(hit)}（画像を cache/thunder/ に保存）")
        except Exception as e:
            logging.info(f"[thunder] 画像の保存に失敗: {e}")
    return {"status": "ok", "at": jst_of(latest[1]), "hit": hit}


_FAILURES = FailureLog("雷ナウキャスト")      # 一時的な失敗は INFO、15 分以上続いたら WARNING


def start_fetch_in_background(lat: float, lon: float, holder: dict) -> None:
    """裏で取得して holder["result"] に入れる（取得中も時計を止めない）"""
    def run():
        try:
            result = fetch_thunder(lat, lon)
        except Exception as e:
            result = {"status": "error", "error": str(e)}
        if result.get("status") == "ok":
            _FAILURES.ok()
        else:
            _FAILURES.failed(result.get("error"))
        holder["result"] = result
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
        info = {"km": hit["km"], "dir": hit["dir"], "at": result["at"],
                "level": hit.get("level"), "rgba": hit.get("rgba")}
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
