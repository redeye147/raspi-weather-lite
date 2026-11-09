"""予報の自動補正（試験期間）と、記録の取り込み"""
import csv
import datetime
import os

import autocorrect
import verify
from utils import JST

NOW = datetime.datetime(2026, 11, 10, 6, 30, tzinfo=JST)


def _write_rows(base, rows):
    os.makedirs(base, exist_ok=True)
    by = {}
    for r in rows:
        by.setdefault(r["obs_time"][:7].replace("-", ""), []).append(r)
    for m, rs in by.items():
        with open(os.path.join(base, f"vf_{m}.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=verify.FIELDS, extrasaction="ignore")
            w.writeheader()
            for r in rs:
                w.writerow({k: r.get(k, "") for k in verify.FIELDS})


def _rows(days=30, icao="RJAA", fc_bias=-1.0, taf_bias=+1.3, temp_bias=+1.0):
    """毎時の記録。元の予報は観測より fc_bias 弱く、TAF（半分の時間）は taf_bias 強い"""
    out = []
    t = NOW - datetime.timedelta(days=days)
    i = 0
    while t < NOW:
        obs = 4 + (i % 7)
        taf = obs + taf_bias if i % 2 == 0 else None
        fc = obs + fc_bias
        out.append({"obs_time": t.strftime("%Y-%m-%d %H:%M"), "icao": icao, "wind": obs, "temp": 15,
                    "fc3_wind": fc, "bl3_wind": taf if taf is not None else fc, "fc3_temp": 15 + temp_bias})
        t += datetime.timedelta(hours=1)
        i += 1
    return out


def test_apply_wind_keeps_strong_taf():
    p = {"taf": 0.0, "bias": 1.0}
    assert autocorrect.apply_wind(5, None, p) == 6
    assert autocorrect.apply_wind(5, 8, p) == 6                 # TAF を使わない設定
    assert autocorrect.apply_wind(5, 12, p) == 12               # 10m/s 以上の TAF は弱めない
    assert autocorrect.apply_wind(0, None, {"taf": 0, "bias": -2}) == 0


def test_compute_finds_bias_and_taf_weight(tmp_path):
    _write_rows(str(tmp_path), _rows())
    res = autocorrect.compute("RJAA", NOW, base_dir=str(tmp_path))
    w, t = res["wind"], res["temp"]
    assert res["n_train"] >= 100 and res["n_valid"] >= 24
    assert w["ok"] and w["mae_corr"] < w["mae_disp"] and w["mae_corr"] < w["mae_raw"]
    assert t["ok"] and abs(t["bias"] + 1.0) < 0.01               # 気温は 1℃ 下げる
    lines = autocorrect.summary_lines(res)
    assert "試験中" in lines[0] and any("○ 良くなる" in l for l in lines)


def test_compute_other_airport_and_too_few(tmp_path):
    _write_rows(str(tmp_path), _rows(days=3))
    res = autocorrect.compute("RJAA", NOW, base_dir=str(tmp_path))
    assert res["wind"] is None and "記録が足りない" in res["reason"]
    res = autocorrect.compute("RJTT", NOW, base_dir=str(tmp_path))        # ほかの空港の記録は使わない
    assert res["n_train"] == 0 and res["n_valid"] == 0


def test_bias_is_limited(tmp_path):
    _write_rows(str(tmp_path), _rows(fc_bias=-5.0, taf_bias=-5.0, temp_bias=+5.0))
    res = autocorrect.compute("RJAA", NOW, base_dir=str(tmp_path))
    assert abs(res["wind"]["bias"]) <= 2.0 and abs(res["temp"]["bias"]) <= 2.0


def test_save_load_history_and_due(tmp_path):
    _write_rows(str(tmp_path), _rows())
    res = autocorrect.compute("RJAA", NOW, base_dir=str(tmp_path))
    sf, hf = str(tmp_path / "ac.json"), str(tmp_path / "hist.csv")
    autocorrect.save(res, sf, hf)
    autocorrect.save(res, sf, hf)
    assert autocorrect.load(sf)["icao"] == "RJAA"
    assert len(autocorrect.history_csv(hf).strip().splitlines()) == 3        # 見出し + 2 日
    assert autocorrect.due(NOW, None) and not autocorrect.due(NOW, res)
    assert not autocorrect.due(NOW.replace(hour=5), None)
    assert autocorrect.load(str(tmp_path / "none.json")) is None


def test_import_csv_merges_without_overwriting(tmp_path):
    base = str(tmp_path / "v")
    mine = [{"obs_time": "2026-11-09 10:00", "icao": "RJTT", "wind": "3"}]
    _write_rows(base, mine)
    text, _ = verify.export_csv(base_dir=base)
    other = "﻿" + ",".join(verify.FIELDS) + "\n" + "\n".join([
        "2026-11-09 10:00,RJTT,,9" + "," * (len(verify.FIELDS) - 4),       # 同じ時刻：この Pi の分を残す
        "2026-11-09 11:00,RJTT,,5" + "," * (len(verify.FIELDS) - 4),
        "2026-11-09 11:00,RJAA,,6" + "," * (len(verify.FIELDS) - 4),
        "2025-01-01 00:00,RJTT,,6" + "," * (len(verify.FIELDS) - 4),       # 古すぎる
        "bad,RJTT,,6" + "," * (len(verify.FIELDS) - 4)])
    added, dup = verify.import_csv(other, base_dir=base, now=NOW)
    assert (added, dup) == (2, 1)
    assert verify.import_csv(other, base_dir=base, now=NOW) == (0, 3)     # 何回取り込んでも増えない
    with open(os.path.join(base, "vf_202611.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(r["obs_time"], r["icao"], r["wind"]) for r in rows] == [
        ("2026-11-09 10:00", "RJTT", "3"), ("2026-11-09 11:00", "RJAA", "6"), ("2026-11-09 11:00", "RJTT", "5")]


def test_import_rejects_other_csv(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        verify.import_csv("a,b\n1,2\n", base_dir=str(tmp_path), now=NOW)
