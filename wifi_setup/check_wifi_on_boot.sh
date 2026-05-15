#!/bin/bash
# 起動時のWi-Fi接続待ちチェック。接続失敗なら wifi-setup-mode を自動起動。
# 接続成功なら何もせず終了（=天気表示へそのまま進む）

set +e

# ─── ステップ1: NetworkManager の online 状態を待つ（最大20秒） ───
if command -v nm-online > /dev/null 2>&1; then
    logger -t wifi-setup-auto "Waiting for NetworkManager to come online (nm-online -t 20)..."
    nm-online -t 20 -q
    logger -t wifi-setup-auto "nm-online finished (rc=$?)"
fi

# ─── ステップ2: wlan0 の接続を確認＋追加ポーリング（最大20秒） ───
TIMEOUT=20
INTERVAL=2
ELAPSED=0

while [ $ELAPSED -lt $TIMEOUT ]; do
    SSID="$(iwgetid -r 2>/dev/null)"
    IPV4="$(ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}' | head -1)"
    if [ -n "$SSID" ] && [ -n "$IPV4" ]; then
        logger -t wifi-setup-auto "wlan0 connected: SSID='${SSID}' IP=${IPV4} (poll=${ELAPSED}s)"
        exit 0
    fi
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

# ─── タイムアウト：未接続 → 設定モードへ ───
if [ ! -e /sys/class/net/wlan1 ]; then
    logger -t wifi-setup-auto "wlan0 not connected and wlan1 missing - cannot enter setup mode"
    exit 1
fi

logger -t wifi-setup-auto "wlan0 not connected after ~40s total - entering setup mode"
exec systemctl start wifi-setup-mode
