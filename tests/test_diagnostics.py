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
                 "metar_raw": "RJAA 050300Z 02005KT 9999 FEW020 22/15 Q1018",
                 "thunder_status": "ok", "thunder_ok_at": ts(12, 17), "thunder_data_at": ts(12, 10),
                 "thunder_error": None, "thunder_shown": None},
        "display": {"fb0": "1920×1080", "hdmi": {"HDMI-A-1": "connected"}}, "recent_starts": 1,
        "version": "main 9ce2603", "problems": [],
    }
    info.update(over)
    return info


def item(result, code):
    return next(i for i in result["items"] if i["code"] == code)


def test_all_ok():
    r = dg.evaluate(healthy(), NOW)
    assert r["overall"] == "ok" and r["codes"] == []
    assert [i["code"] for i in r["items"]] == ["SVC", "DSP", "NET", "NTP", "WX", "JMA", "WBGT", "AVI", "THN", "TMP", "PWR", "SYS"]
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
    ("2026-10-14 12:08:00,000 | WARNING | 警報取得失敗: HTTPSConnectionPool(host='www.jma.go.jp', port=443): Max retries "
     "exceeded with url: /bosai/warning/data/warning/120000.json (Caused by NewConnectionError('<urllib3.connection."
     "HTTPSConnection object>: Failed to establish a new connection: [Errno 101] Network is unreachable'))",
     "10/14 12:08 WARNING 警報取得失敗: ネットワークに届かない"),
    ("2026-10-14 12:08:00,000 | WARNING | 警報取得失敗: HTTPSConnectionPool(host='www.jma.go.jp', port=443): Max retries "
     "exceeded (Caused by NewConnectionError('<HTTPSConnection>: Failed to establish a new connection: [Errno -3] "
     "Temporary failure in name resolution'))",
     "10/14 12:08 WARNING 警報取得失敗: 名前解決エラー（DNS）"),
    ("2026-10-14 12:08:00,000 | WARNING | 警報取得失敗: HTTPSConnectionPool(host='www.jma.go.jp', port=443): Max retries "
     "exceeded (Caused by NewConnectionError('<HTTPSConnection>: Failed to establish a new connection'))",
     "10/14 12:08 WARNING 警報取得失敗: 接続できない"),
    ("2026-10-13 06:00:00,000 | WARNING | Retrying (Retry(total=2)) after connection broken by "
     "'NameResolutionError(\"Failed to resolve 'api.open-meteo.com'\")': /v1/forecast?latitude=34.8583&longitude=136.8053&hourly=x",
     "10/13 06:00 WARNING 再試行（/v1/forecast）: 名前解決エラー（DNS）"),
])
def test_summarize_problem(line, short):
    assert dg.summarize_problem(line) == short


def test_collect_does_not_crash_off_pi():
    """Pi 以外（vcgencmd・nmcli が無い）でも落ちずに判定まで通る"""
    r = dg.evaluate(dg.collect(), NOW)
    assert r["overall"] in ("ok", "warn", "bad")


def test_restart_loop_is_bad_even_if_process_is_active():
    """2026-10-11 の 132：HDMI 未検出で描画先がなく、プロセスは active のまま 5 秒おきに起動をやり直していた"""
    r = dg.evaluate(healthy(recent_starts=40, display={"fb0": None, "hdmi": {"HDMI-A-1": "disconnected"}}), NOW)
    assert item(r, "SVC")["level"] == "bad" and "起動に失敗し続けて" in item(r, "SVC")["value"]
    assert item(r, "DSP")["level"] == "bad" and "HDMI 未検出" in item(r, "DSP")["value"]
    assert {"SVC", "DSP"} <= set(r["codes"])


def test_display_ok_with_fb0_or_connected_hdmi():
    assert item(dg.evaluate(healthy(display={"fb0": None, "hdmi": {"HDMI-A-1": "connected"}}), NOW), "DSP")["level"] == "ok"
    assert item(dg.evaluate(healthy(display={"fb0": "1920×1080", "hdmi": {}}), NOW), "DSP")["level"] == "ok"


