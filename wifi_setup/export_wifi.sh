#!/bin/bash
# このPiに保存されているWiFiプロファイルを wifi_setup/profiles/ にエクスポートする。
# profiles/ はパスワードを含むため .gitignore で除外している（このリポジトリは公開）。
# 別のPiへは USBメモリや scp で wifi_setup/profiles/ にコピーし、install.sh を実行すると取り込まれる。
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILES_DIR="${DIR}/profiles"
NM_DIR="/etc/NetworkManager/system-connections"

echo "=== WiFiプロファイル エクスポート ==="
echo "出力先: ${PROFILES_DIR}"

if [ ! -d "${NM_DIR}" ]; then
    echo "エラー: ${NM_DIR} が見つかりません。NetworkManagerが動作していない可能性があります。"
    exit 1
fi

mkdir -p "${PROFILES_DIR}"
chmod 700 "${PROFILES_DIR}"

count=0
# system-connections は root 専用 (700) なので glob ではなく sudo ls で列挙する
while IFS= read -r f; do
    src="${NM_DIR}/${f}"
    case "$f" in *.nmconnection) ;; *) continue ;; esac
    if sudo grep -qE "^type=(wifi|802-11-wireless)$" "$src" 2>/dev/null; then
        sudo cp "$src" "${PROFILES_DIR}/${f}"
        sudo chown "$(id -u):$(id -g)" "${PROFILES_DIR}/${f}"
        chmod 600 "${PROFILES_DIR}/${f}"
        echo "  エクスポート: ${f}"
        count=$((count + 1))
    fi
done < <(sudo ls -1 "${NM_DIR}")

echo ""
echo "${count}件のWiFiプロファイルをエクスポートしました。"
echo ""
echo "別のPiへのコピー例:"
echo "  scp ${PROFILES_DIR}/*.nmconnection pi@<相手のIP>:~/raspi-weather-lite/wifi_setup/profiles/"
echo "  （相手側で）bash ~/raspi-weather-lite/wifi_setup/install.sh"
echo ""
echo "⚠️  profiles/ にはパスワードが含まれます。git には絶対にコミットしないでください（.gitignore 済み）。"
