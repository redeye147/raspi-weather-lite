#!/bin/bash
# 家（開発環境）の WiFi につながっていたら、表示の前に自動で最新にする（start.sh が起動のたびに 1 回だけ呼ぶ）。
#   対象の SSID は auto_update_ssids.txt（1 行に 1 つ。公開リポジトリには入れない）に書いた Pi だけ。
#   更新が終わってから表示プログラムを起動する（表示中にファイルを書き換えない）。その間は update_splash.py が
#   「WiFi の接続を確認しています」「最新の版に更新しています」の画面を出す（今していることを PHASE に書く）。
#   （2026-10-25 に一度「裏で更新して表示を先に出す」にしたが、表示プログラムと同時に動いて空港の設定が
#    既定に戻って見えるなど危ういので、この形に戻した）
REPO=/home/pi/raspi-weather-lite
AUTO_SSIDS="$REPO/auto_update_ssids.txt"
PHASE=/run/raspi-weather/update_phase
mkdir -p "$(dirname "$PHASE")"
echo wifi > "$PHASE"
ssid=""
for _ in $(seq 1 30); do                   # WiFi がつながるまで最大 60 秒待つ
    ssid=$(LC_ALL=C nmcli -t -f ACTIVE,SSID dev wifi 2>/dev/null | sed -n 's/^yes://p' | head -1 | sed 's/\\:/:/g')
    [ -n "$ssid" ] && break
    sleep 2
done
if [ -z "$ssid" ] || ! tr -d '\r' < "$AUTO_SSIDS" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -Fxq -- "$ssid"; then
    exit 0
fi
echo update > "$PHASE"
mkdir -p "$REPO/cache"
log="$REPO/cache/auto_update.log"
echo "[auto-update] $(date '+%F %T') WiFi「$ssid」→ 最新に更新してから表示" | tee -a "$log"
if timeout 600 bash "$REPO/update.sh" --auto >> "$log" 2>&1; then
    echo "[auto-update] 完了 $(runuser -u pi -- git -C "$REPO" log -1 --format='%h %s' 2>/dev/null)" | tee -a "$log"
else
    echo "[auto-update] 失敗（今の版で表示を続ける）。詳細: $log" | tee -a "$log"
fi
echo done > "$PHASE"
tail -n 1000 "$log" > "$log.tmp" && mv "$log.tmp" "$log"
