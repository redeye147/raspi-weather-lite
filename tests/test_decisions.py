"""メインループの判断（スナップショットの利用・定時取得・定期取得・失敗時の再試行）"""
import datetime

import pytest

from decisions import (decide_snapshot, periodic_fetch_action, retry_base_after_failure,
                       should_fetch_0600, should_fetch_2350,
                       aviation_expected_obs, aviation_fetch_due, aviation_band_visible)

JST = datetime.timezone(datetime.timedelta(hours=9))
T = 1_790_000_000.0          # 起動時刻（UNIX 秒）
TABLE = "2026-10-03T06"      # 今の表の開始（今日の 6 時）


def at(d, hh, mm=0):
    return datetime.datetime(2026, 10, d, hh, mm, tzinfo=JST)


def snapshot(**over):
    s = {"airport": "haneda", "hourly": [1], "daily": [1], "table_start": TABLE,
         "weather_at": T - 600, "jma_at": T - 600, "wbgt_at": T - 600}
    s.update(over)
    return s


# ---------------------------------------------------------------- スナップショット
class TestDecideSnapshot:
    def decide(self, snap, synced=True, interval=2.0):
        return decide_snapshot(snap, "haneda", synced, T, interval, TABLE)

    def test_fresh_snapshot_is_used_without_fetch(self):
        d = self.decide(snapshot())
        assert d["weather_fresh"] and d["jma_fresh"] and d["wbgt_fresh"]
        assert not d["kick_fetch"]

    def test_no_snapshot(self):
        d = self.decide(None)
        assert d == {"snap": None, "weather_fresh": False, "kick_fetch": False,
                     "jma_fresh": False, "wbgt_fresh": False}

    def test_other_airport_is_discarded(self):
        d = self.decide(snapshot(airport="narita"))
        assert d["snap"] is None and not d["weather_fresh"]

    def test_weather_older_than_interval(self):
        assert not self.decide(snapshot(weather_at=T - 2 * 3600))["weather_fresh"]
        assert self.decide(snapshot(weather_at=T - 2 * 3600 + 1))["weather_fresh"]

    def test_table_of_previous_day_is_not_used(self):
        """朝6時をまたいだら前日の表は使わない"""
        assert not self.decide(snapshot(table_start="2026-10-02T06"))["weather_fresh"]

    def test_empty_hourly_is_not_used(self):
        assert not self.decide(snapshot(hourly=[]))["weather_fresh"]

    def test_jma_and_wbgt_expire_after_one_hour(self):
        d = self.decide(snapshot(jma_at=T - 3600, wbgt_at=T - 3599))
        assert not d["jma_fresh"] and d["wbgt_fresh"]

    def test_unsynced_clock_shows_snapshot_and_fetches_now(self):
        """時刻未同期：古さは判断できないので前回データを表示しつつ、すぐ裏で取り直す"""
        d = self.decide(snapshot(weather_at=T - 10 * 3600, table_start="2026-10-02T06"), synced=False)
        assert d["weather_fresh"] and d["kick_fetch"]
        assert not d["jma_fresh"] and not d["wbgt_fresh"]

    def test_unsynced_clock_without_snapshot(self):
        d = self.decide(None, synced=False)
        assert not d["weather_fresh"] and not d["kick_fetch"]


# ---------------------------------------------------------------- 23:50 / 6:00 の定時取得
@pytest.mark.parametrize("hh, mm, expected", [(23, 49, False), (23, 50, True), (23, 51, False), (11, 50, False)])
def test_fetch_2350_only_at_2350(hh, mm, expected):
    assert should_fetch_2350(at(3, hh, mm), "", False) is expected


def test_fetch_2350_once_per_day_and_not_while_pending():
    now = at(3, 23, 50)
    assert should_fetch_2350(now, "2026-10-03", False) is False   # 今日はもう取得済み
    assert should_fetch_2350(now, "2026-10-02", False) is True    # 昨日の記録 → 今日はまだ
    assert should_fetch_2350(now, "", True) is False              # 取得中


