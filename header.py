import socket
import datetime
import time
import pygame
from utils import JST, get_japanese_weekday, get_font

import aviation

CATEGORY_COLORS = {"VFR": (0, 140, 70), "MVFR": (0, 90, 200), "IFR": (200, 0, 0), "LIFR": (140, 0, 160)}
_plane_cache = {}


def _plane_surface(size: int, color) -> pygame.Surface:
    """飛行機のマーク（IPA フォントに ✈ が無いため図形で描く）"""
    key = (size, color)
    if key not in _plane_cache:
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        u = size / 20
        for poly in ([(1, 9), (17, 8.5), (19.5, 10), (17, 11.5), (1, 11)], [(7, 9), (12, 9), (8, 1), (6, 1)],
                     [(7, 11), (12, 11), (8, 19), (6, 19)], [(1, 9), (3.5, 9), (2, 4.5), (0.5, 4.5)],
                     [(1, 11), (3.5, 11), (2, 15.5), (0.5, 15.5)]):
            pygame.draw.polygon(surf, color, [(x * u, y * u) for x, y in poly])
        _plane_cache[key] = surf
    return _plane_cache[key]


def draw_aviation_band(screen, x, y, w, h, base_font_path, metar):
    """空港の観測（METAR）を1行で描く：飛行機マーク・飛行条件の印・観測値（塗りつぶしなし）"""
    cy = y + h // 2
    icon = _plane_surface(max(12, h - 12), (70, 70, 70))
    screen.blit(icon, (x, cy - icon.get_height() // 2))
    cx = x + icon.get_width() + 8
    cat = metar["category"]
    pill_font = get_font(base_font_path, max(12, min(20, h - 14)), bold=True)
    t = pill_font.render(cat, True, (255, 255, 255))
    pill = pygame.Rect(cx, cy - (t.get_height() + 4) // 2, t.get_width() + 14, t.get_height() + 4)
    pygame.draw.rect(screen, CATEGORY_COLORS.get(cat, (90, 90, 90)), pill, border_radius=6)
    screen.blit(t, (pill.x + 7, pill.y + 2))
    cx = pill.right + 10
    texts, size = aviation.fit_band(aviation.band_parts(metar), x + w - cx,
                                    lambda s, sz: get_font(base_font_path, sz).size(s)[0],
                                    sizes=tuple(sz for sz in (24, 22, 20, 18) if sz <= h - 6) or (h - 6,))
    surf = get_font(base_font_path, size).render(" ".join(texts), True, (0, 0, 0))
    screen.blit(surf, (cx, cy - surf.get_height() // 2))


def draw_fetch_error_bar(screen, width, base_font_path):
    """画面最上部の「通信エラー」帯（ヘッダーの白塗りの後に描く）"""
    err_surf = get_font(base_font_path, 20, bold=True).render(
        "通信エラー：キャッシュデータを表示しています", True, (255, 255, 255)
    )
    bar_h = err_surf.get_height() + 8
    pygame.draw.rect(screen, (180, 0, 0), (0, 0, width, bar_h))
    screen.blit(err_surf, ((width - err_surf.get_width()) // 2, 4))

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
    aviation_metar=None,
    fetch_error=False,
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
        bg_color = wbgt_level_info["bg"]
        pygame.draw.rect(screen, bg_color, (bx, by, bw, bh), border_radius=8)
        pygame.draw.rect(screen, wbgt_level_info["fg"], (bx, by, bw, bh), width=2, border_radius=8)
        ty = by + (bh - inner_h) // 2
        for surf in (lbl_s, lvl_s, val_s):
            screen.blit(surf, (bx + (bw - surf.get_width()) // 2, ty))
            ty += surf.get_height() + 2

    # ===== 4) 航空気象（METAR）の帯：2行目の下〜ヘッダー下端の余白。狭すぎる画面では出さない =====
    if aviation_metar:
        band_y = y2 + info_surf.get_height() + 2
        band_h = header_h - 6 - band_y
        if band_h >= 22:
            margin_x = int(width * 0.05)
            draw_aviation_band(screen, margin_x, band_y, width - margin_x * 2,
                               band_h, base_font_path, aviation_metar)

    # ===== 5) 通信エラーの帯（ヘッダーを白で塗った後に描かないと消える） =====
    if fetch_error:
        draw_fetch_error_bar(screen, width, base_font_path)
