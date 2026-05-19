"""
fetch_wbgt.py
環境省「熱中症予防情報サイト」から WBGT 予測値と警戒アラートを取得。

データソース: https://www.wbgt.env.go.jp/
更新頼度: 環境省は 1 時間ごと（本モジュールは呼び出し側でキャッシュすること）
"""

import datetime
import logging
import requests

from utils import JST

# 空港 → 都道府県コード（環境省 WBGT CSV 用）
_PREF_CODE = {
    "centrair": "23",   # 愛知
    "haneda":   "13",   # 東京
    "narita":   "12",   # 千葉
    "kanku":    "27",   # 大阪
    "chitose":  "01",   # 北海道
    "fukuoka":  "40",   # 福岡
    "naha":     "47",   # 沖縄
}

# WBGT しきい値（環境省基準）
WBGT_LEVELS = [
    (33, "危険",     ( 90,   0,  90), (255,  80, 255)),   # (threshold, label, bg, fg)
    (31, "厳重警戒", (140,  0,   0), (255, 130, 130)),
    (28, "警戒",     (150, 70,   0), (255, 175,  60)),
    (25, "注意",     ( 90, 80,   0), (230, 210,  50)),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux armv7l) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _fetch_wbgt_csv(pref_code: str) -> float | None:
    """当日の WBGT 最高予測値を返す。取得失敗時は None。"""
    url = f"https://www.wbgt.env.go.jp/prev15WG/dl/yohou_{pref_code}.csv"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        text = r.content.decode("shift_jis", errors="replace")
    except Exception:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10)
            r.raise_for_status()
            text = r.text
        except Exception as e:
            logging.warning(f"WBGT CSV 取得失敗 pref={pref_code}: {e}")
            return None

    today = datetime.datetime.now(JST).strftime("%Y/%m/%d")
    max_val: float | None = None
    for line in text.splitlines():
        if not line.startswith(today):
            continue
        parts = line.split(",")
        for p in parts[1:]:
            try:
                v = float(p.strip())
                if max_val is None or v > max_val:
                    max_val = v
            except ValueError:
                pass
    return max_val


def _fetch_alert(pref_code: str) -> bool:
    """熱中症警戒アラート発令中なら True。取得失敗時は False。"""
    url = "https://www.wbgt.env.go.jp/alert.php"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        text = r.text
        marker = f'class="alert" data-pref="{pref_code}"'
        alt_marker = f"pref{pref_code}"
        return marker in text or alt_marker in text
    except Exception as e:
        logging.debug(f"アラートチェック失敗 pref={pref_code}: {e}")
        return False


def fetch_wbgt(airport: str) -> tuple:
    """
    (wbgt_max: float|None, alert: bool, level_info: dict|None) を返す。

    level_info = {
        "label": str,       # "危険" / "厳重警戒" / "警戒" / "注意"
        "bg":    (r,g,b),   # バッジ背景色
        "fg":    (r,g,b),   # バッジ文字色
        "value": float,     # WBGT 値
    }
    """
    code = _PREF_CODE.get(airport)
    if not code:
        return None, False, None

    wbgt = _fetch_wbgt_csv(code)
    alert = _fetch_alert(code) if wbgt is not None and wbgt >= 33 else False

    level_info = None
    if wbgt is not None:
        for threshold, label, bg, fg in WBGT_LEVELS:
            if wbgt >= threshold:
                level_info = {"label": label, "bg": bg, "fg": fg, "value": wbgt}
                break

    if wbgt is not None:
        logging.info(f"WBGT: airport={airport} value={wbgt} alert={alert} level={level_info and level_info['label']}")

    return wbgt, alert, level_info
