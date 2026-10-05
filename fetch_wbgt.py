"""
fetch_wbgt.py
環境省「熱中症予防情報サイト」から WBGT 予測値と警戒アラートを取得。

データソース: https://www.wbgt.env.go.jp/
更新頼度: 環境省は 1 時間ごと（本モジュールは呼び出し側でキャッシュすること）
"""

import datetime
import logging
import threading

import requests

from utils import JST

# CSVダウンロード用（英語名形式: yohou_aichi.csv 等）
_PREF_CSV = {
    "centrair": "aichi",     # 愛知
    "haneda":   "tokyo",     # 東京
    "narita":   "chiba",     # 千葉
    "kanku":    "osaka",     # 大阪
    "chitose":  "hokkaido",  # 北海道
    "fukuoka":  "fukuoka",   # 福岡
    "naha":     "okinawa",   # 沖縄
}

# WBGT 予測の地点（気象庁アメダスの地点番号と同じ）。CSV には県内の複数地点が並ぶので、空港に最も近い地点の行を使う
# （2026-10-05 に気象庁のアメダス地点表と各 CSV から距離を計算して選定）
_WBGT_POINT = {
    "centrair": "51311",     # 南知多 17.9km
    "haneda":   "44136",     # 江戸川臨海 12.4km
    "narita":   "45081",     # 香取 14.7km
    "kanku":    "62131",     # 熊取 11.2km
    "chitose":  "21111",     # 厚真 16.8km
    "fukuoka":  "82182",     # 福岡 7.1km
    "naha":     "91197",     # 那覇 4.2km
}

# 警戒アラートHTML検索用（2桁数字都道府県コード）
_PREF_ALERT = {
    "centrair": "23",
    "haneda":   "13",
    "narita":   "12",
    "kanku":    "27",
    "chitose":  "01",
    "fukuoka":  "40",
    "naha":     "47",
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


def _fetch_wbgt_csv(csv_code: str, point: str, today: str = None):
    """当日の WBGT 最高予測値を返す。戻り値 (値 or None, 状態)。
    状態: "ok"（今日の値あり）/ "nodata"（ファイルが無い・地点や今日の列が無い＝提供期間外の可能性）/ "error"（通信エラー等）"""
    url = f"https://www.wbgt.env.go.jp/prev15WG/dl/yohou_{csv_code}.csv"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        if r.status_code == 404:
            return None, "nodata"
        r.raise_for_status()
        text = r.content.decode("shift_jis", errors="replace")
    except Exception as e:
        logging.warning(f"WBGT CSV 取得失敗 ({csv_code}): {e}")
        return None, "error"
    return parse_wbgt_csv(text, point, today or datetime.datetime.now(JST).strftime("%Y%m%d"))


def parse_wbgt_csv(text: str, point: str, today: str):
    """環境省の予測 CSV から、地点 point の今日（today = YYYYMMDD）の最高値を取り出す。
    1行目: ,,2026100521,2026100524,2026100603,…（年月日時。24 は当日の 24 時）
    2行目〜: 地点番号,更新時刻, 190, 190, …（WBGT の 10 倍）
    今日の列は「これから先の 3 時間ごと」なので、今日の残りの最高予測になる。戻り値 (値 or None, "ok" / "nodata")"""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return None, "nodata"
    times = [t.strip() for t in lines[0].split(",")[2:]]
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(",")]
        if cols[0] != point:
            continue
        vals = []
        for t, v in zip(times, cols[2:]):
            if t.startswith(today):
                try:
                    vals.append(int(v) / 10)
                except ValueError:
                    pass
        return (max(vals), "ok") if vals else (None, "nodata")
    return None, "nodata"


def _fetch_alert(alert_code: str) -> bool:
    """熱中症警戒アラート発令中なら True。取得失敗時は False。"""
    url = "https://www.wbgt.env.go.jp/alert.php"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        text = r.text
        marker = f'class="alert" data-pref="{alert_code}"'
        alt_marker = f"pref{alert_code}"
        return marker in text or alt_marker in text
    except Exception as e:
        logging.debug(f"アラートチェック失敗 ({alert_code}): {e}")
        return False


def level_for(wbgt):
    """WBGT 値からバッジの表示（注意〜危険）を決める。25 未満は None（バッジなし）"""
    if wbgt is None:
        return None
    for threshold, label, bg, fg in WBGT_LEVELS:
        if wbgt >= threshold:
            return {"label": label, "bg": bg, "fg": fg, "value": wbgt}
    return None


def fetch_wbgt(airport: str) -> tuple:
    """
    (wbgt_max: float|None, alert: bool, level_info: dict|None, status: str) を返す。

    level_info = {
        "label": str,       # "危険" / "厳重警戒" / "警戒" / "注意"
        "bg":    (r,g,b),   # バッジ背景色
        "fg":    (r,g,b),   # バッジ文字色
        "value": float,     # WBGT 値
    }
    status = "ok" / "nodata"（提供期間外の可能性）/ "error"（通信エラー等）
    """
    csv_code   = _PREF_CSV.get(airport)
    point      = _WBGT_POINT.get(airport)
    alert_code = _PREF_ALERT.get(airport)
    if not csv_code or not point:
        return None, False, None, "nodata"

    wbgt, status = _fetch_wbgt_csv(csv_code, point)
    alert = _fetch_alert(alert_code) if alert_code and wbgt is not None and wbgt >= 33 else False
    level_info = level_for(wbgt)

    if wbgt is not None:
        logging.info(f"WBGT: airport={airport} point={point} value={wbgt} alert={alert} level={level_info and level_info['label']}")
    return wbgt, alert, level_info, status


def start_fetch_in_background(airport: str, holder: dict) -> None:
    """裏で取得して holder["result"] に (wbgt, alert, level_info, status) を入れる（取得中も時計を止めない）"""
    def run():
        try:
            holder["result"] = fetch_wbgt(airport)
        except Exception as e:
            logging.error(f"WBGT更新失敗: {e}")
            holder["result"] = (None, False, None, "error")
    holder.pop("result", None)
    threading.Thread(target=run, daemon=True).start()
