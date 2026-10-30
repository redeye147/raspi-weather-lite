"""
obs_now.py
今日の天気の「今の時間帯」の列を、空港の実際の観測（METAR）で置き換える。

予報（Open-Meteo の気象庁モデル）は計算結果なので、今の天気・気温・風が実際とずれることがある。
今の列だけは、空港で観測した値を出す（降水量は METAR に無いので予報のまま）。
観測が古い（OBS_MAX_AGE_MIN 分より前）・夜間で取得していないときは、予報のまま。
"""

import datetime

KT_TO_MS = 0.514444
OBS_MAX_AGE_MIN = 90


def icon_code_from_metar(m):
    """METAR → 気象庁の天気コード（アイコン）。周辺（VC）の現象は数えない"""
    codes = [c for c in m.get("wx_codes", []) if not c.startswith("VC")]
    has = lambda key: any(key in c for c in codes)
    heavy = lambda key: any(c.startswith("+") and key in c for c in codes)
    if has("TS"):
        return "350"                                  # 雨で雷
    if has("SN") or has("SG") or has("PL"):
        return "405" if heavy("SN") else "400"        # 大雪・雪
    if has("RA") or has("GR") or has("GS"):
        if heavy("RA"):
            return "306"                              # 大雨
        return "300" if any(c.startswith("-") and "RA" in c for c in codes) else "302"
    if has("DZ"):
        return "202"                                  # 霧雨 → 曇一時雨（予報と同じ扱い）
    if any(c in ("FG", "FZFG") for c in codes):
        return "209"                                  # 霧
    covers = {c["cover"] for c in m.get("clouds", [])}
    if "OVC" in covers or "VV" in covers:
        return "200"                                  # 曇
    if "BKN" in covers:
        return "101"                                  # 晴時々曇
    return "100"                                      # 晴（CAVOK・雲なし・FEW・SCT）


def apply_observation(hourly, cur, metar, now_utc=None, rain=None):
    """hourly の cur 列を、METAR の実況と降水ナウキャスト（rain）で置き換えた「表示用の写し」を返す（元の予報は変えない）。
    rain = {"now_mmh": 今の雨}（降水ナウキャストの結果。新しいときだけ渡す）。
    置き換えられないとき（観測なし・古い・列なし）は hourly をそのまま返す"""
    if cur is None or not (0 <= cur < len(hourly)):
        return hourly
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    out = list(hourly)
    if rain is not None:
        # 降水量は、雨雲レーダーで今降っている雨（1 時間あたり）。以前は 1 時間先までの予測のいちばん強い雨も
        # 含めていたが、実際の雨より強めに出たので今の雨だけにした（2026-10-30：雷雲の予測で 40.0 mm/h と出た）
        out[cur] = dict(out[cur], pop=f"{rain['now_mmh']:.1f}mm", radar=True)
    obs = metar.get("obs_utc") if metar else None
    if obs is None or (now_utc - obs).total_seconds() > OBS_MAX_AGE_MIN * 60:
        return out if rain is not None else hourly
    item = dict(out[cur])
    item["code"] = icon_code_from_metar(metar)
    if metar.get("temp") is not None:
        item["temp_val"] = metar["temp"]
        item["temp"] = f"{metar['temp']}℃"
    if metar.get("wind_kt") is not None:
        ms = round(metar["wind_kt"] * KT_TO_MS)
        item["wind_val"] = ms
        item["wind"] = f"{ms} m/s"
        item["wind_dir"] = metar.get("wind_dir")
        # 風向が変動（VRB）：向きが無いので、矢印の代わりに「---」（無風と同じ印）
        item["wind_variable"] = metar.get("wind_dir") is None and ms > 0
    item["observed"] = True                           # 実況で置き換えた列（画面には何も足さない）
    out[cur] = item
    return out
