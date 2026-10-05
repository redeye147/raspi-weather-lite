"""診断ページの判定（diagnostics.evaluate）"""
import datetime

import pytest

import diagnostics as dg

JST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 10, 5, 12, 20, tzinfo=JST)


def ts(hh, mm=0, day=5):
    return datetime.datetime(2026, 10, day, hh, mm, tzinfo=JST).timestamp()


def healthy(**over):
    info = {
        "airport_name": "成田空港", "icao": "RJAA", "interval_hours": 2.0,
        "service": {"active": "active", "sub": "running", "restarts": 0, "uptime_s": 3 * 86400},
        "conn_kind": "wifi", "ssid": "office", "signal": 72, "ip": "192.168.1.132",
        "ntp_synced": "yes", "temp": 52.0, "throttled": 0,
        "cpu": 4, "mem": 45, "disk_free_gb": 9.8,
        "snap": {"weather_at": ts(11, 50), "jma_at": ts(11, 37), "wbgt_at": ts(11, 40),
                 "wbgt_status": "ok", "wbgt_data_at": ts(11, 40),
                 "wbgt_level_info": {"label": "注意", "value": 26.1},
                 "metar_raw": "RJAA 050300Z 02005KT 9999 FEW020 22/15 Q1018"},
        "version": "main 9ce2603", "problems": [],
    }
    info.update(over)
    return info


def item(result, code):
    return next(i for i in result["items"] if i["code"] == code)


def test_all_ok():
    r = dg.evaluate(healthy(), NOW)
    assert r["overall"] == "ok" and r["codes"] == []
    assert [i["code"] for i in r["items"]] == ["SVC", "NET", "NTP", "WX", "JMA", "WBGT", "AVI", "TMP", "PWR", "SYS"]
    assert item(r, "AVI")["value"].startswith("RJAA 12:00 観測")
    assert "注意 26.1℃" in item(r, "WBGT")["value"]


def test_service_stopped_is_bad():
    r = dg.evaluate(healthy(service={"active": "failed", "sub": "failed", "restarts": 5, "uptime_s": None}), NOW)
    assert item(r, "SVC")["level"] == "bad" and r["overall"] == "bad" and "SVC" in r["codes"]


def test_service_restarted_is_warn():
    r = dg.evaluate(healthy(service={"active": "active", "sub": "running", "restarts": 2, "uptime_s": 600}), NOW)
    assert item(r, "SVC")["level"] == "warn"


@pytest.mark.parametrize("throttled, level, word", [
    (0x0, "ok", "問題なし"), (0x50000, "warn", "電圧低下"), (0x50005, "bad", "今 電圧低下"), (None, "info", "確認できません")])
def test_power(throttled, level, word):
    i = item(dg.evaluate(healthy(throttled=throttled), NOW), "PWR")
    assert i["level"] == level and word in i["value"]


@pytest.mark.parametrize("temp, level", [(69.9, "ok"), (70, "warn"), (80, "bad")])
def test_temperature(temp, level):
    assert item(dg.evaluate(healthy(temp=temp), NOW), "TMP")["level"] == level


@pytest.mark.parametrize("kind, signal, level", [
    ("wifi", 72, "ok"), ("wifi", 30, "warn"), ("ethernet", None, "ok"), ("hotspot", None, "warn"), ("", None, "bad")])
def test_network(kind, signal, level):
    assert item(dg.evaluate(healthy(conn_kind=kind, signal=signal), NOW), "NET")["level"] == level


def test_weather_overdue():
    """2時間ごと：最後の取得から 2時間40分までは正常、それ以降は注意、さらに3時間で異常"""
    def lvl(hh, mm):
        snap = dict(healthy()["snap"], weather_at=ts(hh, mm))
        return item(dg.evaluate(healthy(snap=snap), NOW), "WX")["level"]
    assert lvl(9, 40) == "ok" and lvl(9, 30) == "warn" and lvl(6, 30) == "bad"


