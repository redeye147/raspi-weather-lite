# weather_draw.py
"""
weather_draw.py
E61c draw_weather 完全互換移植版 (lite: Pi Zero W 最適化)

変更点:
- フォントオブジェクトを get_font() でキャッシュ（毎フレーム生成を廃止）
- アイコンをスケール済みサーフェスごとキャッシュ（毎フレーム transform.scale を廃止）
- 作業サマリーを静的表示に変更（スクロールアニメーション廃止）
"""

import math
import os
import pygame
import datetime
import re

from config import ICON_DIR
from utils import (
    JST,
    get_last_ip_octet,
    get_japanese_weekday,
    get_font,
    make_qr_surface,
    sun_times,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(BASE_DIR, "weather_icons")

# 天気概況の最大行数（読みやすさ優先で短く）
OVERVIEW_MAX_LINES = 3

# 月アイコンにする列（日の出・日の入りの時刻によらず一律）
NIGHT_HOURS = {"18", "21", "00", "03"}
# 時刻の行のマスの色：昼（06・09・12・15）と夜（18・21・00・03）。月のアイコンと同じ固定の区分。
# 50 インチのテレビを離れて見ても昼夜がわかるよう、上から下へのグラデーション（昼＝黄→白、夜＝紺→青。夜は数字を白）
TIME_DAY_TOP, TIME_DAY_BOTTOM = (255, 225, 140), (255, 251, 236)   # 2026-10 に一段薄く（以前 (255,210,90)→(255,248,225)）
# 2026-10 に 3 段階薄く（(35,50,115)→(95,120,190) は濃すぎ、(70,95,170)→(130,155,215)、(120,145,210)→(185,202,240) もまだ濃い）。薄いので数字は黒
TIME_NIGHT_TOP, TIME_NIGHT_BOTTOM = (160, 180, 228), (212, 223, 247)
TIME_NIGHT_TEXT = (0, 0, 0)
# 夜のマス（紺）に日の出・日の入りの印が入るときの色（ふだんの紺・濃い橙では見えないため）
SUNSET_ON_NIGHT = (25, 25, 110)        # 夜のマスは薄い青なので、ふだんより少し濃い紺
SUNRISE_TEXT_ON_NIGHT = (150, 55, 0)   # 同じく、ふだんより少し濃い橙
WIND_BOLD_FROM = 9                     # 風速の数字を太字にするのは 9 m/s 以上
WIND_ARROW_SCALE = 0.72                # 矢印の大きさ（行の高さに対して。以前の 0.8 の 0.9 倍）


def _wrap_text(text, font, max_width):
    lines, cur = [], ""
    for ch in text:
        if font.size(cur + ch)[0] <= max_width:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _overview_outlook(text: str) -> str:
    """天気概況から「２７日は、…」のような日付ごとの見通し段落だけを抜き出す（無ければ全文）。"""
    paras = ["".join(p.split()) for p in (text or "").split("\n\n")]
    outlook = [p for p in paras if re.match(r"^[０-９0-9]{1,2}日(は|の)", p)]
    return "".join(outlook or paras)


SUNRISE_COLOR = (230, 120, 0)
SUNRISE_TEXT_COLOR = (185, 75, 0)   # 白背景で読めるよう濃いめ（コントラスト比 5.2）
SUNSET_COLOR = (40, 40, 140)


def _as_jst(dt):
    return dt.replace(tzinfo=JST) if dt.tzinfo is None else dt.astimezone(JST)


def _time_to_col(times, t):
    """t を時間別列の位置に換算（i = i 列目の左端 = その列の時刻。時刻の数字が左寄せのため）。
    表の範囲外（先頭列より前 / 最終列の区間より後）なら None。"""
    last = times[-1] - times[-2]
    if t < times[0] or t >= times[-1] + last:
        return None
    for i in range(len(times) - 1):
        if t < times[i + 1]:
            return i + (t - times[i]) / (times[i + 1] - times[i])
    return len(times) - 1 + (t - times[-1]) / last


NOW_FRAME_COLOR = (0, 110, 220)   # 今の時間帯の列の枠の色（青。いったん黒にしたが青に戻した）
NOW_FRAME_WIDTH = 4               # 枠の太さ（px。普段の罫線は 1）


def current_slot_index(hourly, now):
    """now が入っている時間別の列の番号（例 10:30 → 09 時の列）。表の範囲外・時刻が無い列なら None"""
    times = [item.get("datetime") for item in hourly]
    if not times or not all(isinstance(t, datetime.datetime) for t in times):
        return None
    times = [_as_jst(t) for t in times]
    now = _as_jst(now)
    for i, t in enumerate(times):
        end = times[i + 1] if i + 1 < len(times) else t + (t - times[i - 1] if i else datetime.timedelta(hours=3))
        if t <= now < end:
            return i
    return None


SUN_MARK_EDGE_GAP = 3   # ▲▼と列の右端（次の列）の間にあけるすき間（px）
SUN_LABEL_GAP = 12   # 日の出・日の入りの時刻ラベルと、次の列の時刻の数字の間にあけるすき間（px）


def _draw_sun_markers(screen, hourly, latitude, longitude, margin_x, col_w,
                      row_y, row_h, base_font_path):
    """時刻行に 日の出▲ / 日の入り▼ を実時刻の位置で描く。"""
    times = [item.get("datetime") for item in hourly]
    if len(times) < 2 or not all(isinstance(t, datetime.datetime) for t in times):
        return
    times = [_as_jst(t) for t in times]
    hour_font = get_font(base_font_path, 22)
    label_font = get_font(base_font_path, 16, bold=True)
    tri = max(8, int(row_h * 0.55))
    cy = row_y + row_h // 2
    n = len(times)

    for d in sorted({t.date() for t in times}):
        sunrise, sunset = sun_times(d, latitude, longitude)
        for t, is_rise in ((sunrise, True), (sunset, False)):
            pos = _time_to_col(times, t)
            if pos is None:
                continue
            ci = min(n - 1, int(pos))
            x = margin_x + (1 + pos) * col_w
            cell_x = margin_x + (1 + ci) * col_w
            text_right = cell_x + 5 + hour_font.size(hourly[ci]["hour"])[0]
            half = tri // 2
            # 自分の列の時刻の数字（例「03」）と重ならないよう右へ寄せる（最大でも数十分相当のずれ）
            x = int(max(x, text_right + 2 + tri / 2))
            # 次の列の時刻の数字（例「06」）とも重ならないよう、自分の列の中に収める
            # （05:58 のように境目の直前だと、▲が「06」に食い込んでいた。位置は数分ずれるが時刻はラベルで読める）
            x = min(x, cell_x + col_w - half - SUN_MARK_EDGE_GAP)

            on_night = night_mix(hourly, ci, (x - cell_x) / col_w) > 0.5   # 印のある所が夜の色（紺）
            color = SUNRISE_COLOR if is_rise else (SUNSET_ON_NIGHT if on_night else SUNSET_COLOR)
            if is_rise:
                pts = [(x, cy - half), (x - half, cy + half), (x + half, cy + half)]
            else:
                pts = [(x - half, cy - half), (x + half, cy - half), (x, cy + half)]
            pygame.draw.polygon(screen, color, pts)

            text = t.strftime("%H:%M")
            lw = label_font.size(text)[0]
            next_text_x = cell_x + col_w + 5
            right_x = x + half + 2
            left_x = x - half - 2 - lw
            # 右に置くと次の列の時刻（例「18」）にくっついて「17:0518」と読めるので、十分すき間があるときだけ右
            if right_x + lw <= next_text_x - SUN_LABEL_GAP and ci < n:
                lx = right_x
            elif left_x >= text_right + 2:
                lx = left_x
            else:
                continue
            # 文字の色は、文字のある所の背景（昼↔夜の移り変わりの途中もある）で決め、反対の色で縁取って読みやすく
            label_night = night_mix(hourly, ci, (lx + lw / 2 - cell_x) / col_w) > 0.45
            if is_rise:
                text_color = SUNRISE_TEXT_ON_NIGHT if label_night else SUNRISE_TEXT_COLOR
            else:
                text_color = SUNSET_ON_NIGHT if label_night else SUNSET_COLOR
            _blit_outlined(screen, label_font, text, text_color,
                           LABEL_OUTLINE_ON_NIGHT if label_night else LABEL_OUTLINE_ON_DAY,
                           (lx, cy - label_font.get_height() // 2))


LABEL_OUTLINE_ON_DAY = (255, 255, 255)
LABEL_OUTLINE_ON_NIGHT = (255, 255, 255)   # 夜のマスも薄い色なので白で縁取り


def _blit_outlined(screen, font, text, color, outline, pos):
    """縁取りした文字（背景の色が途中で変わっても読めるように）"""
    x, y = pos
    edge = font.render(text, True, outline)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        screen.blit(edge, (x + dx, y + dy))
    screen.blit(font.render(text, True, color), (x, y))


# 風向の矢印の色（風速 m/s の下限, 色）。よく使われる天気図の配色
WIND_ARROW_COLORS = [
    (18, (230, 40, 20)),     # 18 以上：赤
    (12, (240, 140, 20)),    # 12〜17：橙
    (8, (240, 225, 0)),      # 8〜11：黄
    (5, (70, 0, 255)),       # 5〜7：青紫
    (1, (70, 170, 255)),     # 1〜4：水色
    (0, (205, 210, 205)),    # 0：灰色
]
WIND_ARROW_OUTLINE = (90, 90, 90)        # 黄色・灰色でも白地で見えるように縁取り


def wind_arrow_color(speed):
    for low, color in WIND_ARROW_COLORS:
        if speed >= low:
            return color
    return WIND_ARROW_COLORS[-1][1]


# 風速の数字の色：5 m/s 未満はふつうの黒。5 以上は矢印と同じ区切り・色合い（黄は白地で読めないので文字だけ濃く）
_WIND_TEXT_DARKER = {(240, 225, 0): (185, 150, 0)}


WIND_LEGEND_LABELS = ["0", "1-4", "5-7", "8-11", "12-17", "18-"]   # WIND_ARROW_COLORS の区切りと同じ（弱い順）


def _draw_wind_legend(screen, base_font_path, right_x, top_y):
    """「風速(m/s) [0][1-4][5-7][8-11][12-17][18-]」の色の帯。各区切りを矢印の色で塗り、数字を中に書く"""
    font = get_font(base_font_path, 15, bold=True)
    h = 20
    colors = [c for _, c in reversed(WIND_ARROW_COLORS)]          # 弱い順
    widths = [font.size(t)[0] + 12 for t in WIND_LEGEND_LABELS]
    title = get_font(base_font_path, 16).render("風速(m/s)", True, (80, 80, 80))
    x = right_x - sum(widths) - title.get_width() - 6
    screen.blit(title, (x, top_y + (h - title.get_height()) // 2))
    x += title.get_width() + 6
    for label, color, w in zip(WIND_LEGEND_LABELS, colors, widths):
        pygame.draw.rect(screen, color, (x, top_y, w, h))
        light = sum(color) > 450                                    # 明るい色（灰・水色・黄）は黒い字
        t = font.render(label, True, (40, 40, 40) if light else (255, 255, 255))
        screen.blit(t, (x + (w - t.get_width()) // 2, top_y + (h - t.get_height()) // 2))
        x += w
    pygame.draw.rect(screen, WIND_ARROW_OUTLINE, (x - sum(widths), top_y, sum(widths), h), 1)


def wind_text_color(speed):
    if speed < 5:
        return (0, 0, 0)
    c = wind_arrow_color(speed)
    return _WIND_TEXT_DARKER.get(c, c)


def wind_arrow_points(cx, cy, size, deg):
    """風が吹いていく向きを指す矢じり（V 字）の頂点。deg は風が吹いてくる方角（0 = 北風 → 下向き）"""
    # どの向きに回しても直径 size の円に収まる大きさ（斜めにしても上下の行・隣の列にはみ出さない）
    r = size / 2
    # 細長い矢じり（以前は幅が広く正三角形に近く見えた）。h² + w² ≦ 1 で円に収まる
    h, w = r * 0.89, r * 0.44
    base = [(0, h), (w, -h), (0, -h * 0.10), (-w, -h)]     # 下（南）を指す形
    t = math.radians(deg)
    c, s_ = math.cos(t), math.sin(t)
    return [(cx + x * c - y * s_, cy + x * s_ + y * c) for x, y in base]


def draw_wind_arrow(screen, cx, cy, size, deg, speed):
    pts = wind_arrow_points(cx, cy, size, deg)
    pygame.draw.polygon(screen, wind_arrow_color(speed), pts)
    pygame.draw.polygon(screen, WIND_ARROW_OUTLINE, pts, 1)


CALM_MARK_COLOR = (150, 150, 150)


def draw_calm_mark(screen, cx, cy, size):
    """静穏（風速 0 m/s）の印「---」（風向が無いことを表す。矢印と同じ場所に、矢印の幅に収まる 3 本の短い線）"""
    seg = max(3, int(size * 0.22))
    gap = max(2, int(size * 0.12))
    total = seg * 3 + gap * 2
    x = int(cx - total / 2)
    th = max(2, size // 14)
    for _ in range(3):
        pygame.draw.rect(screen, CALM_MARK_COLOR, (x, int(cy - th / 2), seg, th))
        x += seg + gap


def night_mix(hourly, i, frac):
    """時刻の行の i 列目の、左端から frac（0〜1）の位置の「夜らしさ」（0 = 昼、1 = 夜）。
    昼と夜が変わる手前の列（15 時・03 時）の中で、なめらかに移り変わる（急に色が変わらないように）"""
    night = hourly[i].get("hour") in NIGHT_HOURS
    if i + 1 >= len(hourly) or (hourly[i + 1].get("hour") in NIGHT_HOURS) == night:
        return 1.0 if night else 0.0
    f = max(0.0, min(1.0, frac))
    s = f * f * (3 - 2 * f)                           # はじめと終わりをゆるやかに
    return 1.0 - s if night else s


_time_row_cache = {}


def _time_row_surface(hourly, col_w, row_h):
    """時刻の行の背景（全列ぶん）。上下は 上の色→下の色、左右は昼↔夜をなめらかにつなぐ。同じ並びなら作り直さない"""
    key = (tuple(h.get("hour") in NIGHT_HOURS for h in hourly), col_w, row_h)
    surf = _time_row_cache.get(key)
    if surf is None:
        # 上端の色・下端の色の 2 行だけを 1 画素ずつ作り、縦に引き伸ばす（引き伸ばしで上下の間がなめらかになる）。
        # 全部の画素を 1 つずつ塗るより十数倍速い（Pi Zero で 3 時間に 1 回、ほぼ一瞬）
        n = len(hourly)
        edge = pygame.Surface((col_w * n, 2))
        for px in range(col_w * n):
            t = night_mix(hourly, px // col_w, (px % col_w + 0.5) / col_w)
            edge.set_at((px, 0), tuple(int(TIME_DAY_TOP[k] + (TIME_NIGHT_TOP[k] - TIME_DAY_TOP[k]) * t) for k in range(3)))
            edge.set_at((px, 1), tuple(int(TIME_DAY_BOTTOM[k] + (TIME_NIGHT_BOTTOM[k] - TIME_DAY_BOTTOM[k]) * t)
                                       for k in range(3)))
        surf = pygame.transform.smoothscale(edge.convert(24) if edge.get_bitsize() not in (24, 32) else edge,
                                            (col_w * n, max(2, row_h)))
        if row_h < 2:
            surf = surf.subsurface((0, 0, col_w * n, row_h)).copy()
        _time_row_cache.clear()
        _time_row_cache[key] = surf
    return surf


# 週間予報の信頼度（気象庁）：A 確度が高い・B やや高い・C やや低い
# 緑の濃淡で「濃い＝確か・薄い＝あまり確かでない」。赤・橙は警報・高温など注意の意味に使うので避ける
# （A の緑に白を B 30%・C 82% 混ぜた色。C は地が薄いので文字を濃い緑に）
REL_COLORS = {"A": (0, 140, 70), "B": (76, 174, 126), "C": (209, 234, 222)}
REL_TEXT_COLORS = {"A": (255, 255, 255), "B": (255, 255, 255), "C": (0, 110, 55)}
REL_TEXT = {"A": "高い", "B": "やや高い", "C": "やや低い"}


def _draw_rel_badge(screen, base_font_path, rel, right_x, center_y, size):
    """信頼度の札（色の付いた四角に白い A・B・C）。right_x が右端、center_y が上下の真ん中"""
    if size < 10:
        return
    rect = pygame.Rect(0, 0, size, size)
    rect.midright = (right_x, center_y)
    pygame.draw.rect(screen, REL_COLORS[rel], rect, border_radius=max(2, size // 5))
    t = get_font(base_font_path, max(10, int(size * 0.75)), bold=True).render(rel, True, REL_TEXT_COLORS[rel])
    screen.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))


def _draw_rel_legend(screen, base_font_path, right_x, top_y, screen_h):
    """「信頼度 [A]高い [B]やや高い [C]やや低い」を、right_x を右端・top_y を上端にして描く（画面に入らなければ描かない）"""
    font = get_font(base_font_path, 16)
    size = 18
    parts = [("text", "信頼度")] + [p for r in ("A", "B", "C") for p in (("badge", r), ("text", REL_TEXT[r]))]
    widths = [size if k == "badge" else font.size(v)[0] for k, v in parts]
    gap = 5
    x = right_x - sum(widths) - gap * (len(parts) - 1)
    if top_y + size > screen_h - 1:
        return
    cy = top_y + size // 2
    for (k, v), w in zip(parts, widths):
        if k == "badge":
            _draw_rel_badge(screen, base_font_path, v, x + w, cy, size)
        else:
            t = font.render(v, True, (80, 80, 80))
            screen.blit(t, (x, cy - t.get_height() // 2))
        x += w + gap


def _is_night_item(item) -> bool:
    """18・21・00・03 時の列は夜（月アイコン）。日の出・日の入りの時刻では判断しない"""
    return item["hour"] in NIGHT_HOURS

# 「気　温」「風　速」は全角スペースで「降水量」と同じ 3 文字幅にし、右の絵の位置をそろえる
ROW_LABELS = ["日付", "時刻", "天気", "降水量", "気　温", "風　速"]
# 見出しの文字の右に付ける小さな絵（weather_icons/labels/）
LABEL_ICONS = {"降水量": "precip", "気　温": "temp", "風　速": "wind"}
LABEL_FONT_SIZE = 22
WEEK_ROW_LABELS = ["日付", "天気", "降水確率", "気温：最高／最低"]


def week_temp_font_size(base_font_path, max_t, min_t, bold, avail_w) -> int:
    """週間の気温「35℃／-10℃」が列（avail_w）に収まる文字の大きさ。22 から順に小さくし、最小 14"""
    for size in (22, 20, 18, 16, 14):
        w = (get_font(base_font_path, size, bold=bold).size(f"{max_t}℃")[0]
             + get_font(base_font_path, size).size("／")[0]
             + get_font(base_font_path, size).size(f"{min_t}℃")[0])
        if w <= avail_w:
            return size
    return 14


def draw_today_title_bar(
    screen,
    x, y, w, h,
    base_font_path,
    airport_name=None,
    weather_updated_text="",
    cpu_text="",
    qr_surf=None
):
    pygame.draw.rect(screen, (255, 255, 255), (x, y, w, h))

    title_font = get_font(base_font_path, 26, bold=True)
    title = "今日の天気"
    if airport_name:
        title += f"（{airport_name}）"

    ip_suffix = get_last_ip_octet()
    parts = []
    if weather_updated_text:
        parts.append(weather_updated_text)
    if ip_suffix:
        parts.append(f"{ip_suffix}")
    if cpu_text:
        parts.append(f"{cpu_text}")
    status = " / ".join(parts)

    status_font = get_font(base_font_path, 18)
    status_color = (80, 80, 80)
    status_surf = status_font.render(status, True, status_color) if status else None
    status_w = status_surf.get_width() if status_surf else 0

    qr_w = (qr_surf.get_width() + 6) if qr_surf else 0

    max_left_w = w - 16 - status_w - 12 - qr_w
    if max_left_w < 50:
        max_left_w = 50

    title_draw = title
    if title_font.size(title_draw)[0] > max_left_w:
        ell = "…"
        while title_draw and title_font.size(title_draw + ell)[0] > max_left_w:
            title_draw = title_draw[:-1]
        title_draw = title_draw + ell

    title_surf = title_font.render(title_draw, True, (0, 0, 0))
    screen.blit(title_surf, (x + 8, y + (h - title_surf.get_height()) // 2))

    if qr_surf:
        qr_x = x + w - qr_surf.get_width() - 4
        qr_y = y + (h - qr_surf.get_height()) // 2
        screen.blit(qr_surf, (qr_x, qr_y))
        right_edge = qr_x - 6
        # 天気更新 / IP / CPU は文字の下端（ベースライン）を QR コードの底辺にそろえる
        status_y = qr_y + qr_surf.get_height() - status_font.get_ascent()
    else:
        right_edge = x + w - 8
        status_y = y + (h - status_surf.get_height()) // 2 if status_surf else y

    if status_surf:
        screen.blit(status_surf, (right_edge - status_w, status_y))


ALERT_BANNER_H = 44
current_anim = None      # 最後に描いた画面の「今の時間帯のアイコン」{"rect", "icon_code"}（無ければ None）
ALERT_BANNER_H_DOUBLE = 28      # 雷と熱中症の帯が 2 本重なるときは細くする（1280×720 で表が画面の下にはみ出さないように）
SUMMARY_GAP_MIN_HEIGHT = 1000   # この高さ以上の画面で、作業注意情報の下に1行分の余白を入れる


def draw_alert_banner(screen, width, header_h, base_font_path, bh=ALERT_BANNER_H):
    """ヘッダー直下に熱中症警戒アラートバナーを表示。"""
    by = header_h
    pygame.draw.rect(screen, (160, 0, 0), (0, by, width, bh))
    pygame.draw.line(screen, (255, 60, 60), (0, by), (width, by), 3)
    pygame.draw.line(screen, (255, 60, 60), (0, by + bh - 1), (width, by + bh - 1), 2)
    f = get_font(base_font_path, 26 if bh >= ALERT_BANNER_H else 20, bold=True)
    text = "熱中症警戒アラート発令中 ― こまめな水分補給を！日陰で休憩を！"
    s = f.render(text, True, (255, 255, 180))
    screen.blit(s, ((width - s.get_width()) // 2, by + (bh - s.get_height()) // 2))


# 雷の帯：「雷接近」（10km 以内）は赤地に黄色、「雷注意」（20km 以内）は黄色地に黒
THUNDER_STYLE = {
    "near":  dict(bg=(160, 0, 0), edge=(255, 60, 60), fg=(255, 255, 180), bolt=(255, 230, 0)),
    "watch": dict(bg=(255, 200, 0), edge=(200, 140, 0), fg=(0, 0, 0), bolt=(120, 60, 0)),
}


def _draw_bolt(screen, x, y, h, color):
    """稲妻の形（フォントに ⚡ が無いので図形で描く）。幅は高さの 0.8 倍"""
    k = h / 40
    pts = [(22, 0), (6, 22), (18, 22), (12, 40), (32, 14), (20, 14), (28, 0)]
    pygame.draw.polygon(screen, color, [(x + px * k, y + py * k) for px, py in pts])


def draw_thunder_banner(screen, width, by, base_font_path, info, bh=ALERT_BANNER_H):
    """雷の帯。info = fetch_thunder.ThunderState.current() の戻り値"""
    from fetch_thunder import banner_text
    st = THUNDER_STYLE[info["kind"]]
    pygame.draw.rect(screen, st["bg"], (0, by, width, bh))
    pygame.draw.line(screen, st["edge"], (0, by), (width, by), 3)
    pygame.draw.line(screen, st["edge"], (0, by + bh - 1), (width, by + bh - 1), 2)
    title, body = banner_text(info)
    bolt_h = bh - 8
    bolt_w = int(bolt_h * 0.8)
    # 狭い画面では本文を小さくして 1 行に収める
    for size in ((26, 24, 22, 20, 18) if bh >= ALERT_BANNER_H else (18, 16, 14)):
        t = get_font(base_font_path, size + 4, bold=True).render(title, True, st["fg"])
        b = get_font(base_font_path, size, bold=True).render(body, True, st["fg"])
        gap = size
        total = bolt_w + 6 + t.get_width() + gap + b.get_width()
        if total <= width - 20:
            break
    x = max(10, (width - total) // 2)
    _draw_bolt(screen, x, by + 4, bolt_h, st["bolt"])
    x += bolt_w + 6
    screen.blit(t, (x, by + (bh - t.get_height()) // 2))
    screen.blit(b, (x + t.get_width() + gap, by + (bh - b.get_height()) // 2))


def _label_icon(name, size, icon_cache):
    """見出しの絵を、縦横とも size 以内（縦横比はそのまま）に縮めて返す。無ければ None"""
    if not name:
        return None
    key = ("label", name, size)
    if key not in icon_cache:
        try:
            raw = pygame.image.load(os.path.join(ICON_DIR, "labels", f"{name}.png"))
            k = size / max(raw.get_width(), raw.get_height())
            icon_cache[key] = pygame.transform.smoothscale(
                raw, (max(1, round(raw.get_width() * k)), max(1, round(raw.get_height() * k))))
        except Exception:
            icon_cache[key] = None
    return icon_cache[key]


def _load_scaled_icon(icon_path: str, w: int, h: int, icon_cache: dict):
    key = (icon_path, w, h)
    if key not in icon_cache:
        try:
            raw = pygame.image.load(icon_path)
            icon_cache[key] = pygame.transform.scale(raw, (w, h))
        except Exception:
            icon_cache[key] = None
    return icon_cache[key]


def draw_weather(
    screen,
    width,
    height,
    hourly,
    daily,
    icon_cache,
    base_font_path,
    warning_text,
    headline_text,
    updated_text,
    weather_updated_text,
    airport_name,
    sunrise_str,
    sunset_str,
    work_summary,
    cpu_text,
    fetch_ok: bool = True,
    qr_surf=None,
    wbgt_level_info=None,
    wbgt_alert: bool = False,
    latitude=None,
    longitude=None,
    overview_text: str = "",
    now=None,
    thunder=None,
):
    screen.fill((255, 255, 255))

    margin_x = int(width * 0.05)
    header_h = int(height * 0.25)

    # ヘッダー直下の帯：雷（いちばん急ぐ）→ 熱中症警戒アラートの順に重ねる
    banner_y = header_h
    double = bool(thunder) and bool(wbgt_alert)
    bh = ALERT_BANNER_H_DOUBLE if double else ALERT_BANNER_H
    if thunder:
        draw_thunder_banner(screen, width, banner_y, base_font_path, thunder, bh)
        banner_y += bh + 2
    if wbgt_alert:
        draw_alert_banner(screen, width, banner_y, base_font_path, bh)
        banner_y += bh + 2

    # 通信エラーの帯は header.draw_fetch_error_bar（ヘッダーの白塗りの後）で描く

    data_cols = len(hourly)
    total_cols = 1 + data_cols
    col_w = int((width - margin_x * 2) // max(2, total_cols))

    y_offset = banner_y

    row_heights = [
        int(height * 0.055),
        int(height * 0.030),
        int(height * 0.075),
        int(height * 0.040),
        int(height * 0.040),
        int(height * 0.055),
    ]

    # 作業注意情報の行は現在非表示（復活させるときは下のコメントを外す）
    # summary_color = (0, 0, 0)
    # if work_summary and ("強風" in work_summary or "熱中症" in work_summary):
    #     summary_color = (255, 0, 0)
    #
    # summary_surf = get_font(base_font_path, 22, bold=True).render(
    #     f"作業注意情報：{work_summary}", True, summary_color
    # )
    # screen.blit(summary_surf, (margin_x, y_offset))
    # y_offset += summary_surf.get_height() + 4
    # # 作業注意情報と「今日の天気」の間を1行あける（下に余裕のある高さ 1000px 以上の画面のみ。
    # # 1366×768 等は熱中症アラート時に下端まで使っているので従来どおり）
    # if height >= SUMMARY_GAP_MIN_HEIGHT:
    #     y_offset += summary_surf.get_height()

    title_bar_h = 54 if qr_surf else 30
    draw_today_title_bar(
        screen,
        margin_x,
        y_offset,
        width - margin_x * 2,
        title_bar_h,
        base_font_path,
        airport_name=None,
        weather_updated_text=weather_updated_text,
        cpu_text=cpu_text,
        qr_surf=qr_surf
    )
    y_offset += title_bar_h + 4

    global current_anim
    current_anim = None
    icon_cells = {}                     # 列 → (アイコンを描いたマス, 実際に描いたアイコンの番号)
    for row_idx, label in enumerate(ROW_LABELS):
        for col_idx in range(total_cols):
            x = margin_x + col_idx * col_w
            y = y_offset + sum(row_heights[:row_idx])

            # 時刻の行は、昼と夜でマスの色を塗り分ける（枠より先に塗る。全列ぶんを 1 枚で、最初の列のときに）
            if row_idx == 1 and col_idx == 1 and data_cols:
                screen.blit(_time_row_surface(hourly, col_w, row_heights[row_idx]), (x, y))

            # 日付行は3時間ごとの区切り線を引かず、日付ごとにまとめて枠を描く（下で描画）
            if not (row_idx == 0 and col_idx >= 1):
                pygame.draw.rect(screen, (180, 180, 180), (x, y, col_w, row_heights[row_idx]), 1)

            if col_idx == 0:
                text_surf = get_font(base_font_path, LABEL_FONT_SIZE).render(label, True, (0, 0, 0))
                screen.blit(text_surf, (x + 5, y + 5))
                icon = _label_icon(LABEL_ICONS.get(label), LABEL_FONT_SIZE, icon_cache)
                if icon is not None:            # 文字と同じ大きさで、文字のすぐ右に
                    screen.blit(icon, (x + 5 + text_surf.get_width() + 4,
                                       y + 5 + (text_surf.get_height() - icon.get_height()) // 2))
                continue

            di = col_idx - 1
            if di >= data_cols:
                continue

            item = hourly[di]
            color = (0, 0, 0)
            bold = False

            if row_idx == 0:
                if di == 0:
                    text = item["date"]
                else:
                    prev_date = hourly[di - 1]["date"]
                    text = item["date"] if item["date"] != prev_date else ""

            elif row_idx == 1:
                text = item["hour"]
                if night_mix(hourly, di, 0.1) > 0.5:
                    color = TIME_NIGHT_TEXT          # 夜のマスは紺なので白い数字（数字のある左端の色で決める）

            elif row_idx == 2:
                icon_code = item["code"]
                if _is_night_item(item) and icon_code.startswith("1") and len(icon_code) == 3:
                    # 晴れ系 1xx は夜間に月アイコン 7xx へ
                    icon_code = str(int(icon_code) + 600)
                elif icon_code == "100":
                    if (item.get("temp_val") or 0) >= 34:
                        icon_code = "1000A"
                    elif (item.get("temp_val") or 0) >= 30:
                        icon_code = "1000"
                icon_path = os.path.join(ICON_DIR, f"{icon_code}.png")
                icon = _load_scaled_icon(icon_path, col_w - 10, row_heights[row_idx] - 10, icon_cache)
                if icon:
                    screen.blit(icon, (x + 5, y + 5))
                icon_cells[di] = ((x + 5, y + 5, col_w - 10, row_heights[row_idx] - 10), icon_code)
                continue

            elif row_idx == 3:
                text = item["pop"]
                try:
                    v = float(str(text).replace("mm", ""))
                    if v >= 3.0:
                        color, bold = (0, 0, 255), True
                except Exception:
                    pass

            elif row_idx == 4:
                text = item["temp"]
                t = item.get("temp_val", None)
                if isinstance(t, (int, float)):
                    if t >= 34:
                        color, bold = (128, 0, 128), True
                    elif t >= 30:
                        color, bold = (255, 0, 0), True
                    elif 0 <= t <= 5:
                        color, bold = (100, 180, 255), True
                    elif t < 0:
                        color, bold = (0, 0, 180), True

            elif row_idx == 5:
                v = item.get("wind_val", None)
                if not isinstance(v, (int, float)):
                    text = item["wind"]
                else:
                    wcolor = wind_text_color(v)          # 矢印と同じ区切り（0・1〜4・5〜7・8〜11・12〜17・18〜）
                    val_surf  = get_font(base_font_path, 26, bold=v >= WIND_BOLD_FROM).render(str(int(v)), True, wcolor)
                    # 列が狭い画面（1366・1280 幅）は単位を小さくして、風向の矢印の場所を空ける
                    unit_surf = (get_font(base_font_path, 24).render(" m/s", True, wcolor) if col_w >= 140
                                 else get_font(base_font_path, 16).render("m/s", True, wcolor))
                    x_pos = x + 5
                    y_pos = y + (row_heights[row_idx] - val_surf.get_height()) // 2
                    screen.blit(val_surf,  (x_pos, y_pos))
                    screen.blit(unit_surf, (x_pos + val_surf.get_width(),
                                            y_pos + val_surf.get_height() - unit_surf.get_height() - (0 if col_w >= 140 else 3)))
                    # 風向の矢印：どの列も同じ位置（2 桁の太字「88 m/s」の右）に置く。1 桁でも離れすぎず、2 桁でも重ならない。
                    # 列が狭い画面では入る大きさに縮め、入らなければ描かない
                    wdir = item.get("wind_dir")
                    # 0 m/s（ほぼ無風）・実況で風向が変動（VRB）のときは向きが無いので、矢印の代わりに「---」
                    calm = int(v) == 0 or bool(item.get("wind_variable"))
                    if calm or isinstance(wdir, (int, float)):
                        widest = get_font(base_font_path, 26, bold=True).size("88")[0] + unit_surf.get_width()
                        text_right = x_pos + max(widest, val_surf.get_width() + unit_surf.get_width())
                        size = min(int(row_heights[row_idx] * WIND_ARROW_SCALE), x + col_w - text_right - 8)
                        if size >= 16:
                            cx, cy = text_right + 6 + size / 2, y + row_heights[row_idx] / 2
                            if calm:
                                draw_calm_mark(screen, cx, cy, size)
                            else:
                                draw_wind_arrow(screen, cx, cy, size, wdir, v)
                    continue

            if row_idx != 2:
                font_size = 26 if row_idx == 0 else 22
                text_surf = get_font(base_font_path, font_size, bold=bold).render(text, True, color)
                screen.blit(
                    text_surf,
                    (x + 5, y + (row_heights[row_idx] - text_surf.get_height()) // 2)
                )

    # 日付行：同じ日付の列をひとまとめにした枠（区切り線は日付が変わる所だけ）
    start = 0
    for di in range(1, data_cols + 1):
        if di == data_cols or hourly[di]["date"] != hourly[start]["date"]:
            gx = margin_x + (1 + start) * col_w
            pygame.draw.rect(screen, (180, 180, 180), (gx, y_offset, (di - start) * col_w, row_heights[0]), 1)
            start = di

    if latitude is not None and longitude is not None:
        _draw_sun_markers(screen, hourly, latitude, longitude, margin_x, col_w,
                          y_offset + row_heights[0], row_heights[1], base_font_path)

    # 今の時間帯（3 時間ごと）の列を、時刻〜風速の 5 行まとめて太い枠で囲む（日付行は日ごとにまとめてあるので除く）
    cur = current_slot_index(hourly, now or datetime.datetime.now(JST))
    if cur is not None and cur < data_cols:
        pygame.draw.rect(screen, NOW_FRAME_COLOR,
                         (margin_x + (1 + cur) * col_w, y_offset + row_heights[0], col_w + 1, sum(row_heights[1:]) + 1),
                         NOW_FRAME_WIDTH)
        # 今の時間帯のアイコンを動かすための情報（main01 が 1 秒に数回、このマスだけ描き直す）
        if cur in icon_cells:
            rect, code = icon_cells[cur]
            current_anim = {"rect": rect, "icon_code": code}

    # 風速の矢印の色の見方（色の帯）。今日の天気の表のすぐ下・右端（左の「１週間の天気」の題名と同じ高さ）
    _draw_wind_legend(screen, base_font_path, margin_x + col_w * (1 + data_cols), y_offset + sum(row_heights) + 3)

    y_offset += sum(row_heights) + (2 if double else 8)

    week_title_surf = get_font(base_font_path, 28, bold=True).render("１週間の天気", True, (0, 0, 0))
    screen.blit(week_title_surf, (margin_x, y_offset))
    y_offset += week_title_surf.get_height() + 4

    week_row_heights = [int(height * r) for r in [0.06, 0.08, 0.04, 0.06]]

    for row_idx, label in enumerate(WEEK_ROW_LABELS):
        for col_idx in range(len(daily) + 1):
            x = margin_x + col_idx * col_w
            y = y_offset + sum(week_row_heights[:row_idx])

            pygame.draw.rect(screen, (160, 160, 160), (x, y, col_w, week_row_heights[row_idx]), 1)

            if col_idx == 0:
                if row_idx == 3:
                    surf1 = get_font(base_font_path, 22).render("気温：", True, (0, 0, 0))
                    surf2 = get_font(base_font_path, 18).render("（最高／最低）", True, (80, 80, 80))
                    screen.blit(surf1, (x + 5, y + 2))
                    screen.blit(surf2, (x + 5, y + 2 + surf1.get_height()))
                else:
                    screen.blit(
                        get_font(base_font_path, 22).render(label, True, (0, 0, 0)),
                        (x + 5, y + 5)
                    )
            else:
                item = daily[col_idx - 1]

                if row_idx == 0:
                    text = item["day"]
                    if "（日）" in text:
                        dcolor = (255, 0, 0)
                    elif "（土）" in text:
                        dcolor = (0, 0, 255)
                    else:
                        dcolor = (0, 0, 0)
                    screen.blit(
                        get_font(base_font_path, 22).render(text, True, dcolor),
                        (x + 5, y + 5)
                    )

                elif row_idx == 1:
                    icon_path = os.path.join(ICON_DIR, f"{item['code']}.png")
                    icon = _load_scaled_icon(icon_path, col_w - 10, week_row_heights[row_idx] - 10, icon_cache)
                    if icon:
                        screen.blit(icon, (x + 5, y + 5))

                elif row_idx == 2:
                    screen.blit(
                        get_font(base_font_path, 22).render(item["pop"], True, (0, 0, 0)),
                        (x + 5, y + 5)
                    )
                    # 気象庁の週間予報の信頼度（A・B・C）を右端に小さな札で
                    if item.get("rel") in REL_COLORS:
                        _draw_rel_badge(screen, base_font_path, item["rel"],
                                        x + col_w - 6, y + week_row_heights[row_idx] // 2,
                                        min(26, week_row_heights[row_idx] - 6))

                elif row_idx == 3:
                    text = item["temp"]
                    try:
                        max_str, min_str = text.split("/")
                        max_t = int(max_str)
                        min_t = int(min_str)

                        if max_t >= 34:
                            max_color, max_bold = (128, 0, 128), True
                        elif max_t >= 30:
                            max_color, max_bold = (255, 0, 0), True
                        elif max_t >= 28:
                            max_color, max_bold = (255, 165, 0), True
                        else:
                            max_color, max_bold = (0, 0, 0), False

                        tsize = week_temp_font_size(base_font_path, max_t, min_t, max_bold, col_w - 10)
                        max_surf   = get_font(base_font_path, tsize, bold=max_bold).render(f"{max_t}℃", True, max_color)
                        slash_surf = get_font(base_font_path, tsize).render("／", True, (0, 0, 0))
                        min_surf   = get_font(base_font_path, tsize).render(f"{min_t}℃", True, (0, 0, 0))

                        sx = x + 5
                        screen.blit(max_surf,   (sx, y + 5))
                        screen.blit(slash_surf, (sx + max_surf.get_width(), y + 5))
                        screen.blit(min_surf,   (sx + max_surf.get_width() + slash_surf.get_width(), y + 5))

                    except Exception:
                        screen.blit(
                            get_font(base_font_path, 22).render(text, True, (0, 0, 0)),
                            (x + 5, y + 5)
                        )

    # 信頼度の説明（降水確率の右の A・B・C が何か）。週間予報の表のすぐ下・右端にそろえる
    # （雷・熱中症の帯で表が下にずれても画面に入るよう、入らないときは描かない）
    if any(d.get("rel") for d in daily[:5]):
        _draw_rel_legend(screen, base_font_path, margin_x + col_w * (1 + min(5, len(daily))),
                         y_offset + sum(week_row_heights) + 3, height)

    used_w = (len(daily) + 1) * col_w
    remain_w = (width - margin_x * 2) - used_w

    if remain_w >= col_w:
        box_x = margin_x + used_w + 10
        box_y = y_offset
        box_w = remain_w - 20
        box_h = sum(week_row_heights)

        pygame.draw.rect(screen, (120, 120, 120), (box_x, box_y, box_w, box_h), 2)

        y_line = box_y + 10

        title_surf = get_font(base_font_path, 22, bold=True).render(
            "＝＝　警報・注意報　＝＝", True, (0, 0, 0)
        )
        screen.blit(title_surf, (box_x + 10, y_line))
        y_line += title_surf.get_height() + 8

        # 実際に発令中の警報・注意報がある場合のみ色付き表示、解除済みは「発表なし」
        has_active_warning = (
            bool(warning_text)
            and "なし" not in warning_text
            and "失敗" not in warning_text
        )
        if has_active_warning:
            display_warning = warning_text
            if "警報" in display_warning:
                wcolor = (255, 0, 0)
            elif "注意報" in display_warning:
                wcolor = (255, 140, 0)
            else:
                wcolor = (0, 0, 0)
        elif warning_text and "失敗" in warning_text:
            display_warning = "取得失敗（通信エラー）"
            wcolor = (128, 128, 128)
        else:
            display_warning = "発表なし"
            wcolor = (0, 0, 0)

        max_width = box_w - 20

        # 枠の下端に「警報更新：…」。ほかの文字はこれより上に収める（枠や画面の下にはみ出さない）
        small_font = get_font(base_font_path, 20)
        bottom = box_y + box_h - 5
        if updated_text:
            upd_surf = small_font.render(f"警報更新：{updated_text}", True, (0, 0, 0))
            bottom -= upd_surf.get_height()
            screen.blit(upd_surf, (box_x + 10, bottom))

        # 1) 警報・注意報（最優先。長ければ折り返して全部出す。入りきらなければ文字を小さくし、それでも無理なら末尾を…）
        for wsize in (24, 22, 20, 18):
            warn_font = get_font(base_font_path, wsize)
            wlines = _wrap_text(display_warning, warn_font, max_width)
            if len(wlines) * (warn_font.get_height() + 2) <= bottom - 4 - y_line:
                break
        fit = max(1, (bottom - 4 - y_line) // (warn_font.get_height() + 2))
        if len(wlines) > fit:
            wlines = wlines[:fit]
            last = wlines[-1]
            while last and warn_font.size(last + "…")[0] > max_width:
                last = last[:-1]
            wlines[-1] = last + "…"
        for line in wlines:
            warn_surf = warn_font.render(line, True, wcolor)
            screen.blit(warn_surf, (box_x + 10, y_line))
            y_line += warn_surf.get_height() + 2
        y_line += 6

        # 2) 警報発令中のときのみ見出し文（解除後は古い見出しを残さない。入る行数だけ）
        if headline_text and has_active_warning:
            for line in _wrap_text(headline_text, small_font, max_width)[:2]:
                head_surf = small_font.render(line, True, (0, 0, 0))
                if y_line + head_surf.get_height() > bottom - 4:
                    break
                screen.blit(head_surf, (box_x + 10, y_line))
                y_line += head_surf.get_height() + 4

        # 3) 天気概況（最大 OVERVIEW_MAX_LINES 行・残りスペース内。溢れたら末尾を…で切る）
        ov = _overview_outlook(overview_text)
        if ov:
            ov_font = get_font(base_font_path, 20)
            line_h = ov_font.get_linesize()
            y_line += 4
            max_lines = min(OVERVIEW_MAX_LINES, (bottom - 4 - y_line) // line_h)
            if max_lines > 0:
                pygame.draw.line(screen, (180, 180, 180),
                                 (box_x + 10, y_line - 2), (box_x + box_w - 10, y_line - 2), 1)
                lines = _wrap_text("【天気概況】" + ov, ov_font, max_width)
                if len(lines) > max_lines:
                    lines = lines[:max_lines]
                    last = lines[-1]
                    while last and ov_font.size(last + "…")[0] > max_width:
                        last = last[:-1]
                    lines[-1] = last + "…"
                for line in lines:
                    screen.blit(ov_font.render(line, True, (60, 60, 60)), (box_x + 10, y_line))
                    y_line += line_h
