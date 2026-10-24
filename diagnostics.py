"""
diagnostics.py
診断ページ（WiFi ポータルの /diag）用：本体と表示プログラムの状態を集めて、項目ごとに 正常／注意／異常 を判定する。
見るだけ（何も変更しない）。collect() が情報を集め、evaluate() が判定する（判定は tests/test_diagnostics.py で検証）。
"""

import datetime
import glob
import json
import re
import os
import shutil
import subprocess
import time

import aviation
from config import AIRPORT_CONFIG, BASE_DIR, LOG_FILE
from decisions import AVIATION_START_HOUR, WBGT_START_HOUR, wbgt_off_season
from netstate import get_connection_kind

JST = datetime.timezone(datetime.timedelta(hours=9))
SNAPSHOT_FILE = os.path.join(BASE_DIR, "cache", "snapshot.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

OK, WARN, BAD, INFO = "ok", "warn", "bad", "info"
_ORDER = {OK: 0, INFO: 0, WARN: 1, BAD: 2}

# vcgencmd get_throttled のビット（今起きている / 起動後に一度でも起きた）
_THROTTLE_NOW = {0x1: "電圧低下", 0x2: "周波数制限", 0x4: "速度低下", 0x8: "温度制限"}
_THROTTLE_PAST = {0x10000: "電圧低下", 0x20000: "周波数制限", 0x40000: "速度低下", 0x80000: "温度制限"}


# ==========================================================
# 情報を集める（失敗した項目は None。Pi 以外でも落ちない）
# ==========================================================
def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return None


def _service_info(name="main01"):
    out = _run(["systemctl", "show", name, "-p", "ActiveState", "-p", "SubState",
                "-p", "NRestarts", "-p", "ActiveEnterTimestampMonotonic"])
    if not out:
        return None
    d = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    try:
        since_mono = int(d.get("ActiveEnterTimestampMonotonic", "0")) / 1e6
        uptime = time.monotonic() - since_mono if since_mono else None
    except ValueError:
        uptime = None
    return {"active": d.get("ActiveState"), "sub": d.get("SubState"),
            "restarts": int(d.get("NRestarts", "0") or 0), "uptime_s": uptime}


def _cpu_temp():
    out = _run(["vcgencmd", "measure_temp"])                 # temp=48.3'C
    if out and "=" in out:
        try:
            return float(out.split("=")[1].split("'")[0])
        except ValueError:
            pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000
    except Exception:
        return None


def _throttled():
    out = _run(["vcgencmd", "get_throttled"])                # throttled=0x50000
    if out and "=" in out:
        try:
            return int(out.split("=")[1], 16)
        except ValueError:
            pass
    return None


def _wifi_signal():
    """接続中の WiFi の SSID と電波の強さ（0〜100）"""
    out = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"])
    for line in (out or "").splitlines():
        if line.startswith("*:"):
            parts = line.rsplit(":", 1)
            try:
                return parts[0][2:].replace("\\:", ":"), int(parts[1])
            except (ValueError, IndexError):
                return parts[0][2:], None
    return None, None


def _display_info():
    """画面出力の装置。fb0 の大きさ（無ければ None）と、HDMI 端子ごとの接続状態"""
    fb0 = None
    try:
        with open("/sys/class/graphics/fb0/virtual_size") as f:
            fb0 = f.read().strip().replace(",", "×")
    except OSError:
        pass
    hdmi = {}
    for path in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/status")):
        try:
            with open(path) as f:
                hdmi[path.split("/")[-2].split("-", 1)[1]] = f.read().strip()
        except OSError:
            pass
    return {"fb0": fb0, "hdmi": hdmi}


def recent_starts(log_path=LOG_FILE, minutes=10, now=None):
    """直近 minutes 分にログへ「main01 開始」が何回出たか（起動の失敗を繰り返していないかの目安）"""
    now = now or datetime.datetime.now()
    since = (now - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 200_000))
            tail = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    return sum(1 for l in tail if "main01 開始" in l and l[:19] >= since)


def _local_ip():
    out = _run(["hostname", "-I"])
    return (out or "").split()[0] if out else ""


