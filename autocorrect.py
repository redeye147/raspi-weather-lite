"""
autocorrect.py
予報の自動補正（2026-11-09。今は試験期間：計算して確かめるだけで、画面にはまだ使わない）。

予報の精度の記録（verify.py の vf_YYYYMM.csv。3 時間前の予報・表示した予報・空港の観測）から、空港ごとに
  風速：TAF の混ぜ方（0・25・50・75・100%）と、偏りの足し引き
  気温：偏りの足し引き
を 1 日 1 回計算する。補正が当たるかは「古い記録で決めた補正を、まだ使っていない直近 7 日に当てて」確かめる。

  学習：30 日前〜7 日前の記録で補正を決める
  確認：その補正を直近 7 日に当て、ずれ平均（MAE）を元の予報・今の表示と比べる → 良くなるなら「使える」
  本番用の値：30 日全部で決め直した補正（画面に使い始めるときはこの値）

安全の決まり（画面に使うときも同じ。apply_wind）
  - TAF の風が 10m/s 以上なら、補正した値より TAF が強いときは TAF を出す（強い風を弱く見せない）
  - 補正の大きさは ±2（m/s・℃）まで。記録が少ない（学習 100 件・確認 24 件未満）なら補正しない
  - 補正は元の予報と観測で決める（補正した値は使わない。補正が補正を呼んでずれが大きくならないように）
  - 計算に失敗しても、表示には関係しない（今は使っていない。使うときも失敗したら補正なし）

結果は cache/verify/autocorrect.json、毎日の結果は cache/verify/ac_history.csv（試験期間の見比べ用）。
"""

import csv
import datetime
import glob
import json
import logging
import os

import safe_write
import verify

JST = verify.JST
STATE_FILE = os.path.join(verify.BASE_DIR, "autocorrect.json")
HISTORY_FILE = os.path.join(verify.BASE_DIR, "ac_history.csv")
LEAD = 3                       # 3 時間前の予報で決める（件数がいちばん多い）
DAYS = 30
VALID_DAYS = 7
MIN_TRAIN = 100
MIN_VALID = 24
MAX_ADJ = 2.0
TAF_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
STRONG_TAF_MS = 10.0           # これ以上の TAF の風は弱めない（表の黄色以上）
OUTLIER_MS = 10.0              # 予報と観測が 10m/s 以上違う時間は、異常な値として計算に使わない
HIST_FIELDS = ["date", "icao", "n_train", "n_valid", "wind_taf", "wind_bias", "wind_mae_raw", "wind_mae_disp",
               "wind_mae_corr", "wind_ok", "temp_bias", "temp_mae_raw", "temp_mae_corr", "temp_ok"]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clamp(x):
    return max(-MAX_ADJ, min(MAX_ADJ, x))


def apply_wind(fc, taf, params):
    """補正した風速（m/s）。fc：元の予報・taf：TAF の風（無ければ None）・params：{"taf": 混ぜ方, "bias": 足し引き}"""
    w = params.get("taf", 1.0) if taf is not None else 0.0
    base = (1 - w) * fc + w * (taf if taf is not None else fc)
    v = max(0.0, base + params.get("bias", 0.0))
    if taf is not None and taf >= STRONG_TAF_MS:
        v = max(v, taf)                           # 強い風は TAF のまま（見落とし防止）
    return v


