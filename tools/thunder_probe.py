#!/usr/bin/env python3
"""
tools/thunder_probe.py
気象庁の雷ナウキャストが読めるか、Pi で確かめる（雷の帯の仕組みの確認用。画面には何も出さない）。

使い方（Pi で）:
    python3 ~/raspi-weather-lite/tools/thunder_probe.py              # config.json の空港・半径 20km
    python3 ~/raspi-weather-lite/tools/thunder_probe.py 300          # 半径 300km（どこかで雷が出ている日に色を確かめる）

表示するもの:
  - 最新の解析時刻（日本時間）と、今からの遅れ
  - 取得したタイルの枚数（404 = 雷の無い範囲は数えない）
  - タイルの中にあった色と画素数、その色を何の活動度とみなしたか（凡例の色の確認）
  - 活動度 2 以上でいちばん近い雷の距離・方向
"""

import collections
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

import fetch_thunder as ft  # noqa: E402
from config import AIRPORT_CONFIG  # noqa: E402
from utils import JST  # noqa: E402


def main():
    km = float(sys.argv[1]) if len(sys.argv) > 1 else ft.SEARCH_KM
    z = ft.ZOOM if km <= 40 else (6 if km <= 300 else 5)     # 広い範囲は粗いタイルで（Pi Zero で時間がかからないように）
    try:
        airport = json.load(open(os.path.join(ROOT, "config.json"))).get("airport", "centrair")
    except Exception:
        airport = "centrair"
    cfg = AIRPORT_CONFIG[airport]
    lat, lon = cfg["latitude"], cfg["longitude"]
    pygame.display.init()
    print(f"空港: {airport} ({lat}, {lon})  半径 {km:g}km  ズーム {z}")

    latest, tiles = ft.fetch_tiles(lat, lon, km=km, z=z)
    if latest is None:
        print("✗ 雷の解析時刻が見つからない（targetTimes_N3.json の形式が変わった可能性）")
        return 1
    at = ft.jst_of(latest[1])
    lag = (datetime.datetime.now(JST) - at).total_seconds() / 60
    print(f"最新の解析: {at:%Y-%m-%d %H:%M} JST（{lag:.0f} 分前）")
    print(f"タイル: {len(tiles)} 枚 / {len(ft.tiles_for(lat, lon, km, z))} 枚中（残りは 404 = 雷なし）")

    colors = collections.Counter()
    for img in tiles.values():
        w, h = img.get_size()
        for y in range(h):
            for x in range(w):
                c = tuple(img.get_at((x, y)))
                if c[3] >= 128:
                    colors[c[:3]] += 1
    if colors:
        print("タイル内の色（画素数・活動度とみなした値）:")
        for c, n in colors.most_common(12):
            print(f"  RGB{c}  {n:6d} 画素  → 活動度 {ft.level_for_color(c)}")
    else:
        print("タイル内に雷の色は無し（範囲内に雷なし）")

    hit = ft.nearest_thunder(lat, lon, tiles, z=z, km=km)
    if hit:
        print(f"活動度 2 以上でいちばん近い雷: {hit['dir']} {hit['km']:.1f}km（最大の活動度 {hit['max_level']}）")
    else:
        print("活動度 2 以上の雷: 範囲内に無し")
    return 0


if __name__ == "__main__":
    sys.exit(main())
