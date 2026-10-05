#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

REPO_DIR="/home/pi/raspi-weather-lite"

# 設定画面の「更新」ボタンからは root で動く。リポジトリは pi のものなので、git は pi として実行する
# （root で git を触ると .git に root のファイルができ、あとで pi の手動更新が失敗する）
if [ "$(id -u)" -eq 0 ]; then
    git() { runuser -u pi -- env HOME=/home/pi git "$@"; }
fi

echo -e "${GREEN}=== raspi-weather-lite 更新 ===${NC}"

# ── [1/5] 依存パッケージ確認 ──────────────────────────────
echo -e "\n${YELLOW}[1/5] 依存パッケージを確認中...${NC}"

APT_PKGS=(
    python3-pygame
    python3-requests
    python3-psutil
    python3-qrcode
    python3-flask
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

# main01.service は root で動くため、root の python3 から import できるか確認する
# （pi のユーザー領域 ~/.local に入っているだけだと root からは見えず、起動失敗→再起動を繰り返す）
if ! sudo python3 -c "import pytz" &>/dev/null; then
    echo "  pytz 未インストール → apt で導入"
    sudo apt install -y python3-pytz
fi
if ! sudo python3 -c "from astral.sun import sun" &>/dev/null; then
    echo "  astral 未インストール（root） → pip で導入"
    sudo pip3 install "astral>=2.0" --prefer-binary --break-system-packages -q
fi
echo -e "  ${GREEN}パッケージ確認完了${NC}"

# ── [2/5] コード更新 ──────────────────────────────────
echo -e "\n${YELLOW}[2/5] コードを更新中...${NC}"
cd "$REPO_DIR"
# 実行権限（chmod +x start.sh 等）の違いを変更扱いしない。pull / ブランチ切替が止まるのを防ぐ
git config core.fileMode false
CFG="$REPO_DIR/config.json"
CFG_BAK="$HOME/.raspi-weather-config.json.bak"
[ -f "$CFG" ] && cp "$CFG" "$CFG_BAK"

# config.json は Pi ごとに書き換わるが pull の妨げになるので一旦 HEAD に戻し、pull 後に復元する
if git ls-files --error-unmatch config.json &>/dev/null; then
    git checkout HEAD -- config.json
else
    rm -f "$CFG"
fi
# 実行権限だけの差分（chmod +x）も pull の妨げになるので戻す
git diff HEAD --numstat | awk '$1=="0" && $2=="0" {print $3}' | while read -r f; do
    git checkout HEAD -- "$f"
done

if ! git pull --ff-only; then
    [ -f "$CFG_BAK" ] && cp "$CFG_BAK" "$CFG"
    echo -e "\n\033[0;31m✗ git pull に失敗しました。Pi 上に GitHub に無い変更があります。${NC}"
    echo "  確認: git -C $REPO_DIR status && git -C $REPO_DIR log --oneline origin/main..HEAD"
    echo "  README の「トラブルシューティング」を参照してください。"
    exit 1
fi
[ -f "$CFG_BAK" ] && cp "$CFG_BAK" "$CFG"
echo -e "  ${GREEN}完了${NC}"

# ── [3/5] サービスファイル更新 ────────────────────────────
echo -e "\n${YELLOW}[3/5] systemd サービスファイルを更新中...${NC}"
chmod +x "$REPO_DIR/start.sh"
sudo cp "$REPO_DIR/main01.service"      /etc/systemd/system/main01.service
sudo cp "$REPO_DIR/wifi-portal.service" /etc/systemd/system/wifi-portal.service
# 旧方式（.profile / .bashrc からの main01.py 起動）を無効化し、systemd の main01.service に一本化
for _f in /home/pi/.bashrc /home/pi/.xinitrc /home/pi/.profile /home/pi/.bash_profile; do
    [ -f "$_f" ] || continue
    sed -i \
      's|^\([[:space:]]*\)\(exec \)\{0,1\}python3 \(/home/pi/raspi-weather-lite/\)\{0,1\}main01\.py|\1# &  # moved to systemd main01.service|g' \
      "$_f" || true
done
# 旧リポジトリ raspi-weather の自動起動（pi で main01.py を起動する raspi-weather.service）を停止
if [ -f /etc/systemd/system/raspi-weather.service ]; then
    echo "  旧 raspi-weather.service を無効化"
    sudo systemctl disable --now raspi-weather.service 2>/dev/null || true
fi
# 旧方式の startx（X サーバー起動）を無効化。X が画面を掴むと kmsdrm で直接描画できない。
# if ブロックの中身が空になると .profile が構文エラーになるため、コメントではなく ':' に置き換える
for _f in /home/pi/.profile /home/pi/.bash_profile; do
    [ -f "$_f" ] || continue
    sed -i \
      -e 's|^\([[:space:]]*\)\(exec \)\{0,1\}startx\b.*$|\1:  # startx disabled: main01.service が直接描画（kmsdrm）|' \
      -e 's#\(&&\|;\)[[:space:]]*\(exec \)\{0,1\}startx\b.*$#\1 :  \# startx disabled: main01.service が直接描画（kmsdrm）#' \
      "$_f" || true
done
# 有線 LAN の経路優先度を WiFi より下げる（両方つながっていれば WiFi を使う）
sudo cp "$REPO_DIR/wifi_setup/nm-wired-lower-priority.conf" /etc/NetworkManager/conf.d/98-wired-lower-priority.conf
# 有線＋WiFi 同時接続時の「IP 重複」誤検知を防ぐ ARP 設定
sudo cp "$REPO_DIR/wifi_setup/sysctl-arp.conf" /etc/sysctl.d/98-raspi-weather-arp.conf
sudo sysctl -q -p /etc/sysctl.d/98-raspi-weather-arp.conf || true
sudo systemctl daemon-reload
sudo systemctl enable main01
sudo systemctl enable wifi-portal
# .profile から pi ユーザーで起動していた旧インスタンスが画面を掴んでいると二重起動になるので止める
pkill -u pi -f "raspi-weather-lite/main01.py" 2>/dev/null || true
# 短時間に何度も更新・再起動すると StartLimitBurst（10分で5回）に達して起動できなくなるため記録を消す
sudo systemctl reset-failed main01 2>/dev/null || true
sudo systemctl restart main01
sudo systemctl restart wifi-portal
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

    # Pi Zero Wに合わせた車載平均間閾値（5）を設定
    sudo tee /etc/watchdog.conf > /dev/null << 'EOF'
watchdog-device = /dev/watchdog
watchdog-timeout = 15
max-load-1 = 5
min-memory = 1
EOF

    sudo systemctl enable watchdog > /dev/null 2>&1
    sudo systemctl restart watchdog 2>/dev/null || true
    echo -e "  ${GREEN}watchdog 設定完了（再起動後に有効）${NC}"
}

_update_watchdog_conf() {
    # 既存の設定の max-load-1 が古い場合は更新
    if grep -q "max-load-1 = 24" /etc/watchdog.conf 2>/dev/null; then
        sudo sed -i 's/max-load-1 = 24/max-load-1 = 5/' /etc/watchdog.conf
        sudo systemctl restart watchdog 2>/dev/null || true
        echo "  max-load-1 を 24 → 5 に修正しました"
    fi
}

if systemctl is-active --quiet watchdog 2>/dev/null; then
    echo "  既に稼働中です"
    _update_watchdog_conf
else
    _setup_watchdog
fi

# ── [5/5] 完了 ──────────────────────────────────────────
echo -e "\n${GREEN}✓ 更新完了！${NC}"
echo ""
# 設定画面の「更新」ボタンから（端末なし）で動いたときは聞かない
if [ -t 0 ]; then
    read -p "今すぐ再起動しますか？ [y/N]: " do_reboot
    if [[ "$do_reboot" =~ ^[Yy]$ ]]; then
        sudo reboot
    fi
fi
