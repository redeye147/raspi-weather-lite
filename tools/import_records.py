#!/usr/bin/env python3
"""
tools/import_records.py
ほかの Pi の「予報の精度の記録」をこの Pi に取り込む（2026-11-09）。
Pi を入れ替えたとき・空港を切り替えたときに、前の記録をすぐ自動補正や診断ページに使えるように。

使い方（取り込む側の Pi で。記録のファイルは表示プログラム（root）が作るので sudo）:
    sudo python3 ~/raspi-weather-lite/tools/import_records.py --from 192.168.1.110   # その Pi から直接（管理パスワードを聞く）
    sudo python3 ~/raspi-weather-lite/tools/import_records.py verify_raspi2w_RJTT_20261109.csv   # ダウンロードした CSV

同じ時刻・同じ空港の記録がこの Pi に既にあれば、この Pi の分を残す（上書きしない）。何回取り込んでも増えない。
診断ページ（設定画面 → 診断）の「📥 記録を取り込む」でも同じことができる。
"""

import argparse
import getpass
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests  # noqa: E402

import verify  # noqa: E402


def fetch_from(ip, password):
    """ほかの Pi の診断ページから記録（CSV）を取る"""
    base = f"http://{ip}:8080"
    s = requests.Session()
    r = s.post(f"{base}/login", json={"password": password}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"ログインできません：{r.text}")
    r = s.get(f"{base}/diag/verify.csv", timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"記録を取れません：HTTP {r.status_code}")
    r.encoding = "utf-8"
    return r.text


def main():
    ap = argparse.ArgumentParser(description="ほかの Pi の予報の精度の記録を取り込む")
    ap.add_argument("csv", nargs="?", help="ダウンロードした CSV のファイル")
    ap.add_argument("--from", dest="src", help="記録を取る Pi の IP アドレス（例 192.168.1.110）")
    args = ap.parse_args()
    if not args.csv and not args.src:
        ap.error("CSV のファイルか --from <IP> を指定してください")
    if args.src:
        text = fetch_from(args.src, getpass.getpass(f"{args.src} の管理パスワード: "))
    else:
        with open(args.csv, encoding="utf-8", errors="replace") as f:
            text = f.read()
    added, dup = verify.import_csv(text)
    print(f"取り込みました：新しい記録 {added} 件（既にあった {dup} 件はこの Pi の分を残した）")
    print(f"保存先：{verify.BASE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
