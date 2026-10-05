"""WBGT（熱中症予防情報）：CSV の読み取り、提供期間外の扱い、取得の間隔、0 時の非表示"""
import datetime

import pytest

import fetch_wbgt as fw
from decisions import wbgt_badge_visible, wbgt_fetch_due, wbgt_off_season

JST = datetime.timezone(datetime.timedelta(hours=9))


def at(m, d, hh, mm=0):
    return datetime.datetime(2026, m, d, hh, mm, tzinfo=JST)


# ---------------------------------------------------------------- CSV の読み取り
CSV = "Date,Time,0,3,6\n2026/10/04,x,24.0,26.5,25.0\n2026/10/05,x,22.0,27.3,,\n"


def test_parse_today_max():
    assert fw.parse_wbgt_csv(CSV, "2026/10/05") == (27.3, "ok")


def test_parse_no_row_for_today_is_nodata():
    """ファイルはあるが今日の行が無い（提供期間外の可能性）"""
    assert fw.parse_wbgt_csv(CSV, "2026/10/22") == (None, "nodata")


class _Resp:
    def __init__(self, code, body=b""):
        self.status_code, self.content = code, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_csv_404_is_nodata(monkeypatch):
    monkeypatch.setattr(fw.requests, "get", lambda *a, **k: _Resp(404))
    assert fw._fetch_wbgt_csv("chiba") == (None, "nodata")


def test_network_error_is_error_and_requested_once(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1); raise OSError("timeout")
    monkeypatch.setattr(fw.requests, "get", boom)
    assert fw._fetch_wbgt_csv("chiba") == (None, "error")
    assert len(calls) == 1                     # 以前は失敗すると同じ URL をもう1回取りに行っていた


def test_fetch_wbgt_returns_status(monkeypatch):
    monkeypatch.setattr(fw, "_fetch_wbgt_csv", lambda code: (29.0, "ok"))
    wbgt, alert, level, status = fw.fetch_wbgt("narita")
    assert (wbgt, alert, level["label"], status) == (29.0, False, "警戒", "ok")


@pytest.mark.parametrize("v, label", [(24.9, None), (25, "注意"), (28, "警戒"), (31, "厳重警戒"), (33, "危険"), (None, None)])
def test_level_for(v, label):
    lv = fw.level_for(v)
    assert (lv and lv["label"]) == label


# ---------------------------------------------------------------- 提供期間外の判断
def test_off_season_only_after_two_days_without_data():
    now = at(10, 23, 6)
    assert wbgt_off_season(now, "nodata", at(10, 21, 18)) is False      # 最後の値から 2 日以内 → 一時的とみなす
    assert wbgt_off_season(now, "nodata", at(10, 21, 5)) is True
    assert wbgt_off_season(now, "nodata", None) is True                 # 一度も値が無い（冬に設置）
    assert wbgt_off_season(now, "error", None) is False                 # 通信エラーは期間外と判断しない
    assert wbgt_off_season(now, "ok", at(10, 23, 6)) is False


# ---------------------------------------------------------------- 取得の間隔
@pytest.mark.parametrize("hh, due", [(0, False), (5, False), (6, True), (23, True)])
def test_no_fetch_at_night(hh, due):
    assert wbgt_fetch_due(at(10, 5, hh, 30), at(10, 5, 0, 0) - datetime.timedelta(hours=3), "ok", at(10, 4, 23)) is due


def test_first_fetch_without_history():
    assert wbgt_fetch_due(at(10, 5, 9), None, None, None) is True


def test_hourly_in_season_and_after_error():
    last = at(10, 5, 9)
    for status in ("ok", "error"):
        assert wbgt_fetch_due(at(10, 5, 9, 59), last, status, at(10, 5, 9)) is False
        assert wbgt_fetch_due(at(10, 5, 10), last, status, at(10, 5, 9)) is True


def _day_attempts(day, status, data_at, last=None):
    """day の 0:00〜23:59 を 1 分刻みで回し、取得した時刻を返す（結果は status のまま変わらないとする）"""
    tried = []
    for minute in range(24 * 60):
        now = at(*day, 0) + datetime.timedelta(minutes=minute)
        if wbgt_fetch_due(now, last, status, data_at):
            last = now; tried.append(f"{now:%H:%M}")
    return tried, last


def test_in_season_day_is_18_fetches():
    tried, _ = _day_attempts((10, 5), "ok", at(10, 4, 23), last=at(10, 4, 23))
    assert tried[0] == "06:00" and tried[-1] == "23:00" and len(tried) == 18    # 以前は夜も含めて 24 回


def test_off_season_day_is_3_checks():
    """期間外：6・12・18 時の 3 回だけ（以前は 1 日 24 回、失敗時は 48 回）"""
    tried, _ = _day_attempts((12, 1), "nodata", at(10, 21, 18), last=at(11, 30, 18))
    assert tried == ["06:00", "12:00", "18:00"]


def test_season_end_and_start():
    """10/21 で終わり → 10/22・10/23 は 1 時間ごとに再確認 → 10/24 から 6 時間ごと。
    翌年 4/22 の朝 6 時の確認で値が取れたら 1 時間ごとに戻る"""
    last_data = at(10, 21, 23)
    t22, last = _day_attempts((10, 22), "nodata", last_data, last=last_data)
    assert len(t22) == 18
    t24, _ = _day_attempts((10, 24), "nodata", last_data, last=at(10, 23, 23))
    assert t24 == ["06:00", "12:00", "18:00"]
    next_year_last = at(4, 21, 18)
    assert wbgt_fetch_due(at(4, 22, 6), next_year_last, "nodata", None) is True
    assert wbgt_fetch_due(at(4, 22, 7), at(4, 22, 6), "ok", at(4, 22, 6)) is True


# ---------------------------------------------------------------- 0 時の非表示
def test_badge_only_on_the_day_of_data():
    data_at = at(10, 5, 14)
    assert wbgt_badge_visible(at(10, 5, 23, 59), data_at) is True
    assert wbgt_badge_visible(at(10, 6, 0, 0), data_at) is False      # 0 時に消える（前日の最高予測を翌日に出さない）
    assert wbgt_badge_visible(at(10, 6, 6, 0), at(10, 6, 6, 0)) is True
    assert wbgt_badge_visible(at(10, 6, 6, 0), None) is False
