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
