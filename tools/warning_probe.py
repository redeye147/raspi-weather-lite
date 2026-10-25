#!/usr/bin/env python3
"""
tools/warning_probe.py
気象庁の警報・注意報のデータの置き場所を、Pi で探す（画面には何も出さない）。

2026-10-25 に、今まで使っていた bosai/warning/data/warning/{県}.json が 2026-05-28 の発表のまま
止まっていることが分かった（気象庁の防災気象情報の仕組みが変わり、別の場所に移った可能性）。
気象庁ホームページの警報のページが読み込んでいるプログラム（JavaScript）から、データの URL らしい文字を抜き出す。

使い方（Pi で）:
    python3 ~/raspi-weather-lite/tools/warning_probe.py
"""

import re
import sys
from urllib.parse import urljoin

import requests

BASE = "https://www.jma.go.jp"
PAGES = ["/bosai/warning/", "/bosai/warning/index.html", "/bosai/map.html"]
H = {"User-Agent": "raspi-weather-lite (airport weather signage)"}


def get(url):
    try:
        r = requests.get(url, headers=H, timeout=20)
        r.encoding = "utf-8"
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)


def main():
    st, body = get(BASE + "/bosai/warning/data/warning/230000.json")
    m = re.search(r'"reportDatetime"\s*:\s*"([^"]+)"', body or "")
    print(f"今までの場所: HTTP {st}・発表 {m.group(1) if m else '-'}")

    # 2026-10-25 に見つけた新しい場所（r8 = 令和 8 年の新しい防災気象情報？）の中身
    import json
    st, body = get(BASE + "/bosai/warning/data/r8/230000.json")
    print(f"\n新しい場所 /bosai/warning/data/r8/230000.json: HTTP {st}・{len(body or '')} 文字")
    if st == 200:
        try:
            d = json.loads(body)
        except ValueError:
            d = None
            print(body[:1500])
        if d is not None:
            top = d if isinstance(d, dict) else (d[0] if d else {})
            print("一番上の項目:", list(top.keys()) if isinstance(top, dict) else type(d))
            for k in ("reportDatetime", "publishingOffice", "headlineText"):
                if isinstance(top, dict) and k in top:
                    print(f"  {k}: {str(top[k])[:200]}")

            def walk(x, path):
                if isinstance(x, dict):
                    if str(x.get("code")) == "2321600":
                        print(f"\n常滑市（2321600）の所 {path}:")
                        print(json.dumps(x, ensure_ascii=False)[:3000])
                    for k, v in x.items():
                        walk(v, f"{path}.{k}")
                elif isinstance(x, list):
                    for i, v in enumerate(x):
                        walk(v, f"{path}[{i}]")
            walk(d, "")
            print("\n発表の一覧（配列の要素ごと）:")
            for i, rep in enumerate(d if isinstance(d, list) else [d]):
                w = rep.get("warning") or {}
                tok = [it for key in w for it in (w.get(key) or []) if isinstance(it, dict) and it.get("areaCode") == "2321600"]
                print(f"  [{i}] {rep.get('reportDatetime')} {rep.get('dataTypeCode')} {rep.get('infoType')} "
                      f"項目 {list(w.keys())}・常滑市 {json.dumps(tok, ensure_ascii=False)[:600]}")
                print(f"       {str(rep.get('headlineText'))[:120]}")
    for name in ("map_time", "map"):
        st, body = get(BASE + f"/bosai/warning/data/r8/{name}.json")
        print(f"\n/bosai/warning/data/r8/{name}.json: HTTP {st}・先頭 {(body or '')[:400]}")

    # 置き場所がまた変わったときのために、警報のページのプログラムからデータの URL らしい文字も探す
    scripts = set()
    for page in PAGES:
        st, html = get(BASE + page)
        srcs = re.findall(r'<script[^>]*\ssrc\s*=\s*["\']?([^"\' >]+)', html or "", re.I)
        print(f"{page}: HTTP {st}・{len(html or '')} 文字・script {srcs}")
        for src in srcs:
            scripts.add(urljoin(BASE + page, src))
        if page in ("/bosai/warning/", "/bosai/map.html") and html:
            scripts.add(("inline", page, html))            # ページの中に直接書かれたプログラムも調べる
    found = set()
    for js in sorted(scripts, key=str):
        if isinstance(js, tuple):
            st, text, js = 200, js[2], f"{js[1]} の中"
        else:
            st, text = get(js)
        text = text or ""
        hits = set(re.findall(r'["\'`]([^"\'`\s]{0,80}\.json[^"\'`\s]{0,20})["\'`]', text))
        hits |= set(re.findall(r'["\'`]([^"\'`\s]{0,60}data/[^"\'`\s]{0,80})["\'`]', text))
        print(f"\n{js}（HTTP {st}・{len(text)} 文字）")
        for h in sorted(hits)[:80]:
            print("   ", h)
        found |= hits
    if not found:
        print("\nデータの URL らしい文字は見つからなかった")
    return 0


if __name__ == "__main__":
    sys.exit(main())
