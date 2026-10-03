"""
netstate.py
ネットワーク接続の状態判定と WiFi 設定モード（AP）の操作。
main01.py から移動（中身は変更なし）。nmcli / ip / systemctl を呼ぶ。
"""

import logging
import os
import subprocess
import time

SETUP_HOTSPOT_CON = "setup-hotspot"   # wifi_setup/add_setup_hotspot.sh で登録する設定用テザリング


def ipv4_devices(ip_out: str) -> set:
    """`ip -4 -o addr show scope global` の出力から、IPv4 アドレスを持つデバイス名の集合を返す"""
    devs = set()
    for line in ip_out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            devs.add(parts[1])
    return devs


def parse_connection_kind(nmcli_device_out: str, hotspot_con: str, ipv4_devs=None) -> str:
    """`nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device` の出力から接続の種類を返す。
    'wifi'（登録 WiFi）/ 'hotspot'（設定用テザリング）/ 'ethernet'（有線 LAN）/ ''（未接続）。
    ipv4_devs を渡すと、IPv4 アドレスの無いデバイスは未接続扱い（IPv6 だけ取れた場合など）。
    WiFi と有線の両方がつながっていれば WiFi を優先して返す（経路も WiFi 優先に設定している）。"""
    wifi_con = None
    wired = False
    for line in nmcli_device_out.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4 or parts[2] != "connected":
            continue
        dev, dev_type, _, con = parts
        if ipv4_devs is not None and dev not in ipv4_devs:
            continue
        con = con.replace("\\:", ":")
        if dev_type == "wifi":
            wifi_con = con
        elif dev_type == "ethernet":
            wired = True
    if wifi_con is not None:
        return "hotspot" if wifi_con == hotspot_con else "wifi"
    return "ethernet" if wired else ""


def get_connection_kind() -> str:
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"],
                           capture_output=True, text=True, timeout=5)
        ip = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                            capture_output=True, text=True, timeout=5)
        return parse_connection_kind(r.stdout, SETUP_HOTSPOT_CON, ipv4_devices(ip.stdout))
    except Exception:
        return "unknown"   # 判定できないときは接続中扱い（誤って設定モードに入らないため）


def is_network_connected() -> bool:
    """WiFi・テザリング・有線 LAN のいずれかで（IPv4 アドレス付きで）つながっているか"""
    return get_connection_kind() != ""


def wired_cable_status() -> str:
    """有線 LAN の状態：'' = ケーブル無し（またはアダプタ無し）/ 'no_ip' = ケーブルは挿さっているが IP 未取得"""
    try:
        for dev in os.listdir("/sys/class/net"):
            if not os.path.exists(f"/sys/class/net/{dev}/device") or dev.startswith("wlan"):
                continue   # 実デバイスのみ（lo・仮想 IF・WiFi を除く）
            try:
                carrier = open(f"/sys/class/net/{dev}/carrier").read().strip() == "1"
            except OSError:
                carrier = False
            if carrier:
                return "no_ip"
    except Exception:
        pass
    return ""


def stop_ap_mode() -> None:
    try:
        subprocess.Popen(["sudo", "systemctl", "stop", "wifi-setup-mode"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("ネットワーク接続を検出 → 設定モード（AP）を自動終了")
    except Exception as e:
        logging.error(f"wifi-setup-mode 停止失敗: {e}")


def is_ap_mode_active() -> bool:
    return os.path.exists("/run/wifi-setup/state")


def has_wlan1() -> bool:
    return os.path.exists("/sys/class/net/wlan1")


_last_ap_trigger_time = 0.0

def trigger_ap_mode() -> bool:
    global _last_ap_trigger_time
    if time.time() - _last_ap_trigger_time < 60:
        return False
    try:
        subprocess.Popen(
            ["sudo", "systemctl", "start", "wifi-setup-mode"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _last_ap_trigger_time = time.time()
        logging.info("wifi-setup-mode 自動起動をトリガ")
        return True
    except Exception as e:
        logging.error(f"wifi-setup-mode 起動失敗: {e}")
        return False


def get_setup_hotspot_ssid() -> str:
    """設定用テザリングの SSID（未登録なら空文字）。パスワードは画面に出さない。"""
    try:
        r = subprocess.run(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", SETUP_HOTSPOT_CON],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def is_on_setup_hotspot() -> bool:
    """いま設定用テザリング（setup-hotspot）で接続しているか"""
    return get_connection_kind() == "hotspot"
