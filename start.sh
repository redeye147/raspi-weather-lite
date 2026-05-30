#!/bin/bash
# X11ソケットが存在すればデスクトップ(X11)モード、なければPi OS Lite(kmsdrm)モード
if [ -S /tmp/.X11-unix/X0 ]; then
    # デスクトップ環境 (Raspberry Pi OS with Desktop)
    sleep 10
    export DISPLAY=:0
    export XAUTHORITY=/home/pi/.Xauthority
else
    # Pi OS Lite (kmsdrm直接描画)
    export SDL_VIDEODRIVER=kmsdrm
    export SDL_AUDIODRIVER=dummy
    printf "\033[?25l" > /dev/tty1 2>/dev/null
fi
exec /usr/bin/python3 /home/pi/raspi-weather-lite/main01.py "$@"
