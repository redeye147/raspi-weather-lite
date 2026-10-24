"""表示プログラム全体の通しテスト（main01.main）

画面・ネットワーク・Pi 固有のコマンドを偽物に差し替えて、起動 → 天気取得 → メインループ数周 が
例外なく進むかを確かめる。部品のつなぎ間違い（名前の書き間違い・引数の渡し忘れ）は Pi で起動直後に
落ちて画面が出なくなるので、ここで先に見つける。
"""
import datetime
import json
import logging
import time

import pygame
import pytest

import aviation
import decisions
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
                        lambda r, **kw: (pygame.display.init(), pygame.font.init(), pygame.display.set_mode((1920, 1080)))[2])
    monkeypatch.setattr(main01, "present", lambda s: None)
    monkeypatch.setattr(main01, "wait_time_sync", lambda t=15: True)
    monkeypatch.setattr(main01, "get_overview_and_warning",
                        lambda **k: {"headline": "濃霧注意報", "overview": "晴れ。", "updated": "2026-10-11 05:00"})
    monkeypatch.setattr(main01, "DEFER_INITIAL_FETCH_S", 0)
    monkeypatch.setattr(main01, "ANIMATE", False)
    import verify
    monkeypatch.setattr(verify, "BASE_DIR", str(tmp_path / "verify"))   # 予報の精度の記録はテスト用の場所に
    monkeypatch.setattr(main01, "STATUS_FILE", str(tmp_path / "status.json"))    # アイコンを動かすと待ちの回数が増えて、ループの周回の数え方が変わる
    # 通信はすべて止める（裏で取得するスレッドもテスト後に本物の通信をしないように）
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    aviation_calls, wbgt_calls, thunder_calls = [], [], []
    monkeypatch.setattr(aviation, "start_fetch_in_background", lambda *a, **k: aviation_calls.append(a))
    monkeypatch.setattr(main01, "start_wbgt_fetch",
                        lambda airport, holder: (wbgt_calls.append(airport),
                                                 holder.update(result=(27.0, False, fetch_wbgt.level_for(27.0), "ok"))))
    # 雷：空港の南西 8km（雷接近）を返す。ネットには出ない
    monkeypatch.setattr(main01, "start_thunder_fetch",
                        lambda lat, lon, holder: (thunder_calls.append((lat, lon)), holder.update(result={
                            "status": "ok", "at": datetime.datetime.now(JST),
                            "hit": {"km": 8.2, "dir": "南西", "level": 2, "max_level": 2}})))
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

    yield run, snap_file, {"aviation": aviation_calls, "wbgt": wbgt_calls, "thunder": thunder_calls}
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
    assert calls["thunder"] and "雷: near 南西 8.2km" in log          # 雷は起動直後に取りに行き、帯を出す
    # WBGT は起動直後に取りに行く（0:00〜5:59 は取得しない決まりなので、その時間に試験すると呼ばれない）
    if main01.datetime.datetime.now(main01.JST).hour >= decisions.WBGT_START_HOUR:
        assert calls["wbgt"]
    else:
        assert not calls["wbgt"]


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


def test_network_wait_logs_details_and_retries(signage, monkeypatch):
    """起動時にネットワークが無いと「ネットワークに接続できません」の画面で待つ。その間の状態を詳しく残し、
    WiFi の再接続も試す。つながったら天気画面へ（2026-10-14 の 110：約 30 分つながらず、原因を調べるログが無かった）"""
    run, _, _ = signage
    calls = {"n": 0, "reconnect": 0}

    def kind():
        calls["n"] += 1
        return "" if calls["n"] <= 6 else "wifi"
    for mod in (main01, netstate):
        monkeypatch.setattr(mod, "get_connection_kind", kind)
    monkeypatch.setattr(main01, "network_snapshot", lambda: ["WiFi 部品(wlan0): あり down", "見えている WiFi（SSID:電波%:ch）: なし"])
    monkeypatch.setattr(main01, "try_reconnect_wifi",
                        lambda: (calls.__setitem__("reconnect", calls["reconnect"] + 1), "Error: No network with SSID")[1])
    monkeypatch.setattr(main01, "NETWAIT_SNAPSHOT_EVERY_S", 0)
    monkeypatch.setattr(main01, "NETWAIT_RECONNECT_AFTER_S", 0)
    monkeypatch.setattr(main01, "NETWAIT_RECONNECT_EVERY_S", 0)
    log = run(loops=20)
    assert "起動時にネットワーク未接続" in log
    assert "[netwait] 待機開始: WiFi 部品(wlan0): あり down" in log
    assert "見えている WiFi（SSID:電波%:ch）: なし" in log
    assert calls["reconnect"] >= 1 and "WiFi を探し直して再接続: Error: No network with SSID" in log
    assert "[netwait] 待機終了（つながった状態）" in log
    assert "天気画面を表示" in log


