"""子機用のページ（now_page.py・設定画面の /now）"""
import datetime

import now_page
import table_cols
from utils import JST, get_target_datetimes


def _cols(now):
    hourly = [dict(datetime=t, date=t.strftime("%-m/%-d"), hour=t.strftime("%H"), code="100", pop=f"{i * 2}.0mm",
                   temp_val=20 + i, temp=f"{20 + i}℃", wind_val=3 + 3 * i, wind="3m", wind_dir=90)
              for i, t in enumerate(get_target_datetimes(now, layout="now"))]
    obs = lambda h, cur: [dict(x, pop="7.5mm", code="302") if i == cur else x for i, x in enumerate(h)]
    return table_cols.build(hourly, now, observe=obs)


def test_payload():
    now = datetime.datetime(2026, 11, 3, 20, 10, tzinfo=JST)
    thunder = {"kind": "near", "km": 8.4, "dir": "南西", "at": now}
    p = now_page.build_payload(_cols(now), now, "中部空港", "RJGG", "雷注意報（突風・ひょう）", "落雷に注意", thunder)
    assert p["now"]["label"] == "今 20:10" and p["now"]["is_now"] and p["now"]["pop"] == 7.5 and p["now"]["pop_strong"]
    assert p["now"]["icon"] == "302"
    assert len(p["ahead"]) == 4 and p["ahead"][0]["label"] == "21"          # 残り 50 分なので「〜21」は無い
    assert p["ahead"][1]["icon"] == "700"                                    # 夜の晴れは月
    assert p["warning_level"] == "advisory" and p["headline"] == "落雷に注意"
    assert p["thunder"] == {"kind": "near", "km": 8, "dir": "南西", "at": "20:10"}
    assert p["ahead"][3]["wind_color"] != "#000000"                          # 強い風は色付き
    q = now_page.build_payload(_cols(now), now, "中部空港", warning_text="警報・注意報なし")
    assert q["warning"] == "発表なし" and q["warning_level"] == "none" and q["thunder"] is None


def test_write_and_read(tmp_path):
    path = str(tmp_path / "x" / "now.json")
    now_page.write({"a": 1}, path)
    assert now_page.read(path) == {"a": 1}
    assert now_page.read(str(tmp_path / "none.json")) is None
