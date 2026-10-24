"""
fc_blend.py
今日の天気の列（Open-Meteo の気象庁モデル）を、より当たりやすい予報で直した「表示用の写し」を作る。

  1. TAF（空港の予報官の予報。taf.py）が出ている時間の列
       風速・風向 → TAF の風（ふだんの風と「ときどき」の風のうち強い方）
       天気       → TAF に雷・雨・雪・霧があれば、その天気に（悪い方にだけ直す。見落とし防止）
  2. 降水短時間予報（fetch_rainfcst.py）が出ている 6 時間先までの列
       降水量     → 降水短時間予報の 1 時間ごとの雨のいちばん多い値（予報の無い時間は今までの値）
       天気       → 雨が出ていれば雨（雪）のアイコンに。3 時間とも雨なしなら、雨・雪のアイコンを曇りに
今の時間帯の列は、このあと実況（obs_now.py）でさらに置き換える。
元の予報（hourly）は変えない（予報の精度の記録 verify.py は元の予報で取る）。
"""

import datetime

from fetch_rainfcst import hour_key

KT_TO_MS = 0.514444
RAIN_MM = 1.0              # 降水短時間予報でこれ以上なら「雨あり」としてアイコンを雨に
SNOW_TEMP = 1              # 気温がこれ以下なら雨ではなく雪のアイコン
HEAVY_MM = 30.0            # これ以上なら大雨（大雪）のアイコン

# アイコンの「悪さ」：大きいほど悪い。悪い方にだけ直す
_RANK = {"350": 9, "405": 8, "306": 8, "400": 7, "302": 7, "300": 6, "202": 5, "204": 5,
         "102": 4, "104": 4, "209": 3}
_DEFINITE_PRECIP = {"300", "302", "306", "400", "405"}   # 降水短時間予報で雨なしなら曇りに戻すアイコン


def _rank(code):
    return _RANK.get(str(code), 0)


def _worse(code, new):
    return new if _rank(new) > _rank(code) else code


def taf_icon(code, summary):
    """TAF の天気から、列のアイコンを悪い方に直す"""
    wx, tempo = summary["wx"], summary["tempo_wx"]
    has = lambda codes, key: any(key in c for c in codes if not c.startswith("VC"))
    if has(wx + tempo, "TS"):
        return _worse(code, "350")
    if any(has(wx, k) for k in ("RA", "DZ", "SN", "SG", "PL", "GR", "GS", "SH")):
        import obs_now
        return _worse(code, obs_now.icon_code_from_metar({"wx_codes": wx, "clouds": []}))
    snow = any(has(tempo, k) for k in ("SN", "SG", "PL"))
    if snow or any(has(tempo, k) for k in ("RA", "DZ", "GR", "GS", "SH")):
        sunny = str(code) in ("100", "101")
        return _worse(code, ("104" if snow else "102") if sunny else ("204" if snow else "202"))
    if any(c in ("FG", "FZFG") for c in wx):
        return _worse(code, "209")
    return code


def apply_taf(item, summary):
    item = dict(item)
    if summary["wind_kt"] is not None:
        ms = round(summary["wind_kt"] * KT_TO_MS)
        item["wind_val"] = ms
        item["wind"] = f"{ms}m"
        item["wind_dir"] = summary["wind_dir"]
        item["wind_variable"] = summary["wind_dir"] is None and ms > 0   # VRB は矢印の代わりに「---」
    item["code"] = taf_icon(item.get("code"), summary)
    item["taf"] = True
    return item


def _rain_code(mm, temp):
    snow = temp is not None and temp <= SNOW_TEMP
    if mm >= HEAVY_MM:
        return "405" if snow else "306"
    return "400" if snow else "300"


def apply_rainfc(item, hours):
    """hours = {"2026-10-24T13:00": その時刻までの 1 時間の雨(mm/h)}。列の 3 時間に 1 つも予報が無ければ None"""
    dt = item.get("datetime")
    if not isinstance(dt, datetime.datetime):
        return None
    fc, om = [], []
    for h in (1, 2, 3):                                   # 列 09 時 → 10:00・11:00・12:00 までの 1 時間
        key = hour_key(dt + datetime.timedelta(hours=h))
        if key in hours:
            fc.append(hours[key])
        else:
            t = hour_key(dt + datetime.timedelta(hours=h - 1))
            src = next((x for x in item.get("hours") or [] if x.get("t") == t), None)
            if src and src.get("prec") is not None:
                om.append(src["prec"])
    if not fc:
        return None
    item = dict(item)
    mm = max(fc + om)
    item["pop"] = f"{mm:.1f}mm"
    code = str(item.get("code"))
    if max(fc) >= RAIN_MM:
        item["code"] = _worse(code, _rain_code(max(fc), item.get("temp_val")))
    elif len(fc) == 3 and max(fc) == 0 and code in _DEFINITE_PRECIP:
        item["code"] = "200"                              # 3 時間とも雨雲なし → 雨・雪のアイコンは曇りに
    item["rainfc"] = True
    return item


def blend(hourly, taf=None, rain_hours=None):
    """TAF（taf.parse_taf の結果）と降水短時間予報（{時刻: mm/h}）で直した写し"""
    import taf as taf_mod
    out = []
    for item in hourly:
        dt = item.get("datetime")
        if taf is not None and isinstance(dt, datetime.datetime):
            s = taf_mod.slot_summary(taf, dt)
            if s is not None:
                item = apply_taf(item, s)
        if rain_hours:
            item = apply_rainfc(item, rain_hours) or item
        out.append(item)
    return out
