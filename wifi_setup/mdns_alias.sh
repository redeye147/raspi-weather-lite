#!/bin/bash
# 共通の呼び名（tenki.local）を名乗る（2026-11-14。tenki-alias.service が起動のたびに動かす）。
# 子機（iPad など）は、どの現場でも http://tenki.local:8080/now を開けば、その WiFi にいる親の Pi のページが出る。
#   - 各 Pi の名前（tenki-01〜06.local。保守・SSH 用）とは別に、全台が同じ「tenki.local」を名乗ろうとする
#   - 同じ WiFi に何台もいるとき（家など）は、先に名乗った 1 台だけが使い、ほかは 60 秒ごとに名乗り直しを試す
#     （名乗っていた Pi がいなくなれば、ほかの 1 台が引き継ぐ）
#   - 現場が変わって IP アドレスが変わったら、新しい住所で名乗り直す
#   - IPv4 の住所だけを名乗る（iPad が IPv6 でつなぎに行って開けなかったため。avahi_ipv4.sh と同じ考え）
NAME="${MDNS_ALIAS:-tenki}.local"
CHECK_S="${MDNS_CHECK_S:-60}"
pid=""
cur=""

ip_now() {
    # 外へ出るときの自分の IPv4（WiFi と有線のどちらでも）。外への道が無ければ最初の IPv4
    local ip
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}')
    [ -n "$ip" ] || ip=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | grep -v '^127\.' | head -1)
    echo "$ip"
}

trap '[ -n "$pid" ] && kill "$pid" 2>/dev/null; exit 0' TERM INT

while true; do
    ip=$(ip_now)
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
        pid=""                                   # ほかの Pi が名乗っていて、名乗れなかった（あとで試し直す）
    fi
    if [ "$ip" != "$cur" ] && [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; pid=""
    fi
    if [ -n "$ip" ] && [ -z "$pid" ]; then
        [ "$ip" != "$cur" ] && echo "[tenki] $NAME を $ip で名乗ります"
        avahi-publish -a -R "$NAME" "$ip" >/dev/null 2>&1 &
        pid=$!
    fi
    cur="$ip"
    sleep "$CHECK_S"
done
