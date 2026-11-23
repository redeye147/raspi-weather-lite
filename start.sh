#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # この場所（Pi 4 の 2 画面機は /home/pi4b/... など）
OWNER="$(stat -c %U "$REPO" 2>/dev/null || echo pi)"
[ "$OWNER" = root ] && OWNER=pi
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
[ -n "$OWNER_HOME" ] || OWNER_HOME="/home/$OWNER"

# Display mode auto-detection:
#   lightdm active  -> Pi OS Desktop (X11)
#   X11 socket exists -> X11 (fallback)
#   otherwise       -> Pi OS Lite (kmsdrm)

if [ "$(systemctl get-default 2>/dev/null)" = "graphical.target" ] || systemctl is-active --quiet lightdm 2>/dev/null; then
    # デスクトップ環境（Raspberry Pi 4 の 2 画面など）：X が起動するまで最大 90 秒待つ
    for _ in $(seq 1 90); do
        [ -S /tmp/.X11-unix/X0 ] && break
        sleep 1
    done
    sleep 5                                    # デスクトップ（パネルなど）が落ち着くまで
    export DISPLAY=:0
    export XAUTHORITY="$OWNER_HOME/.Xauthority"
    # どちらの画面に出すか（config.json の "x11_display"：0 = 1 つ目の画面・"x11_geometry"："1920x1080+0+0"）
    eval "$(/usr/bin/python3 - "$REPO/config.json" <<'PYEOF'
import json, shlex, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    c = {}
for key, env in (("x11_display", "SIGNAGE_X11_DISPLAY"), ("x11_geometry", "SIGNAGE_X11_GEOMETRY")):
    if c.get(key) not in (None, ""):
        print(f"export {env}={shlex.quote(str(c[key]))}")
PYEOF
)"
elif [ -S /tmp/.X11-unix/X0 ]; then
    export DISPLAY=:0
    export XAUTHORITY="$OWNER_HOME/.Xauthority"
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

exec /usr/bin/python3 "$REPO/main01.py" "$@"
