#!/bin/bash
# AP起動スクリプト：wlan1にhostapd+dnsmasqを立ち上げ、80→8080へiptables redirectを追加
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
HOSTAPD_CONF="${DIR}/hostapd-setup.conf"
DNSMASQ_CONF="${DIR}/dnsmasq-setup.conf"
AP_IP="192.168.50.1"
AP_NETMASK="24"
PORTAL_PORT="8080"

logger -t wifi-setup "Starting AP mode on wlan1"

# 1) NetworkManagerにwlan1を触らせない（恒久設定はインストール時に投入済み）
nmcli device set wlan1 managed no 2>/dev/null || true

# 2) wlan1にIP付与
ip addr flush dev wlan1
ip addr add "${AP_IP}/${AP_NETMASK}" dev wlan1
ip link set wlan1 up

# 3) 日本のチャンネル規制
iw reg set JP

# 4) 既存hostapd/dnsmasqプロセスを完全停止（残骸でアドレス占有を防ぐ）
systemctl stop dnsmasq 2>/dev/null || true
systemctl stop hostapd 2>/dev/null || true
pkill -9 -f "hostapd"  2>/dev/null || true
pkill -9 -f "dnsmasq"  2>/dev/null || true
sleep 1

# 5) hostapd起動（バックグラウンド）
hostapd -B "${HOSTAPD_CONF}"

# 6) dnsmasq起動（バックグラウンド、wlan1専用設定のみ）
dnsmasq --conf-file="${DNSMASQ_CONF}" --pid-file=/run/dnsmasq-setup.pid

# 7) キャプティブポータル：80番ポートへのアクセスをFlask(8080)へリダイレクト
iptables -t nat -C PREROUTING -i wlan1 -p tcp --dport 80 -j REDIRECT --to-port "${PORTAL_PORT}" 2>/dev/null \
  || iptables -t nat -A PREROUTING -i wlan1 -p tcp --dport 80 -j REDIRECT --to-port "${PORTAL_PORT}"

# 8) AP状態ファイル：Flask/main01.pyが「設定モード中」を検知するためのJSON
mkdir -p /run/wifi-setup
SSID=$(grep '^ssid='           "${HOSTAPD_CONF}" | cut -d= -f2)
PASS=$(grep '^wpa_passphrase=' "${HOSTAPD_CONF}" | cut -d= -f2)
cat > /run/wifi-setup/state <<EOF
{
  "ssid": "${SSID}",
  "password": "${PASS}",
  "ip": "${AP_IP}",
  "url": "http://${AP_IP}/",
  "started_at": $(date +%s)
}
EOF

logger -t wifi-setup "AP mode active: SSID=WeatherSetup IP=${AP_IP}"
