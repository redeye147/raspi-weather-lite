"""スクリーンショット（tools/screenshot.py と main01.save_requested_screenshot）"""
import os
import sys
import threading
import time

import numpy as np
import pygame
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import screenshot  # noqa: E402
import main01  # noqa: E402


@pytest.fixture(autouse=True)
def _pygame():
    pygame.display.init()
    yield


def _rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def test_fb0_rgb565_to_surface():
    """fb0 方式（RGB565）の中身を正しい色の画像にする。stride（1 行のバイト数）が幅より大きくても崩れない"""
    w, h, stride = 3, 2, 8                                    # 1 行 3 画素 = 6 バイト + 余り 2 バイト
    pixels = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0), (128, 128, 128)]
    rows = []
    for y in range(h):
        row = np.array([_rgb565(*pixels[y * w + x]) for x in range(w)] + [0], dtype="<u2")
        rows.append(row.tobytes())
    surf = screenshot.fb_to_surface(b"".join(rows), w, h, 16, stride)
    assert surf.get_size() == (3, 2)
    assert surf.get_at((0, 0))[:3] == (248, 0, 0) and surf.get_at((1, 0))[:3] == (0, 252, 0)
    assert surf.get_at((2, 0))[:3] == (0, 0, 248) and surf.get_at((1, 1))[:3] == (0, 0, 0)


def test_fb0_32bit_bgrx_to_surface():
    raw = bytes([0, 0, 255, 0,   0, 255, 0, 0]) * 2       # 2×2：赤・緑（BGRX）
    surf = screenshot.fb_to_surface(raw, 2, 2, 32, 8)
    assert surf.get_at((0, 0))[:3] == (255, 0, 0) and surf.get_at((1, 1))[:3] == (0, 255, 0)


def test_signage_saves_requested_screenshot(tmp_path):
    """依頼ファイルに書いた保存先へ、表示プログラムが今の画面を保存して依頼ファイルを消す"""
    req, dest = tmp_path / "req", tmp_path / "shots" / "a.png"
    req.write_text(str(dest), encoding="utf-8")
    screen = pygame.Surface((40, 30)); screen.fill((10, 20, 30))
    main01.save_requested_screenshot(screen, str(req))
    assert dest.exists() and not req.exists()
    assert pygame.image.load(str(dest)).get_at((5, 5))[:3] == (10, 20, 30)
    main01.save_requested_screenshot(screen, str(req))        # 依頼が無ければ何もしない


def test_request_from_signage_waits_for_file(tmp_path):
    req, dest = tmp_path / "req", tmp_path / "b.png"
    screen = pygame.Surface((10, 10))

    def signage():                                             # 表示プログラムの代わり：少し後に依頼を処理
        time.sleep(0.6)
        main01.save_requested_screenshot(screen, str(req))
    threading.Thread(target=signage).start()
    assert screenshot.request_from_signage(str(dest), str(req), wait_s=5) is True
    assert dest.exists()


def test_request_is_cancelled_when_signage_does_not_answer(tmp_path):
    """表示プログラムが止まっていたら依頼を取り消す（あとで勝手に保存されないように）"""
    req, dest = tmp_path / "req", tmp_path / "c.png"
    assert screenshot.request_from_signage(str(dest), str(req), wait_s=1) is False
    assert not req.exists() and not dest.exists()
