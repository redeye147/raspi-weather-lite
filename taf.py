"""
taf.py
空港の飛行場予報（TAF）の取得・解析。

TAF は気象庁の予報官が空港ごとに出す 24〜30 時間先までの予報（風・視程・天気・雲）。
数値予報に予報官の判断が加わるので、空港の風は数値予報（Open-Meteo）より当たりやすい。
今日の天気の列の風と、雨・雷などの天気に使う（fc_blend.py）。

- 取得元: NOAA Aviation Weather Center（METAR と同じ。format=raw の生電文）
- 解析は電文を直接読む。読めない部分は飛ばす
  本文（最初の状態）・FM（その時刻から全部入れ替わる）・BECMG（期間のうちに変わる）・
  TEMPO / PROB30 / PROB40（期間中ときどき）
- 表示は参考情報（運航判断には公式の航空気象情報を使うこと）
"""

import datetime
import logging
import re
import threading
import time

import aviation

UTC = datetime.timezone.utc
TAF_URL = "https://aviationweather.gov/api/data/taf?ids={icao}&format=raw"
FETCH_INTERVAL_MIN = 30          # 定時の発表は 6 時間ごと（修正報もあるので 30 分ごとに見る）

_PERIOD_RE = re.compile(r"^(\d{2})(\d{2})/(\d{2})(\d{2})$")
_FM_RE = re.compile(r"^FM(\d{2})(\d{2})(\d{2})$")
_PROB_RE = re.compile(r"^PROB(30|40)$")


def _period(tok, ref):
    m = _PERIOD_RE.match(tok)
    if not m:
        return None
    d1, h1, d2, h2 = map(int, m.groups())
    return aviation._utc_from_dh(d1, h1, 0, ref), aviation._utc_from_dh(d2, h2, 0, ref)


def _elements(tokens):
    """群の中身 → {"wind_dir", "wind_kt", "wx"}。書かれていない要素は入れない（前の状態を引き継ぐ）"""
    e = aviation._parse_elements(tokens)
    out = {}
    if e["wind_kt"] is not None:
        out["wind_dir"], out["wind_kt"] = e["wind_dir"], e["wind_kt"]
    if e["wx_codes"]:
        out["wx"] = list(e["wx_codes"])
    elif e["nsw"] or e["cavok"]:
        out["wx"] = []                           # NSW（天気の終わり）・CAVOK（重要な天気なし）
    return out


def parse_taf(raw, ref_utc):
    """生の TAF → {"icao", "issued", "start", "end", "base": 最初の状態, "groups": [...]}。読めなければ None
    groups の各要素 {"kind": "FM"|"BECMG"|"TEMPO", "start", "end", "el": 要素}"""
    tokens = raw.replace("=", " ").split()
    while tokens and tokens[0] in ("TAF", "AMD", "COR"):
        tokens.pop(0)
    if len(tokens) < 3:
        return None
    icao = tokens.pop(0)
    issued = ref_utc
    if re.fullmatch(r"\d{6}Z", tokens[0]):
        t = tokens.pop(0)
        issued = aviation._utc_from_dh(int(t[0:2]), int(t[2:4]), int(t[4:6]), ref_utc)
    period = _period(tokens[0], issued) if tokens else None
    if period is None:
        return None
    tokens.pop(0)
    if tokens and tokens[0] in ("NIL", "CNL"):
        return None

    # 変化群ごとに分ける
    chunks, cur = [], {"kind": "BASE", "start": period[0], "end": period[1], "tokens": []}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "RMK":
            break
        m = _FM_RE.match(t)
        if m or t in ("BECMG", "TEMPO") or _PROB_RE.match(t):
            chunks.append(cur)
            if m:
                start = aviation._utc_from_dh(int(m.group(1)), int(m.group(2)), int(m.group(3)), issued)
                cur = {"kind": "FM", "start": start, "end": period[1], "tokens": []}
                i += 1
                continue
            kind = "BECMG" if t == "BECMG" else "TEMPO"
            i += 1
            if _PROB_RE.match(t) and i < len(tokens) and tokens[i] == "TEMPO":   # PROB30 TEMPO
                i += 1
            p = _period(tokens[i], issued) if i < len(tokens) else None
            if p is None:                        # 期間が読めない群は捨てる
                cur = {"kind": "SKIP", "start": None, "end": None, "tokens": []}
                continue
            cur = {"kind": kind, "start": p[0], "end": p[1], "tokens": []}
            i += 1
            continue
        cur["tokens"].append(t)
        i += 1
    chunks.append(cur)
    base = _elements(chunks[0]["tokens"])
    groups = [{"kind": c["kind"], "start": c["start"], "end": c["end"], "el": _elements(c["tokens"])}
              for c in chunks[1:] if c["kind"] != "SKIP"]
    return {"icao": icao, "issued": issued, "start": period[0], "end": period[1], "base": base, "groups": groups}


