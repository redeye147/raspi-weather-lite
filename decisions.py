"""
decisions.py
メインループの「判断」部分（入力 → 答え。画面・通信・ファイルには触らない）。
main01.py の main() から取り出したもので、判断の内容は変えていない。tests/test_decisions.py で検証する。
"""

import datetime

WEATHER_REFRESH_START_HOUR = 5   # この時刻より後（6時〜23時台）だけ定期取得する

# 朝 6 時からサイネージを見られるよう、6 時前に最新にしておく（2026-10-30）
MORNING_FETCH = datetime.time(5, 45)   # 天気（予報・警報・概況）を取り直す。気象庁の朝の発表（5 時）を反映
MORNING_FETCH_END = datetime.time(6, 10)


TABLE_COVER_HOURS = 24     # 前回の表の始まりがこれより前なら、今の時間帯から先が足りないとみなす


def _covers(snap_start: str, now_start: str) -> bool:
    """前回の表（snap_start から 3 時間ごと 12 列＝36 時間）が、今の時間帯（now_start）から先を十分に含むか。
    表は今の時間帯から並べる（table_cols.py）ので、日付をまたいでも 24 時間以内に始まった表なら使える"""
    try:
        a = datetime.datetime.strptime(snap_start, "%Y-%m-%dT%H")
        b = datetime.datetime.strptime(now_start, "%Y-%m-%dT%H")
    except ValueError:
        return False
    return datetime.timedelta(0) <= b - a <= datetime.timedelta(hours=TABLE_COVER_HOURS)


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
            and _covers(snap.get("table_start", ""), table_start)   # 前回の表が今の時間帯から先を含む
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
    """朝の定時取得をするか（名前は以前の 6:00 のまま。今は 5:45）。
    夜間（0:00〜5:59）は取得しないので、6 時に画面を見たときに最新になっているよう 5:45 に取り直す。
    5:45〜6:09 の間に 1 日 1 回（失敗したら 6:09 まで取り直す。5:40 以降のデータが既にあれば不要）。"""
    t = now.time()
    if MORNING_FETCH <= t < MORNING_FETCH_END:
        prep = datetime.datetime.combine(now.date(), datetime.time(5, 40), now.tzinfo)
        try:
            fetched = last_weather_update >= prep
        except TypeError:                              # 時刻の持ち方が違う（テストなど）ときは取る
            fetched = False
        return done_date != now.strftime("%Y-%m-%d") and not fetch_pending and not fetched
    return False


def periodic_fetch_action(now: datetime.datetime, last_weather_update: datetime.datetime,
                          fetch_pending: bool, interval_hours: float):
    """定期取得の判断。'fetch'（取得する）/ None（まだ）。
    2026-10-31 から夜も取る（夜勤の人も見るので。以前は CPU を下げるため 0:00〜5:59 は 'postpone' で先送りしていた）"""
    if not fetch_pending and (now - last_weather_update).total_seconds() >= interval_hours * 3600:
        return "fetch"
    return None


STARTUP_REFRESH_DELAY_S = 300   # 前回データで起動したときは、起動が落ち着いた 5 分後に最新を取り直す


def startup_refresh_action(now: datetime.datetime, now_ts: float, refresh_at, fetch_pending: bool,
                           fetched_since_boot: bool):
    """前回データ（2 時間以内）で即表示して起動したあとの取り直し。'fetch' / 'cancel'（不要になった）/ None（まだ）
    - 起動 5 分後に 1 回だけ。それより前に別の取得（定期・6:00 など）で最新になっていれば取り消す
    （2026-10-31 から夜も取るので、夜でも取り消さない）"""
    if refresh_at is None:
        return None
    if fetched_since_boot:
        return "cancel"
    if now_ts >= refresh_at and not fetch_pending:
        return "fetch"
    return None


def retry_base_after_failure(now: datetime.datetime, interval_hours: float) -> datetime.datetime:
    """取得失敗時の last_weather_update。定期取得の判断で 30 分後に再試行になるように戻す"""
    return now - datetime.timedelta(hours=interval_hours) + datetime.timedelta(minutes=30)


AVIATION_START_HOUR = 6          # 航空気象の帯は 6 時台から表示（0:00 に帯を消す）
AVIATION_START = datetime.time(0, 0)    # 1 日中取得する（2026-10-31 から。夜勤の人も見るので、夜の「今」も観測に）
# 観測（毎時 00・30 分）から最初の取得までの待ち時間（分）。NOAA に届くまでの実測（2026-10-04 成田 28 回）：
# 00 分の観測は 7〜10 分後（7 分が最多）、30 分の観測は 9〜12 分後（10〜11 分が多い）
AVIATION_FIRST_WAIT_MIN = {0: 7, 30: 10}
AVIATION_RETRY_STEP_MIN = 2      # 新しい観測がまだ届いていなければ 2 分おきに取り直す
AVIATION_MAX_ATTEMPTS = 6        # 1回の観測につき最大 6 回（例 00 分 → :07〜:17、30 分 → :40〜:50）
AVIATION_STALE_EVERY_STEPS = 5   # 手元の観測が古いときは、6 回のあとも 5 区切り（10 分）ごとに取りに行く


