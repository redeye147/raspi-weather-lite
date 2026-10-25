#!/usr/bin/env python3
"""
update_splash.py
起動時の自動更新（auto_update.sh）の間に出す画面。黒い画面のまま 1〜2 分待たせないように。

start.sh が自動更新の前に裏で起動し、更新が終わったら止める（SIGTERM）。そのあと表示プログラムを起動する。
今していること（WiFi の確認・更新）は auto_update.sh が PHASE_FILE に書く。画面は 3 秒ごとに描き直す
（Pi Zero W の fb0 では 1 回の描画が重いので、更新の邪魔をしないように控えめに）。
"""

import os
import signal
import sys
import time

import pygame

import fb_display
from config import BASE_FONT

PHASE_FILE = "/run/raspi-weather/update_phase"
REDRAW_S = 3.0
MESSAGES = {
    "wifi": ("WiFi の接続を確認しています", "最大 1 分ほどお待ちください"),
    "update": ("最新の版に更新しています", "1〜2 分ほどで天気画面になります"),
    "done": ("更新が終わりました", "天気画面を起動しています"),
}
_SPINNER = ["｜", "／", "―", "＼"]


def phase():
    try:
        with open(PHASE_FILE, encoding="utf-8") as f:
            return f.read().strip() or "wifi"
    except OSError:
        return "wifi"


def draw(screen, started, now=None):
    now = now or time.time()
    w, h = screen.get_size()
    screen.fill((10, 12, 20))
    title, sub = MESSAGES.get(phase(), MESSAGES["wifi"])
    f_title = pygame.font.Font(BASE_FONT, max(28, h // 20))
    f_title.set_bold(True)
    t = f_title.render("天気サイネージ", True, (255, 215, 0))
    screen.blit(t, ((w - t.get_width()) // 2, int(h * 0.22)))
    f_msg = pygame.font.Font(BASE_FONT, max(22, h // 30))
    spin = _SPINNER[int(now / REDRAW_S) % len(_SPINNER)]
    m = f_msg.render(f"{spin}  {title}", True, (255, 210, 50))
    screen.blit(m, ((w - m.get_width()) // 2, int(h * 0.48)))
    f_sub = pygame.font.Font(BASE_FONT, max(18, h // 45))
    s = f_sub.render(f"{sub}（{int(now - started)} 秒）", True, (160, 170, 200))
    screen.blit(s, ((w - s.get_width()) // 2, int(h * 0.48) + m.get_height() + 16))
    fb_display.present(screen)


def main():
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    screen = fb_display.init_display("auto", allow_headless=True)
    pygame.mouse.set_visible(False)
    started = time.time()
    while not stop["now"]:
        if fb_display.RENDER_MODE != "headless":
            draw(screen, started)
        end = time.time() + REDRAW_S
        while time.time() < end and not stop["now"]:
            time.sleep(0.2)
    pygame.quit()                               # 表示プログラムが画面を使えるように手放す
    return 0


if __name__ == "__main__":
    sys.exit(main())
