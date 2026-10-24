"""予報の精度の記録と集計（verify.py）"""
import csv
import datetime
import os

import aviation
import verify

JST = datetime.timezone(datetime.timedelta(hours=9))
UTC = datetime.timezone.utc


def _hourly(at, temp, wind, wmo, prec):
    """10:00〜12:00 の 3 時間ぶんの予報（hours）を持つ 1 列"""
    return [{"hours": [{"t": f"2026-10-24T{h:02d}:00", "temp": temp, "wind": wind, "wmo": wmo, "prec": prec}
                       for h in (10, 11, 12)]}]


def metar(raw):
    return aviation.parse_metar(raw, datetime.datetime(2026, 10, 24, 1, 10, tzinfo=UTC))


def test_record_and_compare_with_leads(tmp_path):
    d = str(tmp_path)
    # 前日 10:00 に出した予報（24 時間前）と、当日 07:00 に出した予報（3 時間前）
    verify.record_forecast(_hourly(0, 15.0, 2.0, 0, 0.0), datetime.datetime(2026, 10, 23, 10, 0, tzinfo=JST), d)
    verify.record_forecast(_hourly(0, 17.5, 3.0, 61, 1.2), datetime.datetime(2026, 10, 24, 7, 0, tzinfo=JST), d)
    m = metar("RJGG 240100Z 33012KT 9999 -RA BKN020 19/15 Q1012")         # 10:00 JST・弱い雨・19℃・6.2m/s
    assert verify.record_observation(m, 3.0, d)
    assert not verify.record_observation(m, 3.0, d)                       # 同じ観測は 2 回書かない
    with open(os.path.join(d, "vf_202610.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    r = rows[0]
    assert r["obs_time"] == "2026-10-24 10:00" and r["temp"] == "19" and r["rain"] == "1" and r["code"] == "300"
    assert r["fc1_temp"] == "17.5" and r["fc3_temp"] == "17.5" and r["fc6_temp"] == "15.0"   # 6 時間より前は前日の予報
    assert r["fc24_temp"] == "15.0" and r["fc24_code"] == "100" and r["fc3_code"] == "300"
    assert r["fc12_temp"] == "15.0"


def test_half_hour_observation_is_not_recorded(tmp_path):
    m = metar("RJGG 240130Z 33012KT 9999 FEW020 19/15 Q1012")
    assert not verify.record_observation(m, None, str(tmp_path))


def test_rain_from_radar_only(tmp_path):
    d = str(tmp_path)
    m = metar("RJGG 240100Z 33012KT 9999 VCSH FEW020 19/15 Q1012")         # 周辺のにわか雨だけ
    verify.record_observation(m, 0.5, d)                                  # レーダーで 0.5mm/h
    with open(os.path.join(d, "vf_202610.csv"), encoding="utf-8") as f:
        assert list(csv.DictReader(f))[0]["rain"] == "1"


def test_summarize(tmp_path):
    d = str(tmp_path)
    for h, (fc_t, ob_t, fc_p, rained) in enumerate([(20, 19, 0.0, 0), (21, 19, 2.0, 1), (18, 19, 0.0, 1)]):
        verify.record_forecast([{"hours": [{"t": f"2026-10-24T{10 + h:02d}:00", "temp": fc_t, "wind": 3.0,
                                            "wmo": 61 if fc_p else 0, "prec": fc_p}]}],
                               datetime.datetime(2026, 10, 24, 5, 0, tzinfo=JST), d)
        wx = "-RA " if rained else ""
        verify.record_observation(metar(f"RJGG 24{1 + h:02d}00Z 33012KT 9999 {wx}FEW020 {ob_t}/15 Q1012"), None, d)
    lines = verify.summarize(d, now=datetime.datetime(2026, 10, 24, 13, 0, tzinfo=JST))
    assert lines[0].startswith("記録 3 時間分")
    three = next(l for l in lines if l.startswith("3時間前の予報"))
    assert "気温 +0.7℃（ずれ平均 1.3℃）" in three                         # (+1 +2 −1)/3・(1+2+1)/3
    assert "雨の有無の的中 67%・降った 2 時間のうち予報 1" in three
    assert verify.summarize(str(tmp_path / "none")) == []


def test_prune_old_forecasts(tmp_path):
    d = str(tmp_path)
    for day in ("20261001", "20261023"):
        open(os.path.join(d, f"fc_{day}.jsonl"), "w").close()
    verify.record_forecast(_hourly(0, 1, 1, 0, 0), datetime.datetime(2026, 10, 24, 7, 0, tzinfo=JST), d)
    names = sorted(os.listdir(d))
    assert "fc_20261001.jsonl" not in names and "fc_20261023.jsonl" in names


def test_blended_recorded_and_compared(tmp_path):
    """TAF・降水短時間予報で直した「表示した予報」も記録し、元の予報と並べて比べる"""
    import taf
    d = str(tmp_path)
    # 元の予報：10〜12 時は風 2m/s・雨なし
    verify.record_forecast(_hourly(0, 18.0, 2.0, 0, 0.0), datetime.datetime(2026, 10, 24, 6, 0, tzinfo=JST), d)
    # 6:30 に TAF（33012KT ≒ 6.2m/s）と降水短時間予報（10〜11 時に 3mm/h）が届いた
    t = taf.parse_taf("TAF RJGG 232305Z 2400/2506 33012KT 9999 FEW030", datetime.datetime(2026, 10, 23, 23, 5, tzinfo=UTC))
    assert verify.record_blended(t, {"2026-10-24T11:00": 3.0}, datetime.datetime(2026, 10, 24, 6, 30, tzinfo=JST), d)
    verify.record_observation(metar("RJGG 240100Z 33012KT 9999 -RA BKN020 19/15 Q1012"), None, d)   # 10 時：雨・6.2m/s
    with open(os.path.join(d, "vf_202610.csv"), encoding="utf-8") as f:
        r = list(csv.DictReader(f))[0]
    assert r["fc3_wind"] == "2.0" and r["bl3_wind"] == "6.2"
    assert r["fc3_prec"] == "0.0" and r["bl3_prec"] == "3.0"
    lines = verify.summarize(d, now=datetime.datetime(2026, 10, 24, 13, 0, tzinfo=JST))
    bl = next(l for l in lines if "表示した予報" in l and "1件" in l)
    assert "風速のずれ平均 0.0m/s（元の予報 4.2m/s）" in bl and "雨の有無の的中 100%（元の予報 0%）" in bl


def test_old_csv_header_upgraded(tmp_path):
    """表示した予報の項目を足す前の CSV でも、書き足して読める"""
    d = str(tmp_path)
    old = [f for f in verify.FIELDS if not f.startswith("bl")]
    with open(os.path.join(d, "vf_202610.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old)
        w.writeheader()
        w.writerow({k: "" for k in old} | {"obs_time": "2026-10-24 09:00", "temp": "18", "wind": "3", "rain": "0"})
    verify.record_observation(metar("RJGG 240100Z 33012KT 9999 FEW020 19/15 Q1012"), None, d)
    with open(os.path.join(d, "vf_202610.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["obs_time"] for r in rows] == ["2026-10-24 09:00", "2026-10-24 10:00"]
    assert rows[0]["temp"] == "18" and rows[1]["temp"] == "19" and None not in rows[1]
