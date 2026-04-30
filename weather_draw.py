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

from config import ICON_DIR
from utils import (
    JST,
    get_last_ip_octet,
    get_japanese_weekday,
    get_font,
)

# ==========================================
# パス設定（project02固定）
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(BASE_DIR, "weather_icons")

ROW_LABELS = ["日付", "時刻", "天気", "降水量", "気温", "風速"]
WEEK_ROW_LABELS = ["日付", "天気", "降水確率", "気温：最高／最低"]


# ==========================================
# 固定見出し「今日の天気」
# ==========================================
def draw_today_title_bar(
    screen,
    x, y, w, h,
    base_font_path,
    airport_name=None,
    weather_updated_text="",
    cpu_text=""
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

    max_left_w = w - 16 - status_w - 12
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
    if status_surf:
        screen.blit(status_surf, (x + w - status_w - 8,
                                  y + (h - status_surf.get_height()) // 2))


# ==========================================
# アイコン読み込み＋スケール（キャッシュ付き）
# ==========================================
def _load_scaled_icon(icon_path: str, w: int, h: int, icon_cache: dict):
    """(path, w, h) をキーにスケール済みサーフェスをキャッシュして返す。"""
    key = (icon_path, w, h)
    if key not in icon_cache:
        try:
            raw = pygame.image.load(icon_path)
            icon_cache[key] = pygame.transform.scale(raw, (w, h))
        except Exception:
            icon_cache[key] = None
    return icon_cache[key]


# ==========================================
# draw_weather
# ==========================================
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
    fetch_ok: bool = True
):

    screen.fill((255, 255, 255))

    margin_x = int(width * 0.05)

    # -------------------------
    # 通信エラーバナー（fetch失敗時）
    # -------------------------
    if not fetch_ok:
        err_surf = get_font(base_font_path, 20, bold=True).render(
            "通信エラー：キャッシュデータを表示しています", True, (255, 255, 255)
        )
        bar_h = err_surf.get_height() + 8
        pygame.draw.rect(screen, (180, 0, 0), (0, 0, width, bar_h))
        screen.blit(err_surf, ((width - err_surf.get_width()) // 2, 4))
    data_cols = len(hourly)
    total_cols = 1 + data_cols
    col_w = int((width - margin_x * 2) // max(2, total_cols))

    y_offset = int(height * 0.25)

    row_heights = [
        int(height * 0.06),  # 日付
        int(height * 0.03),  # 時刻
        int(height * 0.08),  # アイコン
        int(height * 0.04),  # 降水
        int(height * 0.04),  # 気温
        int(height * 0.06),  # 風速
    ]

    # =========================================================
    # 作業サマリー（静的表示 — アニメーション廃止）
    # =========================================================
    summary_color = (0, 0, 0)
    if work_summary and ("強風" in work_summary or "熱中症" in work_summary):
        summary_color = (255, 0, 0)

    summary_surf = get_font(base_font_path, 22, bold=True).render(
        f"作業注意情報：{work_summary}", True, summary_color
    )
    screen.blit(summary_surf, (margin_x, y_offset))
    y_offset += summary_surf.get_height() + 8

    # =========================================================
    # 固定見出し「今日の天気」
    # =========================================================
    title_bar_h = 34
    draw_today_title_bar(
        screen,
        margin_x,
        y_offset,
        width - margin_x * 2,
        title_bar_h,
        base_font_path,
        airport_name=None,
        weather_updated_text=weather_updated_text,
        cpu_text=cpu_text
    )
    y_offset += title_bar_h + 8

    # ==========================================
    # 時間別テーブル
    # ==========================================
    for row_idx, label in enumerate(ROW_LABELS):
        for col_idx in range(total_cols):

            x = margin_x + col_idx * col_w
            y = y_offset + sum(row_heights[:row_idx])

            pygame.draw.rect(
                screen,
                (180, 180, 180),
                (x, y, col_w, row_heights[row_idx]),
                1
            )

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

                # E61c猛暑判定ロジック
                if icon_code == "100":
                    if item.get("temp_val", 0) >= 34:
                        icon_code = "1000A"
                    elif item.get("temp_val", 0) >= 30:
                        icon_code = "1000"

                icon_path = os.path.join(ICON_DIR, f"{icon_code}.png")
                icon = _load_scaled_icon(
                    icon_path, col_w - 10, row_heights[row_idx] - 10, icon_cache
                )
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
                    unit_surf = get_font(base_font_path, 24).render(" m", True, wcolor)
                    x_pos = x + 5
                    y_pos = y + (row_heights[row_idx] - val_surf.get_height()) // 2
                    screen.blit(val_surf,  (x_pos, y_pos))
                    screen.blit(unit_surf, (x_pos + val_surf.get_width(), y_pos))
                    continue

            # 共通テキスト描画（アイコン行・風速行以外）
            if row_idx != 2:
                font_size = 26 if row_idx == 0 else 22
                text_surf = get_font(base_font_path, font_size, bold=bold).render(text, True, color)
                screen.blit(
                    text_surf,
                    (x + 5, y + (row_heights[row_idx] - text_surf.get_height()) // 2)
                )

    y_offset += sum(row_heights) + 40

    # ==========================================
    # 週間予報
    # ==========================================
    week_title_surf = get_font(base_font_path, 28, bold=True).render("１週間の天気", True, (0, 0, 0))
    screen.blit(week_title_surf, (margin_x, y_offset))
    y_offset += week_title_surf.get_height() + 10

    week_row_heights = [int(height * r) for r in [0.06, 0.08, 0.04, 0.06]]

    for row_idx, label in enumerate(WEEK_ROW_LABELS):
        for col_idx in range(len(daily) + 1):

            x = margin_x + col_idx * col_w
            y = y_offset + sum(week_row_heights[:row_idx])

            pygame.draw.rect(
                screen,
                (160, 160, 160),
                (x, y, col_w, week_row_heights[row_idx]),
                1
            )

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
                    icon = _load_scaled_icon(
                        icon_path, col_w - 10, week_row_heights[row_idx] - 10, icon_cache
                    )
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

    # ==========================================
    # 警報枠（週間予報の右側スペース）
    # ==========================================
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

        display_warning = warning_text if warning_text else "発表なし"
        if "警報" in display_warning:
            wcolor = (255, 0, 0)
        elif "注意報" in display_warning:
            wcolor = (255, 140, 0)
        else:
            wcolor = (0, 0, 0)

        warn_surf = get_font(base_font_path, 24).render(display_warning, True, wcolor)
        screen.blit(warn_surf, (box_x + 10, y_line))
        y_line += warn_surf.get_height() + 8

        if headline_text:
            small_font = get_font(base_font_path, 20)
            max_width = box_w - 20
            lines = []
            current_line = ""

            for ch in headline_text:
                test_line = current_line + ch
                if small_font.size(test_line)[0] <= max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = ch
            if current_line:
                lines.append(current_line)

            for line in lines[:2]:
                head_surf = small_font.render(line, True, (0, 0, 0))
                screen.blit(head_surf, (box_x + 10, y_line))
                y_line += head_surf.get_height() + 4

        if updated_text:
            upd_surf = get_font(base_font_path, 20).render(
                f"発表時間：{updated_text}", True, (0, 0, 0)
            )
            screen.blit(
                upd_surf,
                (box_x + 10, box_y + box_h - upd_surf.get_height() - 5)
            )
