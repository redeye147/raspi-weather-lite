"""週間予報の読み取り（fetch_weather）：気象庁（短期＋週間）と Open-Meteo の補完

気象庁の forecast/{県}.json は [短期予報, 週間予報] の 2 つ。週間予報の降水確率は天気と同じ timeSeries に、
気温は tempsMax / tempsMin というキーで入っている（以前はこれを読めず、Open-Meteo で補っていた）。
"""
import datetime

import pytest

import fetch_weather as fw


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _t(d, hh=0):
    return f"2026-10-{d:02d}T{hh:02d}:00:00+09:00"


# 2026-10-13 17 時発表の形（成田＝千葉県北西部 120010、気温は千葉 45212）
JMA = [
    {   # 短期予報
        "timeSeries": [
            {"timeDefines": [_t(13, 17), _t(14), _t(15)],
             "areas": [{"area": {"code": "120010"}, "weatherCodes": ["200", "101", "201"]}]},
            {"timeDefines": [_t(13, 18), _t(14, 0), _t(14, 6), _t(14, 12), _t(14, 18), _t(15, 0)],
             "areas": [{"area": {"code": "120010"}, "pops": ["10", "20", "30", "20", "10", "40"]}]},
            {"timeDefines": [_t(14, 0), _t(14, 9)],
             "areas": [{"area": {"code": "45212"}, "temps": ["21", "26"]}]},
        ]},
    {   # 週間予報（今日〜7 日分。今日の降水確率・気温は空）
        "timeSeries": [
            {"timeDefines": [_t(d) for d in range(13, 20)],
             "areas": [{"area": {"code": "120000"},
                        "weatherCodes": ["200", "101", "201", "101", "100", "201", "300"],
                        "pops": ["", "30", "55", "23", "8", "40", "70"]}]},
            {"timeDefines": [_t(d) for d in range(13, 20)],
             "areas": [{"area": {"code": "45212"},
                        "tempsMin": ["", "21", "16", "15", "14", "13", "15"],
                        "tempsMax": ["", "26", "22", "24", "21", "23", "20"]}]},
        ]},
]


@pytest.fixture
def today_1013(monkeypatch):
    class D(datetime.date):
        @classmethod
        def today(cls):
            return datetime.date(2026, 10, 13)
    monkeypatch.setattr(fw.datetime, "date", D)


def test_jma_weekly_pops_and_temps_are_read(monkeypatch, today_1013):
    """週間予報の 5 日目（10/18）まで降水確率と気温が入る（2026-10-13 の画面では 18 日が「-%」「-/-」だった）"""
    monkeypatch.setattr(fw.SESS, "get", lambda url, timeout=10: _Resp(JMA))
    _, daily = fw.fetch_weather_jma("120000", ("1221100", "120010"))
    assert [d["date"] for d in daily] == ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"]
    assert [d["pop"] for d in daily] == ["30%", "55%", "23%", "8%", "40%"]
    assert [d["temp"] for d in daily] == ["26/21", "22/16", "24/15", "21/14", "23/13"]
    assert daily[0]["code"] == "101"                      # 短期予報の天気を優先


def test_openmeteo_fills_6th_day_from_today(monkeypatch):
    """気象庁に値が無い日は Open-Meteo で補う。気象庁は明日から 5 日＝今日から 6 日目まで要るので、
    Open-Meteo は 7 日分返す（以前は今日から 5 日で切っていて、最後の日を補えなかった）。画面・キャッシュは 5 日"""
    days = [f"2026-10-{d}" for d in range(13, 20)]
    om = {"hourly": {"time": []},
          "daily": {"time": days, "weathercode": [1] * 7, "precipitation_probability_max": [10, 20, 30, 40, 50, 60, 70],
                    "temperature_2m_max": [25.2] * 7, "temperature_2m_min": [15.6] * 7}}
    monkeypatch.setattr(fw.SESS, "get", lambda url, timeout=10: _Resp(om))
    monkeypatch.setattr(fw, "CACHE_FILE", "/nonexistent-dir/x/cache.json")   # キャッシュは書かない
    _, daily = fw.fetch_weather_openmeteo(35.7, 140.4)
    assert len(daily) == 7 and daily[5]["date"] == "2026-10-18" and daily[5]["pop"] == "60%"


