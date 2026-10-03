"""航空気象（METAR / TAF）の解析と1行表示の整形

電文は国際書式の例（日本の空港は視程を m で通報）。実データは段階②のログで確認する。
"""
import datetime

import pytest

import aviation as av

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 3, 12, 10, tzinfo=UTC)       # = 21:10 JST


def metar(raw):
    return av.parse_metar(raw, NOW)


# ---------------------------------------------------------------- METAR
def test_basic_metar():
    m = metar("RJGG 031200Z 33012KT 9999 FEW030 22/15 Q1013 NOSIG")
    assert m["icao"] == "RJGG"
    assert m["obs_utc"] == datetime.datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    assert (m["wind_dir"], m["wind_kt"], m["gust_kt"]) == (330, 12, None)
    assert m["vis_m"] == 10000 and m["temp"] == 22 and m["dew"] == 15 and m["qnh"] == 1013
    assert m["clouds"] == [{"cover": "FEW", "base_ft": 3000, "type": None}]
    assert m["ceiling_ft"] is None and m["category"] == "VFR"


def test_gust_variable_weather_and_ceiling():
    m = metar("METAR RJTT 031200Z 18018G30KT 150V220 3000 -SHRA BR FEW008 BKN012 OVC030 18/17 Q1005")
    assert (m["wind_dir"], m["wind_kt"], m["gust_kt"], m["wind_var"]) == (180, 18, 30, (150, 220))
    assert m["vis_m"] == 3000
    assert m["wx"] == ["弱いにわか雨", "もや"]
    assert m["ceiling_ft"] == 1200                 # 一番低い BKN/OVC
    assert m["category"] == "IFR"                  # 視程 3000m < 4800m


def test_cavok_calm_and_negative_temp():
    m = metar("RJCC 031200Z 00000KT CAVOK M02/M05 Q1021")
    assert m["cavok"] and m["vis_m"] == 10000 and m["wind_kt"] == 0
    assert (m["temp"], m["dew"]) == (-2, -5)
    assert m["category"] == "VFR"


def test_vrb_tsra_cb_and_remarks_ignored():
    m = metar("ROAH 031200Z VRB03KT 6000 +TSRA FEW015CB BKN020 27/25 Q1008 RMK 1CB015 A2977")
    assert m["wind_dir"] is None and m["wind_kt"] == 3
    assert m["wx"] == ["強い雷雨"]
    assert m["clouds"][0] == {"cover": "FEW", "base_ft": 1500, "type": "CB"}
    assert m["qnh"] == 1008                        # RMK の A2977 は読まない
    assert m["category"] == "MVFR"                 # 雲底 2000ft ≤ 3000ft


def test_low_vis_fog_is_lifr():
    m = metar("RJAA 032000Z 00000KT 0200 FG VV001 12/12 Q1015")
    assert m["vis_m"] == 200 and m["wx"] == ["霧"] and m["ceiling_ft"] == 100
    assert m["category"] == "LIFR"


def test_month_boundary():
    """電文には月が無い。基準時刻に最も近い日時にする（10/1 の基準で 30日 → 9/30）"""
    ref = datetime.datetime(2026, 10, 1, 0, 30, tzinfo=UTC)
    m = av.parse_metar("RJGG 302330Z 33005KT 9999 FEW030 20/15 Q1015", ref)
    assert m["obs_utc"] == datetime.datetime(2026, 9, 30, 23, 30, tzinfo=UTC)


def test_broken_metar_returns_none():
    assert metar("") is None
    assert metar("RJGG NIL") is None


@pytest.mark.parametrize("token, ja", [("-RA", "弱い雨"), ("+SN", "強い雪"), ("TS", "雷"), ("VCSH", "周辺でにわか"),
                                       ("FZDZ", "着氷性の霧雨"), ("HZ", "煙霧"), ("RJGG", None), ("NOSIG", None)])
def test_wx_to_japanese(token, ja):
    assert av.wx_to_japanese(token) == ja


@pytest.mark.parametrize("vis, ceil, cat", [(10000, None, "VFR"), (8000, None, "MVFR"), (10000, 3000, "MVFR"),
                                            (4700, None, "IFR"), (10000, 900, "IFR"), (1500, None, "LIFR"),
                                            (10000, 400, "LIFR"), (None, None, "VFR")])
def test_flight_category(vis, ceil, cat):
    assert av.flight_category(vis, ceil) == cat


# ---------------------------------------------------------------- TAF
TAF = ("TAF RJGG 031105Z 0312/0418 33010KT 9999 FEW030 "
       "BECMG 0315/0317 36005KT "
       "TEMPO 0313/0316 4000 -SHRA BKN010 "
       "PROB30 TEMPO 0400/0403 2000 BR "
       "FM040600 18015G25KT 8000 SCT020")


