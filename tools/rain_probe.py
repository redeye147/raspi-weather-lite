#!/usr/bin/env python3
"""
tools/rain_probe.py
気象庁の降水ナウキャストが読めるか、Pi で確かめる（今の時間帯の降水量の仕組みの確認用。画面には何も出さない）。

使い方（Pi で）:
    python3 ~/raspi-weather-lite/tools/rain_probe.py          # config.json の空港
    python3 ~/raspi-weather-lite/tools/rain_probe.py 100      # 空港から半径 100km の色も調べる（雨の日に色と雨の強さの対応を確かめる）

表示するもの:
  - 最新の解析時刻（日本時間）と今からの遅れ、予測（15 分おき）の時刻
  - 空港のまわりの今の雨・1 時間先までの最大（画面の「今の時間帯の降水量」に使う値）
  - 半径を付けたとき：タイル内にあった色と画素数、その色を何 mm/h とみなしたか（凡例の色の確認）
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
import requests  # noqa: E402

import fetch_rainnow as fr  # noqa: E402
import fetch_thunder as ft  # noqa: E402
from config import AIRPORT_CONFIG  # noqa: E402
from utils import JST  # noqa: E402


def main():
    try:
        airport = json.load(open(os.path.join(ROOT, "config.json"))).get("airport", "centrair")
    except Exception:
        airport = "centrair"
    cfg = AIRPORT_CONFIG[airport]
    lat, lon = cfg["latitude"], cfg["longitude"]
    pygame.display.init()
    times = []
    for url in fr.TIMES_URLS:
        r = requests.get(url, timeout=20)
        print(f"{url.rsplit('/', 1)[1]}: HTTP {r.status_code}"
              + (f"・{len(r.json())} 件・要素 {sorted({e for t in r.json() for e in t.get('elements', [])})}"
                 if r.ok else ""))
        if r.ok:
            times.append(r.json())
    latest, fcs = fr.analysis_and_forecasts(times)
    if latest is None:
        print("✗ 降水ナウキャスト（hrpns）の解析時刻が見つからない（時刻一覧の形式が変わった可能性）")
        return 1
    at = ft.jst_of(latest[1])
    print(f"最新の解析: {at:%Y-%m-%d %H:%M} JST（{(datetime.datetime.now(JST) - at).total_seconds() / 60:.0f} 分前）")
    print(f"予測（15 分おき）: {[f'{ft.jst_of(v):%H:%M}' for v in fcs] or 'なし'}")
    res = fr.fetch_rainnow(lat, lon)
    print(f"空港（{airport}）の雨: 今 {res.get('now_mmh')} mm/h・1 時間先まで最大 {res.get('max_mmh')} mm/h")

    if len(sys.argv) > 1:
        km = float(sys.argv[1])
        z = 8 if km <= 60 else 6
        colors = collections.Counter()
        for tx, ty in ft.tiles_for(lat, lon, km, z):
            r = requests.get(fr.TILE_URL.format(base=latest[0], valid=latest[1], z=z, x=tx, y=ty), timeout=20)
            if r.status_code != 200:
                continue
            img = ft._load_png(r.content)
            for y in range(img.get_height()):
                for x in range(img.get_width()):
                    c = tuple(img.get_at((x, y)))
                    if c[3] >= 128:
                        colors[c[:3]] += 1
        print(f"半径 {km:g}km（ズーム {z}）のタイル内の色:")
        for c, n in colors.most_common(12):
            print(f"  RGB{c}  {n:7d} 画素  → {fr.mmh_for_color(c)} mm/h とみなす")
        if not colors:
            print("  雨の色は無し")
    return 0


if __name__ == "__main__":
    sys.exit(main())
