"""メインループの判断（スナップショットの利用・定時取得・定期取得・失敗時の再試行）"""
import datetime

import pytest

from decisions import (decide_snapshot, periodic_fetch_action, retry_base_after_failure,
                       should_fetch_0600, should_fetch_2350, should_fetch_aviation,
                       aviation_slot, aviation_band_visible)

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


# ---------------------------------------------------------------- 航空気象の取得（毎時 05・35 分、6:05〜23:35）
@pytest.mark.parametrize("hh, mm, slot", [
    (0, 0, None), (5, 59, None), (6, 0, None), (6, 4, None),       # 0:00〜6:04 は取得しない
    (6, 5, (6, 5)), (6, 34, (6, 5)), (6, 35, (6, 35)), (7, 4, (6, 35)),
    (12, 10, (12, 5)), (23, 35, (23, 35)), (23, 59, (23, 35)),
])
def test_aviation_slot(hh, mm, slot):
    s = aviation_slot(at(3, hh, mm))
    assert (None if s is None else (s.hour, s.minute)) == slot


def test_aviation_fetch_schedule_per_day():
    """1分刻みで1日回すと、6:05 から 23:35 まで毎時 05・35 分に 36 回取得"""
    last, times = None, []
    for minute in range(24 * 60):
        now = at(3, 0) + datetime.timedelta(minutes=minute)
        if should_fetch_aviation(now, last):
            last = aviation_slot(now); times.append(f"{now:%H:%M}")
    assert len(times) == 36 and times[:3] == ["06:05", "06:35", "07:05"] and times[-1] == "23:35"


def test_aviation_fetch_on_boot_within_slot():
    """起動直後（取得枠の途中）はその枠ですぐ取得し、同じ枠ではもう取らない"""
    now = at(3, 10, 20)
    assert should_fetch_aviation(now, None) is True
    assert should_fetch_aviation(now + datetime.timedelta(minutes=10), aviation_slot(now)) is False
    assert should_fetch_aviation(at(3, 10, 35), aviation_slot(now)) is True


@pytest.mark.parametrize("hh, visible", [(0, False), (3, False), (5, False), (6, True), (23, True)])
def test_aviation_band_hidden_from_midnight(hh, visible):
    """0:00 ちょうどに帯を消し、6 時台（6:05 の取得後）に再表示"""
    assert aviation_band_visible(at(3, hh)) is visible
