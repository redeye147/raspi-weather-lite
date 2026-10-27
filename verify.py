"""
verify.py
予報の精度を確かめる：予報と、空港の実際の観測を並べて記録し、ずれを集計する。

  1. 天気を取るたびに、1 時間ごとの予報（気温・風速・天気・雨の量）を記録する（forecasts）
       cache/verify/fc_YYYYMMDD.jsonl   1 行 = 1 回の取得  {"at": 取得時刻, "hours": {"2026-10-24T10:00": {...}}}
  2. 毎時 00 分の METAR が届いたら、その時刻について「1・3・6・12・24 時間前に出していた予報」と観測を 1 行に記録する
       cache/verify/vf_YYYYMM.csv       1 行 = 1 時間
     雨の観測は METAR の天気（雨・雪・霧雨・雷雨など。周辺 VC は除く）か、雨雲レーダー（降水ナウキャスト）で 0.5mm/h 以上
  3. 診断ページで、過去 30 日の「ずれ」を見せる（summarize）

元の予報（Open-Meteo）とは別に、TAF・降水短時間予報で直した「表示した予報」も記録して比べる（record_blended）
       cache/verify/bl_YYYYMMDD.jsonl  1 行 = TAF・降水短時間予報が届いたとき  {"at": ..., "hours": {"…T10:00": {"wind": .., "prec": ..}}}
     直した値だけを持つ（TAF の期間外の風・6 時間より先の雨は無い）。無い値は元の予報と同じとみなす

SD カードへの書き込みは 1 時間に数 KB。予報の記録は 3 日分、比べた記録は 4 か月分（月ごとのファイル）残す。
"""

import csv
import datetime
import glob
import io
import json
import os

import obs_now
import safe_write
from config import CODE_MAPPING

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "verify")
JST = datetime.timezone(datetime.timedelta(hours=9))
LEADS_H = (1, 3, 6, 12, 24)
FC_KEEP_DAYS = 3
VF_KEEP_MONTHS = 4
RAIN_MM = 0.5                     # 予報・レーダーで「雨あり」とみなす 1 時間の量
_PRECIP = ("RA", "DZ", "SN", "SG", "PL", "GR", "GS", "TS", "UP")

FIELDS = ["obs_time", "icao", "temp", "wind", "code", "rain", "radar_mmh"]
for _L in LEADS_H:
    FIELDS += [f"fc{_L}_temp", f"fc{_L}_wind", f"fc{_L}_code", f"fc{_L}_prec"]
for _L in LEADS_H:
    FIELDS += [f"bl{_L}_wind", f"bl{_L}_prec"]          # 表示した予報（TAF・降水短時間予報で直した値。2026-10 追加）


def _hour_key(dt):
    return dt.astimezone(JST).strftime("%Y-%m-%dT%H:00")


# ------------------------------------------------------------------ 1. 予報の記録
def record_forecast(hourly, fetched_at, base_dir=None):
    """天気を取ったときに呼ぶ。hourly の各列の "hours"（1 時間ごとの元の値）をまとめて 1 行に"""
    hours = {}
    since = _hour_key(fetched_at)                    # 過ぎた時間（前の日の列など）は予報ではないので記録しない
    for item in hourly or []:
        for h in item.get("hours") or []:
            if h.get("t") and h["t"] >= since:
                hours[h["t"]] = {k: h.get(k) for k in ("temp", "wind", "wmo", "prec")}
    if not hours:
        return False
    base_dir = base_dir or BASE_DIR                  # 呼んだときの値（テストで差し替えられるように）
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, f"fc_{fetched_at.astimezone(JST):%Y%m%d}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": fetched_at.astimezone(JST).isoformat(), "hours": hours}, ensure_ascii=False) + "\n")
    _prune(base_dir, fetched_at)
    return True


def record_blended(taf=None, rain_hours=None, at=None, base_dir=None, ahead_h=30):
    """TAF・降水短時間予報が届いたときに呼ぶ。この先 ahead_h 時間の「直した値」を 1 行に。
    風：その時刻の TAF の風（ふだんの風と「ときどき」のうち強い方。m/s）
    雨：その時刻からの 1 時間の降水短時間予報（mm/h。rain_hours はその 1 時間の終わりの時刻で引く）"""
    import taf as taf_mod
    at = (at or datetime.datetime.now(JST)).astimezone(JST)
    start = at.replace(minute=0, second=0, microsecond=0)
    hours = {}
    for h in range(ahead_h + 1):
        t = start + datetime.timedelta(hours=h)
        v = {}
        if taf is not None:
            s = taf_mod.slot_summary(taf, t, hours=1)
            if s and s["wind_kt"] is not None:
                v["wind"] = round(s["wind_kt"] * obs_now.KT_TO_MS, 1)
        if rain_hours:
            p = rain_hours.get(_hour_key(t + datetime.timedelta(hours=1)))
            if p is not None:
                v["prec"] = p
        if v:
            hours[_hour_key(t)] = v
    if not hours:
        return False
    base_dir = base_dir or BASE_DIR
    os.makedirs(base_dir, exist_ok=True)
    with open(os.path.join(base_dir, f"bl_{at:%Y%m%d}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": at.isoformat(), "hours": hours}, ensure_ascii=False) + "\n")
    return True