def test_parse_taf_groups():
    t = av.parse_taf(TAF, NOW)
    assert t["icao"] == "RJGG"
    assert t["valid_from"] == datetime.datetime(2026, 10, 3, 12, tzinfo=UTC)
    assert t["valid_to"] == datetime.datetime(2026, 10, 4, 18, tzinfo=UTC)
    assert t["base"]["wind_dir"] == 330 and t["base"]["vis_m"] == 10000
    kinds = [c["kind"] for c in t["changes"]]
    assert kinds == ["BECMG", "TEMPO", "PROB30 TEMPO", "FM"]
    tempo = t["changes"][1]
    assert tempo["vis_m"] == 4000 and tempo["wx"] == ["弱いにわか雨"] and tempo["ceiling_ft"] == 1000
    fm = t["changes"][3]
    assert fm["start"] == datetime.datetime(2026, 10, 4, 6, tzinfo=UTC)
    assert fm["end"] == t["valid_to"]              # FM は有効期間の終わりまで
    assert (fm["wind_kt"], fm["gust_kt"]) == (15, 25)


def test_hour_24_in_taf():
    t = av.parse_taf("TAF RJTT 031105Z 0312/0324 18010KT 9999 FEW030", NOW)
    assert t["valid_to"] == datetime.datetime(2026, 10, 4, 0, tzinfo=UTC)


def test_next_change_picks_ongoing_or_earliest():
    t = av.parse_taf(TAF, NOW)
    # 21:10 JST（12:10Z）：TEMPO 13-16Z が次（BECMG 15-17Z より早い）
    assert av.next_change(t, NOW)["kind"] == "TEMPO"
    # 14:00Z：TEMPO は継続中なのでまだ TEMPO
    assert av.next_change(t, NOW.replace(hour=14))["kind"] == "TEMPO"
    # 16:30Z：TEMPO 終了 → BECMG（継続中）
    assert av.next_change(t, NOW.replace(hour=16, minute=30))["kind"] == "BECMG"
    # 有効期間の後 → なし
    assert av.next_change(t, datetime.datetime(2026, 10, 5, 0, tzinfo=UTC)) is None


# ---------------------------------------------------------------- 1行表示
def test_format_metar_line_units_both():
    m = metar("RJTT 031200Z 18018G30KT 3000 -SHRA BKN012 18/17 Q1005")
    assert av.format_metar_line(m) == ("RJTT 21:00観測 風 180° 9m/s(18kt) 突風15m/s(30kt) 視程3km "
                                       "弱いにわか雨 雲 BKN 370m(1200ft) 18℃ [IFR]")


def test_format_metar_line_cavok_calm():
    m = metar("RJCC 031200Z 00000KT CAVOK M02/M05 Q1021")
    assert av.format_metar_line(m) == "RJCC 21:00観測 風 静穏 視程10km以上 雲1500m(5000ft)以上(CAVOK) -2℃ [VFR]"   # CAVOK は実測値なし → 保証される下限を表示


def test_format_change_line():
    t = av.parse_taf(TAF, NOW)
    line = av.format_change_line(av.next_change(t, NOW), NOW)
    assert line == "TAF 一時 22:00-翌01:00 視程4km 弱いにわか雨 雲 BKN 300m(1000ft)"


def test_format_change_line_prob_and_none():
    t = av.parse_taf(TAF, NOW)
    prob = t["changes"][2]
    assert av.format_change_line(prob, NOW).startswith("TAF 30%で一時 翌09:00-翌12:00 視程2km もや")
    assert av.format_change_line(None, NOW) == "TAF 大きな変化なし"


def test_format_line_is_one_line_and_handles_failure():
    t = av.parse_taf(TAF, NOW)
    line = av.format_line(metar("RJGG 031200Z 33012KT 9999 FEW030 22/15 Q1013"), t, NOW)
    assert "\n" not in line and line.startswith("✈ RJGG 21:00観測") and "｜ TAF 一時" in line
    assert av.format_line(None, None, NOW) == "✈ METAR 取得失敗 ｜ TAF 大きな変化なし"


def test_fetch_and_parse_with_mocked_network(monkeypatch):
    raws = {"metar": "RJGG 031200Z 33012KT 9999 FEW030 22/15 Q1013\n", "taf": TAF.replace(" BECMG", "\n  BECMG")}
    monkeypatch.setattr(av, "fetch_raw", lambda url, timeout=10: raws["metar" if "metar" in url else "taf"])
    m, t, raw_m, raw_t = av.fetch_and_parse("RJGG", NOW)
    assert m["icao"] == "RJGG" and t["changes"][0]["kind"] == "BECMG"
    assert "\n" not in raw_t


def test_fetch_failure_is_not_fatal(monkeypatch):
    def boom(url, timeout=10):
        raise OSError("network down")
    monkeypatch.setattr(av, "fetch_raw", boom)
    assert av.fetch_and_parse("RJGG", NOW) == (None, None, None, None)


