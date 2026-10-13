"""
screenshots.py
天気画面のスクリーンショット（設定画面の「📷 スクリーンショット」と tools/screenshot.py の共通部分）。

保存先: ~/raspi-weather-lite/screenshots/（git の管理外）。最新 MAX_SCREENSHOTS 枚だけ残し、
それより古いものは撮るたびに自動で消す（SD カードを圧迫しないように）。

1. 表示プログラム（main01）に依頼して、画面に出しているものと同じ画像を保存（fb0 / KMS どちらでも）
2. 応答がなければ /dev/fb0 を直接読む（fb0 方式のみ）
"""

import datetime
import os
import re
import time

from config import BASE_DIR, SCREENSHOT_REQUEST

SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
MAX_SCREENSHOTS = 10
WAIT_S = 20          # 表示プログラムは最大 10 秒ごとにループを回るので、その 2 倍待つ
NAME_RE = re.compile(r"^screen_\d{8}_\d{6}\.png$")


def new_path(folder: str = None, now=None) -> str:
    folder = folder or SCREENSHOT_DIR
    now = now or datetime.datetime.now()
    return os.path.join(folder, now.strftime("screen_%Y%m%d_%H%M%S.png"))


def list_shots(folder: str = None) -> list:
    """保存済みのスクリーンショット（新しい順）のファイル名"""
    folder = folder or SCREENSHOT_DIR
    try:
        return sorted((n for n in os.listdir(folder) if NAME_RE.match(n)), reverse=True)
    except OSError:
        return []


def prune(folder: str = None, keep: int = MAX_SCREENSHOTS) -> list:
    """新しい keep 枚を残し、それより古いスクリーンショットを消す。消したファイル名を返す"""
    folder = folder or SCREENSHOT_DIR
    removed = []
    for name in list_shots(folder)[keep:]:
        try:
            os.remove(os.path.join(folder, name))
            removed.append(name)
        except OSError:
            pass
    return removed


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
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
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
    """表示プログラムに保存を依頼し、wait_s 秒以内にファイルができれば True。応答がなければ依頼を取り消す"""
    os.makedirs(os.path.dirname(request_path), exist_ok=True)
    with open(request_path, "w", encoding="utf-8") as f:
        f.write(dest)
    end = time.time() + wait_s
    while time.time() < end:
        if os.path.exists(dest) and not os.path.exists(request_path):
            return True
        time.sleep(0.5)
    try:
        os.remove(request_path)          # あとで勝手に保存されないように
    except OSError:
        pass
    return False


def _give_to_owner(paths, owner_of: str = BASE_DIR) -> None:
    """root（sudo・設定画面）で作ったファイルを、リポジトリの持ち主（pi）のものにする（pi で消せるように）"""
    try:
        st = os.stat(owner_of)
    except OSError:
        return
    for p in paths:
        try:
            os.chown(p, st.st_uid, st.st_gid)
        except OSError:
            pass


def take(folder: str = None, keep: int = MAX_SCREENSHOTS, wait_s: float = WAIT_S,
         request_path: str = SCREENSHOT_REQUEST):
    """スクリーンショットを撮って保存し、古いものを消す。戻り値 (保存したパス, 撮り方)。撮れなければ例外"""
    folder = folder or SCREENSHOT_DIR
    os.makedirs(folder, exist_ok=True)
    dest = new_path(folder)
    if request_from_signage(dest, request_path, wait_s):
        how = "表示プログラムの画面"
    else:
        read_fb0(dest)                    # 失敗したら例外（呼び出し側で表示）
        how = "/dev/fb0"
    _give_to_owner([folder, dest])
    prune(folder, keep)
    return dest, how
