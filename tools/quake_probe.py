#!/usr/bin/env python3
"""
tools/quake_probe.py
気象庁の地震情報の一覧（bosai/quake/data/list.json）の中身を Pi で確かめる（画面には何も出さない）。
地震の帯（quake.py）が、データの形を正しく読めているかの確認用（2026-11-06）。

使い方（Pi で）:
    python3 ~/raspi-weather-lite/tools/quake_probe.py            # config.json の空港
    python3 ~/raspi-weather-lite/tools/quake_probe.py haneda     # 空港を指定
"""

import datetime
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests  # noqa: E402

import quake  # noqa: E402
from config import AIRPORT_CONFIG  # noqa: E402
from utils import JST  # noqa: E402


def main():
    if len(sys.argv) > 1:
        airport = sys.argv[1]
    else:
        try:
            airport = json.load(open(os.path.join(ROOT, "config.json"))).get("airport", "centrair")
        except (OSError, ValueError):
            airport = "centrair"
    code, name = AIRPORT_CONFIG[airport]["quake_city"]
    print(f"空港 {airport}・震度を見る市区町村 {name}（{code}）")

    r = requests.get(quake.LIST_URL, headers=quake._HEADERS, timeout=20)
    print(f"\n一覧: HTTP {r.status_code}・{len(r.content)} バイト・ETag {r.headers.get('ETag')}・"
          f"Last-Modified {r.headers.get('Last-Modified')}")
    if r.headers.get("ETag"):
        r2 = requests.get(quake.LIST_URL, headers={**quake._HEADERS, "If-None-Match": r.headers["ETag"]}, timeout=20)
        print(f"同じ ETag でもう一度: HTTP {r2.status_code}（304 なら、変わっていないときは中身を送らない）")
    data = r.json()
    print(f"件数 {len(data)}・1 件目の項目 {list(data[0].keys()) if data else '-'}")
    print("情報の名前ごとの件数:", dict(Counter(e.get("ttl") for e in data)))

    print("\n新しい 8 件:")
    for e in data[:8]:
        cities = sum(len(p.get("city") or []) for p in e.get("int") or [])
        print(f"  {e.get('rdt')} {e.get('ttl')} 発生 {e.get('at')} 震源 {e.get('anm')!r} M{e.get('mag')!r} "
              f"cod {e.get('cod')!r} 最大震度 {e.get('maxi')!r}・県 {len(e.get('int') or [])}・市区町村 {cities}")
    sample = next((e for e in data if any(p.get("city") for p in e.get("int") or [])), None)
    if sample:
        print("\n市区町村の震度が入っている 1 件の int の先頭:")
        print("  " + json.dumps((sample.get("int") or [])[:1], ensure_ascii=False)[:600])

    seen = [(e, quake.city_intensity(e, code)) for e in data]
    seen = [(e, i) for e, i in seen if i]
    print(f"\n{name}（{code}）が入っている情報: {len(seen)} 件")
    for e, i in seen[:5]:
        print(f"  {e.get('at')} 震源 {e.get('anm')} M{e.get('mag')} → {name} 震度 {quake.intensity_name(i)}")

    # 帯の文字の確かめ：基準を震度 1・期間を一覧全体にして、帯ならどう出るか
    now = datetime.datetime.now(JST)
    q = quake.find_quake(data, code, now, min_intensity="1", hours=24 * 365)
    if q:
        print("\n（確認用）震度 1 以上で探したときの帯:", " ".join(quake.banner_text(q, name)))
    else:
        print(f"\n（確認用）一覧の中に {name} で揺れた地震は無かった")
    q = quake.find_quake(data, code, now)
    print("今の判断（震度 1 以上。5 弱以上は 3 時間・それ以外は 1 時間）:", " ".join(quake.banner_text(q, name)) if q else "帯は出さない")
    return 0


if __name__ == "__main__":
    sys.exit(main())
