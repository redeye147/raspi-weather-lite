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

# systemd のサービスファイルを、この置き場所に合わせて入れる（ファイルの中の /home/pi/raspi-weather-lite を置き換える）
install_unit() {
    sed "s#/home/pi/raspi-weather-lite#$REPO_DIR#g" "$REPO_DIR/$1" | sudo tee "/etc/systemd/system/$(basename "$1")" > /dev/null
}
