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
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)


def main():
    st, body = get(BASE + "/bosai/warning/data/warning/230000.json")
    m = re.search(r'"reportDatetime"\s*:\s*"([^"]+)"', body or "")
    print(f"今までの場所: HTTP {st}・発表 {m.group(1) if m else '-'}")

    scripts = set()
    for page in PAGES:
        st, html = get(BASE + page)
        srcs = re.findall(r'<script[^>]*\ssrc\s*=\s*["\']?([^"\' >]+)', html or "", re.I)
        print(f"{page}: HTTP {st}・{len(html or '')} 文字・script {srcs}")
        for src in srcs:
            scripts.add(urljoin(BASE + page, src))
        if page == "/bosai/warning/" and html:
            print("  ページの先頭:", re.sub(r"\s+", " ", html[:600]))
    found = set()
    for js in sorted(scripts):
        st, text = get(js)
        text = text or ""
        hits = set(re.findall(r'["\'`]([^"\'`\s]{0,80}\.json[^"\'`\s]{0,20})["\'`]', text))
        hits |= set(re.findall(r'["\'`]([^"\'`\s]{0,60}data/[^"\'`\s]{0,80})["\'`]', text))
        print(f"\n{js}（HTTP {st}・{len(text)} 文字）")
        for h in sorted(hits)[:60]:
            print("   ", h)
        found |= hits
    if not found:
        print("\nデータの URL らしい文字は見つからなかった")
    return 0


if __name__ == "__main__":
    sys.exit(main())
