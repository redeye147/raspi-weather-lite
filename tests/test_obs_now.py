"""今日の天気の今の時間帯を、空港の実況（METAR）で置き換える（obs_now）"""
import datetime

import pytest

import aviation
import obs_now

UTC = datetime.timezone.utc
JST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 10, 24, 1, 20, tzinfo=UTC)          # 10:20 JST


def metar(raw):
    return aviation.parse_metar(raw, NOW)


@pytest.mark.parametrize("raw, code", [
    ("RJGG 240100Z 33012KT 9999 FEW020 19/10 Q1015", "100"),           # 晴
    ("RJGG 240100Z 33012KT CAVOK 19/10 Q1015", "100"),
    ("RJGG 240100Z 33012KT 9999 BKN020 19/10 Q1015", "101"),           # 晴時々曇
    ("RJGG 240100Z 33012KT 9999 OVC020 19/10 Q1015", "200"),           # 曇
    ("RJGG 240100Z 33012KT 9999 -RA OVC020 19/10 Q1015", "300"),       # 弱い雨
    ("RJGG 240100Z 33012KT 9999 SHRA BKN020 19/10 Q1015", "302"),      # にわか雨
    ("RJGG 240100Z 33012KT 3000 +RA OVC010 19/10 Q1015", "306"),       # 強い雨 → 大雨
    ("RJGG 240100Z 33012KT 9999 -DZ OVC010 19/10 Q1015", "202"),       # 霧雨
    ("RJGG 240100Z 33012KT 3000 SN OVC010 M01/M03 Q1015", "400"),      # 雪
    ("RJGG 240100Z 33012KT 0800 +SN OVC005 M01/M03 Q1015", "405"),     # 強い雪 → 大雪
    ("RJGG 240100Z 33012KT 5000 TSRA FEW020CB BKN030 19/10 Q1015", "350"),   # 雷雨
    ("RJGG 240100Z 33012KT 0300 FG VV001 15/15 Q1015", "209"),         # 霧
    ("RJGG 240100Z 33012KT 9999 VCSH FEW020 19/10 Q1015", "100"),      # 周辺のにわか雨は数えない
])
def test_icon_code_from_metar(raw, code):
    assert obs_now.icon_code_from_metar(metar(raw)) == code


def _hourly():
    base = datetime.datetime(2026, 10, 24, 6, tzinfo=JST)
    return [dict(datetime=base + datetime.timedelta(hours=3 * i), hour=f"{6 + 3 * i:02d}", code="302",
                 pop="2.5mm", temp_val=15, temp="15℃", wind_val=3, wind="3 m/s", wind_dir=0) for i in range(4)]


def test_apply_replaces_only_current_column():
    hourly = _hourly()
    m = metar("RJGG 240100Z 33012G25KT 9999 FEW020 19/10 Q1015")
    out = obs_now.apply_observation(hourly, 1, m, NOW)
    cur = out[1]
    assert cur["code"] == "100" and cur["temp"] == "19℃" and cur["temp_val"] == 19
    assert cur["wind_val"] == 6 and cur["wind_dir"] == 330                  # 12kt = 6 m/s
    assert cur["pop"] == "2.5mm"                                            # 降水量は予報のまま
    assert cur["observed"] and "obs_label" not in cur                       # 画面に「実況」の文字は足さない
    assert out[0] is hourly[0] and out[2] is hourly[2]                      # ほかの列は予報のまま
    assert hourly[1]["code"] == "302"                                       # 元の予報は変えない


def test_variable_wind_has_no_direction():
    out = obs_now.apply_observation(_hourly(), 1, metar("RJGG 240100Z VRB02KT 9999 FEW020 19/10 Q1015"), NOW)
    assert out[1]["wind_val"] == 1 and out[1]["wind_dir"] is None and out[1]["wind_variable"]


@pytest.mark.parametrize("obs_min_ago, replaced", [(30, True), (90, True), (91, False)])
def test_old_observation_is_not_used(obs_min_ago, replaced):
    m = metar("RJGG 240100Z 33012KT 9999 FEW020 19/10 Q1015")
    now = m["obs_utc"] + datetime.timedelta(minutes=obs_min_ago)
    out = obs_now.apply_observation(_hourly(), 1, m, now)
    assert bool(out[1].get("observed")) == replaced


@pytest.mark.parametrize("cur, m", [(None, "x"), (1, None), (9, "x")])
def test_nothing_to_replace(cur, m):
    hourly = _hourly()
    mm = metar("RJGG 240100Z 33012KT 9999 FEW020 19/10 Q1015") if m else None
    assert obs_now.apply_observation(hourly, cur, mm, NOW) is hourly


def test_calm_is_not_variable():
    """無風（00000KT）は「変動」ではなく 0 m/s（画面では同じ「---」）"""
    out = obs_now.apply_observation(_hourly(), 1, metar("RJGG 240100Z 00000KT 9999 FEW020 19/10 Q1015"), NOW)
    assert out[1]["wind_val"] == 0 and not out[1]["wind_variable"]
