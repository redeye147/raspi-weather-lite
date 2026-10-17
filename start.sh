#!/bin/bash
# 家（開発環境）の WiFi につながっていたら、表示の前に自動で最新にする（update.sh --auto）。
#   対象の SSID は auto_update_ssids.txt（1 行に 1 つ。公開リポジトリには入れない）に書いた Pi だけ。
#   電源を入れて最初の起動のときだけ（表示プログラムの異常終了からの再起動では行わない）。
#   更新が失敗・タイムアウト（10 分）しても、今の版で表示を始める。
REPO=/home/pi/raspi-weather-lite
AUTO_SSIDS="$REPO/auto_update_ssids.txt"
AUTO_MARK=/run/raspi-weather-auto-updated     # /run は再起動で消える
if [ -s "$AUTO_SSIDS" ] && [ ! -e "$AUTO_MARK" ]; then
    touch "$AUTO_MARK"
    ssid=""
    for _ in $(seq 1 30); do                   # WiFi がつながるまで最大 60 秒待つ
        ssid=$(LC_ALL=C nmcli -t -f ACTIVE,SSID dev wifi 2>/dev/null | sed -n 's/^yes://p' | head -1 | sed 's/\\:/:/g')
        [ -n "$ssid" ] && break
        sleep 2
    done
    if [ -n "$ssid" ] && tr -d '\r' < "$AUTO_SSIDS" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -Fxq -- "$ssid"; then
        mkdir -p "$REPO/cache"
        log="$REPO/cache/auto_update.log"
        echo "[auto-update] $(date '+%F %T') WiFi「$ssid」→ 最新に更新してから表示" | tee -a "$log"
        if timeout 600 bash "$REPO/update.sh" --auto >> "$log" 2>&1; then
            echo "[auto-update] 完了 $(runuser -u pi -- git -C "$REPO" log -1 --format='%h %s' 2>/dev/null)" | tee -a "$log"
        else
            echo "[auto-update] 失敗（今の版で表示を続ける）。詳細: $log" | tee -a "$log"
        fi
        tail -n 1000 "$log" > "$log.tmp" && mv "$log.tmp" "$log"
    fi
fi

# Display mode auto-detection:
#   lightdm active  -> Pi OS Desktop (X11)
#   X11 socket exists -> X11 (fallback)
#   otherwise       -> Pi OS Lite (kmsdrm)

if systemctl is-active --quiet lightdm 2>/dev/null; then
    # デスクトップ環境: lightdm が完全起動するまで待つ
    sleep 15
    export DISPLAY=:0
    export XAUTHORITY=/home/pi/.Xauthority
elif [ -S /tmp/.X11-unix/X0 ]; then
    export DISPLAY=:0
    export XAUTHORITY=/home/pi/.Xauthority
else
    # Pi OS Lite: KMS/DRM 直接描画
    export SDL_VIDEODRIVER=kmsdrm
    export SDL_AUDIODRIVER=dummy
    printf "\033[?25l" > /dev/tty1 2>/dev/null
fi

exec /usr/bin/python3 /home/pi/raspi-weather-lite/main01.py "$@"
