#!/bin/bash
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
