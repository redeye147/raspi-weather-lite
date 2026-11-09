"""
bootcheck.py
前回の起動が正常に終了したか（再起動・電源オフの手続きをしたか）を、起動の記録（journalctl）で調べる（2026-11-09）。
突然電源が切れていたら WARNING をログに書き、診断ページの「直近の警告」に出す。

2026-11-09 の 112：テレビの USB から電源を取っていて、7:17〜7:28 の間に突然電源が切れた。
正常に終わったときは、前の起動の最後に終了の手続き（Reached target … Reboot・Journal stopped など）が残る。
突然切れたときは、普段の記録（毎時の cron など）で途切れる。
起動ごとに 1 回だけ調べる（/run は起動のたびに空になるので、そこに「調べた」印を置く）。
"""

import datetime
import logging
import os
import re
import subprocess
import threading

DONE_FILE = "/run/raspi-weather/bootcheck_done"
DELAY_S = 120          # 起動の 2 分後に調べる（起動の混雑を避け、時刻合わせも済ませてから）
_CLEAN = re.compile(
    r"Journal stopped|systemd-shutdown|Reached target .*(Reboot|Power-Off|Poweroff|Halt|Shutdown|Final Step)"
    r"|reboot\.target|poweroff\.target|halt\.target|shutdown\.target|Stopped target .*Multi-User"
    r"|The system will (reboot|power off)|System is (rebooting|powering down)",
    re.I)


def _time_of(line):
    """short-iso の 1 行の先頭の時刻（"2026-11-09T07:17:01+0900 raspi2w CRON[..]: ..."）"""
    try:
        return datetime.datetime.fromisoformat(line.split(" ", 1)[0])
    except (ValueError, IndexError):
        return None


def previous_boot(run=subprocess.run):
    """前回の起動の終わり方。{"clean": True/False, "last": 最後の記録の時刻 or None}。分からなければ None"""
    try:
        r = run(["journalctl", "-b", "-1", "-n", "300", "--no-pager", "-o", "short-iso"],
                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None                              # 前回の記録が無い（初めての起動・記録を残さない設定）
    lines = [l for l in (r.stdout or "").splitlines() if l.strip() and not l.startswith("--")]
    if not lines:
        return None
    last = next((t for t in (_time_of(l) for l in reversed(lines)) if t), None)
    return {"clean": any(_CLEAN.search(l) for l in lines), "last": last}


def message(info, now=None):
    """WARNING に書く文。正常に終わっていれば None"""
    if not info or info["clean"]:
        return None
    last = f"最後の記録 {info['last']:%m/%d %H:%M}" if info.get("last") else "最後の記録の時刻は不明"
    return (f"前回は突然電源が切れて終了した（{last}）。電源（テレビの USB など）が切れていないか確認を")


def check_once(run=subprocess.run, done_file=DONE_FILE):
    """起動ごとに 1 回だけ調べてログに書く。書いた文（無ければ None）を返す"""
    if os.path.exists(done_file):
        return None
    msg = message(previous_boot(run))
    if msg:
        logging.warning(msg)
    else:
        logging.info("前回は正常に終了した（または記録なし）")
    try:
        os.makedirs(os.path.dirname(done_file), exist_ok=True)
        with open(done_file, "w") as f:
            f.write("1\n")
    except OSError:
        pass
    return msg


def start_in_background(delay_s=DELAY_S):
    def run():
        try:
            check_once()
        except Exception as e:                   # 調べられなくても表示には関係しない
            logging.info(f"前回の終わり方を調べられなかった: {e}")

    t = threading.Timer(delay_s, run)
    t.daemon = True
    t.start()
