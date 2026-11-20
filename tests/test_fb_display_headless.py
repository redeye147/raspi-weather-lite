"""画面出力が無いとき（HDMI 未接続）の描画先：fb_display.init_display(allow_headless=True)"""
import pygame
import pytest

import fb_display


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    monkeypatch.setattr(fb_display, "RENDER_MODE", fb_display.RENDER_MODE)
    yield
    pygame.display.quit()


def test_no_display_device_gives_headless_screen(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(fb_display, "wait_display_device", lambda: False)
    monkeypatch.setattr(fb_display, "display_signature", lambda: (False, ("disconnected",)))
    screen = fb_display.init_display("auto", allow_headless=True)
    assert fb_display.RENDER_MODE == "headless" and screen.get_size() == fb_display.HEADLESS_SIZE
    fb_display.present(screen)                            # 表示はしない（例外にならない）


def test_without_allow_headless_still_raises(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(fb_display, "wait_display_device", lambda: False)
    with pytest.raises(RuntimeError):
        fb_display.init_display("auto")


def test_display_attached_when_signature_changes(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(fb_display, "wait_display_device", lambda: False)
    sig = [(False, ("disconnected",))]
    monkeypatch.setattr(fb_display, "display_signature", lambda: sig[0])
    fb_display.init_display("auto", allow_headless=True)
    assert not fb_display.display_attached()
    sig[0] = (False, ("connected",))                      # HDMI をつないだ
    assert fb_display.display_attached()


def test_x11_target_for_two_screens():
    """Raspberry Pi 4 の 2 画面：何も指定しなければ 1 つ目の画面いっぱい。番号・位置の指定もできる"""
    import fb_display as fd
    two = [(1920, 1080), (1920, 1080)]
    assert fd.x11_target({}, two) == ("display", 0, (1920, 1080))
    assert fd.x11_target({"SIGNAGE_X11_DISPLAY": "1"}, two) == ("display", 1, (1920, 1080))
    assert fd.x11_target({"SIGNAGE_X11_GEOMETRY": "1920x1080+0+0"}, two) == ("geometry", (1920, 1080, 0, 0))
    assert fd.x11_target({}, [(1920, 1080)]) == ("all", None)                 # 画面 1 つは今までどおり
    assert fd.x11_target({"SIGNAGE_X11_DISPLAY": "5"}, two) == ("all", None)  # 無い番号
