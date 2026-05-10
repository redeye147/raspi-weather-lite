#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== raspi-weather-lite セットアップ ===${NC}"

# ── 空港選択 ──────────────────────────────────────
echo ""
echo "空港を選択してください:"
echo "  1) centrair - 中部国際空港 (デフォルト)"
echo "  2) narita   - 成田空港"
echo "  3) haneda   - 羽田空港"
echo "  4) kanku    - 関西国際空港"
read -p "番号を入力 [1]: " airport_choice

case "$airport_choice" in
  2) AIRPORT="narita"    ;;
  3) AIRPORT="haneda"   ;;
  4) AIRPORT="kanku"    ;;
  *) AIRPORT="centrair" ;;
esac
echo -e "空港: ${GREEN}$AIRPORT${NC}"

REPO_DIR="/home/pi/raspi-weather-lite"

# ── [1/5] パッケージ ───────────────────────────────
echo -e "\n${YELLOW}[1/5] パッケージをインストール中...${NC}"
sudo apt update -qq
sudo apt install -y \
  python3-pygame python3-requests python3-psutil \
  python3-flask python3-pip \
  fonts-ipafont \
  network-manager git
pip3 install "astral>=2.0" qrcode pillow pytz --break-system-packages -q

# ── [2/5] リポジトリ ───────────────────────────────
echo -e "\n${YELLOW}[2/5] リポジトリをクローン中...${NC}"
if [ -d "$REPO_DIR/.git" ]; then
  echo "既存リポジトリを更新します"
  git -C "$REPO_DIR" pull
else
  git clone https://github.com/redeye147/raspi-weather-lite.git "$REPO_DIR"
fi

# ── [3/5] 設定ファイル ─────────────────────────────
echo -e "\n${YELLOW}[3/5] 設定ファイルを作成中...${NC}"
cat > "$REPO_DIR/config.json" << EOF
{
  "airport": "$AIRPORT",
  "interval_hours": 2.0
}
EOF

# ── [4/5] 自動起動（kmsdrm / X不要）─────────────────
echo -e "\n${YELLOW}[4/5] 自動起動を設定中...${NC}"

# コンソール自動ログイン有効化
sudo raspi-config nonint do_boot_behaviour B2

# videoグループ追加（kmsdrm描画に必要）
sudo usermod -a -G video,render pi

# .profile を設定（startx不要・直接kmsdrm描画）
PROFILE="$HOME/.profile"
if ! grep -q "SDL_VIDEODRIVER" "$PROFILE" 2>/dev/null; then
  cat >> "$PROFILE" << 'PROFILE_EOF'

if [ "$(tty)" = "/dev/tty1" ]; then
    export SDL_VIDEODRIVER=kmsdrm
    exec python3 /home/pi/raspi-weather-lite/main01.py
fi
PROFILE_EOF
fi

# ── [5/5] WiFiポータル systemd ────────────────────
echo -e "\n${YELLOW}[5/5] WiFiポータルをsystemdに登録中...${NC}"
sudo cp "$REPO_DIR/wifi-portal.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wifi-portal
sudo systemctl start wifi-portal

# reboot権限
echo 'pi ALL=(ALL) NOPASSWD: /sbin/reboot' | sudo tee /etc/sudoers.d/pi-reboot > /dev/null

# ── 完了 ──────────────────────────────────────────
echo -e "\n${GREEN}✓ セットアップ完了！${NC}"
echo -e "  空港: ${GREEN}$AIRPORT${NC}"
echo -e "  WiFiポータル: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
read -p "今すぐ再起動しますか？ [y/N]: " do_reboot
if [[ "$do_reboot" =~ ^[Yy]$ ]]; then
  sudo reboot
fi