@pytest.mark.parametrize("hh, mm, expected", [(5, 59, False), (6, 0, True), (6, 9, True), (6, 10, False)])
def test_fetch_0600_window(hh, mm, expected):
    last = at(2, 23, 50)
    assert should_fetch_0600(at(3, hh, mm), last, "", False) is expected


def test_fetch_0600_skipped_if_already_fetched_after_6():
    """起動直後などで 6 時以降のデータが既にあれば取り直さない"""
    assert should_fetch_0600(at(3, 6, 5), at(3, 6, 1), "", False) is False
    assert should_fetch_0600(at(3, 6, 5), at(3, 5, 59), "", False) is True


def test_fetch_0600_once_per_day_and_not_while_pending():
    assert should_fetch_0600(at(3, 6, 1), at(2, 23, 50), "2026-10-03", False) is False
    assert should_fetch_0600(at(3, 6, 1), at(2, 23, 50), "", True) is False


# ---------------------------------------------------------------- 定期取得
@pytest.mark.parametrize("hh, expected", [(3, "postpone"), (5, "postpone"), (6, "fetch"), (12, "fetch"), (23, "fetch")])
def test_periodic_fetch_daytime_only(hh, expected):
    now = at(3, hh)
    assert periodic_fetch_action(now, now - datetime.timedelta(hours=2), False, 2.0) == expected


def test_periodic_fetch_waits_for_interval():
    now = at(3, 12)
    assert periodic_fetch_action(now, now - datetime.timedelta(minutes=119), False, 2.0) is None
    assert periodic_fetch_action(now, now - datetime.timedelta(hours=2), True, 2.0) is None   # 取得中


def test_retry_30_minutes_after_failure():
    now = at(3, 12)
    base = retry_base_after_failure(now, 2.0)
    assert periodic_fetch_action(now + datetime.timedelta(minutes=29), base, False, 2.0) is None
    assert periodic_fetch_action(now + datetime.timedelta(minutes=30), base, False, 2.0) == "fetch"


# ---------------------------------------------------------------- 一晩の流れ（main() のループと同じ順で判断）
def simulate_night(fail_at=None, interval=2.0):
    """22:00〜翌9:00 を1分刻みで回し、取得した時刻を返す（取得はその場で完了とみなす）"""
    now, last = at(2, 22), at(2, 21, 50)
    done_2350 = done_0600 = ""
    fetched = []

    def fetch(tag):
        nonlocal last
        ok = now.strftime("%H:%M") != fail_at
        fetched.append(f"{now:%H:%M}{tag}{'' if ok else '(失敗)'}")
        last = now if ok else retry_base_after_failure(now, interval)

    while now < at(3, 9):
        if should_fetch_2350(now, done_2350, False):
            done_2350 = now.strftime("%Y-%m-%d"); fetch("[23:50]")
        if should_fetch_0600(now, last, done_0600, False):
            done_0600 = now.strftime("%Y-%m-%d"); fetch("[6:00]")
        action = periodic_fetch_action(now, last, False, interval)
        if action == "fetch":
            fetch("")
        elif action == "postpone":
            last = now
        now += datetime.timedelta(minutes=1)
    return fetched


def test_overnight_schedule():
    """夜間は先送りし、6:00 に当日の表へ切り替え、以後は2時間ごと"""
    assert simulate_night() == ["23:50[23:50]", "06:00[6:00]", "08:00"]


def test_overnight_schedule_with_failure_at_6():
    """6:00 の取得に失敗したら 30 分後に再試行"""
    assert simulate_night(fail_at="06:00") == ["23:50[23:50]", "06:00[6:00](失敗)", "06:30", "08:30"]


# ---------------------------------------------------------------- 航空気象の取得（00 分の観測は 7 分後・30 分は 10 分後、届くまで 2 分おきに最大 6 回）
@pytest.mark.parametrize("hh, mm, mark", [
    (0, 0, None), (5, 59, None), (6, 6, None),                     # 0:00〜6:06 は取得しない
    (6, 7, (6, 0)), (6, 39, (6, 0)), (6, 40, (6, 30)), (7, 6, (6, 30)), (7, 7, (7, 0)),
    (23, 40, (23, 30)), (23, 59, (23, 30)),
])
def test_aviation_expected_obs(hh, mm, mark):
    m = aviation_expected_obs(at(3, hh, mm))
    assert (None if m is None else (m.hour, m.minute)) == mark