def _forecast_records(base_dir, obs_dt, prefix="fc"):
    """obs_dt の前の数日分の予報の記録（古い順）"""
    recs = []
    for d in range(FC_KEEP_DAYS, -1, -1):
        day = (obs_dt.astimezone(JST) - datetime.timedelta(days=d)).strftime("%Y%m%d")
        try:
            with open(os.path.join(base_dir, f"{prefix}_{day}.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        recs.append((datetime.datetime.fromisoformat(r["at"]), r["hours"]))
                    except (ValueError, KeyError):
                        continue
        except OSError:
            continue
    recs.sort(key=lambda r: r[0])
    return recs


def forecast_for(obs_dt, lead_h, records):
    """obs_dt（毎時ちょうど）について、lead_h 時間より前に出した予報のうちいちばん新しいもの（無ければ None）"""
    key = _hour_key(obs_dt)
    limit = obs_dt - datetime.timedelta(hours=lead_h)
    for at, hours in reversed(records):
        if at <= limit and key in hours:
            return hours[key]
    return None


# ------------------------------------------------------------------ 2. 観測と並べて記録
def is_raining(metar):
    return any(not c.startswith("VC") and any(p in c for p in _PRECIP) for c in metar.get("wx_codes", []))


def record_observation(metar, radar_mmh=None, base_dir=None):
    """毎時 00 分の METAR が届いたら呼ぶ。同じ観測は 2 回書かない。書いたら True"""
    obs = metar.get("obs_utc") if metar else None
    if obs is None or obs.minute != 0:                 # 30 分の観測は使わない（予報は 1 時間ごと）
        return False
    obs_jst = obs.astimezone(JST)
    base_dir = base_dir or BASE_DIR
    os.makedirs(base_dir, exist_ok=True)
    state = os.path.join(base_dir, "last_obs")
    try:
        if open(state).read().strip() == obs_jst.isoformat():
            return False
    except OSError:
        pass
    records = _forecast_records(base_dir, obs_jst)
    blended = _forecast_records(base_dir, obs_jst, "bl")
    rain = is_raining(metar) or (radar_mmh is not None and radar_mmh >= RAIN_MM)
    wind = round(metar["wind_kt"] * obs_now.KT_TO_MS, 1) if metar.get("wind_kt") is not None else ""
    row = {"obs_time": obs_jst.strftime("%Y-%m-%d %H:%M"), "icao": metar.get("icao", ""),
           "temp": metar.get("temp") if metar.get("temp") is not None else "", "wind": wind,
           "code": obs_now.icon_code_from_metar(metar), "rain": int(rain),
           "radar_mmh": "" if radar_mmh is None else radar_mmh}
    for L in LEADS_H:
        fc = forecast_for(obs_jst, L, records) or {}
        row[f"fc{L}_temp"] = "" if fc.get("temp") is None else fc["temp"]
        row[f"fc{L}_wind"] = "" if fc.get("wind") is None else fc["wind"]
        row[f"fc{L}_code"] = "" if fc.get("wmo") is None else CODE_MAPPING.get(fc["wmo"], "999")
        row[f"fc{L}_prec"] = "" if fc.get("prec") is None else fc["prec"]
        # 表示した予報：直した値があればそれ、無ければ元の予報（元の予報も無ければ空）
        bl = forecast_for(obs_jst, L, blended) or {}
        for k in ("wind", "prec"):
            v = bl.get(k, fc.get(k))
            row[f"bl{L}_{k}"] = "" if v is None else v
    path = os.path.join(base_dir, f"vf_{obs_jst:%Y%m}.csv")
    _upgrade_header(path)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    safe_write.write_text(state, obs_jst.isoformat())
    return True


def _upgrade_header(path):
    """項目が増える前の CSV なら、今の項目で書き直す（足りない項目は空）"""
    try:
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            f.seek(0)
            header = f.readline().strip().split(",")
    except OSError:
        return
    if header == FIELDS:
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) or "" for k in FIELDS})
    safe_write.write_text(path, buf.getvalue())                # 書き直しの途中で電源が切れても記録が消えないように


def _prune(base_dir, now):
    """古い記録を消す（予報 3 日・比べた記録 4 か月）"""
    now = now.astimezone(JST)
    for p in glob.glob(os.path.join(base_dir, "fc_*.jsonl")) + glob.glob(os.path.join(base_dir, "bl_*.jsonl")):
        try:
            d = datetime.datetime.strptime(os.path.basename(p)[3:11], "%Y%m%d").replace(tzinfo=JST)
            if now - d > datetime.timedelta(days=FC_KEEP_DAYS + 1):
                os.remove(p)
        except (ValueError, OSError):
            pass
    months = sorted(glob.glob(os.path.join(base_dir, "vf_*.csv")))
    for p in months[:-VF_KEEP_MONTHS]:
        try:
            os.remove(p)
        except OSError:
            pass


