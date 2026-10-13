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
