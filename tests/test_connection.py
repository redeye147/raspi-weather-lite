"""接続の判定（nmcli / ip の出力 → 'wifi' / 'hotspot' / 'ethernet' / ''）"""
import pytest

from main01 import ipv4_devices, parse_connection_kind

HOTSPOT = "setup-hotspot"
IP_WLAN = "2: wlan0    inet 192.168.1.132/24 brd 192.168.1.255 scope global dynamic wlan0"
IP_ETH = "3: eth0    inet 192.168.1.105/24 brd 192.168.1.255 scope global dynamic eth0"


def kind(nmcli_out, ip_out):
    return parse_connection_kind(nmcli_out, HOTSPOT, ipv4_devices(ip_out))


def test_ipv4_devices():
    assert ipv4_devices(IP_WLAN + "\n" + IP_ETH) == {"wlan0", "eth0"}
    assert ipv4_devices("") == set()


@pytest.mark.parametrize("nmcli_out, ip_out, expected", [
    # WiFi のみ
    ("wlan0:wifi:connected:aterm-658250-g\neth0:ethernet:unavailable:", IP_WLAN, "wifi"),
    # WiFi と有線の両方 → WiFi 優先
    ("eth0:ethernet:connected:Wired connection 1\nwlan0:wifi:connected:aterm-658250-g",
     IP_WLAN + "\n" + IP_ETH, "wifi"),
    # 有線のみ（IPv4 あり）
    ("wlan0:wifi:unavailable:\neth0:ethernet:connected:Wired connection 1", IP_ETH, "ethernet"),
    # USB-LAN アダプタの名前が enx… の場合も有線
    ("enxa0cec8:ethernet:connected:Wired connection 1",
     "4: enxa0cec8    inet 10.0.0.5/24 scope global enxa0cec8", "ethernet"),
    # 有線は connected だが IPv6 だけ（IPv4 なし）→ 未接続扱い
    ("wlan0:wifi:unavailable:\neth0:ethernet:connected:Wired connection 1", "", ""),
    # DHCP 待ち（connecting）→ 未接続
    ("eth0:ethernet:connecting (getting IP configuration):Wired connection 1", "", ""),
    # 設定用テザリング
    ("wlan0:wifi:connected:setup-hotspot", "2: wlan0    inet 172.20.10.3/28 scope global wlan0", "hotspot"),
    # テザリング＋有線 → テザリング（WiFi デバイス優先）
    ("wlan0:wifi:connected:setup-hotspot\neth0:ethernet:connected:Wired connection 1",
     "2: wlan0    inet 172.20.10.3/28 scope global wlan0\n" + IP_ETH, "hotspot"),
    # 何もつながっていない
    ("wlan0:wifi:disconnected:\neth0:ethernet:unavailable:\nlo:loopback:connected (externally):lo", "", ""),
    # loopback は接続扱いしない
    ("lo:loopback:connected (externally):lo", "", ""),
])
def test_parse_connection_kind(nmcli_out, ip_out, expected):
    assert kind(nmcli_out, ip_out) == expected


def test_ssid_with_colon_is_unescaped():
    """nmcli -t は値の中の ':' を '\\:' と出力する。テザリング名の比較が崩れないこと"""
    out = "wlan0:wifi:connected:my\\:hotspot"
    ip = "2: wlan0    inet 172.20.10.3/28 scope global wlan0"
    assert parse_connection_kind(out, "my:hotspot", ipv4_devices(ip)) == "hotspot"
    assert parse_connection_kind(out, HOTSPOT, ipv4_devices(ip)) == "wifi"


def test_without_ipv4_check():
    """ipv4_devs を渡さない場合は nmcli の状態だけで判定（後方互換）"""
    assert parse_connection_kind("eth0:ethernet:connected:Wired connection 1", HOTSPOT) == "ethernet"
