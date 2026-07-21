#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fb_display.py
描画モードの自動判定と /dev/fb0 直書きフォールバック。

一部のハード（例: Pi Zero 2W + 特定TV）では SDL kmsdrm が
set_mode に成功しても実際には HDMI に何も表示されない。
その場合に offscreen レンダリング + /dev/fb0 への直接書き込み
（RGB565）へフォールバックして表示する。

使い方:
    from fb_display import init_display, present
    screen = init_display("auto")   # 'auto' | 'kmsdrm' | 'fb0' | 'x11'
    ...
    present(screen)                 # pygame.display.flip() の代わり

RENDER_MODE が 'fb0' のときだけ /dev/fb0 に書き込む。
それ以外（x11 / kmsdrm）では present() は通常の flip のみ。
"""

import os
import time
import logging
import mmap as _mmap_module

import pygame

try:
    import numpy as _np
except ImportError:
    _np = None

# fb0 直書きモード用ステート（RENDER_MODE='fb0' のとき使用）
_fb_mmap = None
_fb_w = 0
_fb_h = 0

# 描画モード（init_display() で決まる）: 'x11' | 'kmsdrm' | 'fb0'
RENDER_MODE = 'x11'


def _init_fb(tty_path='/dev/tty'):
    """offscreen モード用: VT テキスト描画を抑制して /dev/fb0 をオープン。"""
    global _fb_mmap, _fb_w, _fb_h
    import fcntl
    KD_GRAPHICS = 1
    KDSETMODE   = 0x4B3A
    print("[fb0] _init_fb start", flush=True)
    try:
        # TTY はシーク不可なので 'wb' で開く
        with open(tty_path, 'wb') as tty:
            tty.write(b'\033[2J\033[H\033[?25l')
            tty.flush()
            fcntl.ioctl(tty.fileno(), KDSETMODE, KD_GRAPHICS)
        print("[fb0] KD_GRAPHICS OK", flush=True)
    except Exception as e:
        print(f"[fb0] KD_GRAPHICS FAILED: {e}", flush=True)
    try:
        print("[fb0] opening fb0 ...", flush=True)
        info = open('/sys/class/graphics/fb0/virtual_size').read().strip()
        _fb_w, _fb_h = map(int, info.split(','))
        print(f"[fb0] size={_fb_w}x{_fb_h}", flush=True)
        fd = open('/dev/fb0', 'r+b')
        fb_size = _fb_w * _fb_h * 2   # 16-bit RGB565
        _fb_mmap = _mmap_module.mmap(fd.fileno(), fb_size)
        print(f"[fb0] initialized {_fb_w}x{_fb_h}", flush=True)
    except Exception as e:
        print(f"[fb0] FAILED: {e}", flush=True)


def _try_kmsdrm(verify=True):
    """kmsdrm で pygame display 初期化。
    verify=True のとき: マゼンタを描画→fb0 を読んでピクセルを検証。
    成功→screen を返す。失敗→None。
    """
    global RENDER_MODE
    os.environ['SDL_VIDEODRIVER'] = 'kmsdrm'
    try:
        pygame.display.init()
        pygame.mouse.set_visible(False)
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    except Exception as e:
        print(f"[display] kmsdrm init failed: {e}", flush=True)
        return None

    if not verify:
        RENDER_MODE = 'kmsdrm'
        print(f"[display] mode=kmsdrm size={screen.get_size()}", flush=True)
        return screen

    w, h = screen.get_size()
    screen.fill((255, 0, 255))  # マゼンタ
    pygame.display.flip()
    time.sleep(0.6)
    try:
        with open('/dev/fb0', 'rb') as f:
            f.seek(((h // 2) * w + w // 2) * 2)
            pix = int.from_bytes(f.read(2), 'little')
        # RGB565 マゼンタ = 0xF81F（赤31, 緙0, 獩31）
        # G チャンネルが 0 であることが重要（白 0xFFFF を弾く）
        r = (pix >> 11) & 0x1F
        g = (pix >> 5)  & 0x3F
        b = pix & 0x1F
        if r >= 28 and g <= 4 and b >= 28:
            RENDER_MODE = 'kmsdrm'
            print(f"[display] mode=kmsdrm verified, pix=0x{pix:04x} (R{r} G{g} B{b})", flush=True)
            return screen
        print(f"[display] kmsdrm verification failed (fb0 pix=0x{pix:04x} R{r} G{g} B{b})", flush=True)
    except Exception as e:
        print(f"[display] kmsdrm verify error: {e}", flush=True)
    return None


def _init_fb0_mode():
    """offscreen + /dev/fb0 直書きモードで pygame display 初期化。"""
    global RENDER_MODE
    os.environ['SDL_VIDEODRIVER'] = 'offscreen'
    pygame.display.init()
    pygame.mouse.set_visible(False)
    try:
        _fb_info = open('/sys/class/graphics/fb0/virtual_size').read().strip()
        _fw, _fh = map(int, _fb_info.split(','))
    except Exception:
        _fw, _fh = 1920, 1080
    screen = pygame.display.set_mode((_fw, _fh))
    _init_fb()
    RENDER_MODE = 'fb0'
    print(f"[display] mode=fb0 size={screen.get_size()}", flush=True)
    return screen


def init_display(mode_request):
    """描画モードを決定して pygame の display を初期化。
    mode_request: 'auto' | 'kmsdrm' | 'fb0' | 'x11'
    戻り値: 描画対象の pygame Surface（画面）
    """
    global RENDER_MODE
    pygame.font.init()

    # X11 環境（DISPLAY が設定されている）はそのまま使う
    if mode_request == 'x11' or (mode_request == 'auto' and os.environ.get('DISPLAY')):
        pygame.init()
        pygame.mouse.set_visible(False)
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        RENDER_MODE = 'x11'
        print(f"[display] mode=x11 size={screen.get_size()}", flush=True)
        return screen

    if mode_request == 'fb0':
        return _init_fb0_mode()

    if mode_request == 'kmsdrm':
        screen = _try_kmsdrm(verify=False)
        if screen is None:
            raise RuntimeError("kmsdrm init failed (--render=kmsdrm 指定)")
        return screen

    # auto: kmsdrm を試す → 失敗時 fb0 にフォールバック
    screen = _try_kmsdrm(verify=True)
    if screen is not None:
        return screen
    print("[display] kmsdrm 失敗 → offscreen+fb0 にフォールバック", flush=True)
    pygame.display.quit()
    return _init_fb0_mode()


def flip_to_fb(surface):
    """pygame サーフェスを RGB565 変換して /dev/fb0 へ書き込む。
    fb0 モード以外では何もしない。"""
    if RENDER_MODE != 'fb0' or _fb_mmap is None or _np is None:
        return
    try:
        arr = pygame.surfarray.array3d(surface)   # (W, H, 3) uint8
        if arr.shape[0] != _fb_w or arr.shape[1] != _fb_h:
            surface = pygame.transform.scale(surface, (_fb_w, _fb_h))
            arr = pygame.surfarray.array3d(surface)
        arr = arr.swapaxes(0, 1)                  # (H, W, 3)
        r = arr[:, :, 0].astype(_np.uint16) >> 3
        g = arr[:, :, 1].astype(_np.uint16) >> 2
        b = arr[:, :, 2].astype(_np.uint16) >> 3
        rgb565 = (r << 11) | (g << 5) | b
        _fb_mmap.seek(0)
        _fb_mmap.write(rgb565.astype('<u2').tobytes())
    except Exception as e:
        logging.warning(f"fb0 flip failed: {e}")


def present(surface):
    """通常の flip に加え、fb0 モードなら /dev/fb0 にも書き込む。
    pygame.display.flip() の置き換えとして使う。"""
    pygame.display.flip()
    flip_to_fb(surface)
