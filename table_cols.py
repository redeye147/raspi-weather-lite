"""
table_cols.py
今日の天気の表の列を、見る時刻に合わせて並べる（2026-10-30）。

  今 20:50 │ 〜21 │ 21 │ 00 │ 03 │ …
  ・「今」     ：空港の観測（天気・気温・風）と雨雲レーダーの今の雨（観測が無ければ今の 3 時間帯の予報）
  ・「〜21」   ：今の 3 時間帯の残りの予報（残りが 1 時間より短いときは出さない）
  ・その右     ：次の 3 時間帯からの予報
過ぎた時間帯の列は出さない。屋外に出る人が「今」と「このあと」を切れ目なく見られるように
（以前は朝 6 時〜翌朝 9 時の決まった表で、今の時間帯の列に観測を重ねていたため、同じ列でも
 18:01 と 20:59 で意味が違い、今の時間帯の残りの予報も見えなかった）。
"""

import datetime

LAYOUTS = {                   # 表の形（config.json の "table_layout"。設定画面で選ぶ）
    "fixed": "今まで（朝6時〜翌朝9時。今の時間帯の列を観測で置き換え）",
    "insert": "今を割り込ませる（6〜24時は朝6時から、0〜6時は前日18時から。今の時間帯の右に「今」）",
    "now": "今から並べる（今・今の時間帯の残り・その先）",
}
TABLE_COLS = 10               # 表の列の数
REST_MIN_MINUTES = 60         # 今の 3 時間帯の残りがこれより短ければ「〜21」の列を出さない


_CALM_ORDER = {"200": 2, "101": 1, "100": 0}


def _worst(codes):
    """いちばん悪い天気（雷＞大雨・大雪＞…＞曇り＞晴時々曇＞晴）"""
    from fc_blend import _rank
    return max(codes, key=lambda c: (_rank(c), _CALM_ORDER.get(str(c), 0)))


def fill_with_observed(item, observed):
    """過ぎた 3 時間の列を、記録した毎時 00 分の観測（verify.observed_hours）で埋めた写し（観測が無ければ item のまま）。
    天気は 3 回のうちいちばん悪い天気、気温は平均、風速はいちばん強い値（その風向）、降水量は雨雲レーダーのいちばん強い値"""
    start = item.get("datetime")
    if not isinstance(start, datetime.datetime) or not observed:
        return item
    rows = [observed.get((start + datetime.timedelta(hours=h)).strftime("%Y-%m-%d %H:%M")) for h in range(3)]
    rows = [r for r in rows if r]
    if not rows:
        return item
    out = dict(item, past_observed=True)
    codes = [r["code"] for r in rows if r.get("code")]
    if codes:
        out["code"] = _worst(codes)
    temps = [r["temp"] for r in rows if r.get("temp") is not None]
    if temps:
        t = round(sum(temps) / len(temps))
        out.update(temp_val=t, temp=f"{t}℃")
    winds = [r for r in rows if r.get("wind") is not None]
    if winds:
        w = max(winds, key=lambda r: r["wind"])
        out.update(wind_val=round(w["wind"]), wind=f"{round(w['wind'])}m", wind_dir=w.get("wind_dir"),
                   wind_variable=w.get("wind_dir") is None and round(w["wind"]) > 0)
    radar = [r["radar_mmh"] for r in rows if r.get("radar_mmh") is not None]
    if radar:
        out["pop"] = f"{max(radar):.1f}mm"
    return out


def build_insert(hourly, now, observe=None, observed=None):
    """案 D：決まった表（hourly。6 時か前の日の 18 時から 9 列）の、今の時間帯の列の右に「今」の列を割り込ませる。
    今の時間帯の列は予報のまま（残りの時間の予報も見える）。「今」は観測。
    observed（verify.observed_hours）を渡すと、過ぎた時間帯の列を記録した観測で埋める（2026-10-31）"""
    import weather_draw
    cur = weather_draw.current_slot_index(hourly, now)
    if cur is None:
        return list(hourly[:TABLE_COLS])
    if observed:
        hourly = [fill_with_observed(it, observed) if i < cur else it for i, it in enumerate(hourly)]
    observed = observe(hourly, cur) if observe else hourly
    now_item = dict(observed[cur], hour=f"今 {now:%H:%M}", slot_hour=hourly[cur].get("hour"), is_now=True,
                    datetime=now.replace(second=0, microsecond=0))
    return (list(hourly[:cur + 1]) + [now_item] + list(hourly[cur + 1:]))[:TABLE_COLS]


def build(hourly, now, observe=None):
    """案 C：hourly（予報。3 時間ごと・今の時間帯から先）から、表に出す列を作る。
    observe(hourly, cur) は cur 列を観測で置き換えた写しを返す関数（obs_now.apply_observation など）"""
    import weather_draw
    cur = weather_draw.current_slot_index(hourly, now)
    if cur is None:
        return list(hourly[:TABLE_COLS])
    s0 = hourly[cur]
    start = s0["datetime"]
    end = hourly[cur + 1]["datetime"] if cur + 1 < len(hourly) else start + datetime.timedelta(hours=3)
    observed = observe(hourly, cur) if observe else hourly
    now_item = dict(observed[cur], hour=f"今 {now:%H:%M}", slot_hour=s0.get("hour"), is_now=True, datetime=start)
    cols = [now_item]
    if (end - now) >= datetime.timedelta(minutes=REST_MIN_MINUTES):
        cols.append(dict(s0, hour=f"〜{end:%H}", slot_hour=s0.get("hour"),
                         datetime=now.replace(second=0, microsecond=0)))
    cols += hourly[cur + 1:]
    return cols[:TABLE_COLS]
