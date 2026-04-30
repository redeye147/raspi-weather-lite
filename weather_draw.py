# weather_draw.py
"""
weather_draw.py
E61c draw_weather 完全互換移植版

変更点（必要部分だけ）:
- 時間天気テーブルの直上に「今日の天気」を固定表示（見出しバー）
- そのさらに上に既存の作業注意情報スクロール（現状維持）
"""

import os
import pygame
import datetime

from config import ICON_DIR  # ※下で project02 固定の ICON_DIR に上書き（互換維持）
from utils import (
    JST,
    get_last_ip_octet,
    get_japanese_weekday
)

# =========================
# ティッカーキャッシュ
# =========================
ticker_cache = {
    "text": "",
    "surf": None
}

# =========================
# 警報
# =========================
HEADERS = {"User-Agent": "Mozilla/5.0"}

AIRPORT_AREA = {
    "narita":  {"pref": "120000", "area": "1221100"},  # 成田市
    "haneda":  {"pref": "130000", "area": "1311100"},  # 大田区
    "centrair":{"pref": "230000", "area": "2321600"}   # 常滑市
}

MONITOR_CODES = {
    "02": "大雨警報",
    "03": "大雨注意報",
    "04": "洪水警報",
    "05": "洪水注意報",
    "12": "大雪警報",
    "13": "大雪注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "21": "乾燥注意報",
    "33": "濃霧注意報",
    "36": "乾燥注意報",
    "43": "雷注意報",
    "44": "暴風警報",
    "45": "暴風警報",
}

# ==========================================
# パス設定（project02固定）
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(BASE_DIR, "weather_icons")

ROW_LABELS = ["日付", "時刻", "天気", "降水量", "気温", "風速"]
WEEK_ROW_LABELS = ["日付", "天気", "降水確率", "気温：最高／最低"]

# =========================
# 日付表示制御（06時だけ表示）
# =========================
def should_display_date(hour_str):
    """
    06時のときだけ日付を表示する制御
    """
    if hour_str == "06":
        if not should_display_date.seen_06:
            should_display_date.seen_06 = True
            return True
        else:
            return False
    return False


