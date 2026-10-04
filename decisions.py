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


AVIATION_START_HOUR = 6          # 航空気象は 6 時台から取得・表示（0:00〜6:06 は取得せず、0:00 に帯を消す）
# 観測（毎時 00・30 分）から最初の取得までの待ち時間（分）。NOAA に届くまでの実測（2026-10-04 成田 28 回）：
# 00 分の観測は 7〜10 分後（7 分が最多）、30 分の観測は 9〜12 分後（10〜11 分が多い）
AVIATION_FIRST_WAIT_MIN = {0: 7, 30: 10}
AVIATION_RETRY_STEP_MIN = 2      # 新しい観測がまだ届いていなければ 2 分おきに取り直す
AVIATION_MAX_ATTEMPTS = 6        # 1回の観測につき最大 6 回（例 00 分 → :07〜:17、30 分 → :40〜:50）


def aviation_expected_obs(now: datetime.datetime):
    """今の時刻で取れているはずの観測時刻（直近の 00/30 分のうち、最初の取得までの待ち時間がたったもの）。
    0:00〜6:06 は取得しないので None"""
    mark = now.replace(minute=30 if now.minute >= 30 else 0, second=0, microsecond=0)
    if now < mark + datetime.timedelta(minutes=AVIATION_FIRST_WAIT_MIN[mark.minute]):
        mark -= datetime.timedelta(minutes=30)
    if mark.date() != now.date() or mark.hour < AVIATION_START_HOUR:
        return None
    return mark


def aviation_fetch_due(now: datetime.datetime, latest_obs, last_attempt):
    """航空気象（METAR）を今取得するか。取得するなら「試行の区切り」を返す（次回 last_attempt に渡す）。取得しないなら None。

    - 期待する観測（直近の 00/30 分）がまだ無ければ、2 分ごとの区切りで1回ずつ、最大6回取得する
    - 期待する観測（またはそれより新しい観測）が取れていれば取得しない
    - まだ何も取れていない（起動直後・通信障害）ときは、6 時台以降なら 2 分ごとに取得を試みる
    """
    mark = aviation_expected_obs(now)
    if mark is None:
        return None
    waited = (now - mark).total_seconds() // 60 - AVIATION_FIRST_WAIT_MIN[mark.minute]
    attempt = (mark, int(waited) // AVIATION_RETRY_STEP_MIN)
    if attempt == last_attempt:
        return None
    if latest_obs is None:
        return attempt
    if latest_obs >= mark or attempt[1] >= AVIATION_MAX_ATTEMPTS:
        return None
    return attempt


def aviation_band_visible(now: datetime.datetime) -> bool:
    """帯を出す時間帯か（0:00 ちょうどに消し、6 時台の取得で再表示）"""
    return now.hour >= AVIATION_START_HOUR
