#!/bin/bash
# WiFi設定モード（USB WiFiドングル＋AP＋キャプティブポータル）導入スクリプト
# Pi Zero W / Pi Zero 2 Bookworm 想定。
# プロジェクトのある /home/pi/raspi-weather-lite/ で実行する。
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${DIR}/.." && pwd)"

echo "=== WiFi Setup Mode インストール ==="
echo "プロジェクト: ${PROJECT_DIR}"

# 1) 必要パッケージ
sudo apt update
sudo apt install -y hostapd dnsmasq iptables

# 1-2) Pi本体画面のQRコード表示用 Pythonパッケージ
if [ -d "${PROJECT_DIR}/venv" ]; then
  "${PROJECT_DIR}/venv/bin/pip" install --quiet qrcode pillow flask
else
  sudo apt install -y python3-qrcode python3-pil python3-flask
fi

# 2) hostapd / dnsmasq の自動起動を無効化（設定モード時だけ起こすため）
sudo systemctl unmask hostapd 2>/dev/null || true
sudo systemctl disable hostapd dnsmasq 2>/dev/null || true
sudo systemctl stop hostapd dnsmasq 2>/dev/null || true
sudo systemctl mask dnsmasq 2>/dev/null || true   # 二度と勝手に起動させない
# 過去の手動テストで作られた可能性のある旧設定を退避
if [ -f /etc/dnsmasq.d/setup-ap.conf ]; then
  sudo mv /etc/dnsmasq.d/setup-ap.conf /etc/dnsmasq.d/setup-ap.conf.bak
fi

# 3) NetworkManager に wlan1 を触らせない
sudo cp "${DIR}/nm-unmanage-wlan1.conf" /etc/NetworkManager/conf.d/99-unmanaged-wlan1.conf
sudo systemctl restart NetworkManager
sleep 2

# 4) スクリプトを実行可能に
chmod +x "${DIR}/start_ap.sh" "${DIR}/stop_ap.sh"

# 5) systemd ユニット配置
sudo cp "${DIR}/wifi-setup-mode.service" /etc/systemd/system/
sudo cp "${DIR}/wifi-setup-auto.service" /etc/systemd/system/
chmod +x "${DIR}/check_wifi_on_boot.sh"
sudo systemctl daemon-reload

# 5-2) 起動時自動チェックを有効化（USB挿しっぱなし運用 + WiFi状態で自動分岐）
sudo systemctl enable wifi-setup-auto.service

# 6) udev ルール配置（USB抜去時の安全停止用）
sudo cp "${DIR}/99-wifi-setup-usb.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules

# 6-2) WiFiプロファイルの自動インポート（profiles/ に export_wifi.sh の出力を置いた場合）
PROFILES_DIR="${DIR}/profiles"
if [ -d "${PROFILES_DIR}" ] && ls "${PROFILES_DIR}"/*.nmconnection 2>/dev/null | grep -q .; then
    echo ""
    echo "--- WiFiプロファイル インポート ---"
    NM_DIR="/etc/NetworkManager/system-connections"
    imported=0
    skipped=0
    for src in "${PROFILES_DIR}"/*.nmconnection; do
        name=$(basename "$src")
        dest="${NM_DIR}/${name}"
        if [ -f "${dest}" ]; then
            echo "  スキップ（既存）: ${name}"
            skipped=$((skipped + 1))
        else
            sudo cp "$src" "${dest}"
            sudo chmod 600 "${dest}"
            sudo chown root:root "${dest}"
            echo "  追加: ${name}"
            imported=$((imported + 1))
        fi
    done
    if [ "${imported}" -gt 0 ]; then
        sudo nmcli connection reload 2>/dev/null || sudo systemctl reload NetworkManager 2>/dev/null || true
        echo "  ${imported}件追加、${skipped}件スキップ"
    else
        echo "  全件既存のためスキップ（${skipped}件）"
    fi
    echo ""
fi

# 7) sudoers：portal/main01 が再起動・サービス停止を実行できるよう設定
sudo tee /etc/sudoers.d/wifi-portal > /dev/null <<'EOF'
pi ALL=(ALL) NOPASSWD: /sbin/reboot
pi ALL=(ALL) NOPASSWD: /bin/systemctl stop wifi-setup-mode
pi ALL=(ALL) NOPASSWD: /bin/systemctl start wifi-setup-mode
EOF
sudo chmod 440 /etc/sudoers.d/wifi-portal

# 8) wifi-portal.service の更新（既存）
if [ -f "${PROJECT_DIR}/wifi-portal.service" ]; then
  sudo cp "${PROJECT_DIR}/wifi-portal.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable wifi-portal.service
fi

# 9) main01.service の配置（天気表示を systemd で起動、X不要）
if [ -f "${PROJECT_DIR}/main01.service" ]; then
  sudo cp "${PROJECT_DIR}/main01.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable main01.service
  # .bashrc / .xinitrc / .profile の main01.py 起動行をコメントアウト（重複起動防止）
  for _f in /home/pi/.bashrc /home/pi/.xinitrc /home/pi/.profile /home/pi/.bash_profile; do
    [ -f "$_f" ] || continue
    sed -i \
      's|^\([[:space:]]*\)\(exec \)\{0,1\}python3 \(/home/pi/raspi-weather-lite/\)\{0,1\}main01\.py|\1# &  # moved to systemd main01.service|g' \
      "$_f" || true
  done
fi

echo ""
echo "=== インストール完了 ==="
echo ""
echo "次の手順で動作確認："
echo "  1) USB WiFi ドングル（WD-1513B / 0bda:b711）を挿入"
echo "  2) wlan1 が認識されたか:  ip link show wlan1"
echo "  3) 設定モード起動確認:    systemctl status wifi-setup-mode"
echo "  4) スマホで SSID 'WeatherSetup' に接続（PW: setup1234）"
echo "  5) ブラウザは自動で http://192.168.50.1/ に飛ぶ（キャプティブポータル）"
echo "  6) USBを抜くと設定モード自動終了"
echo ""
echo "手動テスト:  sudo systemctl start wifi-setup-mode"
echo "手動停止:    sudo systemctl stop  wifi-setup-mode"
