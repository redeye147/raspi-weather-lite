#!/bin/bash
# 設定用テザリング（スマホのアクセスポイント）を「setup-hotspot」として登録する。
# 未登録の WiFi 環境でも、スマホのテザリングを同じ SSID/パスワードでオンにすれば Pi が自動接続し、
# 画面の QR コードから WiFi ポータル（:8080）で現場の WiFi を設定できる。
# 優先度を低く（-10）するので、登録済みの現場 WiFi がある場所ではそちらが優先される。
#
# 使い方: bash add_setup_hotspot.sh [SSID]
#   パスワードは入力を求める（公開リポジトリ・コマンド履歴に残さないため）
set -e

CON="setup-hotspot"
SSID="${1:-}"
if [ -z "$SSID" ]; then
    read -r -p "テザリングの SSID: " SSID
fi
read -r -s -p "テザリングのパスワード（8文字以上）: " PSK; echo
if [ ${#PSK} -lt 8 ]; then
    echo "パスワードは8文字以上にしてください（WPA2 の仕様）"; exit 1
fi

if nmcli -g NAME connection show | grep -Fxq "$CON"; then
    sudo nmcli connection modify "$CON" 802-11-wireless.ssid "$SSID" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
        connection.autoconnect yes connection.autoconnect-priority -10
    echo "更新しました: $CON (SSID=$SSID)"
else
    sudo nmcli connection add type wifi ifname wlan0 con-name "$CON" ssid "$SSID" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
        connection.autoconnect yes connection.autoconnect-priority -10 >/dev/null
    echo "登録しました: $CON (SSID=$SSID)"
fi
nmcli -f NAME,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show | grep -E "NAME|$CON"