def format_git_log(out: str) -> str:
    """「3bbd350 1792302667」（版・作った時刻の秒）→「3bbd350 2026-10-18 14:51」（日本時間。
    以前はコミットした環境の時刻（UTC）のまま「05:51」と出ていた。天気画面右下の版表示と同じ日本時間に）"""
    parts = out.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        return out.strip()
    return f"{parts[0]} {datetime.datetime.fromtimestamp(int(parts[1]), JST):%Y-%m-%d %H:%M}"


def _git_version():
    env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory", GIT_CONFIG_VALUE_0=BASE_DIR)
    try:
        out = format_git_log(subprocess.run(["git", "log", "-1", "--format=%h %ct"],
                                            cwd=BASE_DIR, capture_output=True, text=True, timeout=5, env=env).stdout)
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=BASE_DIR, capture_output=True, text=True, timeout=5, env=env).stdout.strip()
        return f"{br} {out}".strip()
    except Exception:
        return ""


# よくある通信エラーは要点だけにする（長い例外文はスマホで読みにくい）
_ERROR_HINTS = [      # 上から順に調べる（名前解決の失敗は「接続できない」にも含まれるので先に）
    ("Failed to resolve", "名前解決エラー（DNS）"), ("NameResolutionError", "名前解決エラー（DNS）"),
    ("Temporary failure in name resolution", "名前解決エラー（DNS）"),
    ("Name or service not known", "名前解決エラー（DNS）"),
    ("timed out", "タイムアウト"), ("Connection reset", "接続が切れた"),
    ("Connection refused", "接続を拒否された"), ("Network is unreachable", "ネットワークに届かない"),
    ("NewConnectionError", "接続できない"), ("Failed to establish a new connection", "接続できない"),
    ("Max retries exceeded", "接続失敗"),
]


def short_error(err) -> str:
    """例外の長い文（URL・内部の型名など）を「名前解決エラー（DNS）」のように短くする"""
    text = str(err or "")
    for key, hint in _ERROR_HINTS:
        if key in text:
            return hint
    return text if len(text) <= 80 else text[:80] + "…"


def _problem_parts(line: str):
    """ログ1行 → (時刻「10/05 15:40」, レベル, 短くした内容)。形式が違う行は (None, None, 行の先頭 200 文字)"""
    parts = [p.strip() for p in line.split("|", 2)]
    if len(parts) < 3:
        return None, None, line[:200]
    when, level, msg = parts
    try:
        when = datetime.datetime.strptime(when[:16], "%Y-%m-%d %H:%M").strftime("%m/%d %H:%M")
    except ValueError:
        pass
    for key, hint in _ERROR_HINTS:
        if key in msg:
            if msg.startswith("Retrying"):            # requests の自動再試行（どの URL かを残す）
                url = msg.rsplit(': ', 1)[-1].strip().split("?", 1)[0]     # 「?」より後（長い条件）は省く
                msg = f"再試行（{url}）: {hint}"
            else:
                msg = f"{msg.split(':', 1)[0]}: {hint}"
            break
    else:
        msg = msg if len(msg) <= 160 else msg[:160] + "…"
    return when, level, msg


def summarize_problem(line: str) -> str:
    """ログ1行を「10/05 15:40 WARNING METAR 取得失敗 (RJAA): 名前解決エラー（DNS）」のように短くする"""
    when, level, msg = _problem_parts(line)
    return msg if when is None else f"{when} {level} {msg}"


PROBLEM_LIMIT = 20       # 診断ページに出す件数（同じ内容はまとめて 1 件）
PROBLEM_MAX_DAYS = 7     # 件数に足りないときにさかのぼるログの日数（ログは 7 日分残る）


