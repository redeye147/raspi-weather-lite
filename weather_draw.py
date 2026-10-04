# weather_draw.py
"""
weather_draw.py
E61c draw_weather 完全互換移植版 (lite: Pi Zero W 最適化)

変更点:
- フォントオブジェクトを get_font() でキャッシュ（毎フレーム生成を廃止）
- アイコンをスケール済みサーフェスごとキャッシュ（毎フレーム transform.scale を廃止）
- 作業サマリーを静的表示に変更（スクロールアニメーション廃止）
"""

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
            # 時刻の数字と重ならないよう右へ寄せる（最大でも数十分相当のずれ）
            x = int(max(x, text_right + 2 + tri / 2))

            color = SUNRISE_COLOR if is_rise else SUNSET_COLOR
            half = tri // 2
            if is_rise:
                pts = [(x, cy - half), (x - half, cy + half), (x + half, cy + half)]
            else:
                pts = [(x - half, cy - half), (x + half, cy - half), (x, cy + half)]
            pygame.draw.polygon(screen, color, pts)

            text_color = SUNRISE_TEXT_COLOR if is_rise else color
            label = label_font.render(t.strftime("%H:%M"), True, text_color)
            lw = label.get_width()
            next_text_x = cell_x + col_w + 5
            right_x = x + half + 2
            left_x = x - half - 2 - lw
            if right_x + lw <= next_text_x - 2 and ci < n:
                screen.blit(label, (right_x, cy - label.get_height() // 2))
            elif left_x >= text_right + 2:
                screen.blit(label, (left_x, cy - label.get_height() // 2))


def _is_night_item(item) -> bool:
    """18・21・00・03 時の列は夜（月アイコン）。日の出・日の入りの時刻では判断しない"""
    return item["hour"] in NIGHT_HOURS

ROW_LABELS = ["日付", "時刻", "天気", "降水量", "気温", "風速"]
WEEK_ROW_LABELS = ["日付", "天気", "降水確率", "気温：最高／最低"]


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
    else:
        right_edge = x + w - 8

    if status_surf:
        screen.blit(status_surf, (right_edge - status_w,
                                  y + (h - status_surf.get_height()) // 2))


ALERT_BANNER_H = 44
SUMMARY_GAP_MIN_HEIGHT = 1000   # この高さ以上の画面で、作業注意情報の下に1行分の余白を入れる


def draw_alert_banner(screen, width, header_h, base_font_path):
    """ヘッダー直下に熱中症警戒アラートバナーを表示。"""
    bh = ALERT_BANNER_H
    by = header_h
    pygame.draw.rect(screen, (160, 0, 0), (0, by, width, bh))
    pygame.draw.line(screen, (255, 60, 60), (0, by), (width, by), 3)
    pygame.draw.line(screen, (255, 60, 60), (0, by + bh - 1), (width, by + bh - 1), 2)
    f = get_font(base_font_path, 26, bold=True)
    text = "熱中症警戒アラート発令中 ― こまめな水分補給を！日陰で休憩を！"
    s = f.render(text, True, (255, 255, 180))
    screen.blit(s, ((width - s.get_width()) // 2, by + (bh - s.get_height()) // 2))


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
):
    screen.fill((255, 255, 255))

    margin_x = int(width * 0.05)
    header_h = int(height * 0.25)

    if wbgt_alert:
        draw_alert_banner(screen, width, header_h, base_font_path)

    # 通信エラーの帯は header.draw_fetch_error_bar（ヘッダーの白塗りの後）で描く

    data_cols = len(hourly)
    total_cols = 1 + data_cols
    col_w = int((width - margin_x * 2) // max(2, total_cols))

    y_offset = int(height * 0.25)
    if wbgt_alert:
        y_offset += ALERT_BANNER_H + 2

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

    for row_idx, label in enumerate(ROW_LABELS):
        for col_idx in range(total_cols):
            x = margin_x + col_idx * col_w
            y = y_offset + sum(row_heights[:row_idx])

            # 日付行は3時間ごとの区切り線を引かず、日付ごとにまとめて枠を描く（下で描画）
            if not (row_idx == 0 and col_idx >= 1):
                pygame.draw.rect(screen, (180, 180, 180), (x, y, col_w, row_heights[row_idx]), 1)

            if col_idx == 0:
                text_surf = get_font(base_font_path, 22).render(label, True, (0, 0, 0))
                screen.blit(text_surf, (x + 5, y + 5))
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
                    wcolor = (
                        (255, 0, 0) if v >= 15 else
                        (128, 0, 128) if v >= 10 else
                        (0, 0, 255) if v >= 5 else
                        (0, 0, 0)
                    )
                    val_surf  = get_font(base_font_path, 26, bold=v >= 5).render(str(int(v)), True, wcolor)
                    unit_surf = get_font(base_font_path, 24).render(" m/s", True, wcolor)
                    x_pos = x + 5
                    y_pos = y + (row_heights[row_idx] - val_surf.get_height()) // 2
                    screen.blit(val_surf,  (x_pos, y_pos))
                    screen.blit(unit_surf, (x_pos + val_surf.get_width(), y_pos))
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

    y_offset += sum(row_heights) + 8

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

                        max_surf   = get_font(base_font_path, 22, bold=max_bold).render(f"{max_t}℃", True, max_color)
                        slash_surf = get_font(base_font_path, 22).render("／", True, (0, 0, 0))
                        min_surf   = get_font(base_font_path, 22).render(f"{min_t}℃", True, (0, 0, 0))

                        sx = x + 5
                        screen.blit(max_surf,   (sx, y + 5))
                        screen.blit(slash_surf, (sx + max_surf.get_width(), y + 5))
                        screen.blit(min_surf,   (sx + max_surf.get_width() + slash_surf.get_width(), y + 5))

                    except Exception:
                        screen.blit(
                            get_font(base_font_path, 22).render(text, True, (0, 0, 0)),
                            (x + 5, y + 5)
                        )

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

        # 1) 警報・注意報（最優先。長ければ折り返して全部出す）
        warn_font = get_font(base_font_path, 24)
        for line in _wrap_text(display_warning, warn_font, max_width):
            warn_surf = warn_font.render(line, True, wcolor)
            screen.blit(warn_surf, (box_x + 10, y_line))
            y_line += warn_surf.get_height() + 2
        y_line += 6

        # 2) 警報発令中のときのみ見出し文（解除後は古い見出しを残さない）
        small_font = get_font(base_font_path, 20)
        if headline_text and has_active_warning:
            for line in _wrap_text(headline_text, small_font, max_width)[:2]:
                head_surf = small_font.render(line, True, (0, 0, 0))
                screen.blit(head_surf, (box_x + 10, y_line))
                y_line += head_surf.get_height() + 4

        bottom = box_y + box_h - 5
        if updated_text:
            upd_surf = small_font.render(f"警報更新：{updated_text}", True, (0, 0, 0))
            bottom -= upd_surf.get_height()
            screen.blit(upd_surf, (box_x + 10, bottom))

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
