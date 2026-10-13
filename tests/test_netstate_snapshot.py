"""つながらないときの状態の記録（netstate.network_snapshot・try_reconnect_wifi）"""
import netstate


def test_snapshot_lines(monkeypatch):
    outputs = {
        ("nmcli", "radio", "wifi"): "enabled",
        ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"): "wlan0:wifi:disconnected:\neth0:ethernet:unavailable:",
        ("ip", "-4", "-o", "addr", "show", "scope", "global"): "",
        ("nmcli", "-t", "-f", "TYPE,NAME", "connection", "show"):
            "802-11-wireless:aterm-658250-g\n802-11-wireless:setup-hotspot\n802-3-ethernet:Wired connection 1",
        ("nmcli", "-t", "-f", "SSID,SIGNAL,CHAN", "device", "wifi", "list", "--rescan", "no"):
            "aterm-658250-g:72:6\n:40:11\nBuffalo-G-52B8:30:1",
        ("journalctl", "-u", "NetworkManager", "-n", "8", "--no-pager", "-o", "cat"):
            "device (wlan0): Activation: failed for connection 'aterm-658250-g'",
    }
    monkeypatch.setattr(netstate, "_cmd", lambda args, timeout=8: outputs.get(tuple(args), ""))
    monkeypatch.setattr(netstate.os.path, "exists", lambda p: p == "/sys/class/net/wlan0")
    monkeypatch.setattr(netstate, "wired_cable_status", lambda: "")
    monkeypatch.setattr("builtins.open", lambda *a, **k: __import__("io").StringIO("down\n"))
    lines = netstate.network_snapshot()
    text = "\n".join(lines)
    assert "WiFi 部品(wlan0): あり down / WiFi の電源: enabled / LANケーブル: なし" in text
    assert "装置: wlan0:wifi:disconnected:" in text
    assert "IPv4: なし" in text
    assert "登録済み WiFi: aterm-658250-g, setup-hotspot" in text
    assert "見えている WiFi（SSID:電波%:ch）: aterm-658250-g:72:6, Buffalo-G-52B8:30:1" in text   # 名前なしは除く
    assert "NetworkManager: device (wlan0): Activation: failed" in text


def test_snapshot_without_wlan0(monkeypatch):
    monkeypatch.setattr(netstate, "_cmd", lambda args, timeout=8: "")
    monkeypatch.setattr(netstate.os.path, "exists", lambda p: False)
    monkeypatch.setattr(netstate, "wired_cable_status", lambda: "no_ip")
    text = "\n".join(netstate.network_snapshot())
    assert "WiFi 部品(wlan0): なし（WiFi が認識されていない）" in text and "LANケーブル: あり" in text
    assert "見えている WiFi（SSID:電波%:ch）: なし" in text
    assert "再接続できない" in netstate.try_reconnect_wifi()


def test_reconnect_asks_networkmanager(monkeypatch):
    calls = []
    monkeypatch.setattr(netstate, "_cmd", lambda args, timeout=8: (calls.append(args), "成功")[1])
    monkeypatch.setattr(netstate.os.path, "exists", lambda p: True)
    assert netstate.try_reconnect_wifi() == "成功"
    assert ["nmcli", "device", "wifi", "rescan"] in calls
    assert ["nmcli", "--wait", "30", "device", "connect", "wlan0"] in calls
