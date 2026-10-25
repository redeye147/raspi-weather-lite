#!/bin/bash
# 家（開発環境）の WiFi につながっていたら、裏で自動で最新にする（auto_update.sh）。
#   対象の SSID は auto_update_ssids.txt（1 行に 1 つ。公開リポジトリには入れない）に書いた Pi だけ。
#   電源を入れて最初の起動のときだけ（表示プログラムの異常終了からの再起動では行わない）。
#   天気画面は待たずにすぐ出す。新しい版が入ったら auto_update.sh が表示プログラムを起動し直す。
#   （以前は更新が終わるまで天気画面を出さず、1〜2 分黒い画面のままだった。2026-10-25 の 118）
REPO=/home/pi/raspi-weather-lite
AUTO_SSIDS="$REPO/auto_update_ssids.txt"
AUTO_MARK=/run/raspi-weather-auto-updated     # /run は再起動で消える
if [ -s "$AUTO_SSIDS" ] && [ ! -e "$AUTO_MARK" ]; then
    touch "$AUTO_MARK"
    # 表示プログラムとは別のユニットで動かす（表示プログラムを起動し直しても更新が止まらないように）
    systemd-run --unit=raspi-weather-auto-update --collect --quiet /bin/bash "$REPO/auto_update.sh" 2>/dev/null \
        || setsid /bin/bash "$REPO/auto_update.sh" > /dev/null 2>&1 < /dev/null &
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
