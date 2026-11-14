#!/bin/bash
# Pi の名前（例 raspberrypi2.local）で引いたとき、IPv4 の住所だけを返すようにする（avahi の設定）。
# 2026-11-14 の 118：名前で引くと IPv6 の住所も返り、iPad はその IPv6 でつなぎに行って「サーバーが応答を停止」になった
# （IP アドレスなら開けた）。IPv6 の知らせを止めると、iPad でも名前で開けた。
# 名前が勝手に「-2」付きに変わる（自分の IPv6 の知らせを他人のものと見間違える）ことも減る。
#   [server]  use-ipv6=no                 IPv6 では知らせない・答えない
#   [publish] publish-aaaa-on-ipv4=no     IPv4 の知らせに IPv6 の住所を載せない
# 使い方: avahi_ipv4.sh [avahi-daemon.conf のパス] [--no-restart]   既にそうなっていれば何もしない
conf="${1:-/etc/avahi/avahi-daemon.conf}"
[ -f "$conf" ] || { echo "  avahi の設定ファイルが見つかりません（$conf）"; exit 0; }
changed=$(python3 - "$conf" <<'EOF'
import re, sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
orig = text

def ensure(text, section, key, value):
    line = f"{key}={value}"
    pat = re.compile(rf"^[#;]?\s*{re.escape(key)}\s*=.*$", re.M)
    if pat.search(text):
        return pat.sub(line, text, count=1)
    sec = re.compile(rf"^\[{section}\]\s*$", re.M).search(text)
    if sec:
        return text[:sec.end()] + "\n" + line + text[sec.end():]
    return text.rstrip("\n") + f"\n\n[{section}]\n{line}\n"

text = ensure(text, "server", "use-ipv6", "no")
text = ensure(text, "publish", "publish-aaaa-on-ipv4", "no")
if text != orig:
    open(path, "w", encoding="utf-8").write(text)
    print("yes")
EOF
)
if [ "$changed" = "yes" ]; then
    echo "  名前で引いたとき IPv4 の住所だけを返すようにしました（avahi）"
    [ "$2" = "--no-restart" ] || systemctl restart avahi-daemon 2>/dev/null || true
else
    echo "  名前で引いたとき IPv4 の住所だけを返す設定になっています（avahi）"
fi
