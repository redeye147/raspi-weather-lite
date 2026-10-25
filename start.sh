#!/bin/bash
REPO=/home/pi/raspi-weather-lite

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

# 家（開発環境）の WiFi につながっていたら、表示の前に自動で最新にする（auto_update.sh）。
#   対象の SSID は auto_update_ssids.txt（1 行に 1 つ。公開リポジトリには入れない）に書いた Pi だけ。
#   電源を入れて最初の起動のときだけ（表示プログラムの異常終了からの再起動では行わない）。
#   更新が終わってから表示プログラムを起動する。その間は黒い画面ではなく「更新しています」の画面
#   （update_splash.py）を出す。更新と表示を同時に動かさない（2026-10-25 に一度同時にしたら、
#   空港の設定が既定に戻って見えた）
AUTO_SSIDS="$REPO/auto_update_ssids.txt"
AUTO_MARK=/run/raspi-weather-auto-updated     # /run は再起動で消える
if [ -s "$AUTO_SSIDS" ] && [ ! -e "$AUTO_MARK" ]; then
    touch "$AUTO_MARK"
    /usr/bin/python3 "$REPO/update_splash.py" > /dev/null 2>&1 &
    splash=$!
    bash "$REPO/auto_update.sh"
    kill -TERM "$splash" 2>/dev/null
    for _ in $(seq 1 25); do                   # 画面を手放すまで最大 5 秒待ってから表示プログラムを起動
        kill -0 "$splash" 2>/dev/null || break
        sleep 0.2
    done
    kill -KILL "$splash" 2>/dev/null
    wait "$splash" 2>/dev/null
fi

exec /usr/bin/python3 /home/pi/raspi-weather-lite/main01.py "$@"
