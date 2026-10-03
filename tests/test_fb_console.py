"""fb0 モードのコンソール切り替え（カーソルの点滅を消す）"""
import fcntl

import pytest

import fb_display as fb


def test_falls_back_to_next_tty_when_first_cannot_open(tmp_path, monkeypatch):
    """systemd 起動では /dev/tty が開けない → 開ける TTY を順に試して KD_GRAPHICS にする"""
    ok = tmp_path / "tty1"
    ok.write_bytes(b"")
    calls = []
    monkeypatch.setattr(fcntl, "ioctl", lambda fd, req, mode: calls.append((req, mode)))
    path = fb._set_console_mode(fb.KD_GRAPHICS, (str(tmp_path / "nodir" / "tty0"), str(ok)))
    assert path == str(ok)
    assert calls == [(fb.KDSETMODE, fb.KD_GRAPHICS)]
    assert ok.read_bytes().endswith(b"\033[?25l")          # カーソル非表示


def test_raises_with_all_errors_when_no_tty_works(tmp_path):
    with pytest.raises(OSError) as e:
        fb._set_console_mode(fb.KD_GRAPHICS, (str(tmp_path / "x" / "a"), str(tmp_path / "x" / "b")))
    assert "a:" in str(e.value) and "b:" in str(e.value)
