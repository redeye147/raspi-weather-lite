"""子機用ページのカード表示（now_page.build_card）"""
import datetime

import now_page
from utils import JST


def _hours(start, n, temp=lambda h: 10 + (h % 24) // 2, wind=3.0, wmo=0, prec=0.0):
    out = []
    for i in range(n):
        t = start + datetime.timedelta(hours=i)
        out.append({"t": t.strftime("%Y-%m-%dT%H:00"), "temp": temp(i), "wind": wind, "dir": 340, "wmo": wmo, "prec": prec})
    return out


START = datetime.datetime(2026, 11, 10, 0, tzinfo=JST)     # 前の日から 3 日分


def test_today_before_18_and_tomorrow_after():
    card = {"hours": _hours(START, 72), "pops6": {"2026-11-11T06": 0, "2026-11-11T12": 10, "2026-11-12T06": 60}}
    c = now_page.build_card(datetime.datetime(2026, 11, 11, 10, 0, tzinfo=JST), card)
    assert c["tomorrow"] is False and c["date_label"] == "11/11（水）"
    assert [p["name"] for p in c["periods"]] == ["朝", "昼", "夕", "夜"]
    assert c["periods"][0]["pop"] == 0 and c["periods"][1]["pop"] == 10 and c["umbrella"] is False
    assert c["periods"][2]["icon"] == "700"                    # 夕方の晴れは月
    c = now_page.build_card(datetime.datetime(2026, 11, 11, 18, 0, tzinfo=JST), card)
    assert c["tomorrow"] is True and c["date_label"] == "11/12（木）" and c["umbrella"] is True   # 朝 60%


def test_max_temp_diff_and_official():
    card = {"hours": _hours(START, 72, temp=lambda h: 10 + (h // 24) * 2 + (h % 24) // 4), "pops6": {}}
    now = datetime.datetime(2026, 11, 11, 9, 0, tzinfo=JST)
    c = now_page.build_card(now, card)
    assert c["max"] == 17 and c["diff"] == 2                   # 昨日より 2℃ 高い
    c = now_page.build_card(now, card, daily=[{"date": "2026-11-11", "temp": "18/6"}])
    assert (c["max"], c["min"]) == (18, 6)                    # 気象庁の最高・最低があればそれ


def test_umbrella_from_rain_and_wind_max():
    card = {"hours": _hours(START, 72, prec=0.0), "pops6": {}}
    now = datetime.datetime(2026, 11, 11, 9, 0, tzinfo=JST)
    assert now_page.build_card(now, card)["umbrella"] is False
    rain = {"2026-11-11T14:00": 1.5}                          # 13 時台に 1.5mm/h（降水短時間予報）
    assert now_page.build_card(now, card, rain_hours=rain)["umbrella"] is True
    c = now_page.build_card(now, card)
    assert c["wind_max"]["ms"] == 3 and c["wind_max"]["dir_name"] == "北北西"
    assert now_page.dir_name(0) == "北" and now_page.dir_name(None) == ""


def test_no_data():
    assert now_page.build_card(datetime.datetime(2026, 11, 11, 9, tzinfo=JST), {"hours": [], "pops6": {}}) is None