def test_aviation_no_fetch_when_new_obs_already_there():
    assert aviation_fetch_due(at(3, 10, 7), at(3, 10, 0), None) is None
    assert aviation_fetch_due(at(3, 10, 7), at(3, 10, 2), None) is None      # 特別観測（SPECI）など、より新しい


def _tries(hh, start_obs, minutes, arrive=None):
    """1分刻みに回して取得した分を返す。arrive（分）以降の取得では新しい観測が取れたことにする"""
    shown, last, tried = start_obs, None, []
    for minute in minutes:
        now = at(3, hh, minute)
        a = aviation_fetch_due(now, shown, last)
        if a:
            last = a; tried.append(minute)
            if arrive is not None and minute >= arrive:
                shown = a[0]
    return tried


def test_aviation_retry_on_the_hour():
    """10:00 の観測：10:07 から 2 分おきに最大 6 回（10:07〜10:17）。届けばそこで終わり"""
    assert _tries(10, at(3, 9, 30), range(0, 40)) == [7, 9, 11, 13, 15, 17]
    assert _tries(10, at(3, 9, 30), range(0, 40), arrive=8) == [7, 9]


def test_aviation_retry_on_the_half_hour():
    """10:30 の観測：10:40 から 2 分おきに最大 6 回（10:40〜10:50）"""
    assert _tries(10, at(3, 10, 0), range(30, 60)) == [40, 42, 44, 46, 48, 50]
    assert _tries(10, at(3, 10, 0), range(30, 60), arrive=11 + 30) == [40, 42]


def test_aviation_without_any_data_keeps_trying_every_2_min():
    assert _tries(10, None, range(7, 42)) == [7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 40]


# 2026-10-04 に成田で実測した「観測から NOAA に届くまでの分」（00 分の観測 / 30 分の観測）
MEASURED_00 = [9, 7, 7, 10, 7, 7, 7, 8, 9, 8, 7, 7, 8, 8]
MEASURED_30 = [10, 11, 12, 10, 11, 9, 9, 11, 11, 11, 12, 10, 12, 10]


def _simulate(delays_00, delays_30):
    """実測の遅れで1日を回す。戻り値: (取得回数, 観測から画面に出るまでの分のリスト)"""
    fetches, lags = 0, []
    for i, hh in enumerate(range(7, 21)):
        for mm, delay in ((0, delays_00[i]), (30, delays_30[i])):
            obs = at(3, hh, mm)
            shown, last = obs - datetime.timedelta(minutes=30), None
            for k in range(30):
                now = obs + datetime.timedelta(minutes=k)
                a = aviation_fetch_due(now, shown, last)
                if a:
                    last, fetches = a, fetches + 1
                    if k >= delay:
                        shown = obs; lags.append(k)
    return fetches, lags


def test_aviation_measured_delays():
    """実測の遅れでは、すべての観測が取れて、画面に出るまで最大 12 分・平均 10 分以内。取得は 28 観測で 44 回"""
    fetches, lags = _simulate(MEASURED_00, MEASURED_30)
    assert len(lags) == 28 and max(lags) <= 12 and sum(lags) / len(lags) < 10
    assert fetches == 44


def test_aviation_slow_noaa_still_caught():
    """届くのが 17 分（00 分）/ 20 分（30 分）まで遅れても、最大 6 回のうちに取れる"""
    fetches, lags = _simulate([17] * 14, [20] * 14)
    assert len(lags) == 28


@pytest.mark.parametrize("hh, visible", [(0, False), (3, False), (5, False), (6, True), (23, True)])
def test_aviation_band_hidden_from_midnight(hh, visible):
    """0:00 ちょうどに帯を消し、6 時台（6:05 の取得後）に再表示"""
    assert aviation_band_visible(at(3, hh)) is visible