# ---------------------------------------------------------------- 画面出力なし（HDMI 未接続）でも取得を続ける
def test_headless_keeps_fetching_and_restarts_when_hdmi_attached(signage, monkeypatch):
    """HDMI が無くても天気・WBGT・雷を取りに行き、前回データを保存する。HDMI がつながったら作り直す"""
    run, snap_file, calls = signage

    def headless(r, **kw):
        assert kw.get("allow_headless") is True
        pygame.display.init(); pygame.font.init()
        monkeypatch.setattr(fb_display, "RENDER_MODE", "headless")
        return pygame.display.set_mode((1920, 1080))
    monkeypatch.setattr(main01, "init_display", headless)
    monkeypatch.setattr(main01, "DISPLAY_CHECK_S", 0)
    attached = iter([False, False, False, True])
    monkeypatch.setattr(fb_display, "display_attached", lambda: next(attached))
    with pytest.raises(main01.DisplayAttached):
        run(loops=50)
    with open(snap_file, encoding="utf-8") as f:
        assert json.load(f)["hourly"]                     # 画面が無くても天気を取って保存している
    assert calls["thunder"]
    # WBGT は 0:00〜5:59 は取りに行かない決まり（その時間に試験すると呼ばれない）
    assert bool(calls["wbgt"]) == (main01.datetime.datetime.now(main01.JST).hour >= decisions.WBGT_START_HOUR)


def test_aviation_band_hidden_but_metar_still_fetched(signage, monkeypatch):
    """航空気象（METAR）の帯は画面に出さない（SHOW_AVIATION_BAND = False）。METAR の取得は続ける"""
    run, snap_file, calls = signage
    metar = aviation.parse_metar("RJGG 010000Z 07009KT 8000 -SHRA BKN050 19/15 Q1012",
                                 datetime.datetime.now(datetime.timezone.utc))
    fresh = dict(metar, obs_utc=datetime.datetime.now(datetime.timezone.utc))

    def fetch(icao, state, expected_obs=None):
        calls["aviation"].append(icao)
        state.update({"metar": fresh, "raw": "RJGG"})
    monkeypatch.setattr(aviation, "start_fetch_in_background", fetch)
    monkeypatch.setattr(main01, "aviation_band_visible", lambda now: True)
    # 夜間（0:00〜6:06）は取りに行かない決まりなので、試験する時刻によらず「取りに行く時刻」とみなす
    monkeypatch.setattr(main01, "aviation_fetch_due", lambda now, latest, last: None if latest else (now, 0))
    shown = []
    real = main01.draw_header
    monkeypatch.setattr(main01, "draw_header", lambda *a, **k: (shown.append(k.get("aviation_metar")), real(*a, **k)))
    assert main01.SHOW_AVIATION_BAND is False
    run(loops=12)
    assert shown and all(m is None for m in shown)                        # 帯は出さない
    assert calls["aviation"]                                               # 取得はしている


def test_taf_and_rain_forecast_shown_in_table(signage, monkeypatch):
    """TAF の風と降水短時間予報の雨が、今日の天気の列に入る（元の予報・保存する予報は変えない）"""
    import fetch_rainfcst
    import taf as taf_mod
    run, snap_file, calls = signage
    now = datetime.datetime.now(datetime.timezone.utc)
    s, e = now - datetime.timedelta(hours=2), now + datetime.timedelta(hours=28)
    raw = f"TAF RJGG {s:%d%H}00Z {s:%d%H}/{e:%d%H} 27040KT 9999 FEW030"

    def fetch_taf(icao, holder):
        holder["result"] = {"status": "ok", "taf": taf_mod.parse_taf(raw, now), "raw": raw, "fetched_at": time.time()}
    monkeypatch.setattr(taf_mod, "start_fetch_in_background", fetch_taf)
    jst = datetime.datetime.now(JST).replace(minute=0, second=0, microsecond=0)
    hours = {(jst + datetime.timedelta(hours=h)).strftime("%Y-%m-%dT%H:00"): 65.0 for h in range(1, 7)}
    monkeypatch.setattr(fetch_rainfcst, "start_fetch_in_background",
                        lambda lat, lon, holder: holder.update(result={"status": "ok", "at": datetime.datetime.now(JST),
                                                                       "hours": hours}))
    drawn = []
    real = main01.draw_weather
    monkeypatch.setattr(main01, "draw_weather", lambda screen, w, h, hourly, *a, **k: (drawn.append(hourly), real(screen, w, h, hourly, *a, **k)))
    run(loops=12)
    last = drawn[-1]
    assert any(it.get("taf") and it["wind_val"] == 21 for it in last)            # 40kt → 21m/s
    assert any(it.get("rainfc") and it["pop"] == "65.0mm" for it in last)
    with open(snap_file, encoding="utf-8") as f:
        snap = json.load(f)
    assert snap["taf_raw"] == raw and snap["rainfc_hours"] == hours
    assert all(not it.get("taf") for it in snap["hourly"])                       # 保存する予報はそのまま