# ---------------------------------------------------------------- 実データ（2026-10-03 22:09 JST に Pi で取得した成田）
REAL_NOW = datetime.datetime(2026, 10, 3, 13, 9, tzinfo=UTC)
REAL_METAR = "METAR RJAA 031300Z 02005KT CAVOK 17/12 Q1021 NOSIG"
REAL_TAF = "TAF RJAA 031105Z 0312/0418 36008KT 9999 FEW030"


def test_real_rjaa_line():
    m = av.parse_metar(REAL_METAR, REAL_NOW)
    t = av.parse_taf(REAL_TAF, REAL_NOW)
    assert m["cavok"] and m["qnh"] == 1021 and t["changes"] == []
    assert av.format_line(m, t, REAL_NOW) == (
        "✈ RJAA 22:00観測 風 020° 3m/s(5kt) 視程10km以上 雲1500m(5000ft)以上(CAVOK) 17℃ [VFR] ｜ TAF 大きな変化なし")


# ---------------------------------------------------------------- 画面の帯（観測のみ）
def test_band_parts_real_rjaa():
    m = av.parse_metar(REAL_METAR, REAL_NOW)
    assert [t for t, _ in av.band_parts(m)] == ["RJAA 22:00観測", "風 020° 3m/s(5kt)", "視程10km以上", "雲1500m(5000ft)以上(CAVOK)", "17℃"]


def test_band_parts_priorities():
    m = metar("RJTT 031200Z 18018G30KT 3000 -SHRA BR BKN012 18/17 Q1005")
    assert av.band_parts(m) == [("RJTT 21:00観測", 0), ("風 180° 9m/s(18kt) 突風15m/s(30kt)", 0), ("視程3km", 0),
                                ("弱いにわか雨", 1), ("もや", 2), ("雲 BKN 370m(1200ft)", 0), ("18℃", 3)]


def _measure(text, size):        # 1文字 = size px とみなす簡易な幅
    return len(text) * size


def test_fit_band_shrinks_then_drops_low_priority():
    parts = [("AAAA", 0), ("BB", 1), ("CC", 2), ("DD", 3)]          # 全体 13 文字
    assert av.fit_band(parts, 13 * 24, _measure) == (["AAAA", "BB", "CC", "DD"], 24)
    assert av.fit_band(parts, 13 * 20, _measure) == (["AAAA", "BB", "CC", "DD"], 20)
    # 18px でも入らない → 優先度 3 → 2 の順に省く（必ず残す 0 と、1 は残る）
    assert av.fit_band(parts, 10 * 18, _measure) == (["AAAA", "BB", "CC"], 18)
    assert av.fit_band(parts, 7 * 18, _measure) == (["AAAA", "BB"], 18)
    assert av.fit_band(parts, 1, _measure) == (["AAAA"], 18)        # 最後まで残すのは優先度 0


@pytest.mark.parametrize("age_min, stale", [(0, False), (179, False), (181, True)])
def test_is_stale(age_min, stale):
    m = metar("RJGG 031200Z 33012KT 9999 FEW030 22/15 Q1013")
    assert av.is_stale(m, m["obs_utc"] + datetime.timedelta(minutes=age_min)) is stale
    assert av.is_stale(None, NOW) is True


def test_fetch_into_keeps_last_good(monkeypatch):
    holder = {}
    monkeypatch.setattr(av, "fetch_and_parse", lambda icao, now=None: (metar(REAL_METAR.replace("031300Z", "031200Z")), None, "RAW1", None))
    av.fetch_into("RJAA", holder)
    assert holder["raw"] == "RAW1" and holder["metar"]["icao"] == "RJAA"
    monkeypatch.setattr(av, "fetch_and_parse", lambda icao, now=None: (None, None, None, None))
    av.fetch_into("RJAA", holder)                                   # 失敗しても前回の値を残す
    assert holder["raw"] == "RAW1"


@pytest.mark.parametrize("cloud_group", ["NSC", "SKC", "CLR", "NCD"])
def test_no_cloud_is_shown(cloud_group):
    """雲なし（NSC 等）は「雲なし」と表示"""
    m = metar(f"RJAA 031200Z 02005KT 9999 {cloud_group} 17/12 Q1021")
    assert m["no_cloud"] and m["clouds"] == [] and m["category"] == "VFR"
    assert [t for t, _ in av.band_parts(m)] == ["RJAA 21:00観測", "風 020° 3m/s(5kt)", "視程10km以上", "雲なし", "17℃"]


def test_missing_cloud_group_shows_nothing():
    """雲の通報そのものが無い／観測不能（///）なら、雲は表示しない（「雲なし」とは断定しない）"""
    for raw in ("RJAA 031200Z 02005KT 9999 17/12 Q1021", "RJAA 031200Z 02005KT 9999 //////// 17/12 Q1021"):
        m = metar(raw)
        assert not m["no_cloud"]
        assert not any("雲" in t for t, _ in av.band_parts(m))
