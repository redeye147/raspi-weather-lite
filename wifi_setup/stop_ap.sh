#!/bin/bash
# AP停止スクリプト：hostapd+dnsmasqを止め、iptablesルール削除、wlan1解放
set +e

PORTAL_PORT="8080"

logger -t wifi-setup "Stopping AP mode"

# iptablesルール削除
iptables -t nat -D PREROUTING -i wlan1 -p tcp --dport 80 -j REDIRECT --to-port "${PORTAL_PORT}" 2>/dev/null

# hostapd停止
pkill -f "hostapd .*hostapd-setup.conf" 2>/dev/null

# dnsmasq停止
if [ -f /run/dnsmasq-setup.pid ]; then
  kill "$(cat /run/dnsmasq-setup.pid)" 2>/dev/null
  rm -f /run/dnsmasq-setup.pid
fi

# wlan1のIP解放
ip addr flush dev wlan1 2>/dev/null
ip link set wlan1 down 2>/dev/null

# 状態フラグ削除
rm -f /run/wifi-setup/state

logger -t wifi-setup "AP mode stopped"
exit 0
