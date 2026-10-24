#!/usr/bin/env python3
"""
tools/forecast_probe.py
降水短時間予報（気象庁「今後の雨」のタイル）と TAF（空港の予報）が読めるか、Pi で確かめる（画面には何も出さない）。

使い方（Pi で）:
    python3 ~/raspi-weather-lite/tools/forecast_probe.py          # config.json の空港
    python3 ~/raspi-weather-lite/tools/forecast_probe.py 100      # 降水短時間予報の、空港から半径 100km の色も調べる（雨の日に）

表示するもの:
  - 降水短時間予報：時刻一覧の中身（最初の数件）、使う発表時刻・member・要素、タイルの HTTP の結果、空港の 1 時間ごとの雨
  - TAF：生の電文と、今日の天気の列ごとの風・天気のまとめ
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

import fetch_rainfcst as rf  # noqa: E402
import fetch_rainnow as fr  # noqa: E402
import fetch_thunder as ft  # noqa: E402
import taf as taf_mod  # noqa: E402
from config import AIRPORT_CONFIG  # noqa: E402
from utils import JST  # noqa: E402


def rain_forecast(lat, lon, km):
    print("==== 降水短時間予報")
    r = requests.get(rf.TIMES_URL, timeout=20)
    print(f"targetTimes.json: HTTP {r.status_code}")
    if not r.ok:
        return
    times = r.json()
    print(f"  {len(times)} 件。最初の 3 件: {json.dumps(times[:3], ensure_ascii=False)}")
    print(f"  member: {sorted({str(t.get('member')) for t in times})}・要素: {sorted({e for t in times for e in t.get('elements', [])})}")
    for m in ("immed", "none"):
        sample = [t for t in times if t.get("member") == m][:2]
        print(f"  member {m} の例: {json.dumps(sample, ensure_ascii=False)}")
    latest, valids = rf.forecast_targets(times)
    if latest is None:
        print("✗ 予報の時刻が見つからない（時刻一覧の形式が変わった可能性）")
        return
    base, member, element = latest
    print(f"使う発表: {ft.jst_of(base):%m/%d %H:%M} JST・member {member}・要素 {element}")
    print(f"予報の時刻（発表から 1 時間おき）: {[f'{ft.jst_of(v):%H:%M}' for v in valids]}")
    if valids:
        for z in rf.ZOOMS:
            for tx, ty in ft.tiles_for(lat, lon, fr.RADIUS_KM, z):
                url = rf.TILE_URL.format(base=base, member=member, valid=valids[0], element=element, z=z, x=tx, y=ty)
                print(f"  ズーム {z} {url.split('/rasrf/', 1)[1]}: HTTP {requests.get(url, timeout=20).status_code}")
    res = rf.fetch_rainfcst(lat, lon)
    print(f"空港の雨（その時刻までの 1 時間）: {res.get('hours', res)}")
    if km and valids:
        z = 8 if km <= 60 else 6
        colors = collections.Counter()
        for v in valids:
            for tx, ty in ft.tiles_for(lat, lon, km, z):
                tr = requests.get(rf.TILE_URL.format(base=base, member=member, valid=v, element=element, z=z, x=tx, y=ty),
                                  timeout=20)
                if tr.status_code != 200:
                    continue
                img = ft._load_png(tr.content)
                for y in range(img.get_height()):
                    for x in range(img.get_width()):
                        c = tuple(img.get_at((x, y)))
                        if c[3] >= 128:
                            colors[c[:3]] += 1
        print(f"半径 {km:g}km（ズーム {z}・{len(valids)} 時刻分）のタイル内の色:")
        for c, n in colors.most_common(12):
            print(f"  RGB{c}  {n:7d} 画素  → {fr.mmh_for_color(c)} mm/h とみなす")
        if not colors:
            print("  雨の色は無し")


def taf_check(icao):
    print(f"==== TAF（{icao}）")
    try:
        t, raw = taf_mod.fetch_and_parse(icao)
    except Exception as e:
        print(f"✗ 取得・解析できない: {e}")
        return
    print(raw)
    print(f"発表 {t['issued'].astimezone(JST):%m/%d %H:%M}・期間 {t['start'].astimezone(JST):%m/%d %H時}〜{t['end'].astimezone(JST):%m/%d %H時}（JST）")
    start = datetime.datetime.now(JST).replace(minute=0, second=0, microsecond=0)
    start -= datetime.timedelta(hours=start.hour % 3)
    for i in range(10):
        dt = start + datetime.timedelta(hours=3 * i)
        s = taf_mod.slot_summary(t, dt)
        if s is None:
            print(f"  {dt:%d日%H時} の列: 予報の期間外（数値予報のまま）")
            continue
        if s["wind_kt"] is None:
            wind = "-"
        else:
            d = "変動" if s["wind_dir"] is None else f"{s['wind_dir']:03d}°"
            wind = f"{d} {round(s['wind_kt'] * taf_mod.aviation.KT_TO_MS)}m/s"
        print(f"  {dt:%d日%H時} の列: 風 {wind}・天気 {s['wx'] or '-'}・ときどき {s['tempo_wx'] or '-'}")


def main():
    try:
        airport = json.load(open(os.path.join(ROOT, "config.json"))).get("airport", "centrair")
    except Exception:
        airport = "centrair"
    cfg = AIRPORT_CONFIG[airport]
    pygame.display.init()
    km = float(sys.argv[1]) if len(sys.argv) > 1 else 0
    rain_forecast(cfg["latitude"], cfg["longitude"], km)
    if cfg.get("icao"):
        taf_check(cfg["icao"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