def recent_problems(log_path=LOG_FILE, limit=PROBLEM_LIMIT, max_days=PROBLEM_MAX_DAYS, today=None):
    """ログの WARNING / ERROR を新しい順に最大 limit 件。
    同じ内容（時刻・数字だけ違う。例「停止（801回目）→ 60秒後に再起動」）は 1 件にまとめ、
    「×81回（10/17 09:00〜21:11）」のように回数と期間を付ける（同じ失敗が続いても、ほかの記録が押し出されない）。
    今日・前日のファイルは必ず読み、それでも limit 件に足りなければ max_days 日前までさかのぼる"""
    today = today or datetime.datetime.now(JST).date()
    groups = {}          # まとめる鍵 → {"line": 最新の 1 行, "last": 最新の時刻, "first": 最古の時刻, "count": 回数}
    for d in range(max_days):
        if d >= 2 and len(groups) >= limit:
            break
        path = log_path if d == 0 else f"{log_path}.{today - datetime.timedelta(days=d):%Y-%m-%d}"
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [l.rstrip("\n") for l in f if "| WARNING |" in l or "| ERROR |" in l]
        except OSError:
            continue
        for l in reversed(lines):                     # 新しい順
            when, level, msg = _problem_parts(l)
            key = (level, re.sub(r"\d+", "#", msg))
            g = groups.get(key)
            if g is None:
                if len(groups) >= limit:              # 件数は満杯：新しい種類は増やさず、回数だけ数える
                    continue
                g = groups[key] = {"line": msg if when is None else f"{when} {level} {msg}",
                                   "last": when, "count": 0}
            g["count"] += 1
            g["first"] = when
    out = []
    for g in groups.values():
        if g["count"] == 1:
            out.append(g["line"])
        else:
            span = f"{g['first']}〜{g['last'][-5:] if g['first'] and g['last'] and g['first'][:5] == g['last'][:5] else g['last']}"
            out.append(f"{g['line']} ×{g['count']}回（{span}）")
    return out


def _read_status(path=None, max_age_s=90):
    """表示プログラムが書いた直近 1 分の CPU 使用率の平均（古い・無いときは None）"""
    from config import STATUS_FILE
    try:
        with open(path or STATUS_FILE) as f:
            st = json.load(f)
        if time.time() - st["at"] <= max_age_s:
            return float(st["cpu_1min"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def collect() -> dict:
    """診断に使う情報をまとめて集める（数秒以内）"""
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            snap = json.load(f)
    except Exception:
        snap = None
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    ssid, signal = _wifi_signal()
    cpu, cpu_avg = None, False
    status = _read_status()
    if status is not None:
        cpu, cpu_avg = status, True                  # 表示プログラムが測った直近 1 分の平均
    try:
        import psutil
        if cpu is None:
            cpu = psutil.cpu_percent(interval=0.5)   # 表示プログラムが止まっているときだけ、その場で測る
        mem = psutil.virtual_memory().percent
    except Exception:
        mem = None
    try:
        free_gb = shutil.disk_usage("/").free / 1e9
    except Exception:
        free_gb = None
    try:
        load1 = os.getloadavg()[0]
    except OSError:
        load1 = None
    airport = cfg.get("airport", "centrair")
    return {
        "airport": airport,
        "airport_name": AIRPORT_CONFIG.get(airport, {}).get("name", airport),
        "icao": AIRPORT_CONFIG.get(airport, {}).get("icao"),
        "interval_hours": float(cfg.get("interval_hours", 1.0)),
        "service": _service_info(),
        "display": _display_info(),
        "recent_starts": recent_starts(),
        "conn_kind": get_connection_kind(),
        "ssid": ssid, "signal": signal, "ip": _local_ip(),
        "ntp_synced": _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]),
        "temp": _cpu_temp(), "throttled": _throttled(),
        "cpu": cpu, "cpu_avg": cpu_avg, "mem": mem, "load1": load1, "disk_free_gb": free_gb,
        "snap": snap,
        "version": _git_version(),
        "problems": recent_problems(),
        "accuracy": _accuracy(),
    }


# ==========================================================
# 判定（入力 → 結果。画面・通信・ファイルには触らない）
# ==========================================================
def _item(code, name, level, value, detail=""):
    return {"code": code, "name": name, "level": level, "value": value, "detail": detail}


