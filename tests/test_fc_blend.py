"""列を TAF・降水短時間予報で直す（fc_blend.py）"""
import datetime

import fc_blend
import taf
from utils import JST

UTC = datetime.timezone.utc


def slot(h, code="100", pop="0.0mm", wind=5, temp=20, precs=(0, 0, 0)):
    dt = datetime.datetime(2026, 10, 24, h, tzinfo=JST)
    return {"datetime": dt, "hour": f"{h:02d}", "code": code, "pop": pop, "temp_val": temp,
            "wind_val": wind, "wind": f"{wind}m", "wind_dir": 90,
            "hours": [{"t": (dt + datetime.timedelta(hours=i)).strftime("%Y-%m-%dT%H:00"), "prec": p}
                      for i, p in enumerate(precs)]}


def key(h):
    return f"2026-10-24T{h:02d}:00"


def test_taf_wind_and_weather():
    # 2406/2512 UTC = 24 日 15 時〜26 日 21 時 JST
    t = taf.parse_taf("TAF RJGG 240505Z 2406/2512 33016KT 9999 FEW030 TEMPO 2409/2412 -SHRA", datetime.datetime(2026, 10, 24, 6, tzinfo=UTC))
    out = fc_blend.blend([slot(12), slot(15, code="101"), slot(18, code="306")], taf=t)
    assert out[0]["wind_val"] == 5 and "taf" not in out[0]                 # 予報の期間の前の列はそのまま
    assert out[1]["wind_val"] == 8 and out[1]["wind_dir"] == 330          # 16kt → 8m/s
    assert out[1]["code"] == "101"                                         # 天気の指定なし → そのまま
    assert out[2]["code"] == "306"                                         # 「ときどき弱いにわか雨」で大雨を下げない


def test_taf_icons():
    s = lambda wx=(), tempo=(): {"wind_kt": None, "wind_dir": None, "wx": list(wx), "tempo_wx": list(tempo)}
    assert fc_blend.taf_icon("100", s(tempo=["-SHRA"])) == "102"           # 晴一時雨
    assert fc_blend.taf_icon("200", s(tempo=["-SN"])) == "204"             # 曇一時雪
    assert fc_blend.taf_icon("200", s(wx=["RA"])) == "302"
    assert fc_blend.taf_icon("101", s(tempo=["TSRA"])) == "350"
    assert fc_blend.taf_icon("101", s(wx=["BR"])) == "101"                 # もやは天気を変えない
    assert fc_blend.taf_icon("100", s(wx=["FG"])) == "209"
    assert fc_blend.taf_icon("306", s(wx=["-RA"])) == "306"                # 悪い方にだけ直す


def test_rain_forecast():
    hours = {key(13): 0, key(14): 3.0, key(15): 0, key(16): 0, key(17): 0, key(18): 0, key(19): 0}
    out = fc_blend.blend([slot(12, precs=(0.2, 0, 0)), slot(15, code="302", pop="2.0mm"), slot(18, pop="1.0mm", precs=(0, 0.4, 0))],
                         rain_hours=hours)
    assert out[0]["pop"] == "3.0mm" and out[0]["code"] == "300"            # 予報に雨 → 雨のアイコン
    assert out[1]["pop"] == "0.0mm" and out[1]["code"] == "200"            # 3 時間とも雨なし → 曇り
    assert out[2]["pop"] == "0.4mm" and out[2]["code"] == "100"            # 20・21 時までは予報なし → 今までの値と合わせる
    cold = fc_blend.blend([slot(12, temp=0)], rain_hours={key(13): 40.0})
    assert cold[0]["code"] == "405"
    assert fc_blend.blend([slot(21)], rain_hours=hours)[0]["pop"] == "0.0mm"   # 予報の範囲外の列はそのまま
    assert "rainfc" not in fc_blend.blend([slot(21)], rain_hours=hours)[0]


def test_thunder_kept_when_no_rain():
    hours = {key(16): 0, key(17): 0, key(18): 0}
    assert fc_blend.blend([slot(15, code="350")], rain_hours=hours)[0]["code"] == "350"
    assert fc_blend.blend([slot(15, code="202")], rain_hours=hours)[0]["code"] == "202"   # 「一時雨」は残す
