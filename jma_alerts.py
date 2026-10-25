#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JMA: 概況（overview_forecast）＋ 警報注意報（warning）
- 取得失敗時は cache_json を返す（なければ失敗メッセージ）
"""

import os
import json
import time
import datetime
from typing import Dict, Tuple, Any, List

import requests

import safe_write
from requests.adapters import HTTPAdapter, Retry

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "cache", "jma_overview.json")


JMA_BASE = "https://www.jma.go.jp"
JST = datetime.timezone(datetime.timedelta(hours=9))


def _session_with_retry() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3, backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "raspi-weather-display/1.0"})
    return s


SESS = _session_with_retry()


def _load_cache(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(path: str, data: Dict[str, Any]) -> None:
    try:
        safe_write.write_json(path, data, indent=2)       # 電源が突然切れても前の内容が残るように
    except Exception:
        pass


def _get_json(url: str, timeout: int = 10) -> Any:
    r = SESS.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _fmt_updated(dt_str: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")


# 気象庁 bosai warning JSON の警報・注意報コード（JSON には名称が含まれずコードのみ）
WARNING_CODES = {
    "02": "暴風雪警報", "03": "大雨警報", "04": "洪水警報", "05": "暴風警報",
    "06": "大雪警報", "07": "波浪警報", "08": "高潮警報",
    "10": "大雨注意報", "12": "大雪注意報", "13": "風雪注意報", "14": "雷注意報",
    "15": "強風注意報", "16": "波浪注意報", "17": "融雪注意報", "18": "洪水注意報",
    "19": "高潮注意報", "20": "濃霧注意報", "21": "乾燥注意報", "22": "なだれ注意報",
    "23": "低温注意報", "24": "霜注意報", "25": "着氷注意報", "26": "着雪注意報",
    "27": "その他の注意報",
    "32": "暴風雪特別警報", "33": "大雨特別警報", "35": "暴風特別警報",
    "36": "大雪特別警報", "37": "波浪特別警報", "38": "高潮特別警報",
}


WARNING_STALE_DAYS = 3     # 発表がこれより古い警報データは使わない（更新が止まっているとみなす）


def warning_data_stale(report_datetime, now=None, days=WARNING_STALE_DAYS):
    """警報データの発表時刻が days 日より古ければ、その日付（"5/28"）を返す。新しい・読めなければ None"""
    try:
        rep = datetime.datetime.fromisoformat(str(report_datetime).replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        return None
    now = now or datetime.datetime.now(JST)
    return f"{rep.month}/{rep.day}" if now - rep > datetime.timedelta(days=days) else None


def active_warning_names(warn_json: Dict[str, Any], area_codes) -> List[str]:
    """指定エリアで発表・継続中の警報・注意報名を、特別警報→警報→注意報の順で返す。"""
    names: List[str] = []
    for at in (warn_json.get("areaTypes") or []):
        for area in (at.get("areas") or []):
            if str(area.get("code", "")) not in area_codes:
                continue
            for w in (area.get("warnings") or []):
                code = str(w.get("code") or "")
                status = (w.get("status") or "").strip()
                if not code or "解除" in status or "なし" in status:
                    continue
                # 未知コードも握りつぶさず表示（コード体系変更に気付けるように）
                name = WARNING_CODES.get(code, f"警報コード{code}")
                if name not in names:
                    names.append(name)
    rank = lambda n: 0 if "特別警報" in n else 1 if "警報" in n else 2
    return sorted(names, key=rank)


# ── 2026 年の新しい防災気象情報（r8 = 令和 8 年）────────────────
# 今までの bosai/warning/data/warning/{県}.json は 2026-05-28 の発表のまま止まっていた（2026-10-25 に判明。
# 5 か月前の「濃霧注意報」を出し続けていた）。気象庁の警報のページは bosai/warning/data/r8/{県}.json を読んでいる。
# 中身は発表（電文の種類 dataTypeCode ごと。例 VPWW61）の一覧で、それぞれが市町村（class20Items の areaCode）ごとの
# 警報・注意報（kinds の code・status、付け加え additions「突風」「ひょう」など）を持つ。種類ごとに最新の発表を合わせたものが今の状態
WARNING_R8_URL = JMA_BASE + "/bosai/warning/data/r8/{pref}.json"
WARNING_R8_TIME_URL = JMA_BASE + "/bosai/warning/data/r8/map_time.json"   # 全国の最新の更新時刻
R8_STALE_HOURS = 48       # 全国の最新の更新がこれより古ければ、データが止まっているとみなす


def _latest_per_type(reports):
    """電文の種類（dataTypeCode）ごとに最新の発表だけ"""
    latest = {}
    for r in reports if isinstance(reports, list) else [reports]:
        if not isinstance(r, dict):
            continue
        key = r.get("dataTypeCode") or ""
        if key not in latest or (r.get("reportDatetime") or "") > (latest[key].get("reportDatetime") or ""):
            latest[key] = r
    return list(latest.values())


def _active_kinds(report, area_codes):
    """1 つの発表の中で、指定の市町村に発表・継続中の警報・注意報（解除・なしは除く）"""
    out = []
    for item in ((report.get("warning") or {}).get("class20Items") or []):
        if str(item.get("areaCode", "")) not in area_codes:
            continue
        for k in (item.get("kinds") or []):
            status = (k.get("status") or "").strip()
            if k.get("code") and "解除" not in status and "なし" not in status:
                out.append(k)
    return out


def active_warning_names_r8(reports, area_codes) -> List[str]:
    """新しい形（r8）：指定の市町村で発表・継続中の警報・注意報名（付け加えがあれば「雷注意報（突風・ひょう）」）を、
    特別警報→警報→注意報の順で"""
    names: List[str] = []
    for r in _latest_per_type(reports):
        for k in _active_kinds(r, area_codes):
            code = str(k.get("code"))
            name = WARNING_CODES.get(code, f"警報コード{code}")    # 知らないコードも出す（体系の変更に気付けるように）
            adds = [a for a in (k.get("additions") or []) if isinstance(a, str)]
            if adds:
                name += f"（{'・'.join(adds)}）"
            if name not in names:
                names.append(name)
    rank = lambda n: 0 if "特別警報" in n else 1 if "警報" in n else 2
    return sorted(names, key=rank)


def latest_active_report(reports, area_codes):
    """指定の市町村に発表・継続中の警報・注意報がある発表のうち、いちばん新しいもの（無ければ None）。
    見出しはこの発表のものを使う（ほかの種類の「注意報を解除します。」を、発表中の雷注意報に添えて出さないように。
    2026-10-25 の 118：雷注意報（突風・ひょう）の下に、別の注意報の「注意報を解除します。」が出ていた）"""
    rs = [r for r in _latest_per_type(reports) if _active_kinds(r, area_codes)]
    return max(rs, key=lambda r: r.get("reportDatetime") or "") if rs else None


def headline_r8(reports, area_codes) -> str:
    """指定の市町村に発表中の警報・注意報の発表の見出し（発表中のものが無ければ空）"""
    r = latest_active_report(reports, area_codes)
    return (r.get("headlineText") or "").strip() if r else ""


def r8_feed_stale(map_time, now=None, hours=R8_STALE_HOURS) -> bool:
    """全国の最新の更新時刻（map_time.json）が hours 時間より古ければ True（読めなければ False）"""
    try:
        t = datetime.datetime.fromisoformat(str(map_time.get("latestControlDatetime")).replace("Z", "+00:00"))
    except Exception:
        return False
    now = now or datetime.datetime.now(JST)
    return now - t > datetime.timedelta(hours=hours)


def fetch_warnings_r8(pref_code: str, area_codes, get_json=None):
    """(警報・注意報名の並び, 見出し)。データが止まっていれば ValueError"""
    get_json = get_json or _get_json
    reports = get_json(WARNING_R8_URL.format(pref=pref_code))
    try:
        if r8_feed_stale(get_json(WARNING_R8_TIME_URL)):
            raise ValueError("警報データ（r8）の全国の更新が 2 日以上止まっている")
    except ValueError:
        raise
    except Exception:
        pass                                   # 更新時刻が取れないだけなら、警報はそのまま使う
    return active_warning_names_r8(reports, tuple(area_codes)), headline_r8(reports, tuple(area_codes))


def _extract_warning_text(warn_json: Dict[str, Any], area_codes: Tuple[str, ...]) -> str:
    names = active_warning_names(warn_json, area_codes)
    if not names:
        return "警報・注意報：発表なし"
    return "警報・注意報：" + "、".join(names)


def get_overview_and_warning(
    office_code: str,
    area_codes: Tuple[str, ...],
    cache_json_path: str,
) -> Dict[str, str]:
    """
    返り値:
      headline: 1行（概要の見出し + 警報headlineTextの先頭）
      overview: 概況本文
      warning: 警報注意報（指定エリア優先）
      updated: "YYYY-mm-dd HH:MM"  ← 予報概況の更新時刻（毎日5/11/17時更新）
    """
    cache = _load_cache(cache_json_path)

    overview_url = f"{JMA_BASE}/bosai/forecast/data/overview_forecast/{office_code}.json"

    try:
        ov = _get_json(overview_url)
        ov_text = (ov.get("text") or "").strip()
        ov_head = (ov.get("headlineText") or "").strip()
        # 予報概況の更新時刻を使用（毎日3回更新されるため警報より新しい）
        updated = _fmt_updated(ov.get("reportDatetime") or "")
    except Exception:
        ov_text = (cache.get("overview") or "概況取得失敗")
        ov_head = (cache.get("headline") or "")
        updated = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    try:
        reports = _get_json(WARNING_R8_URL.format(pref=office_code))
        names = active_warning_names_r8(reports, tuple(area_codes))
        w_text = "警報・注意報：" + ("、".join(names) if names else "発表なし")
        # 見出しは 1 日以上前の発表なら出さない（警報が無い日は古い発表のまま）
        w_head = ""
        latest = latest_active_report(reports, tuple(area_codes))   # 発表中の警報・注意報の発表の見出しだけ
        if latest:
            try:
                rep_dt = datetime.datetime.fromisoformat(latest["reportDatetime"].replace("Z", "+00:00"))
                if (datetime.datetime.now(JST) - rep_dt.astimezone(JST)).days < 1:
                    w_head = (latest.get("headlineText") or "").strip()
            except Exception:
                pass
    except Exception:
        w_head = ""
        # キャッシュが2時間以内なら使用。古いキャッシュは解除済み警報を表示し続けるため使わない
        cache_age = time.time() - cache.get("_saved_at", 0)
        if cache_age < 7200:
            w_text = cache.get("warning") or "警報・注意報：取得失敗"
        else:
            w_text = "警報・注意報：取得失敗"

    headline = ""
    if ov_head:
        headline = ov_head
    if w_head:
        headline = (headline + " / " if headline else "") + w_head
    headline = headline.strip()

    out = {
        "headline": headline,
        "overview": ov_text if ov_text else "概況：取得できませんでした",
        "warning": w_text,
        "updated": updated,
        "_saved_at": time.time(),
    }

    _save_cache(cache_json_path, out)
    return out

if __name__ == "__main__":

    print("テスト開始")

    print("CACHE_PATH =", CACHE_PATH)

    data = get_overview_and_warning(
        office_code="120000",
        area_codes=("1221100",),
        cache_json_path=CACHE_PATH
    )

    print("取得データ:")
    print(data)
