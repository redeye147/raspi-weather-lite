"""
startup.py
起動の補助：起動ログ（経過秒数つき）、時刻同期の確認、前回の表示データ（スナップショット）の保存・読込。
main01.py から移動（中身は変更なし）。
"""

import datetime
import json
import logging
import os
import subprocess
import time

from utils import JST


# 起動高速化：前回の表示データ（スナップショット）の保存先
SNAPSHOT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "snapshot.json")


def boot_log(msg: str) -> None:
    """起動からの経過秒数つきで journal とログに記録（起動直後の時刻ずれの影響を受けない）"""
    try:
        up = float(open("/proc/uptime").read().split()[0])
    except Exception:
        up = -1.0
    print(f"[boot] {up:.1f}s {msg}", flush=True)
    logging.info(f"[boot] 起動後 {up:.1f}s {msg}")


def wait_time_sync(timeout_s: float = 15) -> bool:
    """NTP で時刻同期済みになるまで最大 timeout_s 秒待つ（Pi は電池時計が無く起動直後は時刻がずれる）"""
    end = time.time() + timeout_s
    while True:
        try:
            r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                               capture_output=True, text=True, timeout=3)
            if r.stdout.strip() == "yes":
                return True
        except Exception:
            return False
        if time.time() >= end:
            return False
        time.sleep(1)


def _json_default(o):
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def save_snapshot(state: dict) -> None:
    """表示に必要なデータ一式を保存（取得・更新が成功したときだけ呼ぶ。SD 書込みを減らすため）"""
    try:
        os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
        tmp = SNAPSHOT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, default=_json_default, ensure_ascii=False)
        os.replace(tmp, SNAPSHOT_FILE)
    except Exception as e:
        logging.warning(f"スナップショット保存失敗: {e}")


def load_snapshot():
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            snap = json.load(f)
        for item in snap.get("hourly", []):
            if isinstance(item.get("datetime"), str):
                dt = datetime.datetime.fromisoformat(item["datetime"])
                item["datetime"] = dt.replace(tzinfo=JST) if dt.tzinfo is None else dt
        return snap
    except Exception:
        return None
