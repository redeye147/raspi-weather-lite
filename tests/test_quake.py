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


def test_ignores_weaker_other_city_and_old():
    es = [_entry("1", "2026-11-06T10:26:00+09:00", "2026-11-06T10:23:00+09:00", "4"),
          _entry("2", "2026-11-06T10:40:00+09:00", "2026-11-06T10:37:00+09:00", "6-", city="2320100"),
          _entry("3", "2026-11-06T07:50:00+09:00", "2026-11-06T07:45:00+09:00", "6+")]   # 3 時間より前
    assert quake.find_quake(es, "2321600", NOW) is None
    assert quake.find_quake(es, None, NOW) is None


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
