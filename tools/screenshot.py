#!/usr/bin/env python3
"""
tools/screenshot.py
天気サイネージの今の画面を PNG で保存する。

使い方（Pi で）:
    sudo python3 ~/raspi-weather-lite/tools/screenshot.py                 # ~/raspi-weather-lite/screenshots/ に保存
    sudo python3 ~/raspi-weather-lite/tools/screenshot.py ~/写真          # 指定したフォルダに保存

1. 表示プログラム（main01）に依頼して、画面に出しているものと同じ画像を保存する（fb0 / KMS どちらでも）
2. 20 秒以内に応答がなければ（表示プログラムが止まっている等）、/dev/fb0 を直接読んで保存する（fb0 方式のみ）
ファイル名は screen_YYYYmmdd_HHMMSS.png。sudo で動かしても、保存したファイルは実行した人（pi）のものにする。
"""

import datetime
import os
import sys
import time

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_DIR)

from config import SCREENSHOT_REQUEST  # noqa: E402

DEFAULT_DIR = os.path.join(REPO_DIR, "screenshots")
WAIT_S = 20          # 表示プログラムは最大 10 秒ごとにループを回るので、その 2 倍待つ


def fb_to_surface(raw: bytes, width: int, height: int, bpp: int, stride: int):
    """/dev/fb0 の中身（RGB565 または 32bit BGRX）を pygame の Surface にする"""
    import numpy as np
    import pygame
    if bpp == 16:
        px = np.frombuffer(raw, dtype="<u2", count=stride // 2 * height).reshape(height, stride // 2)[:, :width]
        r = ((px >> 11) & 0x1F).astype(np.uint8) << 3
        g = ((px >> 5) & 0x3F).astype(np.uint8) << 2
        b = (px & 0x1F).astype(np.uint8) << 3
        rgb = np.dstack([r, g, b])
    elif bpp == 32:
        px = np.frombuffer(raw, dtype=np.uint8, count=stride * height).reshape(height, stride // 4, 4)[:, :width]
        rgb = px[:, :, [2, 1, 0]]                       # BGRX → RGB
    else:
        raise ValueError(f"対応していない色数: {bpp}bit")
    return pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))


def read_fb0(dest: str) -> None:
    import pygame
    sysfs = "/sys/class/graphics/fb0"
    with open(f"{sysfs}/virtual_size") as f:
        width, height = map(int, f.read().strip().split(","))
    with open(f"{sysfs}/bits_per_pixel") as f:
        bpp = int(f.read().strip())
    try:
        with open(f"{sysfs}/stride") as f:
            stride = int(f.read().strip())
    except OSError:
        stride = width * bpp // 8
    with open("/dev/fb0", "rb") as f:
        raw = f.read(stride * height)
    pygame.image.save(fb_to_surface(raw, width, height, bpp, stride), dest)


def request_from_signage(dest: str, request_path: str = SCREENSHOT_REQUEST, wait_s: float = WAIT_S) -> bool:
    """表示プログラムに保存を依頼し、wait_s 秒以内にファイルができれば True"""
    os.makedirs(os.path.dirname(request_path), exist_ok=True)
    with open(request_path, "w", encoding="utf-8") as f:
        f.write(dest)
    end = time.time() + wait_s
    while time.time() < end:
        if os.path.exists(dest) and not os.path.exists(request_path):
            return True
        time.sleep(0.5)
    try:
        os.remove(request_path)          # 応答がなかった依頼は取り消す（あとで勝手に保存されないように）
    except OSError:
        pass
    return False


def give_to_caller(path: str) -> None:
    """sudo で実行したとき、作ったファイルとフォルダを実行した人のものにする"""
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid and gid:
        for p in (os.path.dirname(path), path):
            try:
                os.chown(p, int(uid), int(gid))
            except OSError:
                pass


def main(argv) -> int:
    folder = os.path.abspath(os.path.expanduser(argv[1])) if len(argv) > 1 else DEFAULT_DIR
    if os.environ.get("SUDO_USER") and len(argv) > 1 and argv[1].startswith("~"):
        folder = os.path.abspath(os.path.expanduser(argv[1].replace("~", f"~{os.environ['SUDO_USER']}", 1)))
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, datetime.datetime.now().strftime("screen_%Y%m%d_%H%M%S.png"))

    print("表示プログラムに画面の保存を依頼中…")
    if request_from_signage(dest):
        how = "表示プログラムの画面"
    else:
        print("表示プログラムの応答がないので、/dev/fb0 を直接読みます")
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        try:
            read_fb0(dest)
        except Exception as e:
            print(f"保存できませんでした: {e}")
            print("（表示プログラムが止まっていて、fb0 方式でもない場合は撮れません。sudo で実行しているかも確認）")
            return 1
        how = "/dev/fb0"
    give_to_caller(dest)
    print(f"保存しました（{how}）: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
