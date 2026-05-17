import socket
import datetime
import time
import pygame
from utils import JST, get_japanese_weekday, get_font

def get_ip_last3():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.split(".")[-1].zfill(3)
    except Exception:
        return "---"


def draw_header(
    screen, width, height, base_font_path,
    airport_label,
    sunrise_str, sunset_str,
    weather_updated_text,
    cpu_text="--",
    wbgt_level_info=None,
):
    now = datetime.datetime.now(JST)

    header_h = int(height * 0.25)
    header_rect = pygame.Rect(0, 0, width, header_h)
    screen.fill((255, 255, 255), header_rect)

    top_margin = int(height * 0.03)
    line_gap   = int(height * 0.01)

    # ===== 0) WBGT バッジを先にレンダリング（サイズを知るため） =====
    badge_data = None
    badge_reserve = 0
    if wbgt_level_info:
        f_small = get_font(base_font_path, int(height * 0.028))
        f_large = get_font(base_font_path, int(height * 0.045), bold=True)
        lbl_s = f_small.render("熱中症", True, wbgt_level_info["fg"])
        lvl_s = f_large.render(wbgt_level_info["label"], True, wbgt_level_info["fg"])
        val_s = f_small.render(f"WBGT {wbgt_level_info['value']:.1f}℃", True, wbgt_level_info["fg"])
        bw = max(lbl_s.get_width(), lvl_s.get_width(), val_s.get_width()) + 20
        inner_h = lbl_s.get_height() + lvl_s.get_height() + val_s.get_height() + 4
        bh = inner_h + 12
        badge_data = (lbl_s, lvl_s, val_s, bw, bh, inner_h)
        badge_reserve = bw + 24

    available_w = width - badge_reserve
    center_x = available_w // 2

    # ===== 1) 大きい日付時刻 =====
    date_str = (
        f"{now.month}月{now.day}日"
        f"({get_japanese_weekday(now)})"
        f"{now.strftime('%H:%M')}"
    )
    title_surf = get_font(base_font_path, int(height * 0.14), bold=True).render(date_str, True, (0, 0, 0))
    title_x = max(10, center_x - title_surf.get_width() // 2)
    screen.blit(title_surf, (title_x, top_margin))

    # ===== 2) 2行目 =====
    info = f"{airport_label}  日の出:{sunrise_str} / 日の入り:{sunset_str}  "
    info_surf = get_font(base_font_path, int(height * 0.035)).render(info, True, (0, 0, 0))
    y2 = top_margin + title_surf.get_height() + line_gap
    x2 = max(10, center_x - info_surf.get_width() // 2)
    screen.blit(info_surf, (x2, y2))

    # ===== 3) WBGT バッジ =====
    if badge_data:
        lbl_s, lvl_s, val_s, bw, bh, inner_h = badge_data
        bx = width - bw - 8
        title_center_y = top_margin + title_surf.get_height() // 2
        by = title_center_y - bh // 2
        if by < top_margin:
            by = top_margin
        if by + bh > header_h - 4:
            by = header_h - bh - 4
        if wbgt_level_info["label"] == "危険":
            blink_on = int(time.time()) % 2 == 0
            bg_color = wbgt_level_info["bg"] if blink_on else (180, 0, 0)
        else:
            bg_color = wbgt_level_info["bg"]
        pygame.draw.rect(screen, bg_color, (bx, by, bw, bh), border_radius=8)
        pygame.draw.rect(screen, wbgt_level_info["fg"], (bx, by, bw, bh), width=2, border_radius=8)
        ty = by + (bh - inner_h) // 2
        for surf in (lbl_s, lvl_s, val_s):
            screen.blit(surf, (bx + (bw - surf.get_width()) // 2, ty))
            ty += surf.get_height() + 2