def aviation_expected_obs(now: datetime.datetime):
    """今の時刻で取れているはずの観測時刻（直近の 00/30 分のうち、最初の取得までの待ち時間がたったもの）。
    0:00〜6:06 は取得しないので None"""
    mark = now.replace(minute=30 if now.minute >= 30 else 0, second=0, microsecond=0)
    if now < mark + datetime.timedelta(minutes=AVIATION_FIRST_WAIT_MIN[mark.minute]):
        mark -= datetime.timedelta(minutes=30)
    if mark.date() != now.date() or mark.time() < AVIATION_START:
        return None
    return mark


def aviation_fetch_due(now: datetime.datetime, latest_obs, last_attempt):
    """航空気象（METAR）を今取得するか。取得するなら「試行の区切り」を返す（次回 last_attempt に渡す）。取得しないなら None。

    - 期待する観測（直近の 00/30 分）がまだ無ければ、2 分ごとの区切りで1回ずつ、最大6回取得する
    - 期待する観測（またはそれより新しい観測）が取れていれば取得しない
    - まだ何も取れていない（起動直後・通信障害）ときは、6 時台以降なら 2 分ごとに取得を試みる
    - 手元の観測が 1 つ前の観測より古い（停止・通信障害のあとの起動など）ときも、最大 6 回で諦めず
      まず 6 回は 2 分ごと、その後は 10 分ごとに取りに行く（次の観測の取得時刻まで待たない）
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
    if latest_obs >= mark:
        return None
    if attempt[1] < AVIATION_MAX_ATTEMPTS:
        return attempt
    stale = latest_obs < mark - datetime.timedelta(minutes=30)
    first_for_mark = last_attempt is None or last_attempt[0] != mark   # 起動直後など、この観測ではまだ1回も取りに行っていない
    return attempt if stale and (first_for_mark or attempt[1] % AVIATION_STALE_EVERY_STEPS == 0) else None


def aviation_band_visible(now: datetime.datetime) -> bool:
    """帯を出す時間帯か（0:00 ちょうどに消し、6 時台の取得で再表示）"""
    return now.hour >= AVIATION_START_HOUR


WBGT_START_HOUR = 6              # （以前の取得開始。今は WBGT_START）
WBGT_START = datetime.time(5, 45)   # WBGT は 5:45〜23 時台だけ取得（6 時に画面を見たときバッジが出ているように）


def wbgt_active(now: datetime.datetime) -> bool:
    """WBGT を取りに行く時間帯か（5:45〜23:59）"""
    return now.time() >= WBGT_START
WBGT_INTERVAL_MIN = 60           # 通常は 1 時間ごと
WBGT_RECENT_DATA_DAYS = 2        # 直近 2 日以内に値が取れていれば、データなしは一時的とみなして 1 時間後に再確認


def wbgt_off_season(now: datetime.datetime, last_status, last_data_at) -> bool:
    """提供期間外とみなすか。「データなし」が返り、かつ直近 2 日以上値が取れていないとき。
    期間（例 4/22〜10/21）は年ごとに変わるので日付では決めず、データの有無で判断する"""
    if last_status != "nodata":
        return False
    return last_data_at is None or now - last_data_at > datetime.timedelta(days=WBGT_RECENT_DATA_DAYS)


def wbgt_fetch_due(now: datetime.datetime, last_attempt, last_status, last_data_at) -> bool:
    """WBGT を今取得するか。
    - 0:00〜5:44 は取得しない
    - 通常（値あり・通信エラー）は前回の取得から 1 時間ごと
    - 提供期間外（wbgt_off_season）は 1 日 1 回（朝 6 時、その日まだ確認していなければ）。翌年の開始も自動で見つける
    """
    if not wbgt_active(now):
        return False
    if last_attempt is None:
        return True
    if wbgt_off_season(now, last_status, last_data_at):
        return last_attempt.date() != now.date()
    return now - last_attempt >= datetime.timedelta(minutes=WBGT_INTERVAL_MIN)


def wbgt_badge_visible(now: datetime.datetime, data_at) -> bool:
    """バッジ・熱中症アラートを出すか。値は「その日の最高予測」なので、取得した日のうちだけ（0:00 に消す）"""
    return data_at is not None and data_at.date() == now.date()
