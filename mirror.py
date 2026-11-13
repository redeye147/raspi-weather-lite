"""
mirror.py
子機用のページの「サイネージと同じ画面」（2026-11-13）：サイネージの画面をそのまま画像にして子機（iPad など）に見せる。

  - 子機が /screen.jpg を読むたびに、設定画面のサーバー（wifi_portal.py）が want() で「見られている」印を付ける
  - 表示プログラム（main01.py）は、印が 3 分以内に付いていれば、画面を 1 分に 1 回まで画像にする（maybe_save）
  - 見ている子機が無いときは画像を作らない（Pi Zero W の負担を増やさない）
  - 画像はメモリ上（/run）に置く（SD カードに書かない）。書きかけを読まれないよう、別名で書いてから入れ替える
"""

import os
import time

RUN_DIR = "/run/raspi-weather"
SCREEN_FILE = os.path.join(RUN_DIR, "screen.jpg")
WANT_FILE = os.path.join(RUN_DIR, "screen_wanted")
WANT_S = 180            # 最後に見られてからこの秒数のあいだ画像を作る
MIN_INTERVAL_S = 55     # 画像を作るのは 1 分に 1 回まで（画面も 1 分ごとに変わる）


def want(want_file=None):
    """子機が画面の画像を読んだ（見られている印を付ける）"""
    want_file = want_file or WANT_FILE
    try:
        os.makedirs(os.path.dirname(want_file), exist_ok=True)
        with open(want_file, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def _age(path, now):
    try:
        return now - os.path.getmtime(path)
    except OSError:
        return None


def maybe_save(screen, now=None, screen_file=None, want_file=None):
    """見られていて、前の画像から 55 秒以上たっていれば、今の画面を画像にする。作ったら True"""
    import pygame
    now = now or time.time()
    screen_file, want_file = screen_file or SCREEN_FILE, want_file or WANT_FILE
    wanted = _age(want_file, now)
    if wanted is None or wanted > WANT_S:
        return False
    age = _age(screen_file, now)
    if age is not None and age < MIN_INTERVAL_S:
        return False
    os.makedirs(os.path.dirname(screen_file), exist_ok=True)
    root, ext = os.path.splitext(screen_file)
    tmp = f"{root}.tmp{ext}"                      # 拡張子で JPEG にする（pygame は名前の拡張子で形式を決める）
    try:
        pygame.image.save(screen, tmp)
    except Exception:
        tmp = f"{root}.tmp.png"                   # JPEG で書けない pygame なら PNG（中身で見分けて返す）
        pygame.image.save(screen, tmp)
    os.replace(tmp, screen_file)
    return True


def screen_time(screen_file=None):
    """画像を作った時刻（"02:26"。無ければ空）"""
    try:
        return time.strftime("%H:%M", time.localtime(os.path.getmtime(screen_file or SCREEN_FILE)))
    except OSError:
        return ""


def mimetype_of(path):
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return "image/jpeg"
    return "image/png" if head.startswith(b"\x89PNG") else "image/jpeg"