def test_recent_starts_counts_only_last_10_minutes(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("\n".join([
        "2026-10-11 07:30:00,000 | INFO | [boot] 起動後 1.0s main01 開始",
        "2026-10-11 07:50:00,000 | INFO | [boot] 起動後 2.0s main01 開始",
        "2026-10-11 07:54:00,000 | INFO | [boot] 起動後 3.0s main01 開始",
        "2026-10-11 07:55:00,000 | INFO | 起動: airport=narita",
    ]), encoding="utf-8")
    assert dg.recent_starts(str(log), now=datetime.datetime(2026, 10, 11, 7, 56)) == 2


def test_thunder_ok_shows_none_or_banner():
    assert item(dg.evaluate(healthy(), NOW), "THN")["value"] == "20km 以内に雷なし（12:10 解析）"
    snap = dict(healthy()["snap"], thunder_shown={"kind": "near", "km": 5.6, "dir": "南西", "at": ts(12, 10)})
    it = item(dg.evaluate(healthy(snap=snap), NOW), "THN")
    assert it["level"] == "ok" and it["value"] == "雷接近 南西 6km（12:10 解析）"


@pytest.mark.parametrize("ok_at, level", [(ts(12, 7), "ok"), (ts(11, 40), "warn"), (ts(10, 0), "bad")])
def test_thunder_age(ok_at, level):
    snap = dict(healthy()["snap"], thunder_ok_at=ok_at, thunder_status="error", thunder_error="timeout")
    it = item(dg.evaluate(healthy(snap=snap), NOW), "THN")
    assert it["level"] == level
    if level != "ok":
        assert "timeout" in it["detail"]


def test_thunder_never_fetched():
    snap = {k: v for k, v in healthy()["snap"].items() if not k.startswith("thunder")}
    it = item(dg.evaluate(healthy(snap=snap), NOW), "THN")
    assert it["level"] == "warn" and it["value"] == "データなし"


def _log_line(day, hh, mm, level, msg):
    return f"2026-10-{day:02d} {hh:02d}:{mm:02d}:00,000 | {level} | {msg}\n"


def test_recent_problems_groups_same_message_with_count_and_span(tmp_path):
    """同じ内容（回数・秒数だけ違う）は 1 件にまとめ、回数と期間を付ける。ほかの記録は押し出されない"""
    log = tmp_path / "log.txt"
    lines = [_log_line(17, 8, 50, "WARNING", "雷ナウキャスト取得失敗（15分以上続いている）: timed out")]
    for i, hh in enumerate(range(9, 22)):
        lines.append(_log_line(17, hh, 0, "ERROR", f"表示プログラムが停止（{(i + 1) * 10}回目）→ 60秒後に再起動: "
                                                   "RuntimeError: /dev/fb0 を開けない（描画先なし）"))
    log.write_text("".join(lines), encoding="utf-8")
    out = dg.recent_problems(str(log), today=datetime.date(2026, 10, 17))
    assert out == [
        "10/17 21:00 ERROR 表示プログラムが停止（130回目）→ 60秒後に再起動: RuntimeError: /dev/fb0 を開けない（描画先なし）"
        " ×13回（10/17 09:00〜21:00）",
        "10/17 08:50 WARNING 雷ナウキャスト取得失敗（15分以上続いている）: タイムアウト",
    ]


def test_recent_problems_reads_older_days_until_limit(tmp_path):
    """今日・前日で 20 件に足りなければ、さらに前の日のログもさかのぼる。期間が日をまたぐと日付も出す"""
    log = tmp_path / "log.txt"
    log.write_text(_log_line(18, 9, 0, "WARNING", "A 失敗"), encoding="utf-8")
    (tmp_path / "log.txt.2026-10-17").write_text(_log_line(17, 9, 0, "WARNING", "A 失敗"), encoding="utf-8")
    (tmp_path / "log.txt.2026-10-15").write_text(
        "".join(_log_line(15, 9, m, "WARNING", f"B{chr(65 + m)} 失敗") for m in range(3)), encoding="utf-8")
    out = dg.recent_problems(str(log), today=datetime.date(2026, 10, 18))
    assert out[0] == "10/18 09:00 WARNING A 失敗 ×2回（10/17 09:00〜10/18 09:00）"
    assert len(out) == 4 and out[-1] == "10/15 09:00 WARNING BA 失敗"


def test_recent_problems_limit_20(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("".join(_log_line(18, 9, m, "WARNING", f"種類{chr(0x3042 + m)} 失敗") for m in range(30)),
                   encoding="utf-8")
    out = dg.recent_problems(str(log), today=datetime.date(2026, 10, 18))
    assert len(out) == dg.PROBLEM_LIMIT == 20
    assert out[0].startswith("10/18 09:29")                  # 新しい順


def test_thunder_error_detail_is_short():
    """雷の取得失敗の詳細に、URL などの長い例外の文をそのまま出さない"""
    err = ("HTTPSConnectionPool(host='www.jma.go.jp', port=443): Max retries exceeded with url: /bosai/jmatile/data/nowc/"
           "20261018050000/none/20261018050000/surf/thns/8/227/100.png (Caused by NewConnectionError('<urllib3.connection."
           "HTTPSConnection object at 0xa4208fd0>: Failed to establish a new connection: [Errno -3] Temporary failure in "
           "name resolution'))")
    snap = dict(healthy()["snap"], thunder_ok_at=ts(11, 45), thunder_status="error", thunder_error=err)
    it = item(dg.evaluate(healthy(snap=snap), NOW), "THN")
    assert it["detail"] == "35分前から取得できていません（名前解決エラー（DNS））"


def test_short_error():
    assert dg.short_error("Read timed out. (read timeout=15)") == "タイムアウト"
    assert dg.short_error("x" * 100).endswith("…") and len(dg.short_error("x" * 100)) == 81
    assert dg.short_error(None) == ""


def test_git_version_time_is_japan_time():
    """版の時刻は日本時間（2026-10-18 05:51 UTC のコミット → 14:51）"""
    ts = int(datetime.datetime(2026, 10, 18, 5, 51, tzinfo=datetime.timezone.utc).timestamp())
    assert dg.format_git_log(f"3bbd350 {ts}\n") == "3bbd350 2026-10-18 14:51"
    assert dg.format_git_log("") == ""