# ==========================================
# 追加：固定見出し「今日の天気」
# ==========================================
def draw_today_title_bar(
    screen,
    x, y, w, h,
    base_font_path,
    airport_name=None,
    weather_updated_text="",
    cpu_text=""
):
    # 背景は白
    pygame.draw.rect(screen, (255, 255, 255), (x, y, w, h))
    # 枠線（要らなければコメントアウト可）
    #pygame.draw.rect(screen, (160, 160, 160), (x, y, w, h), 1)

    # 左：タイトル
    title_font = pygame.font.Font(base_font_path, 26)
    title_font.set_bold(True)

    title = "今日の天気"
    if airport_name:
        title += f"（{airport_name}）"

    # 右：更新/IP/CPU
    ip_suffix = get_last_ip_octet()
    parts = []
    if weather_updated_text:
        parts.append(weather_updated_text)
    if ip_suffix:
        parts.append(f"{ip_suffix}")
    if cpu_text:
        parts.append(f"{cpu_text}")
    status = " / ".join(parts)

    status_font = pygame.font.Font(base_font_path, 18)
    status_color = (80, 80, 80)

    status_surf = status_font.render(status, True, status_color) if status else None
    status_w = status_surf.get_width() if status_surf else 0

    # 左タイトルは右と衝突しないよう省略
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

    # 描画
    screen.blit(title_surf, (x + 8, y + (h - title_surf.get_height()) // 2))
    if status_surf:
        screen.blit(status_surf, (x + w - status_w - 8,
                                  y + (h - status_surf.get_height()) // 2))

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
    updated_text,           # JMA発表時間
    weather_updated_text,   # ★時間天気更新
    airport_name,
    sunrise_str,
    sunset_str,
    work_summary,
    cpu_text
):

    screen.fill((255, 255, 255))

    if not hasattr(draw_weather, "_dbg_once"):
        print("DEBUG(draw_weather) warning_text:", repr(warning_text), flush=True)
        print("DEBUG(draw_weather) headline_text:", (repr(headline_text)[:120]), flush=True)
        draw_weather._dbg_once = True

    margin_x = int(width * 0.05)
    data_cols = len(hourly)
    total_cols = 1 + data_cols
    col_w = int((width - margin_x * 2) // max(2, total_cols))

#B部（時間天気ブロック）を「画面の上からどれだけ下にずらして描き始めるか」 を決める値です
    y_offset = int(height * 0.25)
#    y_offset = int(height * 0.2)　　初期２０％

    # =========================
    # 時間別テーブル行高さ
    # =========================
    row_heights = [
        int(height * 0.06),  # 日付
        int(height * 0.03),  # 時刻
        int(height * 0.08),  # アイコン
        int(height * 0.04),  # 降水
        int(height * 0.04),  # 気温
        int(height * 0.06),  # 風速
    ]

    # =========================================================
    # ★ 作業サマリー表示（スクロール）  ※現状の位置（上段）
    # =========================================================
    summary_font = pygame.font.Font(base_font_path, 22)
    summary_font.set_bold(True)

    summary_color = (0, 0, 0)
    if work_summary and ("強風" in work_summary or "熱中症" in work_summary):
        summary_color = (255, 0, 0)

    ticker_text = f"作業注意情報：{work_summary}   "

    # ★ サマリーが変わった時だけrenderし直す
    if ticker_cache["text"] != ticker_text or ticker_cache["surf"] is None:
        ticker_cache["text"] = ticker_text
        ticker_cache["surf"] = summary_font.render(ticker_text, True, summary_color)
        ticker_cache["w"] = ticker_cache["surf"].get_width()
        ticker_cache["x"] = width  # 右端からスタート

    # 1フレームで進むピクセル（小さいほどゆっくり）
    # ※ speed_px=30 はかなり速いので、見やすさ優先なら 2〜6 あたり推奨
    speed_px = 4

    ticker_y = y_offset
    ticker_h = ticker_cache["surf"].get_height()
    ticker_x = ticker_cache["x"]

    # 画面外に出たら右に戻す
    if ticker_x + ticker_cache["w"] < margin_x:
        ticker_cache["x"] = width
    else:
        ticker_cache["x"] -= speed_px

    # はみ出しをクリップして描画（簡易）
    clip_rect = pygame.Rect(margin_x, ticker_y, width - margin_x * 2, ticker_h)
    old_clip = screen.get_clip()
    screen.set_clip(clip_rect)
    screen.blit(ticker_cache["surf"], (ticker_x, ticker_y))
    screen.set_clip(old_clip)

    y_offset += ticker_h + 8

    # =========================================================
    # ★ 追加：固定見出し「今日の天気」  ※スクロールの下、表の上
    # =========================================================
    title_bar_h = 34
    draw_today_title_bar(
        screen,
        margin_x,
        y_offset,
        width - margin_x * 2,
        title_bar_h,
        base_font_path,
        airport_name=None,  # 空港名も入れたいなら airport_name を渡す
        weather_updated_text=weather_updated_text,
        cpu_text=cpu_text
    )
    y_offset += title_bar_h + 8

    # ==========================================
    # 時間別テーブル
    # ==========================================
    should_display_date.seen_06 = False

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
                if row_idx == 0:
                    font = pygame.font.Font(base_font_path, 22)  # 日付だけ大きく
                else:
                    font = pygame.font.Font(base_font_path, 22)

                text_surf = font.render(label, True, (0, 0, 0))
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

                # ★E61c猛暑判定ロジック（重要）
                if icon_code == "100":
                    if item.get("temp_val", 0) >= 34:
                        icon_code = "1000A"
                    elif item.get("temp_val", 0) >= 30:
                        icon_code = "1000"

                icon_path = os.path.join(ICON_DIR, f"{icon_code}.png")

                if icon_path not in icon_cache:
                    try:
                        icon_cache[icon_path] = pygame.image.load(icon_path)
                    except:
                        icon_cache[icon_path] = None

                icon = icon_cache[icon_path]
                if icon:
                    icon = pygame.transform.scale(
                        icon,
                        (col_w - 10, row_heights[row_idx] - 10)
                    )
                    screen.blit(icon, (x + 5, y + 5))

                continue  # ★アイコン行はここで終わり

            elif row_idx == 3:
                # 降水量（mm）: 3.0mm以上は青＋太字（E61c）
                text = item["pop"]
                try:
                    v = float(str(text).replace("mm", ""))
                    if v >= 3.0:
                        color, bold = (0, 0, 255), True
                except:
                    pass

            elif row_idx == 4:
                # 気温: 高温/低温で色分け（E61c）
                text = item["temp"]
                t = item.get("temp_val", None)
                if isinstance(t, (int, float)):
                    if t >= 34:
                        color, bold = (128, 0, 128), True     # 猛暑：紫
                    elif t >= 30:
                        color, bold = (255, 0, 0), True       # 真夏日：赤
                    elif 0 <= t <= 5:
                        color, bold = (100, 180, 255), True   # 5〜0℃：水色
                    elif t < 0:
                        color, bold = (0, 0, 180), True       # 0℃未満：濃い青

            elif row_idx == 5:
                # 風速: 数値と単位を分け、5以上は太字（E61c）
                v = item.get("wind_val", None)
                if not isinstance(v, (int, float)):
                    text = item["wind"]
                else:
                    text_val = str(int(v))
                    text_unit = " m"

                    if v < 5:
                        color = (0, 0, 0)
                    elif v < 10:
                        color = (0, 0, 255)
                    elif v < 15:
                        color = (128, 0, 128)
                    else:
                        color = (255, 0, 0)

                    bold_font = pygame.font.Font(base_font_path, 26)
                    bold_font.set_bold(v >= 5)
                    unit_font = pygame.font.Font(base_font_path, 24)

                    val_surf = bold_font.render(text_val, True, color)
                    unit_surf = unit_font.render(text_unit, True, color)

                    x_pos = x + 5
                    y_pos = y + (row_heights[row_idx] - val_surf.get_height()) // 2
                    screen.blit(val_surf, (x_pos, y_pos))
                    screen.blit(unit_surf, (x_pos + val_surf.get_width(), y_pos))
                    continue

            # ======= 共通描画（row_idx != 2 のとき） =======
            if row_idx != 2:
                if row_idx == 0:
                    font = pygame.font.Font(base_font_path, 26)
                else:
                    font = pygame.font.Font(base_font_path, 22)

                if bold:
                    font.set_bold(True)

                text_surf = font.render(text, True, color)
                screen.blit(
                    text_surf,
                    (x + 5, y + (row_heights[row_idx] - text_surf.get_height()) // 2)
                )

    y_offset += sum(row_heights) + 40

    # ==========================================
    # 週間予報
    # ==========================================
    week_title_font = pygame.font.Font(base_font_path, 28)
    week_title_font.set_bold(True)

    week_title_surf = week_title_font.render("１週間の天気", True, (0, 0, 0))
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
                if row_idx == 3:  # 気温行だけ特別処理
                    font_big = pygame.font.Font(base_font_path, 22)
                    font_small = pygame.font.Font(base_font_path, 18)

                    surf1 = font_big.render("気温：", True, (0, 0, 0))
                    surf2 = font_small.render("（最高／最低）", True, (80, 80, 80))

                    screen.blit(surf1, (x + 5, y + 2))
                    screen.blit(surf2, (x + 5, y + 2 + surf1.get_height()))
                else:
                    font = pygame.font.Font(base_font_path, 22)
                    screen.blit(font.render(label, True, (0, 0, 0)), (x + 5, y + 5))

            else:
                item = daily[col_idx - 1]

                if row_idx == 0:
                    text = item["day"]
                    font = pygame.font.Font(base_font_path, 22)

                    # ★曜日色分け
                    if "（日）" in text:
                        color = (255, 0, 0)
                    elif "（土）" in text:
                        color = (0, 0, 255)
                    else:
                        color = (0, 0, 0)

                    text_surf = font.render(text, True, color)
                    screen.blit(text_surf, (x + 5, y + 5))

                elif row_idx == 1:
                    icon_path = os.path.join(ICON_DIR, f"{item['code']}.png")

                    if icon_path not in icon_cache:
                        try:
                            icon_cache[icon_path] = pygame.image.load(icon_path)
                        except:
                            icon_cache[icon_path] = None

                    icon = icon_cache[icon_path]
                    if icon:
                        icon = pygame.transform.scale(
                            icon,
                            (col_w - 10, week_row_heights[row_idx] - 10)
                        )
                        screen.blit(icon, (x + 5, y + 5))

                elif row_idx == 2:
                    text = item["pop"]
                    font = pygame.font.Font(base_font_path, 22)
                    screen.blit(font.render(text, True, (0, 0, 0)), (x + 5, y + 5))

                elif row_idx == 3:
                    text = item["temp"]
                    font = pygame.font.Font(base_font_path, 22)
                    try:
                        max_temp_str, min_temp_str = text.split("/")
                        max_temp = int(max_temp_str)
                        min_temp = int(min_temp_str)

                        if max_temp >= 34:
                            max_color, max_bold = (128, 0, 128), True
                        elif max_temp >= 30:
                            max_color, max_bold = (255, 0, 0), True
                        elif max_temp >= 28:
                            max_color, max_bold = (255, 165, 0), True
                        else:
                            max_color, max_bold = (0, 0, 0), False

                        max_font = pygame.font.Font(base_font_path, 22)
                        max_font.set_bold(max_bold)
                        min_font = pygame.font.Font(base_font_path, 22)

                        max_surf = max_font.render(f"{max_temp}℃", True, max_color)
                        slash_surf = font.render("／", True, (0, 0, 0))
                        min_surf = min_font.render(f"{min_temp}℃", True, (0, 0, 0))

                        start_x = x + 5
                        screen.blit(max_surf, (start_x, y + 5))
                        screen.blit(slash_surf, (start_x + max_surf.get_width(), y + 5))
                        screen.blit(min_surf, (start_x + max_surf.get_width() + slash_surf.get_width(), y + 5))

                    except:
                        screen.blit(font.render(text, True, (0, 0, 0)), (x + 5, y + 5))

    # ==========================================
    # 警報枠（E61c互換：週間の右側空きスペース）
    # ==========================================
    used_w = (len(daily) + 1) * col_w
    remain_w = (width - margin_x * 2) - used_w

    if remain_w >= col_w:

        box_x = margin_x + used_w + 10
        box_y = y_offset
        box_w = remain_w - 20
        box_h = sum(week_row_heights)

        pygame.draw.rect(
            screen,
            (120, 120, 120),
            (box_x, box_y, box_w, box_h),
            2
        )

        title_font = pygame.font.Font(base_font_path, 22)
        title_font.set_bold(True)

        warn_font = pygame.font.Font(base_font_path, 24)
        small_font = pygame.font.Font(base_font_path, 20)

        y_line = box_y + 10

        # 1行目：固定タイトル
        title_text = "＝＝　警報・注意報　＝＝"
        title_surf = title_font.render(title_text, True, (0, 0, 0))
        screen.blit(title_surf, (box_x + 10, y_line))
        y_line += title_surf.get_height() + 8

        # 2行目：警報内容 or 発表なし
        display_warning = warning_text if warning_text else "発表なし"

        if "警報" in display_warning:
            color = (255, 0, 0)
        elif "注意報" in display_warning:
            color = (255, 140, 0)
        else:
            color = (0, 0, 0)

        warn_surf = warn_font.render(display_warning, True, color)
        screen.blit(warn_surf, (box_x + 10, y_line))
        y_line += warn_surf.get_height() + 8

        # 3行目：概要（最大2行）
        if headline_text:
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

        # 最下段：発表時間
        if updated_text:
            display_time = f"発表時間：{updated_text}"
            upd_surf = small_font.render(display_time, True, (0, 0, 0))
            screen.blit(
                upd_surf,
                (box_x + 10, box_y + box_h - upd_surf.get_height() - 5)
            )