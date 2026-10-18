"""ネットの一時的な失敗への対処（netretry）：1 回だけの取り直しと、続いたときだけの警告"""
import logging

import pytest
import requests

import netretry


class Session:
    def __init__(self, fails):
        self.fails, self.calls = list(fails), 0

    def get(self, url, **kw):
        self.calls += 1
        if self.fails:
            raise self.fails.pop(0)
        return "ok"


def test_retry_once_after_dns_error():
    s, waits = Session([requests.exceptions.ConnectionError("Failed to resolve 'www.jma.go.jp'")]), []
    assert netretry.get_with_retry("u", session=s, sleep=waits.append) == "ok"
    assert s.calls == 2 and waits == [netretry.RETRY_WAIT_S]


def test_retry_only_once():
    s = Session([requests.exceptions.Timeout(), requests.exceptions.Timeout()])
    with pytest.raises(requests.exceptions.Timeout):
        netretry.get_with_retry("u", session=s, sleep=lambda w: None)
    assert s.calls == 2


def test_other_errors_are_not_retried():
    s = Session([ValueError("壊れた応答")])
    with pytest.raises(ValueError):
        netretry.get_with_retry("u", session=s, sleep=lambda w: None)
    assert s.calls == 1


def _levels(caplog):
    return [(r.levelname, r.getMessage()) for r in caplog.records]


def test_single_failure_is_info_and_recovery_is_quiet(caplog):
    caplog.set_level(logging.INFO)
    t = [0.0]
    f = netretry.FailureLog("雷ナウキャスト", clock=lambda: t[0])
    f.failed("名前解決エラー")
    t[0] = 300
    f.ok()
    assert [lv for lv, _ in _levels(caplog)] == ["INFO", "INFO"]


def test_warning_once_after_15_minutes_then_recovery_warning(caplog):
    caplog.set_level(logging.INFO)
    t = [0.0]
    f = netretry.FailureLog("雷ナウキャスト", clock=lambda: t[0])
    for t[0] in (0, 300, 600, 900, 1200):          # 5 分ごとに失敗し続ける
        f.failed("timeout")
    t[0] = 1500
    f.ok()
    logs = _levels(caplog)
    warnings = [m for lv, m in logs if lv == "WARNING"]
    assert warnings == ["雷ナウキャスト取得失敗（15分以上続いている）: timeout", "雷ナウキャスト取得が回復（25分ぶり）"]
    # 回復のあとは、また最初から数える
    caplog.clear()
    t[0] = 2000
    f.failed("timeout")
    assert _levels(caplog)[0][0] == "INFO"


def test_diagnostics_summary_of_long_failure():
    import diagnostics
    line = ("2026-10-18 13:13:00,000 | WARNING | 雷ナウキャスト取得失敗（15分以上続いている）: "
            "HTTPSConnectionPool(host='www.jma.go.jp'): NameResolutionError Failed to resolve")
    s = diagnostics.summarize_problem(line)
    assert s == "10/18 13:13 WARNING 雷ナウキャスト取得失敗（15分以上続いている）: 名前解決エラー（DNS）"
