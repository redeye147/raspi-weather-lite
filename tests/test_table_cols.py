"""今日の天気の表の列を、見る時刻に合わせて並べる（table_cols.py）"""
import datetime

import pytest

import table_cols
from utils import JST, get_target_datetimes


def _hourly(now):
    return [dict(datetime=t, date=t.strftime("%-m/%-d"), hour=t.strftime("%H"), code="101", pop=f"{i}.0mm",
                 temp_val=20, temp="20℃", wind_val=3, wind="3m", wind_dir=90)
            for i, t in enumerate(get_target_datetimes(now, layout="now"))]


def at(h, m):
    return datetime.datetime(2026, 10, 30, h, m, tzinfo=JST)


def test_targets_start_at_current_slot():
    ts = get_target_datetimes(at(20, 50), layout="now")
    assert ts[0] == at(18, 0) and len(ts) == 12 and ts[1] == at(21, 0)


def test_now_rest_then_next_slots():
    """18:05：今・〜21（残り 3 時間弱の予報）・21・00 …"""
    now = at(18, 5)
    obs = lambda h, cur: [dict(x, pop="7.5mm") if i == cur else x for i, x in enumerate(h)]
    cols = table_cols.build(_hourly(now), now, observe=obs)
    assert [c["hour"] for c in cols] == ["今 18:05", "〜21", "21", "00", "03", "06", "09", "12", "15", "18"]
    assert cols[0]["is_now"] and cols[0]["pop"] == "7.5mm"           # 今は観測
    assert cols[1]["pop"] == "0.0mm" and not cols[1].get("is_now")   # 〜21 は今の時間帯の予報
    assert cols[0]["slot_hour"] == cols[1]["slot_hour"] == "18"      # 夜の色は元の時間帯で


def test_rest_omitted_when_less_than_an_hour():
    """20:50：残り 10 分なので「〜21」は出さず、今のすぐ右が 21"""
    now = at(20, 50)
    cols = table_cols.build(_hourly(now), now)
    assert [c["hour"] for c in cols][:3] == ["今 20:50", "21", "00"] and len(cols) == 10


@pytest.mark.parametrize("h, m, rest", [(6, 0, True), (7, 59, True), (8, 1, False)])
def test_rest_threshold(h, m, rest):
    now = at(h, m)
    cols = table_cols.build(_hourly(now), now)
    assert (cols[1]["hour"] == "〜09") is rest


@pytest.mark.parametrize("h, m, start, now_after", [
    (13, 15, "06", "12"),        # 昼の表（6 時から）：12 の列の右に今
    (23, 50, "06", "21"),
    (0, 20, "18", "00"),         # 夜の表（前の日の 18 時から）：00 の列の右に今
    (5, 50, "18", "03"),
])
def test_insert_layout(h, m, start, now_after):
    """案 D：6:00〜23:59 は今日の 6 時から、0:00〜5:59 は前の日の 18 時から 9 列。今の時間帯の右に「今」を割り込ませる"""
    now = at(h, m)
    ts = get_target_datetimes(now, layout="insert")
    hourly = [dict(datetime=t, date=t.strftime("%-m/%-d"), hour=t.strftime("%H"), code="101", pop="1.0mm")
              for t in ts]
    cols = table_cols.build_insert(hourly, now, observe=lambda hh, cur: [dict(x, pop="9.0mm") if i == cur else x
                                                                         for i, x in enumerate(hh)])
    hours = [c["hour"] for c in cols]
    assert hours[0] == start and len(cols) == 10
    i = hours.index(f"今 {now:%H:%M}")
    assert hours[i - 1] == now_after and cols[i]["is_now"] and cols[i]["pop"] == "9.0mm"
    assert cols[i - 1]["pop"] == "1.0mm"                                  # 今の時間帯の列は予報のまま


def test_fixed_layout_targets_unchanged():
    """今までの表：朝 6 時〜翌朝 9 時（6 時より前は前の日の 6 時から）"""
    ts = get_target_datetimes(at(13, 15), layout="fixed")
    assert ts[0] == at(6, 0) and len(ts) == 10
    ts = get_target_datetimes(at(3, 0), layout="fixed")
    assert ts[0] == datetime.datetime(2026, 10, 29, 6, tzinfo=JST)


def test_insert_fills_past_columns_with_observations():
    """案 D：過ぎた時間帯の列は、記録した毎時 00 分の観測で埋める（今の時間帯の列は予報のまま）"""
    now = at(13, 15)
    ts = get_target_datetimes(now, layout="insert")
    hourly = [dict(datetime=t, date=t.strftime("%-m/%-d"), hour=t.strftime("%H"), code="100", pop="0.0mm",
                   temp_val=20, temp="20℃", wind_val=3, wind="3m", wind_dir=90) for t in ts]
    observed = {
        "2026-10-30 06:00": {"temp": 15, "wind": 2.1, "wind_dir": 330, "code": "200", "rain": False, "radar_mmh": 0.0},
        "2026-10-30 07:00": {"temp": 16, "wind": 5.7, "wind_dir": 10, "code": "302", "rain": True, "radar_mmh": 7.5},
        "2026-10-30 08:00": {"temp": 17, "wind": 4.0, "wind_dir": None, "code": "300", "rain": True, "radar_mmh": 3.0},
        "2026-10-30 12:00": {"temp": 25, "wind": 9.0, "wind_dir": 200, "code": "350", "rain": True, "radar_mmh": 40.0},
    }
    cols = table_cols.build_insert(hourly, now, observed=observed)
    c06, c09, c12 = cols[0], cols[1], cols[2]
    assert c06["code"] == "302" and c06["temp"] == "16℃" and c06["wind_val"] == 6 and c06["wind_dir"] == 10
    assert c06["pop"] == "7.5mm" and c06["past_observed"]
    assert c09["code"] == "100" and not c09.get("past_observed")        # 観測の記録が無い列は予報のまま
    assert c12["code"] == "100" and not c12.get("past_observed")        # 今の時間帯の列は予報のまま
    assert cols[3]["is_now"]


def test_verify_observed_hours_roundtrip(tmp_path):
    import aviation
    import verify
    d = str(tmp_path)
    m = aviation.parse_metar("RJGG 300300Z 33012KT 9999 -RA BKN020 19/15 Q1012",
                             datetime.datetime(2026, 10, 30, 3, 10, tzinfo=datetime.timezone.utc))
    verify.record_observation(m, 3.0, d)
    obs = verify.observed_hours("RJGG", base_dir=d)
    r = obs["2026-10-30 12:00"]
    assert r["temp"] == 19 and r["wind_dir"] == 330 and r["code"] == "300" and r["radar_mmh"] == 3.0
    assert verify.observed_hours("RJTT", base_dir=d) == {}


def test_past_column_without_recorded_direction_has_no_calm_mark():
    """記録に風向が無い行（項目を足す前）は「---」（変動・無風の印）にしない。VRB のときだけ「---」"""
    item = dict(datetime=at(18, 0), date="10/30", hour="18", code="100", pop="0.0mm", temp_val=18, temp="18℃",
                wind_val=3, wind="3m", wind_dir=90)
    no_dir = {"2026-10-30 18:00": {"temp": 18, "wind": 3.1, "wind_dir": None, "code": "100", "rain": False, "radar_mmh": None}}
    out = table_cols.fill_with_observed(item, no_dir)
    assert out["wind_dir"] is None and not out["wind_variable"]
    vrb = {"2026-10-30 18:00": dict(no_dir["2026-10-30 18:00"], wind_dir="VRB")}
    assert table_cols.fill_with_observed(item, vrb)["wind_variable"]
