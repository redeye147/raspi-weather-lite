"""
diagnostics.py
診断ページ（WiFi ポータルの /diag）用：本体と表示プログラムの状態を集めて、項目ごとに 正常／注意／異常 を判定する。
見るだけ（何も変更しない）。collect() が情報を集め、evaluate() が判定する（判定は tests/test_diagnostics.py で検証）。
"""

import datetime
import json
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


def _local_ip():
    out = _run(["hostname", "-I"])
    return (out or "").split()[0] if out else ""


def _git_version():
    env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory", GIT_CONFIG_VALUE_0=BASE_DIR)
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h %cd", "--date=format:%Y-%m-%d %H:%M"],
                             cwd=BASE_DIR, capture_output=True, text=True, timeout=5, env=env).stdout.strip()
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=BASE_DIR, capture_output=True, text=True, timeout=5, env=env).stdout.strip()
        return f"{br} {out}".strip()
    except Exception:
        return ""


def recent_problems(log_path=LOG_FILE, limit=10):
    """ログの WARNING / ERROR の行を新しい順に最大 limit 件（今日のファイル → 前日のファイル）"""
    paths = [log_path]
    yesterday = (datetime.datetime.now(JST) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    paths.append(f"{log_path}.{yesterday}")
    found = []
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = [l.rstrip("\n") for l in f if "| WARNING |" in l or "| ERROR |" in l]
        except OSError:
            continue
        found.extend(reversed(lines))
        if len(found) >= limit:
            break
    return found[:limit]


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
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
    except Exception:
        cpu = mem = None
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
        "interval_hours": float(cfg.get("interval_hours", 2.0)),
        "service": _service_info(),
        "conn_kind": get_connection_kind(),
        "ssid": ssid, "signal": signal, "ip": _local_ip(),
        "ntp_synced": _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]),
        "temp": _cpu_temp(), "throttled": _throttled(),
        "cpu": cpu, "mem": mem, "load1": load1, "disk_free_gb": free_gb,
        "snap": snap,
        "version": _git_version(),
        "problems": recent_problems(),
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
                     f"6時間ごとに確認中（最後の確認 {_hm(attempt)}）")
    if not attempt:
        return _item("WBGT", "WBGT（熱中症）", WARN, "データなし", "まだ取得していません")
    age = now.timestamp() - attempt
    lv = (snap.get("wbgt_level_info") or {})
    val = f"{lv['label']} {lv['value']:.1f}℃" if lv and data_dt and data_dt.date() == now.date() else "25℃未満（バッジなし）"
    if status == "error":
        return _item("WBGT", "WBGT（熱中症）", WARN, f"取得失敗（{_hm(attempt)}）", "通信エラー。1時間後に再取得します")
    if now.hour < WBGT_START_HOUR:
        return _item("WBGT", "WBGT（熱中症）", OK, "夜間は取得なし（6時から）", f"最後の取得 {_hm(attempt)}")
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


def evaluate(info: dict, now: datetime.datetime) -> dict:
    """集めた情報から、項目ごとの判定と総合判定を返す"""
    items = []

    svc = info.get("service")
    if not svc:
        items.append(_item("SVC", "表示プログラム", WARN, "状態を確認できません"))
    elif svc["active"] != "active":
        items.append(_item("SVC", "表示プログラム", BAD, f"停止中（{svc['active']}/{svc['sub']}）",
                           "天気画面が止まっています。sudo systemctl restart main01"))
    else:
        restarts = svc.get("restarts", 0)
        items.append(_item("SVC", "表示プログラム", WARN if restarts else OK,
                           f"稼働中 {_uptime(svc.get('uptime_s'))}",
                           f"異常終了からの自動再起動 {restarts} 回（ログを確認）" if restarts else ""))

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
    items.append(_weather_item(now, snap, info.get("interval_hours", 2.0)))
    items.append(_jma_item(now, snap))
    items.append(_wbgt_item(now, snap))
    items.append(_aviation_item(now, snap, info.get("icao")))

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
        parts.append(f"CPU {info['cpu']:.0f}%")
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
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def diagnose() -> dict:
    return evaluate(collect(), datetime.datetime.now(JST))
