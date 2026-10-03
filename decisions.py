"""
decisions.py
メインループの「判断」部分（入力 → 答え。画面・通信・ファイルには触らない）。
main01.py の main() から取り出したもので、判断の内容は変えていない。tests/test_decisions.py で検証する。
"""

import datetime

WEATHER_REFRESH_START_HOUR = 5   # この時刻より後（6時〜23時台）だけ定期取得する


def decide_snapshot(snap, airport: str, synced: bool, now_ts: float,
                    interval_hours: float, table_start: str) -> dict:
    """起動時に前回の表示データ（スナップショット）をどう使うかを決める。

    戻り値:
      snap          空港が違えば None（使わない）
      weather_fresh 天気を前回データで表示するか
      kick_fetch    表示しつつ、すぐ裏で天気を取り直すか（時刻未同期のとき）
      jma_fresh     警報・天気概況を前回値のまま使うか（1時間以内）
      wbgt_fresh    WBGT を前回値のまま使うか（1時間以内）
    """
    if snap and snap.get("airport") != airport:
        snap = None
    if synced:
        # 時刻が正しい：同じ空港・interval 以内・同じ日の表なら前回データで表示し、取得も省略
        weather_fresh = bool(
            snap and snap.get("hourly")
            and now_ts - snap.get("weather_at", 0) < interval_hours * 3600
            and snap.get("table_start") == table_start
        )
        kick_fetch = False
    else:
        # 時刻が未確定：新しさは判断できないが、前回データがあればまず表示し、すぐ裏で取り直す
        weather_fresh = bool(snap and snap.get("hourly"))
        kick_fetch = weather_fresh
    jma_fresh = bool(synced and snap and now_ts - snap.get("jma_at", 0) < 3600)
    wbgt_fresh = bool(synced and snap and now_ts - snap.get("wbgt_at", 0) < 3600)
    return {"snap": snap, "weather_fresh": weather_fresh, "kick_fetch": kick_fetch,
            "jma_fresh": jma_fresh, "wbgt_fresh": wbgt_fresh}


def should_fetch_2350(now: datetime.datetime, done_date: str, fetch_pending: bool) -> bool:
    """23:50 の定時取得をするか（1日1回）"""
    if now.hour == 23 and now.minute == 50:
        return done_date != now.strftime("%Y-%m-%d") and not fetch_pending
    return False


def should_fetch_0600(now: datetime.datetime, last_weather_update: datetime.datetime,
                      done_date: str, fetch_pending: bool) -> bool:
    """6:00 の定時取得をするか。
    時間別の表は 6 時で「今日の 6 時〜」に切り替わるが、夜間は取得を先送りするため次の定期取得が
    7:50 頃になる。それまで前日の列が残らないよう取り直す。
    6:00〜6:09 の間に 1 日 1 回（起動直後などで 6 時以降のデータが既にあれば不要）。"""
    if now.hour == 6 and now.minute < 10:
        fetched_after_6 = last_weather_update.date() == now.date() and last_weather_update.hour >= 6
        return done_date != now.strftime("%Y-%m-%d") and not fetch_pending and not fetched_after_6
    return False


def periodic_fetch_action(now: datetime.datetime, last_weather_update: datetime.datetime,
                          fetch_pending: bool, interval_hours: float):
    """定期取得の判断。'fetch'（取得する）/ 'postpone'（夜間なので次回へ先送り）/ None（まだ）"""
    if not fetch_pending and (now - last_weather_update).total_seconds() >= interval_hours * 3600:
        if WEATHER_REFRESH_START_HOUR < now.hour <= 23:
            return "fetch"
        return "postpone"
    return None


def retry_base_after_failure(now: datetime.datetime, interval_hours: float) -> datetime.datetime:
    """取得失敗時の last_weather_update。定期取得の判断で 30 分後に再試行になるように戻す"""
    return now - datetime.timedelta(hours=interval_hours) + datetime.timedelta(minutes=30)


AVIATION_START_HOUR = 6          # 航空気象は 6 時台から取得・表示（0:00〜5:59 は取得せず、帯も出さない）
AVIATION_SLOT_MINUTES = (5, 35)  # 日本の主な空港の METAR は毎時 00・30 分に発表 → その 5 分後に取得


def aviation_slot(now: datetime.datetime):
    """今が属する取得枠（直近の 05分 または 35分）。0:00〜6:04 は取得しないので None"""
    if now.minute >= AVIATION_SLOT_MINUTES[1]:
        slot = now.replace(minute=AVIATION_SLOT_MINUTES[1], second=0, microsecond=0)
    elif now.minute >= AVIATION_SLOT_MINUTES[0]:
        slot = now.replace(minute=AVIATION_SLOT_MINUTES[0], second=0, microsecond=0)
    else:
        slot = (now - datetime.timedelta(hours=1)).replace(minute=AVIATION_SLOT_MINUTES[1], second=0, microsecond=0)
    if slot.date() != now.date() or slot.hour < AVIATION_START_HOUR:
        return None
    return slot


def should_fetch_aviation(now: datetime.datetime, last_slot) -> bool:
    """航空気象（METAR）を取得するか：毎時 05・35 分の枠ごとに1回（6:05〜23:35、1日36回）。
    起動直後や取得し損ねたときは、その枠の時間内なら取得する"""
    slot = aviation_slot(now)
    return slot is not None and slot != last_slot


def aviation_band_visible(now: datetime.datetime) -> bool:
    """帯を出す時間帯か（0:00 ちょうどに消し、6 時台の取得で再表示）"""
    return now.hour >= AVIATION_START_HOUR
