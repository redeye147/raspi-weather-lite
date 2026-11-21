#!/bin/bash
# update.sh・setup.sh が読み込む共通の設定（2026-11-20）。
# 置き場所とユーザーを決め打ちにしない（Pi Zero は /home/pi、Raspberry Pi 4 の現場サイネージ機は /home/pi4b など）。
#   REPO_DIR   このリポジトリの場所（この install_lib.sh のあるフォルダ）
#   OWNER      リポジトリの持ち主（git・デスクトップのユーザー）。OWNER_HOME はその家のフォルダ
#   DESKTOP    1 = デスクトップ（X11）で動く機械（Raspberry Pi 4 の 2 画面など）。0 = Pi Zero のように画面へ直接描く
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OWNER="$(stat -c %U "$REPO_DIR" 2>/dev/null || echo pi)"
[ "$OWNER" = root ] && OWNER=pi
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
[ -n "$OWNER_HOME" ] || OWNER_HOME="/home/$OWNER"
DESKTOP=0
[ "$(systemctl get-default 2>/dev/null)" = "graphical.target" ] && DESKTOP=1
systemctl is-enabled --quiet lightdm 2>/dev/null && DESKTOP=1     # デスクトップのログイン画面が入っていれば、それも

# systemd のサービスファイルを、この置き場所に合わせて入れる（ファイルの中の /home/pi/raspi-weather-lite を置き換える）
install_unit() {
    sed "s#/home/pi/raspi-weather-lite#$REPO_DIR#g" "$REPO_DIR/$1" | sudo tee "/etc/systemd/system/$(basename "$1")" > /dev/null
}

# 古い OS（Raspberry Pi OS Bullseye・Python 3.9。2026-11-20 の Pi 4）でも入るように
PYTZ_PKG=python3-pytz                                  # Bookworm 以降の名前。Bullseye は python3-tz
apt-cache show python3-pytz > /dev/null 2>&1 || PYTZ_PKG=python3-tz
PIP_BSP=""                                             # 古い pip は --break-system-packages を知らない
pip3 install --help 2>/dev/null | grep -q -- "--break-system-packages" && PIP_BSP="--break-system-packages"

# pygame 2 が無ければ（Bullseye の apt は 1.9）pip で入れる（root の python3 から import できるように）
ensure_pygame2() {
    if ! sudo python3 -c "import pygame, sys; sys.exit(0 if pygame.version.vernum[0] >= 2 else 1)" &> /dev/null; then
        echo "  pygame 2 が無い → pip で導入"
        sudo pip3 install "pygame>=2" --prefer-binary $PIP_BSP -q
    fi
    # pip の pygame 2 は、文字・画像・音の部品（SDL2_ttf など）を OS のものを使う。無いと文字が描けずに止まる
    # （2026-11-21 の Pi 4・Bullseye：「libSDL2_ttf-2.0.so.0 が無い」で表示プログラムが起動しなかった）
    if ! sudo python3 -c "import pygame.font; pygame.font.init()" &> /dev/null; then
        echo "  pygame の文字・画像の部品（SDL2）を apt で導入"
        sudo apt install -y libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0
    fi
}

# 起動の設定ファイル（Bookworm 以降は /boot/firmware/config.txt、Bullseye は /boot/config.txt）
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt
