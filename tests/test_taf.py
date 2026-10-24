"""TAF（taf.py）の解析と、列ごとのまとめ"""
import datetime

import taf

UTC = datetime.timezone.utc
REF = datetime.datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
RAW = ("TAF RJGG 240505Z 2406/2512 33012KT 9999 FEW030 "
       "BECMG 2409/2411 VRB03KT "
       "TEMPO 2412/2415 -SHRA BKN020 "
       "FM250000 18015G25KT 9999 SCT030 "
       "PROB30 TEMPO 2503/2506 TSRA")


def u(d, h):
    return datetime.datetime(2026, 10, d, h, tzinfo=UTC)


def test_parse():
    t = taf.parse_taf(RAW, REF)
    assert t["icao"] == "RJGG"
    assert (t["issued"], t["start"], t["end"]) == (datetime.datetime(2026, 10, 24, 5, 5, tzinfo=UTC), u(24, 6), u(25, 12))
    assert t["base"] == {"wind_dir": 330, "wind_kt": 12}
    assert [g["kind"] for g in t["groups"]] == ["BECMG", "TEMPO", "FM", "TEMPO"]
    assert t["groups"][1]["el"] == {"wx": ["-SHRA"]}


def test_conditions():
    t = taf.parse_taf(RAW, REF)
    assert taf.conditions_at(t, u(24, 5)) is None                         # 期間の前
    assert taf.conditions_at(t, u(24, 7)) == ({"wind_dir": 330, "wind_kt": 12}, [])
    state, alts = taf.conditions_at(t, u(24, 10))                          # 移り変わり中：どちらもありうる
    assert state["wind_kt"] == 12 and alts[0]["wind_kt"] == 3
    state, alts = taf.conditions_at(t, u(24, 13))
    assert state == {"wind_dir": None, "wind_kt": 3} and alts[0]["wx"] == ["-SHRA"]
    state, alts = taf.conditions_at(t, u(25, 4))                           # FM で全部入れ替わる
    assert state["wind_kt"] == 15 and alts[0]["wx"] == ["TSRA"]
    assert taf.conditions_at(t, u(25, 12)) is None                         # 期間の後


def test_slot_summary():
    t = taf.parse_taf(RAW, REF)
    s = taf.slot_summary(t, u(24, 9))                                      # 09〜12Z：12kt と 3kt → 強い方
    assert s["wind_kt"] == 12 and s["wind_dir"] == 330 and s["wx"] == [] and s["tempo_wx"] == []
    s = taf.slot_summary(t, u(24, 12))
    assert s["wind_kt"] == 3 and s["wind_dir"] is None and s["tempo_wx"] == ["-SHRA"]
    assert taf.slot_summary(t, u(25, 3))["tempo_wx"] == ["TSRA"]
    assert taf.slot_summary(t, u(25, 11)) is None                          # 期間からはみ出す列は使わない


def test_multiline_and_nsw():
    raw = "TAF AMD RJGG 241000Z 2410/2512 VRB02KT 9999 -RA FEW010\n      BECMG 2412/2413 NSW="
    t = taf.parse_taf(" ".join(raw.split()), REF)
    assert t["base"]["wx"] == ["-RA"]
    assert taf.conditions_at(t, u(24, 14))[0]["wx"] == []


def test_unreadable():
    assert taf.parse_taf("TAF RJGG 240505Z NIL", REF) is None
    assert taf.parse_taf("garbage", REF) is None
    assert taf.parse_taf("TAF RJGG 240505Z 2406/2512 NIL", REF) is None