# ------------------------------------------------------------------ 3. 集計（診断ページ）
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _wind_rain(rows, prefix, L):
    """(風速の [(予報, 観測)], 雨の [(予報で雨, 観測で雨)])"""
    w = [(_num(r.get(f"{prefix}{L}_wind")), _num(r["wind"])) for r in rows]
    w = [(f, o) for f, o in w if f is not None and o is not None]
    rr = [(_num(r.get(f"{prefix}{L}_prec")), r["rain"] == "1") for r in rows]
    rr = [(f >= RAIN_MM, o) for f, o in rr if f is not None]
    return w, rr


def _hit(rr):
    return sum(1 for f, o in rr if f == o) / len(rr) * 100


def _blended_line(rows, L):
    """表示した予報と元の予報を、両方の値と観測がそろった同じ時間どうしで比べた 1 行（無ければ None）。
    以前は表示した予報と元の予報で比べる時間の数が違っていた（2026-10-27：24 時間前で 35 件と 12 件）"""
    rows = [r for r in rows if r.get(f"bl{L}_wind", "") != "" or r.get(f"bl{L}_prec", "") != ""]
    w = [(_num(r.get(f"bl{L}_wind")), _num(r.get(f"fc{L}_wind")), _num(r["wind"])) for r in rows]
    w = [x for x in w if None not in x]
    rr = [(_num(r.get(f"bl{L}_prec")), _num(r.get(f"fc{L}_prec")), r["rain"] == "1") for r in rows]
    rr = [(b >= RAIN_MM, f >= RAIN_MM, o) for b, f, o in rr if b is not None and f is not None]
    parts = []
    if w:
        n = len(w)
        parts.append(f"風速 {sum(b - o for b, f, o in w) / n:+.1f}m/s（ずれ平均 {sum(abs(b - o) for b, f, o in w) / n:.1f}m/s、"
                     f"元の予報 {sum(f - o for b, f, o in w) / n:+.1f}・{sum(abs(f - o) for b, f, o in w) / n:.1f}m/s）{n}件")
    if rr:
        n = len(rr)
        parts.append(f"雨の有無の的中 {_hit([(b, o) for b, f, o in rr]):.0f}%"
                     f"（元の予報 {_hit([(f, o) for b, f, o in rr]):.0f}%）{n}件")
    if not parts:
        return None
    return "　└ 表示した予報（TAF・降水短時間予報で直した値。同じ時間どうし）：" + "・".join(parts)


def summarize(base_dir=None, now=None, days=30, leads=(3, 24)):
    """過去 days 日の「予報のずれ」を、画面に出せる文の並びで返す（記録が無ければ空）"""
    base_dir = base_dir or BASE_DIR
    now = (now or datetime.datetime.now(JST)).astimezone(JST)
    since = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    rows = []
    for p in sorted(glob.glob(os.path.join(base_dir, "vf_*.csv"))):
        try:
            with open(p, encoding="utf-8") as f:
                rows += [r for r in csv.DictReader(f) if r.get("obs_time", "") >= since]
        except OSError:
            continue
    if not rows:
        return []
    out = [f"記録 {len(rows)} 時間分（過去 {days} 日・毎時 00 分の観測）"]
    for L in leads:
        t = [(_num(r[f"fc{L}_temp"]), _num(r["temp"])) for r in rows]
        t = [(f, o) for f, o in t if f is not None and o is not None]
        w = [(_num(r[f"fc{L}_wind"]), _num(r["wind"])) for r in rows]
        w = [(f, o) for f, o in w if f is not None and o is not None]
        rr = [(_num(r[f"fc{L}_prec"]), r["rain"] == "1") for r in rows]
        rr = [(f >= RAIN_MM, o) for f, o in rr if f is not None]
        if not (t or w or rr):
            continue
        parts = []
        if t:
            bias = sum(f - o for f, o in t) / len(t)
            mae = sum(abs(f - o) for f, o in t) / len(t)
            parts.append(f"気温 {bias:+.1f}℃（ずれ平均 {mae:.1f}℃）")
        if w:
            bias = sum(f - o for f, o in w) / len(w)
            mae = sum(abs(f - o) for f, o in w) / len(w)
            parts.append(f"風速 {bias:+.1f}m/s（ずれ平均 {mae:.1f}m/s）")
        if rr:
            hit = sum(1 for f, o in rr if f == o) / len(rr)
            rained = [f for f, o in rr if o]
            caught = f"・降った {len(rained)} 時間のうち予報 {sum(rained)}" if rained else ""
            parts.append(f"雨の有無の的中 {hit * 100:.0f}%{caught}")
        n = max(len(t), len(w), len(rr))
        out.append(f"{L}時間前の予報（{n}件）：" + "・".join(parts))
        bl = _blended_line(rows, L)
        if bl:
            out.append(bl)
    out.append("＋は予報が高い（強い）、−は低い（弱い）")
    return out
