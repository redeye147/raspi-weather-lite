"""Pi に配る設定ファイルと、それを配置する setup.sh / update.sh の対応"""
import configparser
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as f:
        return f.read()


def test_wifi_powersave_off():
    """WiFi の省電力を切る（NetworkManager の wifi.powersave = 2）"""
    c = configparser.ConfigParser()
    c.read_string(_read("wifi_setup/nm-wifi-powersave-off.conf"))
    sec = c["connection-wifi-powersave-off"]
    assert sec["match-device"] == "type:wifi" and sec["wifi.powersave"] == "2"


def test_journal_persistent_with_limit():
    """ログを SD にも保存（前回の起動の記録を見られる）。書き込みを抑えるため上限あり"""
    c = configparser.ConfigParser()
    c.read_string(_read("wifi_setup/journald-persistent.conf"))
    assert c["Journal"]["Storage"] == "persistent" and c["Journal"]["SystemMaxUse"] == "50M"


@pytest.mark.parametrize("script", ["update.sh", "setup.sh"])
@pytest.mark.parametrize("src, dest", [
    ("wifi_setup/nm-wifi-powersave-off.conf", "/etc/NetworkManager/conf.d/98-wifi-powersave-off.conf"),
    ("wifi_setup/journald-persistent.conf", "/etc/systemd/journald.conf.d/99-persistent.conf"),
    ("wifi_setup/nm-wired-lower-priority.conf", "/etc/NetworkManager/conf.d/98-wired-lower-priority.conf"),
])
def test_scripts_install_config(script, src, dest):
    """setup.sh（新しい Pi）と update.sh（既存の Pi）の両方が同じ設定を配置する"""
    s = _read(script)
    assert f'"$REPO_DIR/{src}" {dest}' in s


@pytest.mark.parametrize("script", ["update.sh", "setup.sh"])
def test_scripts_prepare_journal_dir(script):
    s = _read(script)
    assert "mkdir -p /var/log/journal /etc/systemd/journald.conf.d" in s
    assert "systemctl restart systemd-journald" in s
    assert "journalctl --flush" in s          # 設定した起動のログも SD に書き出す（無いと次の再起動で消える）


@pytest.mark.parametrize("script", ["update.sh", "setup.sh"])
def test_scripts_offer_setup_hotspot(script):
    """未登録の Pi では設定用テザリング（setup-hotspot）の登録を聞く。再起動の質問より前に"""
    s = _read(script)
    assert 'grep -Fxq "setup-hotspot"' in s
    assert '"$REPO_DIR/wifi_setup/add_setup_hotspot.sh"' in s
    assert s.index("add_setup_hotspot.sh") < s.index("今すぐ再起動しますか")


def test_add_setup_hotspot_keeps_secret_out_of_args():
    """パスワードはコマンド引数ではなく、画面に出さない入力（read -s）で受け取る"""
    s = _read("wifi_setup/add_setup_hotspot.sh")
    assert "read -r -s -p" in s and "autoconnect-priority -10" in s


# ---------------------------------------------------------------- 起動時の自動更新（家の WiFi のとき）
def test_update_auto_mode_never_asks_or_restarts_display():
    """update.sh --auto は質問をせず（起動中に止まらない）、表示プログラムも再起動しない（start.sh が続けて起動する）"""
    s = _read("update.sh")
    assert '[ "${1:-}" = "--auto" ] && AUTO=1' in s
    for prompt in ("今すぐ再起動しますか", "今ここで登録しますか"):
        i = s.index(prompt)
        guard = s.rfind('[ "$AUTO" = 1 ] && exit 0', 0, i) if "再起動" in prompt else s.rfind('[ "$AUTO" = 0 ]', 0, i)
        assert guard != -1, prompt
    restart = s.index("sudo systemctl restart main01")
    assert s.rfind('if [ "$AUTO" = 1 ]; then', 0, restart) > s.index("[3/5]")
    assert "runuser -u pi -- /usr/bin/git" in s          # root で動いても git は pi として


def test_start_sh_auto_update_only_on_listed_wifi_once_per_boot():
    s = _read("start.sh")
    assert 'AUTO_SSIDS="$REPO/auto_update_ssids.txt"' in s
    assert "/run/raspi-weather-auto-updated" in s          # 再起動で消える目印：起動ごとに 1 回だけ
    assert 'timeout 600 bash "$REPO/update.sh" --auto' in s
    assert s.index("update.sh\" --auto") < s.index("exec /usr/bin/python3")   # 更新してから表示
    assert "auto_update_ssids.txt" in _read(".gitignore")  # SSID は公開リポジトリに入れない
