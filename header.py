import socket
import datetime
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
    cpu_text="--"
):
    now = datetime.datetime.now(JST)

    # 上部高さ（これを基準に下側の描画開始も決める）
    header_h = int(height * 0.25)
    header_rect = pygame.Rect(0, 0, width, header_h)

    # 上部は header が責任を持って塗りつぶす
    screen.fill((255, 255, 255), header_rect)

    # ★ 上端余白（ここで調整）
    top_margin = int(height * 0.03)   # ← 好みで 0.02〜0.05
    line_gap   = int(height * 0.01)

    # ===== 1) 大きい日付時刻（中央） =====
    date_str = (
        f"{now.month}月{now.day}日"
        f"（{get_japanese_weekday(now)}） "
        f"{now.strftime('%H:%M')}"
    )
    title_surf = get_font(base_font_path, int(height * 0.14), bold=True).render(date_str, True, (0, 0, 0))
    screen.blit(title_surf, ((width - title_surf.get_width()) // 2, top_margin))

    # ===== 2) 2行目 =====
    info = f"{airport_label}  日の出:{sunrise_str} / 日の入り:{sunset_str}  "
    info_surf = get_font(base_font_path, int(height * 0.035)).render(info, True, (0, 0, 0))

    y2 = top_margin + title_surf.get_height() + line_gap
    x2 = max(10, (width - info_surf.get_width()) // 2)
    screen.blit(info_surf, (x2, y2))