def test_fetcher_merges_jma_with_openmeteo(monkeypatch, today_1013):
    """気象庁に週間の値が無い場合でも、Open-Meteo の 7 日分で 5 日目まで埋まる"""
    jma_no_weekly_values = [JMA[0], {"timeSeries": [JMA[1]["timeSeries"][0] | {
        "areas": [{"area": {"code": "120000"}, "weatherCodes": ["200"] * 7, "pops": [""] * 7}]}]}]
    om_daily = [{"date": f"2026-10-{d}", "day": "", "code": "100", "pop": f"{d}%", "temp": "20/10"} for d in range(13, 20)]
    monkeypatch.setattr(fw, "fetch_weather_openmeteo", lambda lat, lon: ([], om_daily))
    monkeypatch.setattr(fw.SESS, "get", lambda url, timeout=10: _Resp(jma_no_weekly_values))
    f = fw.WeatherFetcher({"latitude": 35.7, "longitude": 140.4, "office_code": "120000",
                           "area_codes": ("1221100", "120010")}, type("A", (), {"jma": True})())
    f._run()
    _, daily = f._result
    assert len(daily) == 5 and daily[-1]["date"] == "2026-10-18"
    assert daily[-1]["pop"] == "18%" and daily[-1]["temp"] == "20/10"


# ---------------------------------------------------------------- 今日の天気：Open-Meteo の気象庁モデル
def _om(days=7, pop=None):
    return {"hourly": {"time": ["2026-10-13T06:00"], "weathercode": [1], "precipitation": [0.0],
                       "temperature_2m": [18.4], "windspeed_10m": [7.2]},
            "daily": {"time": [f"2026-10-{d}" for d in range(13, 13 + days)], "weathercode": [1] * days,
                      "precipitation_probability_max": pop or [None] * days,
                      "temperature_2m_max": [25.2] * days, "temperature_2m_min": [15.6] * days}}


def test_openmeteo_uses_jma_model(monkeypatch):
    urls = []
    monkeypatch.setattr(fw.SESS, "get", lambda url, timeout=10: (urls.append(url), _Resp(_om()))[1])
    monkeypatch.setattr(fw, "CACHE_FILE", "/nonexistent-dir/x/cache.json")
    fw.fetch_weather_openmeteo(35.7651, 140.3854)
    assert len(urls) == 1 and "&models=jma_seamless" in urls[0]


def test_openmeteo_jma_model_has_no_pop(monkeypatch):
    """気象庁モデルは降水確率を出さない（null）→「None%」ではなく「-%」。その日も捨てない"""
    monkeypatch.setattr(fw.SESS, "get", lambda url, timeout=10: _Resp(_om()))
    monkeypatch.setattr(fw, "CACHE_FILE", "/nonexistent-dir/x/cache.json")
    _, daily = fw.fetch_weather_openmeteo(35.7651, 140.3854)
    assert len(daily) == 7 and daily[0]["pop"] == "-%" and daily[0]["temp"] == "25/16"


def test_openmeteo_falls_back_when_jma_model_fails(monkeypatch, caplog):
    """気象庁モデルで取れなければ、指定なし（Open-Meteo の自動選択）で取り直す"""
    urls = []

    def get(url, timeout=10):
        urls.append(url)
        if "models=" in url:
            raise RuntimeError("400 Bad Request")
        return _Resp(_om(pop=[30] * 7))
    monkeypatch.setattr(fw.SESS, "get", get)
    monkeypatch.setattr(fw, "CACHE_FILE", "/nonexistent-dir/x/cache.json")
    import logging
    with caplog.at_level(logging.WARNING):
        _, daily = fw.fetch_weather_openmeteo(35.7651, 140.3854)
    assert len(urls) == 2 and "models=" not in urls[1]
    assert daily[0]["pop"] == "30%"
    assert "標準のモデルで取り直し" in caplog.text
