"""夜間の判定（月アイコンの切替）と日の出・日の入りマークの位置"""
import datetime

import pytest

import utils
import weather_draw
from utils import JST, is_night

CENTRAIR = (34.8583, 136.8053)
NAHA = (26.1958, 127.6458)
CHITOSE = (42.7752, 141.6922)


def at(y, m, d, hh, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=JST)


@pytest.mark.parametrize("when, place, expected", [
    (at(2026, 9, 26, 18), CENTRAIR, True),    # 日の入り 17:44 → 18時は夜
    (at(2026, 9, 26, 18), NAHA, False),       # 日の入り 18:21 → 18時は昼（西の空港ほど遅い）
    (at(2026, 9, 26, 18), CHITOSE, True),     # 日の入り 17:22
    (at(2026, 9, 26, 12), CENTRAIR, False),   # 昼
    (at(2026, 12, 21, 6), CENTRAIR, True),    # 冬至：日の出 6:56 → 6時は夜
    (at(2026, 6, 21, 6), CENTRAIR, False),    # 夏至：日の出 4:39 → 6時は昼
    (at(2026, 6, 21, 18), CENTRAIR, False),   # 夏至：日の入り 19:09 → 18時は昼
    (at(2026, 9, 26, 0), CENTRAIR, True),     # 深夜
])
def test_is_night(when, place, expected):
    assert is_night(when, *place) is expected


def test_is_night_accepts_naive_datetime_as_jst():
    """時刻情報（タイムゾーン）なしの datetime は JST として扱う"""
    assert is_night(datetime.datetime(2026, 9, 26, 18), *CENTRAIR) is True


@pytest.fixture
def fixed_sun(monkeypatch):
    """日の出・日の入りを任意の時刻に固定する"""
    def _set(sunrise, sunset):
        def fake(day, lat, lon):
            return (datetime.datetime.combine(day, sunrise, tzinfo=JST),
                    datetime.datetime.combine(day, sunset, tzinfo=JST))
        monkeypatch.setattr(utils, "sun_times", fake)
    return _set


def test_sunrise_exactly_at_6(fixed_sun):
    """日の出が 6:00 ちょうど → 6:00 は昼、5:59 は夜"""
    fixed_sun(datetime.time(6, 0), datetime.time(17, 0))
    assert is_night(at(2026, 10, 20, 6, 0), 0, 0) is False
    assert is_night(at(2026, 10, 20, 5, 59), 0, 0) is True


def test_sunset_boundary(fixed_sun):
    """日の入りちょうどは夜（日の入り以降が夜）"""
    fixed_sun(datetime.time(6, 0), datetime.time(18, 0))
    assert is_night(at(2026, 10, 20, 17, 59), 0, 0) is False
    assert is_night(at(2026, 10, 20, 18, 0), 0, 0) is True


@pytest.mark.parametrize("hour, night", [("06", False), ("09", False), ("12", False), ("15", False),
                                         ("18", True), ("21", True), ("00", True), ("03", True)])
def test_night_columns_are_fixed(hour, night):
    """月アイコンは 18・21・00・03 時の列に一律（日の出・日の入りの時刻によらない）"""
    assert weather_draw._is_night_item({"hour": hour}) is night


def _table_times():
    base = datetime.datetime(2026, 9, 27, 6, tzinfo=JST)
    return [base + datetime.timedelta(hours=3 * i) for i in range(10)]   # 06〜翌09時


@pytest.mark.parametrize("hh, mm, day_offset, expected", [
    (6, 0, 0, 0.0),            # 先頭の列（06時）の左端
    (7, 30, 0, 0.5),           # 06〜09時の真ん中
    (17, 28, 0, 3 + 148 / 180),  # 15時の列の右寄り
    (5, 30, 1, 7 + 150 / 180),   # 翌日の日の出：03時の列の右寄り
    (5, 59, 0, None),          # 表の先頭より前 → 表示しない
])
def test_time_to_col(hh, mm, day_offset, expected):
    t = datetime.datetime(2026, 9, 27 + day_offset, hh, mm, tzinfo=JST)
    pos = weather_draw._time_to_col(_table_times(), t)
    if expected is None:
        assert pos is None
    else:
        assert pos == pytest.approx(expected)
