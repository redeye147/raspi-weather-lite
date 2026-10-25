#!/bin/bash
# 家（開発環境）の WiFi につながっていたら、裏で自動で最新にする（start.sh が起動のたびに 1 回だけ呼ぶ）。
#   対象の SSID は auto_update_ssids.txt（1 行に 1 つ。公開リポジトリには入れない）に書いた Pi だけ。
#   天気画面は先に（前回のデータで）出しておき、更新はその裏で行う。新しい版が入ったときだけ、
#   最後に表示プログラムを起動し直す（以前は更新が終わるまで 1〜2 分、画面が黒いままだった）。
#   表示プログラムとは別の systemd のユニット（raspi-weather-auto-update）で動くので、
#   表示プログラムを起動し直しても更新は途中で止まらない。
REPO=/home/pi/raspi-weather-lite
AUTO_SSIDS="$REPO/auto_update_ssids.txt"
ssid=""
for _ in $(seq 1 30); do                   # WiFi がつながるまで最大 60 秒待つ
    ssid=$(LC_ALL=C nmcli -t -f ACTIVE,SSID dev wifi 2>/dev/null | sed -n 's/^yes://p' | head -1 | sed 's/\\:/:/g')
    [ -n "$ssid" ] && break
    sleep 2
done
if [ -z "$ssid" ] || ! tr -d '\r' < "$AUTO_SSIDS" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -Fxq -- "$ssid"; then
    exit 0
fi
mkdir -p "$REPO/cache"
log="$REPO/cache/auto_update.log"
before=$(runuser -u pi -- git -C "$REPO" rev-parse HEAD 2>/dev/null)
echo "[auto-update] $(date '+%F %T') WiFi「$ssid」→ 裏で最新に更新（画面はそのまま）" | tee -a "$log"
if timeout 600 bash "$REPO/update.sh" --auto >> "$log" 2>&1; then
    after=$(runuser -u pi -- git -C "$REPO" rev-parse HEAD 2>/dev/null)
    echo "[auto-update] 完了 $(runuser -u pi -- git -C "$REPO" log -1 --format='%h %s' 2>/dev/null)" | tee -a "$log"
    # 表示中の空港が設定と食い違っていないか（古い版の update.sh は更新の間 config.json を既定の中部国際空港に
    # 戻していたので、その間に表示プログラムが設定を読むと中部になった。2026-10-25 の 112（羽田））
    want=$(python3 -c "import json;print(json.load(open('$REPO/config.json')).get('airport','centrair'))" 2>/dev/null)
    shown=""
    for _ in $(seq 1 12); do                    # 表示プログラムが状態を書くまで最大 2 分待つ（10 秒ごとに書く）
        shown=$(python3 -c "import json;print(json.load(open('/run/raspi-weather/status.json')).get('airport') or '')" 2>/dev/null)
        [ -n "$shown" ] && break
        sleep 10
    done
    if [ -n "$after" ] && [ "$before" != "$after" ]; then
        echo "[auto-update] 新しい版 → 表示プログラムを起動し直す" | tee -a "$log"
        systemctl restart main01
    elif [ -n "$want" ] && [ -n "$shown" ] && [ "$want" != "$shown" ]; then
        echo "[auto-update] 表示中の空港（$shown）が設定（$want）と違う → 表示プログラムを起動し直す" | tee -a "$log"
        systemctl restart main01
    fi
else
    echo "[auto-update] 失敗（今の版で表示を続ける）。詳細: $log" | tee -a "$log"
fi
tail -n 1000 "$log" > "$log.tmp" && mv "$log.tmp" "$log"
