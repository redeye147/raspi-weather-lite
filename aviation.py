"""
aviation.py
空港の航空気象（METAR：定時観測、TAF：飛行場予報）の取得・解析・1行表示用の整形。

- 取得元: NOAA Aviation Weather Center（aviationweather.gov、無料・登録不要）の生電文（format=raw）
- 解析は国際書式の電文を直接読む（取得元の JSON 項目名の変更に影響されない）
- 解析・整形は画面・通信に触れない関数で、tests/test_aviation.py で検証する
- 表示は参考情報（運航判断には公式の航空気象情報を使うこと）
"""

import datetime
import logging
import re
import threading
import time

JST = datetime.timezone(datetime.timedelta(hours=9))
UTC = datetime.timezone.utc

METAR_URL = "https://aviationweather.gov/api/data/metar?ids={icao}&format=raw"
TAF_URL = "https://aviationweather.gov/api/data/taf?ids={icao}&format=raw"
FETCH_INTERVAL_S = 30 * 60

KT_TO_MS = 0.514444
FT_TO_M = 0.3048

# ------------------------------------------------------------------ 天気現象（日本語）
_WX_INTENSITY = {"-": "弱い", "+": "強い", "VC": "周辺で"}
_WX_DESC = {"MI": "浅い", "PR": "部分的な", "BC": "散在する", "DR": "低い地吹雪の", "BL": "高い地吹雪の",
            "SH": "にわか", "TS": "雷", "FZ": "着氷性の"}
_WX_PHEN = {"DZ": "霧雨", "RA": "雨", "SN": "雪", "SG": "霧雪", "IC": "細氷", "PL": "凍雨", "GR": "ひょう",
            "GS": "あられ", "UP": "不明な降水", "BR": "もや", "FG": "霧", "FU": "煙", "VA": "火山灰",
            "DU": "ちり", "SA": "砂", "HZ": "煙霧", "PO": "じん旋風", "SQ": "スコール", "FC": "竜巻",
            "SS": "砂じん嵐", "DS": "砂じん嵐"}
_WX_RE = re.compile(r"^(\+|-|VC)?(MI|PR|BC|DR|BL|SH|TS|FZ)?((?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PO|SQ|FC|SS|DS)*)$")

_WIND_RE = re.compile(r"^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)$")
_WIND_VAR_RE = re.compile(r"^(\d{3})V(\d{3})$")
_CLOUD_RE = re.compile(r"^(FEW|SCT|BKN|OVC|VV)(\d{3}|///)(CB|TCU)?$")
_TEMP_RE = re.compile(r"^(M?\d{2})/(M?\d{2})?$")


def wx_to_japanese(token: str):
    """'-SHRA' → '弱いにわか雨'。天気現象でなければ None"""
    m = _WX_RE.match(token)
    if not m or not (m.group(2) or m.group(3)):
        return None
    inten, desc, phen = m.group(1), m.group(2), m.group(3)
    phens = "".join(_WX_PHEN[phen[i:i + 2]] for i in range(0, len(phen), 2))
    return (_WX_INTENSITY.get(inten, "") + _WX_DESC.get(desc, "") + phens) or None


def _parse_elements(tokens):
    """風・視程・天気・雲・気温・気圧を読み取る（METAR 本文・TAF の各グループ共通）"""
    out = {"wind_dir": None, "wind_kt": None, "gust_kt": None, "wind_var": None, "vis_m": None,
           "cavok": False, "nsw": False, "wx": [], "clouds": [], "no_cloud": False,
           "temp": None, "dew": None, "qnh": None}
    for t in tokens:
        if m := _WIND_RE.match(t):
            spd = int(m.group(2)); gst = int(m.group(3)) if m.group(3) else None
            if m.group(4) == "MPS":   # m/s 表記の国もある → kt に換算して統一
                spd = round(spd / KT_TO_MS); gst = round(gst / KT_TO_MS) if gst else None
            out["wind_dir"] = None if m.group(1) == "VRB" else int(m.group(1))
            out["wind_kt"], out["gust_kt"] = spd, gst
        elif m := _WIND_VAR_RE.match(t):
            out["wind_var"] = (int(m.group(1)), int(m.group(2)))
        elif t == "CAVOK":
            out["cavok"] = True; out["vis_m"] = 10000
        elif re.fullmatch(r"\d{4}", t):
            out["vis_m"] = 10000 if t == "9999" else int(t)
        elif t == "NSW":
            out["nsw"] = True
        elif t in ("NSC", "SKC", "CLR", "NCD"):   # 雲なし（電文で明示されたとき）
            out["clouds"] = []; out["no_cloud"] = True
        elif m := _CLOUD_RE.match(t):
            if m.group(2) != "///":
                out["clouds"].append({"cover": m.group(1), "base_ft": int(m.group(2)) * 100, "type": m.group(3)})
        elif m := _TEMP_RE.match(t):
            conv = lambda s: -int(s[1:]) if s.startswith("M") else int(s)
            out["temp"] = conv(m.group(1)); out["dew"] = conv(m.group(2)) if m.group(2) else None
        elif re.fullmatch(r"Q\d{4}", t):
            out["qnh"] = int(t[1:])
        elif re.fullmatch(r"A\d{4}", t):
            out["qnh"] = round(int(t[1:]) / 100 * 33.8639)
        else:
            jp = wx_to_japanese(t)
            if jp:
                out["wx"].append(jp)
    return out


