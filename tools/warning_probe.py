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

import requests

BASE = "https://www.jma.go.jp"
PAGES = ["/bosai/warning/", "/bosai/map.html"]
H = {"User-Agent": "raspi-weather-lite (airport weather signage)"}


def get(url):
    try:
        r = requests.get(url, headers=H, timeout=20)
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)


def main():
    old = BASE + "/bosai/warning/data/warning/230000.json"
    st, body = get(old)
    m = re.search(r'"reportDatetime"\s*:\s*"([^"]+)"', body or "")
    print(f"今までの場所: HTTP {st}・発表 {m.group(1) if m else '-'}")

    scripts, found = set(), set()
    for page in PAGES:
        st, html = get(BASE + page)
        print(f"{page}: HTTP {st}")
        for src in re.findall(r'<script[^>]+src="([^"]+)"', html or ""):
            if src.startswith("http"):
                scripts.add(src)
            elif src.startswith("/"):
                scripts.add(BASE + src)
            else:
                scripts.add(BASE + page.rsplit("/", 1)[0] + "/" + src)
    for js in sorted(scripts):
        st, text = get(js)
        hits = set(re.findall(r'["\'`](/?bosai/[A-Za-z0-9_./${}-]*data/[A-Za-z0-9_./${}-]*)', text or ""))
        hits |= set(re.findall(r'["\'`]((?:\.\./)*data/[A-Za-z0-9_./${}-]*warning[A-Za-z0-9_./${}-]*)', text or ""))
        if hits:
            print(f"\n{js} （HTTP {st}）")
            for h in sorted(hits):
                print("   ", h)
            found |= hits
    if not found:
        print("データの URL らしい文字は見つからなかった")
    return 0


if __name__ == "__main__":
    sys.exit(main())
