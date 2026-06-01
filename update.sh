#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

REPO_DIR="/home/pi/raspi-weather-lite"

echo -e "${GREEN}=== raspi-weather-lite 更新 ===${NC}"

# ── [1/5] 依存パッケージ確認 ──────────────────────────────
echo -e "\n${YELLOW}[1/5] 依存パッケージを確認中...${NC}"

# aptパッケージチェック（Bookworm/Trixie共通）
APT_PKGS=(
    python3-pygame
    python3-requests
    python3-psutil
    python3-qrcode
    fonts-ipafont-gothic
)
MISSING_APT=()
for pkg in "${APT_PKGS[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING_APT+=("$pkg")
    fi
done
if [ ${#MISSING_APT[@]} -gt 0 ]; then
    echo "  apt 未インストール: ${MISSING_APT[*]}"
    sudo apt install -y "${MISSING_APT[@]}"
fi

# Pythonモジュールチェック（aptのパッケージ名が環境により異なる場合も対応）
PY_MODULES=(pytz astral)
for mod in "${PY_MODULES[@]}"; do
    if ! python3 -c "import $mod" &>/dev/null; then
        echo "  $mod 未インストール → apt で試みる..."
        sudo apt install -y "python3-$mod" 2>/dev/null || \
            sudo pip3 install "$mod" --break-system-packages
    fi
done
echo -e "  ${GREEN}パッケージ確認完了${NC}"

# ── [2/5] コード更新 ──────────────────────────────────────
echo -e "\n${YELLOW}[2/5] コードを更新中...${NC}"
git -C "$REPO_DIR" pull
echo -e "  ${GREEN}完了${NC}"

# ── [3/5] サービスファイル更新 ────────────────────────────
echo -e "\n${YELLOW}[3/5] systemd サービスファイルを更新中...${NC}"
chmod +x "$REPO_DIR/start.sh"
sudo cp "$REPO_DIR/main01.service" /etc/systemd/system/main01.service
sudo systemctl daemon-reload
sudo systemctl restart main01
echo -e "  ${GREEN}完了${NC}"

# ── [4/5] watchdog（未設定の場合のみ）────────────────────
echo -e "\n${YELLOW}[4/5] watchdog を確認中...${NC}"

_setup_watchdog() {
    sudo apt install -y watchdog -qq

    local cfg=/boot/firmware/config.txt
    if ! grep -q "dtparam=watchdog=on" "$cfg" 2>/dev/null; then
        echo 'dtparam=watchdog=on' | sudo tee -a "$cfg" > /dev/null
        echo "  DTパラメータを追加しました（再起動後に有効）"
    fi

    sudo tee /etc/watchdog.conf > /dev/null << 'EOF'
watchdog-device = /dev/watchdog
watchdog-timeout = 15
max-load-1 = 24
min-memory = 1
EOF

    sudo systemctl enable watchdog > /dev/null 2>&1
    sudo systemctl restart watchdog 2>/dev/null || true
    echo -e "  ${GREEN}watchdog 設定完了（再起動後に有効）${NC}"
}

if systemctl is-active --quiet watchdog 2>/dev/null; then
    echo "  既に稼働中です（スキップ）"
else
    _setup_watchdog
fi

# ── [5/5] 完了 ────────────────────────────────────────────
echo -e "\n${GREEN}✓ 更新完了！${NC}"
echo ""
read -p "今すぐ再起動しますか？ [y/N]: " do_reboot
if [[ "$do_reboot" =~ ^[Yy]$ ]]; then
    sudo reboot
fi