def _utc_from_dh(day: int, hour: int, minute: int, ref_utc: datetime.datetime) -> datetime.datetime:
    """電文の「日・時・分」（月が書かれていない）を、基準時刻に最も近い UTC の日時にする"""
    extra = datetime.timedelta(0)
    if hour == 24:                          # TAF の「24時」は翌日 0 時
        hour, extra = 0, datetime.timedelta(days=1)
    best = None
    for months in (-1, 0, 1):
        y, mth = ref_utc.year, ref_utc.month + months
        if mth < 1: y, mth = y - 1, 12
        if mth > 12: y, mth = y + 1, 1
        try:
            cand = datetime.datetime(y, mth, day, hour, minute, tzinfo=UTC) + extra
        except ValueError:
            continue
        if best is None or abs(cand - ref_utc) < abs(best - ref_utc):
            best = cand
    return best


def ceiling_ft(clouds):
    """雲底（BKN・OVC・VV のうち一番低い高さ、ft）。無ければ None"""
    bases = [c["base_ft"] for c in clouds if c["cover"] in ("BKN", "OVC", "VV")]
    return min(bases) if bases else None


def flight_category(vis_m, ceil_ft) -> str:
    """飛行条件：LIFR / IFR / MVFR / VFR（米国式の区分を m に換算。値が無ければ良好とみなす）"""
    vis = 99999 if vis_m is None else vis_m
    ceil = 99999 if ceil_ft is None else ceil_ft
    if ceil < 500 or vis < 1600:
        return "LIFR"
    if ceil < 1000 or vis < 4800:
        return "IFR"
    if ceil <= 3000 or vis <= 8000:
        return "MVFR"
    return "VFR"


def parse_metar(raw: str, ref_utc: datetime.datetime):
    """生の METAR を解析。読めなければ None"""
    tokens = raw.split()
    while tokens and tokens[0] in ("METAR", "SPECI"):
        tokens.pop(0)
    if len(tokens) < 2 or not re.fullmatch(r"\d{6}Z", tokens[1]):
        return None
    icao, t = tokens[0], tokens[1]
    obs = _utc_from_dh(int(t[0:2]), int(t[2:4]), int(t[4:6]), ref_utc)
    body = []
    for tok in tokens[2:]:
        if tok in ("RMK", "NOSIG", "TEMPO", "BECMG"):   # 以降は備考・着陸予報なので本文に含めない
            break
        if tok in ("AUTO", "COR"):
            continue
        body.append(tok)
    out = {"icao": icao, "obs_utc": obs, "raw": raw.strip()}
    out.update(_parse_elements(body))
    out["ceiling_ft"] = ceiling_ft(out["clouds"])
    out["category"] = flight_category(out["vis_m"], out["ceiling_ft"])
    return out


_GROUP_START_RE = re.compile(r"^(FM\d{6}|BECMG|TEMPO|PROB\d{2})$")
_PERIOD_RE = re.compile(r"^(\d{2})(\d{2})/(\d{2})(\d{2})$")