def _ago(sec):
    if sec is None:
        return "-"
    m = int(sec // 60)
    if m < 60:
        return f"{m}分前"
    if m < 48 * 60:
        return f"{m // 60}時間{m % 60}分前"
    return f"{m // 1440}日前"


def _hm(ts):
    return datetime.datetime.fromtimestamp(ts, JST).strftime("%m/%d %H:%M") if ts else "-"


def _uptime(sec):
    if sec is None:
        return ""
    d, h, m = int(sec // 86400), int(sec % 86400 // 3600), int(sec % 3600 // 60)
    return f"{d}日{h}時間" if d else (f"{h}時間{m}分" if h else f"{m}分")


def _weather_item(now, snap, interval_h):
    ts = (snap or {}).get("weather_at")
    if not ts:
        return _item("WX", "天気", BAD, "データなし", "まだ一度も取得できていません")
    age = now.timestamp() - ts
    # 夜間（0:00〜6:10 ごろ）は 23:50 の取得が最後なので、その分を許す
    night = now.hour < 6 or (now.hour == 6 and now.minute < 15)
    limit = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() + 20 * 60 if night \
        else interval_h * 3600 + 40 * 60
    level = OK if age <= limit else (WARN if age <= limit + 3 * 3600 else BAD)
    detail = "" if level == OK else "予定の時刻を過ぎても取得できていません（通信エラーの可能性）"
    return _item("WX", "天気", level, f"{_hm(ts)} 取得（{_ago(age)}）", detail)


def _jma_item(now, snap):
    ts = (snap or {}).get("jma_at")
    if not ts:
        return _item("JMA", "警報・天気概況", BAD, "データなし")
    age = now.timestamp() - ts
    level = OK if age <= 90 * 60 else (WARN if age <= 3 * 3600 else BAD)
    return _item("JMA", "警報・天気概況", level, f"{_hm(ts)} 取得（{_ago(age)}）",
                 "" if level == OK else "1時間ごとの取得ができていません")


def _wbgt_item(now, snap):
    snap = snap or {}
    status, attempt, data_ts = snap.get("wbgt_status"), snap.get("wbgt_at"), snap.get("wbgt_data_at")
    data_dt = datetime.datetime.fromtimestamp(data_ts, JST) if data_ts else None
    if wbgt_off_season(now, status, data_dt):
        return _item("WBGT", "WBGT（熱中症）", INFO, "提供期間外（データなし）",
                     f"1日1回（朝6時）確認中（最後の確認 {_hm(attempt)}）")
    # 夜間（0:00〜5:59）は取りに行かない決まりなので、まだ取っていない・前回失敗でも正常（夜に起動し直すと
    # 朝まで「データなし」の注意になっていた。2026-10-20 の 112）
    if now.hour < WBGT_START_HOUR:
        return _item("WBGT", "WBGT（熱中症）", OK, "夜間は取得なし（6時から）",
                     f"最後の取得 {_hm(attempt)}" if attempt else "起動後まだ取得していません（6時に取得）")
    if not attempt:
        return _item("WBGT", "WBGT（熱中症）", WARN, "データなし", "まだ取得していません")
    age = now.timestamp() - attempt
    lv = (snap.get("wbgt_level_info") or {})
    val = f"{lv['label']} {lv['value']:.1f}℃" if lv and data_dt and data_dt.date() == now.date() else "25℃未満（バッジなし）"
    if status == "error":
        return _item("WBGT", "WBGT（熱中症）", WARN, f"取得失敗（{_hm(attempt)}）", "通信エラー。1時間後に再取得します")
    level = OK if age <= 90 * 60 else (WARN if age <= 3 * 3600 else BAD)
    return _item("WBGT", "WBGT（熱中症）", level, f"{val}・{_hm(attempt)} 取得（{_ago(age)}）")


def _aviation_item(now, snap, icao):
    if not icao:
        return _item("AVI", "航空気象", INFO, "対象外（空港コードなし）")
    raw = (snap or {}).get("metar_raw")
    m = aviation.parse_metar(raw, now.astimezone(datetime.timezone.utc)) if raw else None
    if now.hour < AVIATION_START_HOUR or (now.hour == AVIATION_START_HOUR and now.minute < 7):
        return _item("AVI", "航空気象", OK, "夜間は取得なし（6:07 から）",
                     f"最後の観測 {m['obs_utc'].astimezone(JST):%m/%d %H:%M}" if m else "")
    if not m:
        return _item("AVI", "航空気象", BAD, "データなし", "METAR を取得できていません")
    age = (now - m["obs_utc"]).total_seconds()
    level = OK if age <= 50 * 60 else (WARN if age <= 3 * 3600 else BAD)
    detail = "" if level == OK else ("観測が古いままです" if level == WARN else "3時間以上古いので画面の帯は消えています")
    return _item("AVI", "航空気象", level,
                 f"{icao} {m['obs_utc'].astimezone(JST):%H:%M} 観測（{_ago(age)}）・{m['category']}", detail)


def _thunder_item(now, snap):
    snap = snap or {}
    ok_at, err = snap.get("thunder_ok_at"), snap.get("thunder_error")
    if not ok_at:
        return _item("THN", "雷ナウキャスト", WARN, "データなし",
                     f"まだ取得できていません（{short_error(err)}）" if err else "まだ取得していません（起動直後は約20秒後）")
    age = now.timestamp() - ok_at
    data_at = snap.get("thunder_data_at")
    at = f"{_hm(data_at)[-5:]} 解析" if data_at else "解析時刻不明"
    shown = snap.get("thunder_shown")
    if shown:
        value = f"{'雷接近' if shown['kind'] == 'near' else '雷注意'} {shown['dir']} {max(1, round(shown['km']))}km（{at}）"
    else:
        value = f"20km 以内に雷なし（{at}）"
    level = OK if age <= 15 * 60 else (WARN if age <= 60 * 60 else BAD)
    detail = ""
    if level != OK:
        detail = f"{_ago(age)}から取得できていません" + (f"（{short_error(err)}）" if err else "") + \
            ("。雷の帯は出ません" if level == BAD else "")
    return _item("THN", "雷ナウキャスト", level, value, detail)


def _accuracy():
    """予報の精度（過去 30 日の予報と観測のずれ。verify.py）"""
    try:
        import verify
        return verify.summarize()
    except Exception:
        return []


def _rain_item(now, snap):
    """降水ナウキャスト（今の時間帯の降水量に使う雨雲レーダー）"""
    snap = snap or {}
    ok_at, err = snap.get("rain_ok_at"), snap.get("rain_error")
    if not ok_at:
        return _item("RAD", "降水ナウキャスト", WARN, "データなし",
                     f"まだ取得できていません（{short_error(err)}）" if err else "まだ取得していません（起動直後は約20秒後）")
    age = now.timestamp() - ok_at
    data_at = snap.get("rain_data_at")
    at = f"{_hm(data_at)[-5:]} 解析" if data_at else "解析時刻不明"
    now_mmh, max_mmh = snap.get("rain_now_mmh") or 0, snap.get("rain_max_mmh") or 0
    value = (f"空港に雨なし・1時間先まで雨なし（{at}）" if not max_mmh
             else f"今 {now_mmh:g}mm/h・1時間先まで最大 {max_mmh:g}mm/h（{at}）")
    level = OK if age <= 30 * 60 else (WARN if age <= 90 * 60 else BAD)
    detail = "" if level == OK else (f"{_ago(age)}から取得できていません" + (f"（{short_error(err)}）" if err else "")
                                     + ("。今の時間帯の降水量は予報のまま" if level != OK else ""))
    return _item("RAD", "降水ナウキャスト", level, value, detail)


def _rainfc_item(now, snap):
    """降水短時間予報（6 時間先までの列の降水量）"""
    snap = snap or {}
    ok_at, err = snap.get("rainfc_ok_at"), snap.get("rainfc_error")
    if not ok_at:
        return _item("RSF", "降水短時間予報", WARN, "データなし",
                     f"まだ取得できていません（{short_error(err)}）" if err else "まだ取得していません（起動直後は約20秒後）")
    age = now.timestamp() - ok_at
    data_at = snap.get("rainfc_data_at")
    at = f"{_hm(data_at)[-5:]} 発表" if data_at else "発表時刻不明"
    hours = snap.get("rainfc_hours") or {}
    if not hours:
        value = f"空港の予報を読めず（{at}）"
    else:
        mx = max(hours.values())
        value = (f"{len(hours)}時間先まで雨なし（{at}）" if not mx
                 else f"{len(hours)}時間先まで最大 {mx:g}mm/h（{at}）")
    level = OK if age <= 75 * 60 else (WARN if age <= 3 * 3600 else BAD)
    detail = "" if level == OK else (f"{_ago(age)}から取得できていません" + (f"（{short_error(err)}）" if err else "")
                                     + "。先の列の降水量は数値予報のまま")
    return _item("RSF", "降水短時間予報", level, value, detail)


def _taf_item(now, snap, icao):
    """TAF（空港の予報。列の風と天気）"""
    snap = snap or {}
    if not icao:
        return _item("TAF", "空港の予報", INFO, "空港の設定なし")
    raw, ok_at, err = snap.get("taf_raw"), snap.get("taf_ok_at"), snap.get("taf_error")
    if not raw or not ok_at:
        return _item("TAF", "空港の予報", WARN, "データなし",
                     f"まだ取得できていません（{short_error(err)}）" if err else "まだ取得していません（起動直後は約20秒後）")
    try:
        import taf as taf_mod
        t = taf_mod.parse_taf(raw, now.astimezone(datetime.timezone.utc))
    except Exception:
        t = None
    if t is None:
        return _item("TAF", "空港の予報", WARN, "電文を読めません", raw[:60])
    age = now.timestamp() - ok_at
    span = f"{t['issued'].astimezone(JST):%H:%M} 発表・{t['end'].astimezone(JST):%d日%H時}まで"
    valid = now.astimezone(datetime.timezone.utc) < t["end"]
    level = OK if age <= 75 * 60 and valid else (WARN if valid else BAD)
    detail = "" if level == OK else (("予報の期間が終わっています。列の風は数値予報のまま" if not valid
                                      else f"{_ago(age)}から取得できていません")
                                     + (f"（{short_error(err)}）" if err else ""))
    return _item("TAF", "空港の予報", level, f"{icao} {span}", detail)


def evaluate(info: dict, now: datetime.datetime) -> dict:
    """集めた情報から、項目ごとの判定と総合判定を返す"""
    items = []

    svc = info.get("service")
    if not svc:
        items.append(_item("SVC", "表示プログラム", WARN, "状態を確認できません"))
    elif svc["active"] != "active":
        items.append(_item("SVC", "表示プログラム", BAD, f"停止中（{svc['active']}/{svc['sub']}）",
                           "天気画面が止まっています。sudo systemctl restart main01"))
    elif (info.get("recent_starts") or 0) >= 3:
        # プロセスは動いているが、中で起動に失敗してやり直しを繰り返している（例：HDMI 未検出で描画先がない）
        items.append(_item("SVC", "表示プログラム", BAD,
                           f"起動に失敗し続けています（直近10分で {info['recent_starts']} 回起動）",
                           "天気画面が出ていません。下の「直近の警告・エラー」と「画面出力」を確認"))
    else:
        restarts = svc.get("restarts", 0)
        items.append(_item("SVC", "表示プログラム", WARN if restarts else OK,
                           f"稼働中 {_uptime(svc.get('uptime_s'))}",
                           f"異常終了からの自動再起動 {restarts} 回（ログを確認）" if restarts else ""))

    disp = info.get("display")
    if disp is not None:
        connected = [k for k, v in disp.get("hdmi", {}).items() if v == "connected"]
        if disp.get("fb0"):
            items.append(_item("DSP", "画面出力", OK, f"fb0 {disp['fb0']}" + (f"・{'/'.join(connected)} 接続" if connected else "")))
        elif connected:
            items.append(_item("DSP", "画面出力", OK, f"{'/'.join(connected)} 接続"))
        else:
            items.append(_item("DSP", "画面出力", BAD, "画面出力なし（HDMI 未検出）",
                               "画面なしで天気などの取得は続けています。HDMI をつなぐと 1 分ほどで表示を始めます。"
                               "始まらなければテレビの電源・入力切替・HDMI ケーブルを確認して再起動（sudo reboot）。"
                               "テレビが消えていても起動できる設定は README「トラブルシューティング」"))

    kind, sig = info.get("conn_kind"), info.get("signal")
    if kind == "wifi":
        lvl = WARN if sig is not None and sig < 40 else OK
        items.append(_item("NET", "ネットワーク", lvl,
                           f"WiFi「{info.get('ssid') or '?'}」" + (f" 電波 {sig}%" if sig is not None else "") + f" / {info.get('ip')}",
                           "電波が弱いです（ルーターとの距離・向きを確認）" if lvl == WARN else ""))
    elif kind == "ethernet":
        items.append(_item("NET", "ネットワーク", OK, f"有線LAN / {info.get('ip')}"))
    elif kind == "hotspot":
        items.append(_item("NET", "ネットワーク", WARN, f"設定用テザリングで仮接続中 / {info.get('ip')}",
                           "通常の WiFi を登録してください"))
    else:
        items.append(_item("NET", "ネットワーク", BAD, "未接続"))

    ntp = info.get("ntp_synced")
    items.append(_item("NTP", "時刻同期", OK if ntp == "yes" else WARN,
                       "同期済み" if ntp == "yes" else ("未同期" if ntp == "no" else "確認できません"),
                       "" if ntp == "yes" else "時刻がずれていると取得の予定が狂います"))

    snap = info.get("snap")
    items.append(_weather_item(now, snap, info.get("interval_hours", 1.0)))
    items.append(_jma_item(now, snap))
    items.append(_wbgt_item(now, snap))
    items.append(_aviation_item(now, snap, info.get("icao")))
    items.append(_thunder_item(now, snap))
    items.append(_rain_item(now, snap))
    items.append(_rainfc_item(now, snap))
    items.append(_taf_item(now, snap, info.get("icao")))

    t = info.get("temp")
    if t is None:
        items.append(_item("TMP", "本体温度", INFO, "確認できません"))
    else:
        lvl = OK if t < 70 else (WARN if t < 80 else BAD)
        items.append(_item("TMP", "本体温度", lvl, f"{t:.0f}℃",
                           "" if lvl == OK else "熱がこもっています（設置場所・ケースの通気を確認）"))

    th = info.get("throttled")
    if th is None:
        items.append(_item("PWR", "電源", INFO, "確認できません"))
    else:
        now_bits = [v for k, v in _THROTTLE_NOW.items() if th & k]
        past_bits = [v for k, v in _THROTTLE_PAST.items() if th & k]
        if now_bits:
            items.append(_item("PWR", "電源", BAD, "今 " + "・".join(now_bits) + " が起きています",
                               "電源アダプタ（5V 2.5A 以上）・USB ケーブルを交換してください"))
        elif past_bits:
            items.append(_item("PWR", "電源", WARN, "起動後に " + "・".join(past_bits) + " がありました",
                               "電源アダプタ・USB ケーブルが弱い可能性があります"))
        else:
            items.append(_item("PWR", "電源", OK, "問題なし"))

    free = info.get("disk_free_gb")
    parts = []
    if info.get("cpu") is not None:
        parts.append(f"CPU {info['cpu']:.0f}%" + ("（1分平均）" if info.get("cpu_avg") else ""))
    if info.get("mem") is not None:
        parts.append(f"メモリ {info['mem']:.0f}%")
    if free is not None:
        parts.append(f"SD 空き {free:.1f}GB")
    lvl = OK
    detail = ""
    if free is not None and free < 0.3:
        lvl, detail = BAD, "SD カードの空きがほとんどありません"
    elif (free is not None and free < 1.0) or (info.get("mem") or 0) > 90:
        lvl, detail = WARN, "空き容量・メモリが少なくなっています"
    items.append(_item("SYS", "CPU / メモリ / SD", lvl, " / ".join(parts) or "確認できません", detail))

    worst = max((_ORDER[i["level"]] for i in items), default=0)
    overall = {0: OK, 1: WARN, 2: BAD}[worst]
    return {
        "overall": overall,
        "codes": [i["code"] for i in items if i["level"] in (WARN, BAD)],
        "items": items,
        "airport": info.get("airport_name", ""),
        "ip": info.get("ip", ""),
        "version": info.get("version", ""),
        "problems": info.get("problems", []),
        "accuracy": info.get("accuracy", []),
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def diagnose() -> dict:
    return evaluate(collect(), datetime.datetime.now(JST))
