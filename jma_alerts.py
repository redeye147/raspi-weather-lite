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
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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


def _extract_warning_text(warn_json: Dict[str, Any], area_codes: Tuple[str, ...]) -> str:
    """
    warning JSON:
      headlineText, reportDatetime, areaTypes:[{areas:[{code, warnings:[...]}]}]
    から、指定 area_codes の「発表中」を文字列化
    """
    area_types = warn_json.get("areaTypes") or []
    hits: List[str] = []

    for at in area_types:
        for area in (at.get("areas") or []):
            code = str(area.get("code", ""))
            if area_codes and code not in area_codes:
                continue

            for w in (area.get("warnings") or []):
                name = (w.get("name") or "").strip()
                status = (w.get("status") or "").strip()

                if not name:
                    continue
                if status and ("解除" in status or "取消" in status):
                    continue

                if status and status not in ("発表",):
                    hits.append(f"{name}（{status}）")
                else:
                    hits.append(name)

    if not hits:
        for at in area_types:
            for area in (at.get("areas") or [])[:3]:
                for w in (area.get("warnings") or [])[:6]:
                    name = (w.get("name") or "").strip()
                    status = (w.get("status") or "").strip()
                    if not name:
                        continue
                    if status and ("解除" in status or "取消" in status):
                        continue
                    hits.append(name)
            if hits:
                break

    if not hits:
        return "警報・注意報：発表なし"

    seen = set()
    uniq = []
    for x in hits:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)

    return "警報・注意報：" + "、".join(uniq)


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
    warning_url  = f"{JMA_BASE}/bosai/warning/data/warning/{office_code}.json"

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
        wj = _get_json(warning_url)
        w_head = (wj.get("headlineText") or "").strip()
        w_text = _extract_warning_text(wj, area_codes)
        # updated は警報 reportDatetime で上書きしない（警報なしの日は古い日付になるため）
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
