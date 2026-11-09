"""地震（震度 5 弱以上）の帯：quake.py"""
import datetime

import quake
from utils import JST


def _entry(eid, rdt, at, city_maxi, anm="愛知県西部", cod="+35.0+136.9-10000/", mag="5.8", city="2321600", ttl="震源・震度情報"):
    return {"eid": eid, "rdt": rdt, "at": at, "ttl": ttl, "anm": anm, "cod": cod, "mag": mag, "maxi": city_maxi,
            "int": [{"code": "23", "maxi": city_maxi, "city": [{"code": city, "maxi": city_maxi}]}]}


NOW = datetime.datetime(2026, 11, 6, 11, 0, tzinfo=JST)


def test_finds_5_lower_or_more_in_airport_city():
    es = [_entry("1", "2026-11-06T10:26:00+09:00", "2026-11-06T10:23:00+09:00", "5+")]
    q = quake.find_quake(es, "2321600", NOW)
    assert q["intensity"] == "5+" and q["epicenter"] == "愛知県西部" and q["depth_km"] == 10 and q["mag"] == "5.8"
    title, body = quake.banner_text(q, "常滑市")
    assert title == "地震 震度5強"
    assert body == "常滑市（11/6 10:23 発生・震源 愛知県西部 深さ 10km・M5.8）"


def test_ignores_other_city_and_out_of_time():
    es = [_entry("2", "2026-11-06T10:40:00+09:00", "2026-11-06T10:37:00+09:00", "6-", city="2320100"),
          _entry("3", "2026-11-06T07:50:00+09:00", "2026-11-06T07:45:00+09:00", "6+"),     # 5 弱以上でも 3 時間より前
          _entry("4", "2026-11-06T09:55:00+09:00", "2026-11-06T09:50:00+09:00", "4")]      # 4 は 1 時間まで
    assert quake.find_quake(es, "2321600", NOW) is None
    assert quake.find_quake(es, None, NOW) is None


def test_levels_and_show_hours():
    assert [quake.level_of(i) for i in ("1", "3", "4", "5-", "7")] == ["low", "low", "mid", "high", "high"]
    assert quake.show_hours("3") == 1 and quake.show_hours("4") == 1 and quake.show_hours("5-") == 3
    es = [_entry("1", "2026-11-06T10:15:00+09:00", "2026-11-06T10:10:00+09:00", "1")]
    q = quake.find_quake(es, "2321600", NOW)                          # 震度 1・50 分前 → 出す
    assert q["level"] == "low" and quake.banner_text(q, "常滑市")[0] == "地震 震度1"
    assert quake.find_quake(es, "2321600", NOW + datetime.timedelta(minutes=15)) is None   # 1 時間を過ぎたら消す


def test_strong_quake_is_kept_over_later_weak_ones():
    """5 弱以上の帯が出ている 3 時間は、あとの弱い揺れ（余震）でそちらに替えない。弱いものどうしは新しい方"""
    strong = _entry("1", "2026-11-06T09:05:00+09:00", "2026-11-06T09:00:00+09:00", "5+")
    weak = _entry("2", "2026-11-06T10:50:00+09:00", "2026-11-06T10:45:00+09:00", "2")
    mid = _entry("3", "2026-11-06T10:35:00+09:00", "2026-11-06T10:30:00+09:00", "4")
    assert quake.find_quake([weak, strong, mid], "2321600", NOW)["eid"] == "1"
    assert quake.find_quake([weak, mid], "2321600", NOW)["eid"] == "2"


def test_uses_latest_report_of_same_quake_and_unknown_epicenter():
    first = _entry("1", "2026-11-06T10:25:00+09:00", "2026-11-06T10:23:00+09:00", "5-", anm="", cod="", mag="")
    later = _entry("1", "2026-11-06T10:29:00+09:00", "2026-11-06T10:23:00+09:00", "5+")
    q = quake.find_quake([first], "2321600", NOW)
    assert quake.banner_text(q, "常滑市")[1] == "常滑市（11/6 10:23 発生・震源 調査中）"
    q = quake.find_quake([later, first], "2321600", NOW)
    assert q["intensity"] == "5+" and q["epicenter"] == "愛知県西部"


def test_intensity_order_and_depth():
    assert quake.intensity_rank("5-") < quake.intensity_rank("5+") < quake.intensity_rank("7")
    assert quake.intensity_rank("不明") == -1
    assert quake.depth_km("+35.0+136.9-10000/") == 10 and quake.depth_km("") is None
    assert quake.depth_km("+35.0+136.9+0/") == 0


def test_fetch_list_handles_304_and_errors():
    class R:
        def __init__(self, code, data=None, etag=None):
            self.status_code, self._d, self.headers = code, data, {"ETag": etag} if etag else {}

        def json(self):
            return self._d

    class S:
        def __init__(self, r):
            self.r, self.headers = r, None

        def get(self, url, headers=None, timeout=None):
            self.headers = headers
            return self.r

    s = S(R(200, [{"eid": "1"}], '"abc"'))
    assert quake.fetch_list(session=s) == ("ok", [{"eid": "1"}], '"abc"')
    s = S(R(304))
    assert quake.fetch_list(session=s, etag='"abc"')[0] == "same" and s.headers["If-None-Match"] == '"abc"'
    assert quake.fetch_list(session=S(R(500)))[0].startswith("error")
    assert quake.fetch_list(session=S(R(200, {"x": 1})))[0].startswith("error")


def test_every_airport_has_quake_city():
    from config import AIRPORT_CONFIG
    for key, c in AIRPORT_CONFIG.items():
        code, name = c["quake_city"]
        assert len(code) == 7 and code.isdigit() and name, key