def conditions_at(taf, t):
    """時刻 t の (ふだんの状態, [ときどき・移り変わり中の状態]) を返す。予報の期間外なら None"""
    if not (taf["start"] <= t < taf["end"]):
        return None
    state = dict(taf["base"])
    alts = []
    for g in taf["groups"]:
        if g["kind"] == "FM":
            if t >= g["start"]:
                state = dict(g["el"])
                alts = []                       # FM の前の「ときどき」は、FM 以降には持ち越さない
        elif g["kind"] == "BECMG":
            if t >= g["end"]:
                state.update(g["el"])
            elif t >= g["start"]:
                alts.append({**state, **g["el"]})   # 移り変わり中は、前の状態と新しい状態のどちらもありうる
        elif g["start"] <= t < g["end"]:
            alts.append({**state, **g["el"]})
    return state, alts


def slot_summary(taf, start, hours=3):
    """start から hours 時間（列 1 つ分）の予報のまとめ。全部の時間が予報の期間に入っていなければ None
    {"wind_kt": いちばん強い風, "wind_dir": その風向（変動なら None）, "wx": ふだんの天気, "tempo_wx": ときどきの天気}"""
    if taf is None:
        return None
    start = start.astimezone(UTC)
    best = None
    wx, tempo_wx = [], []
    for h in range(hours):
        c = conditions_at(taf, start + datetime.timedelta(hours=h))
        if c is None:
            return None
        state, alts = c
        for s in [state] + alts:
            if s.get("wind_kt") is not None and (best is None or s["wind_kt"] > best["wind_kt"]):
                best = s
        wx += [w for w in state.get("wx", []) if w not in wx]
        tempo_wx += [w for a in alts for w in a.get("wx", []) if w not in tempo_wx and w not in wx]
    return {"wind_kt": best["wind_kt"] if best else None, "wind_dir": best.get("wind_dir") if best else None,
            "wx": wx, "tempo_wx": [w for w in tempo_wx if w not in wx]}


# ------------------------------------------------------------------ 取得
def fetch_and_parse(icao, now_utc=None):
    """(taf, raw)。失敗したら例外"""
    now_utc = now_utc or datetime.datetime.now(UTC)
    text = aviation.fetch_raw(TAF_URL.format(icao=icao))
    raw = " ".join(line.strip() for line in text.splitlines() if line.strip())
    taf = parse_taf(raw, now_utc)
    if taf is None:
        raise ValueError(f"TAF を読めない: {raw[:60]}")
    return taf, raw


def is_valid(taf, now_utc):
    return bool(taf and taf["start"] - datetime.timedelta(hours=1) <= now_utc < taf["end"])


def start_fetch_in_background(icao, holder):
    from netretry import FailureLog
    log = holder.setdefault("_failures", FailureLog(f"TAF ({icao}) "))

    def run():
        try:
            taf, raw = fetch_and_parse(icao)
            log.ok()
            logging.info(f"[taf] {raw}")
            holder["result"] = {"status": "ok", "taf": taf, "raw": raw, "fetched_at": time.time()}
        except Exception as e:
            log.failed(e)
            holder["result"] = {"status": "error", "error": str(e)}
    holder.pop("result", None)
    threading.Thread(target=run, daemon=True).start()