def test_weather_at_night_allows_2350():
    """夜間（0〜6時）は 23:50 の取得が最後でも正常"""
    snap = dict(healthy()["snap"], weather_at=ts(23, 50, day=4))
    r = dg.evaluate(healthy(snap=snap), datetime.datetime(2026, 10, 5, 5, 50, tzinfo=JST))
    assert item(r, "WX")["level"] == "ok"


def test_wbgt_off_season_is_info_not_warning():
    snap = dict(healthy()["snap"], wbgt_status="nodata", wbgt_data_at=ts(18, day=1) - 30 * 86400)
    r = dg.evaluate(healthy(snap=snap), NOW)
    assert item(r, "WBGT")["level"] == "info" and "期間外" in item(r, "WBGT")["value"]
    assert r["overall"] == "ok"


def test_wbgt_error_is_warn():
    snap = dict(healthy()["snap"], wbgt_status="error")
    assert item(dg.evaluate(healthy(snap=snap), NOW), "WBGT")["level"] == "warn"


@pytest.mark.parametrize("obs, level", [("050300Z", "ok"), ("050130Z", "warn"), ("042300Z", "bad")])
def test_aviation_age(obs, level):
    snap = dict(healthy()["snap"], metar_raw=f"RJAA {obs} 02005KT 9999 FEW020 22/15 Q1018")
    assert item(dg.evaluate(healthy(snap=snap), NOW), "AVI")["level"] == level


def test_aviation_night_is_ok():
    r = dg.evaluate(healthy(), datetime.datetime(2026, 10, 6, 3, 0, tzinfo=JST))
    assert item(r, "AVI")["level"] == "ok" and "夜間" in item(r, "AVI")["value"]


def test_no_snapshot():
    r = dg.evaluate(healthy(snap=None), NOW)
    assert item(r, "WX")["level"] == "bad" and r["overall"] == "bad"


def test_disk_and_memory():
    assert item(dg.evaluate(healthy(disk_free_gb=0.2), NOW), "SYS")["level"] == "bad"
    assert item(dg.evaluate(healthy(disk_free_gb=0.8), NOW), "SYS")["level"] == "warn"
    assert item(dg.evaluate(healthy(mem=95), NOW), "SYS")["level"] == "warn"


def test_recent_problems_newest_first(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("a | INFO | x\nb | WARNING | first\nc | ERROR | second\n", encoding="utf-8")
    assert dg.recent_problems(str(log)) == ["c ERROR second", "b WARNING first"]


@pytest.mark.parametrize("line, short", [
    ("2026-10-05 15:40:10,078 | WARNING | METAR 取得失敗 (RJAA): HTTPSConnectionPool(host='aviationweather.gov', port=443): "
     "Max retries exceeded (Caused by NameResolutionError(\"Failed to resolve 'aviationweather.gov'\"))",
     "10/05 15:40 WARNING METAR 取得失敗 (RJAA): 名前解決エラー（DNS）"),
    ("2026-10-05 11:12:31,346 | WARNING | WBGT CSV 取得失敗 (chiba): HTTPSConnectionPool(host='www.wbgt.env.go.jp', port=443): Read timed out.",
     "10/05 11:12 WARNING WBGT CSV 取得失敗 (chiba): タイムアウト"),
    ("2026-10-04 18:39:21,377 | WARNING | Retrying (Retry(total=2)) after connection broken by "
     "'ConnectionResetError(104, 'Connection reset by peer')': /bosai/forecast/data/overview_forecast/120000.json",
     "10/04 18:39 WARNING 再試行（/bosai/forecast/data/overview_forecast/120000.json）: 接続が切れた"),
    ("2026-10-05 06:00:01,000 | ERROR | JMA更新失敗: KeyError 'x'", "10/05 06:00 ERROR JMA更新失敗: KeyError 'x'"),
])
def test_summarize_problem(line, short):
    assert dg.summarize_problem(line) == short


def test_collect_does_not_crash_off_pi():
    """Pi 以外（vcgencmd・nmcli が無い）でも落ちずに判定まで通る"""
    r = dg.evaluate(dg.collect(), NOW)
    assert r["overall"] in ("ok", "warn", "bad")