def parse_taf(raw: str, ref_utc: datetime.datetime):
    """生の TAF を解析。{'icao','valid_from','valid_to','base','changes':[...]}。読めなければ None"""
    tokens = raw.split()
    while tokens and tokens[0] in ("TAF", "AMD", "COR"):
        tokens.pop(0)
    if len(tokens) < 3:
        return None
    icao = tokens[0]
    i = 1
    if re.fullmatch(r"\d{6}Z", tokens[i]):
        i += 1
    m = _PERIOD_RE.match(tokens[i]) if i < len(tokens) else None
    if not m:
        return None
    v_from = _utc_from_dh(int(m.group(1)), int(m.group(2)), 0, ref_utc)
    v_to = _utc_from_dh(int(m.group(3)), int(m.group(4)), 0, ref_utc)
    tokens = [t for t in tokens[i + 1:] if t != "RMK"]

    # グループに分割
    groups, cur = [], {"kind": "BASE", "tokens": []}
    j = 0
    while j < len(tokens):
        t = tokens[j]
        if _GROUP_START_RE.match(t):
            groups.append(cur)
            kind = t
            if t.startswith("PROB") and j + 1 < len(tokens) and tokens[j + 1] == "TEMPO":
                kind = t + " TEMPO"; j += 1
            cur = {"kind": kind, "tokens": []}
        else:
            cur["tokens"].append(t)
        j += 1
    groups.append(cur)

    base = None
    changes = []
    for g in groups:
        toks = g["tokens"]
        start = end = None
        if g["kind"].startswith("FM"):
            s = g["kind"][2:]
            start = _utc_from_dh(int(s[0:2]), int(s[2:4]), int(s[4:6]), ref_utc)
            g["kind"] = "FM"
        elif toks and (pm := _PERIOD_RE.match(toks[0])):
            start = _utc_from_dh(int(pm.group(1)), int(pm.group(2)), 0, ref_utc)
            end = _utc_from_dh(int(pm.group(3)), int(pm.group(4)), 0, ref_utc)
            toks = toks[1:]
        el = _parse_elements(toks)
        el["ceiling_ft"] = ceiling_ft(el["clouds"])
        entry = {"kind": g["kind"], "start": start, "end": end, **el}
        if g["kind"] == "BASE":
            base = entry
        else:
            changes.append(entry)
    # FM は次の FM（または有効期間の終わり）まで
    fms = [c for c in changes if c["kind"] == "FM"]
    for a, b in zip(fms, fms[1:] + [None]):
        a["end"] = b["start"] if b else v_to
    return {"icao": icao, "valid_from": v_from, "valid_to": v_to, "base": base, "changes": changes}


def next_change(taf, now_utc: datetime.datetime):
    """「これからの変化」：今も続いている、またはこれから始まる変化のうち、一番早いもの"""
    if not taf:
        return None
    upcoming = [c for c in taf["changes"] if c["start"] and c["end"] and c["end"] > now_utc]
    return min(upcoming, key=lambda c: c["start"]) if upcoming else None


# ------------------------------------------------------------------ 1行表示用の整形
def _wind_text(d) -> str:
    if d["wind_kt"] is None:
        return ""
    if d["wind_kt"] == 0:
        return "風 静穏"
    ms = round(d["wind_kt"] * KT_TO_MS)
    dirs = "変動" if d["wind_dir"] is None else f"{d['wind_dir']:03d}°"
    s = f"風 {dirs} {ms}m/s({d['wind_kt']}kt)"
    if d["gust_kt"]:
        s += f" 突風{round(d['gust_kt'] * KT_TO_MS)}m/s({d['gust_kt']}kt)"
    return s


def _vis_text(d) -> str:
    if d["cavok"]:
        return "視程10km以上"               # CAVOK は実測値を通報しない。保証される下限を示す
    if d["vis_m"] is None:
        return ""
    if d["vis_m"] >= 10000:
        return "視程10km以上"
    return f"視程{d['vis_m'] / 1000:g}km" if d["vis_m"] >= 1000 else f"視程{d['vis_m']}m"


def _cloud_text(d) -> str:
    if d["cavok"]:
        # CAVOK：1500m(5000ft) 未満（または最低安全高度のどちらか高い方）に雲なし・重要な天気なし。
        # 実際の雲の高さは通報されないので「以上」で保証される下限を示す
        return "雲1500m(5000ft)以上(CAVOK)"
    if not d["clouds"]:
        return "雲なし" if d.get("no_cloud") else ""   # 雲の通報自体が無いときは何も出さない
    c = next((c for c in d["clouds"] if c["cover"] in ("BKN", "OVC", "VV")), d["clouds"][0])
    m = round(c["base_ft"] * FT_TO_M / 10) * 10
    return f"雲 {c['cover']} {m}m({c['base_ft']}ft)" + (f" {c['type']}" if c["type"] else "")


def format_metar_line(metar) -> str:
    """例: 'RJGG 21:00観測 風 330° 6m/s(12kt) 視程10km以上 雲 FEW 910m(3000ft) 22℃ [VFR]'"""
    if not metar:
        return "METAR 取得失敗"
    parts = [f"{metar['icao']} {metar['obs_utc'].astimezone(JST):%H:%M}観測", _wind_text(metar),
             _vis_text(metar), " ".join(metar["wx"]), _cloud_text(metar),
             f"{metar['temp']}℃" if metar["temp"] is not None else "", f"[{metar['category']}]"]
    return " ".join(p for p in parts if p)


_KIND_JA = {"TEMPO": "一時", "BECMG": "次第に", "FM": "以降"}


