"""子機用のページの「サイネージと同じ画面」：mirror.py"""
import os

import pygame

import mirror


def test_saves_only_when_wanted_and_once_a_minute(tmp_path):
    pygame.display.init()
    screen = pygame.Surface((64, 36))
    sf, wf = str(tmp_path / "run" / "screen.jpg"), str(tmp_path / "run" / "wanted")
    assert mirror.maybe_save(screen, now=1000.0, screen_file=sf, want_file=wf) is False      # 見られていない
    mirror.want(wf)
    t = os.path.getmtime(wf)
    assert mirror.maybe_save(screen, now=t + 1, screen_file=sf, want_file=wf) is True
    assert os.path.exists(sf) and not any(n.endswith((".tmp.jpg", ".tmp.png")) for n in os.listdir(tmp_path / "run"))
    m = os.path.getmtime(sf)
    assert mirror.maybe_save(screen, now=m + 30, screen_file=sf, want_file=wf) is False      # 1 分に 1 回まで
    assert mirror.maybe_save(screen, now=t + mirror.WANT_S + 60, screen_file=sf, want_file=wf) is False   # 見られなくなった
    assert mirror.mimetype_of(sf) in ("image/jpeg", "image/png") and mirror.screen_time(sf)



def test_diag_mirror_item(tmp_path, monkeypatch):
    """診断の「子機用の画面」：画像の時刻と、見ている子機がいるか。見られているのに 3 分以上古ければ注意"""
    import diagnostics
    sf, wf = tmp_path / "screen.jpg", tmp_path / "wanted"
    monkeypatch.setattr(mirror, "SCREEN_FILE", str(sf))
    monkeypatch.setattr(mirror, "WANT_FILE", str(wf))
    it = diagnostics._mirror_item(1_000_000.0)
    assert it["code"] == "MIR" and it["level"] == "info" and "画像なし" in it["value"]
    sf.write_bytes(b"x"); wf.write_text("1")
    os.utime(sf, (1_000_000.0 - 30, 1_000_000.0 - 30)); os.utime(wf, (1_000_000.0 - 10, 1_000_000.0 - 10))
    it = diagnostics._mirror_item(1_000_000.0)
    assert it["level"] == "ok" and "見ている子機あり" in it["value"]
    os.utime(sf, (1_000_000.0 - 400, 1_000_000.0 - 400))
    assert diagnostics._mirror_item(1_000_000.0)["level"] == "warn"
