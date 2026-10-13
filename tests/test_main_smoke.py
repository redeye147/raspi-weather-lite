"""表示プログラム全体の通しテスト（main01.main）

画面・ネットワーク・Pi 固有のコマンドを偽物に差し替えて、起動 → 天気取得 → メインループ数周 が
例外なく進むかを確かめる。部品のつなぎ間違い（名前の書き間違い・引数の渡し忘れ）は Pi で起動直後に
落ちて画面が出なくなるので、ここで先に見つける。
"""
import json
import logging
import time

import pygame
import pytest

import aviation
import fb_display
import fetch_wbgt
import main01
import netstate
import requests
import startup
from utils import JST, get_target_datetimes


def _fake_weather(ok=True):
    def run(self):
        if ok:
            hourly = [dict(datetime=t.replace(tzinfo=JST), date=t.strftime("%-m/%-d"), hour=t.strftime("%H"),
                           code="100", pop="0.0mm", temp_val=20, temp="20℃", wind_val=2, wind="2m")
                      for t in get_target_datetimes()]
            daily = [dict(day=f"10/{11 + i}", code="101", pop="10%", temp="25/15", date="") for i in range(7)]
            self._result, self._ok = (hourly, daily), True
        else:
            self._result, self._ok = (None, None), False
        self._event.set()
    return run


@pytest.fixture
def signage(tmp_path, monkeypatch):
    """main01.main() を偽の環境で動かす。戻り値 run(loops) でメインループを loops 周させる"""
    snap_file = str(tmp_path / "snapshot.json")
    log_file = str(tmp_path / "log.txt")
    monkeypatch.setattr(startup, "SNAPSHOT_FILE", snap_file)
    monkeypatch.setattr(main01, "SNAPSHOT_FILE", snap_file, raising=False)
    monkeypatch.setattr(main01, "LOG_FILE", log_file)
    monkeypatch.setattr(fb_display, "RENDER_MODE", "fb0")
    monkeypatch.setattr(main01, "init_display",
                        lambda r: (pygame.display.init(), pygame.font.init(), pygame.display.set_mode((1920, 1080)))[2])
    monkeypatch.setattr(main01, "present", lambda s: None)
    monkeypatch.setattr(main01, "wait_time_sync", lambda t=15: True)
    monkeypatch.setattr(main01, "get_overview_and_warning",
                        lambda **k: {"headline": "濃霧注意報", "overview": "晴れ。", "updated": "2026-10-11 05:00"})
    monkeypatch.setattr(main01, "DEFER_INITIAL_FETCH_S", 0)
    # 通信はすべて止める（裏で取得するスレッドもテスト後に本物の通信をしないように）
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    aviation_calls, wbgt_calls = [], []
    monkeypatch.setattr(aviation, "start_fetch_in_background", lambda *a, **k: aviation_calls.append(a))
    monkeypatch.setattr(main01, "start_wbgt_fetch",
                        lambda airport, holder: (wbgt_calls.append(airport),
                                                 holder.update(result=(27.0, False, fetch_wbgt.level_for(27.0), "ok"))))
    for mod in (main01, netstate):
        monkeypatch.setattr(mod, "get_connection_kind", lambda: "wifi")
    monkeypatch.setattr(main01, "wired_cable_status", lambda: "")
    monkeypatch.setattr(main01, "has_wlan1", lambda: False)
    monkeypatch.setattr(main01, "is_ap_mode_active", lambda: False)
    monkeypatch.setattr(main01, "get_setup_hotspot_ssid", lambda: "")

    root = logging.getLogger()
    saved = (root.handlers[:], root.level)

    def run(loops=12, weather_ok=True):
        monkeypatch.setattr(main01.WeatherFetcher, "_run", _fake_weather(weather_ok))
        n = {"w": 0}

        def wait(ms):
            n["w"] += 1
            if n["w"] > loops:
                raise SystemExit
            time.sleep(0.01)
        monkeypatch.setattr(main01, "_wait_ms", wait)
        monkeypatch.setattr(main01.sys, "argv", ["main01.py"])
        with pytest.raises(SystemExit):
            main01.main()
        for h in root.handlers:
            h.flush()
        with open(log_file, encoding="utf-8") as f:
            return f.read()

    yield run, snap_file, {"aviation": aviation_calls, "wbgt": wbgt_calls}
    for h in root.handlers:
        if h not in saved[0]:
            h.close()
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    try:
        pygame.quit()
    except Exception:
        pass


def test_cold_start_without_snapshot(signage):
    """前回データなし：起動画面で天気を取得 → 天気画面 → 表示データを保存"""
    run, snap_file, calls = signage
    log = run()
    assert "天気画面を表示" in log
    assert "ERROR" not in log
    with open(snap_file, encoding="utf-8") as f:
        snap = json.load(f)
    assert snap["hourly"] and snap["daily"] and snap["airport"]
    assert calls["wbgt"]                                  # WBGT は起動直後に取りに行く


def test_restart_with_fresh_snapshot(signage):
    """2 回目の起動は前回データで即表示（起動画面での取得を省略）"""
    run, _, _ = signage
    run()
    log = run()
    assert "前回スナップショットで即表示" in log
    assert log.count("天気画面を表示") == 2


def test_weather_fetch_failure_does_not_crash(signage):
    """天気の取得に失敗しても、落ちずに天気画面のループが回る"""
    run, _, _ = signage
    log = run(weather_ok=False)
    assert "天気画面を表示" in log
    assert "Traceback" not in log


def test_main_again_after_pygame_quit(signage):
    """run_forever は失敗後に pygame.quit() してから main() をやり直す。前回のフォントのキャッシュが残っていると
    Segmentation fault で落ちていた（2026-10 にこのテストを作って発見）"""
    run, _, _ = signage
    run()
    pygame.quit()
    log = run()
    assert log.count("天気画面を表示") == 2


def test_screenshot_request_saves_weather_screen(signage, tmp_path, monkeypatch):
    """tools/screenshot.py の依頼で、表示プログラムが天気画面を PNG に保存する"""
    run, _, _ = signage
    req, dest = tmp_path / "screenshot_request", tmp_path / "shots" / "screen.png"
    monkeypatch.setattr(main01, "SCREENSHOT_REQUEST", str(req))
    req.write_text(str(dest), encoding="utf-8")
    log = run()
    assert dest.exists() and not req.exists()
    assert pygame.image.load(str(dest)).get_size() == (1920, 1080)
    assert "スクリーンショットを保存" in log