def format_change_line(change, now_utc: datetime.datetime) -> str:
    """例: 'TAF 一時 22:00-02:00 視程4km 弱いにわか雨 雲 BKN 300m(1000ft)'"""
    if not change:
        return "TAF 大きな変化なし"
    kind = change["kind"]
    if kind.startswith("PROB"):
        p = kind[4:6]
        label = f"{p}%で" + ("一時" if kind.endswith("TEMPO") else "")
    else:
        label = _KIND_JA.get(kind, kind)
    s_jst, e_jst = change["start"].astimezone(JST), change["end"].astimezone(JST)
    today = now_utc.astimezone(JST).date()
    fmt = lambda t: ("翌" if t.date() > today else "") + f"{t:%H:%M}"
    parts = ["TAF", label, f"{fmt(s_jst)}-{fmt(e_jst)}", _wind_text(change), _vis_text(change),
             " ".join(change["wx"]), "天気回復" if change["nsw"] else "", _cloud_text(change)]
    return " ".join(p for p in parts if p)


def format_line(metar, taf, now_utc: datetime.datetime) -> str:
    """ヘッダー下の帯に出す1行（METAR ＋ TAF のこれからの変化）"""
    return f"✈ {format_metar_line(metar)} ｜ {format_change_line(next_change(taf, now_utc), now_utc)}"


# ------------------------------------------------------------------ 画面の帯（観測のみ、1行）
METAR_MAX_AGE_S = 3 * 3600


def is_stale(metar, now_utc: datetime.datetime, max_age_s: float = METAR_MAX_AGE_S) -> bool:
    """観測が古すぎる（または無い）なら True（帯を出さない）"""
    return metar is None or (now_utc - metar["obs_utc"]).total_seconds() > max_age_s


def band_parts(metar):
    """帯に並べる文字（観測のみ）。[(文字, 優先度)]。優先度が大きいものほど、幅が足りないとき先に省く"""
    parts = [(f"{metar['icao']} {metar['obs_utc'].astimezone(JST):%H:%M}観測", 0)]
    for text in (_wind_text(metar), _vis_text(metar)):
        if text:
            parts.append((text, 0))
    for i, w in enumerate(metar["wx"]):
        parts.append((w, 1 if i == 0 else 2))
    cloud = _cloud_text(metar)
    if cloud:
        parts.append((cloud, 0))
    if metar["temp"] is not None:
        parts.append((f"{metar['temp']}℃", 3))
    return parts


def fit_band(parts, avail: int, measure, sizes=(24, 22, 20, 18)):
    """幅 avail に収まる (文字の並び, 文字サイズ) を返す。
    まず文字を小さくし、それでも入らなければ優先度の大きい（重要度の低い）ものから省く"""
    join = lambda ps: " ".join(t for t, _ in ps)
    for size in sizes:
        if measure(join(parts), size) <= avail:
            return [t for t, _ in parts], size
    size = sizes[-1]
    for drop in sorted({p for _, p in parts if p > 0}, reverse=True):
        parts = [p for p in parts if p[1] < drop]
        if measure(join(parts), size) <= avail:
            break
    return [t for t, _ in parts], size


# ------------------------------------------------------------------ 取得
def fetch_raw(url: str, timeout: float = 10) -> str:
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "raspi-weather-lite (weather signage)"})
    r.raise_for_status()
    return r.text.strip()


def fetch_and_parse(icao: str, now_utc=None):
    """METAR と TAF を取得して解析。戻り値 (metar, taf, raw_metar, raw_taf)。失敗した方は None"""
    now_utc = now_utc or datetime.datetime.now(UTC)
    metar = taf = raw_m = raw_t = None
    try:
        raw_m = fetch_raw(METAR_URL.format(icao=icao)).splitlines()[0]
        metar = parse_metar(raw_m, now_utc)
    except Exception as e:
        logging.warning(f"METAR 取得失敗 ({icao}): {e}")
    try:
        raw_t = " ".join(fetch_raw(TAF_URL.format(icao=icao)).split())
        taf = parse_taf(raw_t, now_utc)
    except Exception as e:
        logging.warning(f"TAF 取得失敗 ({icao}): {e}")
    return metar, taf, raw_m, raw_t


def fetch_into(icao: str, holder: dict) -> None:
    """取得して holder に最新の METAR を入れる（失敗時は前回の値を残す）。生電文と表示案はログに出す"""
    now = datetime.datetime.now(UTC)
    metar, taf, raw_m, raw_t = fetch_and_parse(icao, now)
    logging.info(f"[aviation] METAR raw: {raw_m}")
    logging.info(f"[aviation] TAF raw: {raw_t}")
    logging.info(f"[aviation] 表示案: {format_line(metar, taf, now)}")
    if metar:
        holder.update({"metar": metar, "raw": raw_m, "fetched_at": time.time()})


def start_fetch_in_background(icao: str, holder: dict) -> None:
    threading.Thread(target=fetch_into, args=(icao, holder), daemon=True).start()
