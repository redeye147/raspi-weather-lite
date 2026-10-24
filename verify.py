"""
verify.py
予報の精度を確かめる：予報と、空港の実際の観測を並べて記録し、ずれを集計する。

  1. 天気を取るたびに、1 時間ごとの予報（気温・風速・天気・雨の量）を記録する（forecasts）
       cache/verify/fc_YYYYMMDD.jsonl   1 行 = 1 回の取得  {"at": 取得時刻, "hours": {"2026-10-24T10:00": {...}}}
  2. 毎時 00 分の METAR が届いたら、その時刻について「1・3・6・12・24 時間前に出していた予報」と観測を 1 行に記録する
       cache/verify/vf_YYYYMM.csv       1 行 = 1 時間
     雨の観測は METAR の天気（雨・雪・霧雨・雷雨など。周辺 VC は除く）か、雨雲レーダー（降水ナウキャスト）で 0.5mm/h 以上
  3. 診断ページで、過去 30 日の「ずれ」を見せる（summarize）

SD カードへの書き込みは 1 時間に数 KB。予報の記録は 3 日分、比べた記録は 4 か月分（月ごとのファイル）残す。
"""

import csv
import datetime
import glob
import json
import os

import obs_now
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


def _hour_key(dt):
    return dt.astimezone(JST).strftime("%Y-%m-%dT%H:00")


# ------------------------------------------------------------------ 1. 予報の記録
def record_forecast(hourly, fetched_at, base_dir=None):
    """天気を取ったときに呼ぶ。hourly の各列の "hours"（1 時間ごとの元の値）をまとめて 1 行に"""
    hours = {}
    for item in hourly or []:
        for h in item.get("hours") or []:
            if h.get("t"):
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


def _forecast_records(base_dir, obs_dt):
    """obs_dt の前の数日分の予報の記録（古い順）"""
    recs = []
    for d in range(FC_KEEP_DAYS, -1, -1):
        day = (obs_dt.astimezone(JST) - datetime.timedelta(days=d)).strftime("%Y%m%d")
        try:
            with open(os.path.join(base_dir, f"fc_{day}.jsonl"), encoding="utf-8") as f:
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
    path = os.path.join(base_dir, f"vf_{obs_jst:%Y%m}.csv")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    with open(state, "w") as f:
        f.write(obs_jst.isoformat())
    return True


def _prune(base_dir, now):
    """古い記録を消す（予報 3 日・比べた記録 4 か月）"""
    now = now.astimezone(JST)
    for p in glob.glob(os.path.join(base_dir, "fc_*.jsonl")):
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
    out.append("＋は予報が高い（強い）、−は低い（弱い）")
    return out