def load_rows(icao, now, base_dir=None, days=DAYS):
    """その空港の過去 days 日の記録（3 時間前の予報と観測がそろった行）"""
    base_dir = base_dir or verify.BASE_DIR
    since = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    rows = []
    for p in sorted(glob.glob(os.path.join(base_dir, "vf_*.csv"))):
        try:
            with open(p, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("obs_time", "") < since or (icao and r.get("icao") not in ("", icao)):
                        continue
                    fc_w, obs_w = _num(r.get(f"fc{LEAD}_wind")), _num(r.get("wind"))
                    bl_w = _num(r.get(f"bl{LEAD}_wind"))
                    rows.append({"t": r["obs_time"], "fc_w": fc_w, "obs_w": obs_w,
                                 # 表示した予報が元の予報と違う＝TAF が出ていた（同じなら TAF なし）
                                 "taf": bl_w if bl_w is not None and fc_w is not None and abs(bl_w - fc_w) > 0.05 else None,
                                 "fc_t": _num(r.get(f"fc{LEAD}_temp")), "obs_t": _num(r.get("temp"))})
        except OSError:
            continue
    return rows


def _wind_rows(rows):
    return [r for r in rows if r["fc_w"] is not None and r["obs_w"] is not None
            and abs(r["fc_w"] - r["obs_w"]) < OUTLIER_MS]


def _temp_rows(rows):
    return [r for r in rows if r["fc_t"] is not None and r["obs_t"] is not None]


def _mae(pairs):
    return sum(abs(a - b) for a, b in pairs) / len(pairs) if pairs else None


def fit_wind(rows):
    """TAF の混ぜ方と偏りを決める（ずれ平均がいちばん小さくなる組み合わせ）"""
    rows = _wind_rows(rows)
    if not rows:
        return None
    best = None
    for w in TAF_WEIGHTS:
        p0 = {"taf": w, "bias": 0.0}
        bias = _clamp(sum(r["obs_w"] - apply_wind(r["fc_w"], r["taf"], p0) for r in rows) / len(rows))
        p = {"taf": w, "bias": round(bias, 2)}
        mae = _mae([(apply_wind(r["fc_w"], r["taf"], p), r["obs_w"]) for r in rows])
        if best is None or mae < best[0] - 1e-9:
            best = (mae, p)
    return best[1]


def fit_temp(rows):
    rows = _temp_rows(rows)
    if not rows:
        return None
    return {"bias": round(_clamp(sum(r["obs_t"] - r["fc_t"] for r in rows) / len(rows)), 2)}


def evaluate(rows, wind_p, temp_p):
    """直近の記録に補正を当てたときのずれ平均。元の予報・今の表示（TAF の強い方）・補正後"""
    wr, tr = _wind_rows(rows), _temp_rows(rows)
    out = {"n_wind": len(wr), "n_temp": len(tr)}
    if wr and wind_p:
        out["wind_mae_raw"] = _mae([(r["fc_w"], r["obs_w"]) for r in wr])
        out["wind_mae_disp"] = _mae([(r["taf"] if r["taf"] is not None else r["fc_w"], r["obs_w"]) for r in wr])
        out["wind_mae_corr"] = _mae([(apply_wind(r["fc_w"], r["taf"], wind_p), r["obs_w"]) for r in wr])
    if tr and temp_p:
        out["temp_mae_raw"] = _mae([(r["fc_t"], r["obs_t"]) for r in tr])
        out["temp_mae_corr"] = _mae([(r["fc_t"] + temp_p["bias"], r["obs_t"]) for r in tr])
    return out


def compute(icao, now=None, base_dir=None):
    """補正を計算する（書き込みはしない）。戻り値は autocorrect.json の中身"""
    now = (now or datetime.datetime.now(JST)).astimezone(JST)
    rows = load_rows(icao, now, base_dir)
    cut = (now - datetime.timedelta(days=VALID_DAYS)).strftime("%Y-%m-%d %H:%M")
    train = [r for r in rows if r["t"] < cut]
    valid = [r for r in rows if r["t"] >= cut]
    res = {"computed_at": now.isoformat(), "icao": icao, "trial": True,
           "n_train": len(_wind_rows(train)), "n_valid": len(_wind_rows(valid)), "wind": None, "temp": None}
    if res["n_train"] < MIN_TRAIN or res["n_valid"] < MIN_VALID:
        res["reason"] = f"記録が足りない（学習 {res['n_train']} 件・確認 {res['n_valid']} 件。" \
                        f"学習 {MIN_TRAIN} 件・確認 {MIN_VALID} 件以上で計算）"
        return res
    ev = evaluate(valid, fit_wind(train), fit_temp(train))
    wind_all, temp_all = fit_wind(rows), fit_temp(rows)
    if wind_all and "wind_mae_corr" in ev:
        res["wind"] = {**wind_all, "mae_raw": ev["wind_mae_raw"], "mae_disp": ev["wind_mae_disp"],
                       "mae_corr": ev["wind_mae_corr"], "ok": ev["wind_mae_corr"] < ev["wind_mae_disp"]}
    if temp_all and "temp_mae_corr" in ev:
        res["temp"] = {**temp_all, "mae_raw": ev["temp_mae_raw"], "mae_corr": ev["temp_mae_corr"],
                       "ok": ev["temp_mae_corr"] < ev["temp_mae_raw"]}
    return res


def save(res, state_file=None, history_file=None):
    state_file, history_file = state_file or STATE_FILE, history_file or HISTORY_FILE
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    safe_write.write_text(state_file, json.dumps(res, ensure_ascii=False, indent=1))
    w, t = res.get("wind") or {}, res.get("temp") or {}
    r2 = lambda v: "" if v is None else round(v, 2)
    row = {"date": res["computed_at"][:10], "icao": res.get("icao") or "", "n_train": res["n_train"],
           "n_valid": res["n_valid"], "wind_taf": r2(w.get("taf")), "wind_bias": r2(w.get("bias")),
           "wind_mae_raw": r2(w.get("mae_raw")), "wind_mae_disp": r2(w.get("mae_disp")),
           "wind_mae_corr": r2(w.get("mae_corr")), "wind_ok": "" if not w else int(w["ok"]),
           "temp_bias": r2(t.get("bias")), "temp_mae_raw": r2(t.get("mae_raw")),
           "temp_mae_corr": r2(t.get("mae_corr")), "temp_ok": "" if not t else int(t["ok"])}
    new = not os.path.exists(history_file)
    with open(history_file, "a", encoding="utf-8", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=HIST_FIELDS)
        if new:
            cw.writeheader()
        cw.writerow(row)


def load(state_file=None):
    try:
        with open(state_file or STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def due(now, state):
    """今日の分を計算する時か（6 時以降に 1 日 1 回）"""
    if now.hour < 6:
        return False
    return not state or str(state.get("computed_at", ""))[:10] != now.strftime("%Y-%m-%d")


def run_daily(icao, now=None):
    """1 日 1 回、計算して保存する（裏で呼ぶ。失敗しても表示には関係しない）"""
    try:
        res = compute(icao, now)
        save(res)
        logging.info(f"自動補正（試験）を計算: {summary_lines(res)[1:] or res.get('reason')}")
    except Exception as e:
        logging.info(f"自動補正の計算に失敗: {e}")


def summary_lines(res):
    """診断ページの「予報の精度」の下に出す文"""
    if not res:
        return []
    at = str(res.get("computed_at", ""))[5:16].replace("-", "/").replace("T", " ")
    head = f"自動補正（試験中・画面にはまだ使っていない）{at} 計算・学習 {res.get('n_train', 0)} 件・確認 {res.get('n_valid', 0)} 件（直近 {VALID_DAYS} 日）"
    if res.get("reason"):
        return [head, "　" + res["reason"]]
    out = [head]
    w = res.get("wind")
    if w:
        out.append(f"　風速：TAF {int(w['taf'] * 100)}%・{w['bias']:+.1f}m/s → 直近 {VALID_DAYS} 日のずれ平均 補正 {w['mae_corr']:.2f}m/s"
                   f"（今の表示 {w['mae_disp']:.2f}・元の予報 {w['mae_raw']:.2f}）"
                   + ("　○ 良くなる" if w["ok"] else "　× 良くならない（使わない）"))
    t = res.get("temp")
    if t:
        out.append(f"　気温：{t['bias']:+.1f}℃ → ずれ平均 補正 {t['mae_corr']:.2f}℃（元の予報 {t['mae_raw']:.2f}）"
                   + ("　○ 良くなる" if t["ok"] else "　× 良くならない（使わない）"))
    return out


def history_csv(history_file=None):
    try:
        with open(history_file or HISTORY_FILE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
