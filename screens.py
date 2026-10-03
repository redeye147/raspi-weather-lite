"""
screens.py
Pi の画面に出す案内画面（設定モード・テザリング仮接続の案内・未接続）と、天気画面左上の接続ラベル。
main01.py から移動（中身は変更なし）。
"""

import time

import pygame

from config import BASE_FONT
from fb_display import present
from utils import make_qr_surface, wait_ms as _wait_ms


def show_ap_screen(screen):
    import json as _json
    ssid, password, portal_url = "WeatherSetup", "setup1234", "http://192.168.50.1/"
    try:
        with open("/run/wifi-setup/state") as f:
            st = _json.load(f)
            ssid       = st.get("ssid",     ssid)
            password   = st.get("password", password)
            portal_url = st.get("url",      portal_url)
    except Exception:
        pass

    screen.fill((10, 12, 20))
    w, h = screen.get_size()
    wifi_qr = make_qr_surface(f"WIFI:S:{ssid};T:WPA;P:{password};;", max_size=160)
    url_qr  = make_qr_surface(portal_url, max_size=160)

    font_title = pygame.font.Font(BASE_FONT, 42)
    font_title.set_bold(True)
    title_surf = font_title.render("WiFi 設定モード", True, (255, 215, 0))
    title_y = 28
    screen.blit(title_surf, ((w - title_surf.get_width()) // 2, title_y))

    qr_size, gap = 160, 80
    qr_y   = title_y + title_surf.get_height() + 24
    left_x = (w - qr_size * 2 - gap) // 2
    right_x = left_x + qr_size + gap
    if wifi_qr: screen.blit(wifi_qr, (left_x,  qr_y))
    if url_qr:  screen.blit(url_qr,  (right_x, qr_y))

    font_label = pygame.font.Font(BASE_FONT, 22)
    label_y = qr_y + qr_size + 6
    for x, text in [(left_x, "① WiFi接続"), (right_x, "② 設定ページ")]:
        s = font_label.render(text, True, (180, 220, 255))
        screen.blit(s, (x + (qr_size - s.get_width()) // 2, label_y))

    info_y = label_y + font_label.get_height() + 20
    for text, color, bold in [
        (f"SSID: {ssid}", (255, 255, 255), True),
        (f"PW:   {password}", (200, 200, 200), False),
        ("", (0, 0, 0), False),
        (f"URL: {portal_url}", (100, 200, 255), True),
        ("", (0, 0, 0), False),
        ("設定ページで「WiFi 設定（パスワードが必要）」→ 管理パスワードを入力", (200, 200, 200), False),
    ]:
        if not text:
            info_y += 12
            continue
        f = pygame.font.Font(BASE_FONT, 26)
        if bold: f.set_bold(True)
        s = f.render(text, True, color)
        screen.blit(s, ((w - s.get_width()) // 2, info_y))
        info_y += s.get_height() + 4
    present(screen)


def show_hotspot_announce(screen, ip: str, ssid: str, seconds: int = 30) -> bool:
    """テザリングで仮接続したことと、現場 WiFi の設定手順を seconds 秒表示する。
    ESC / 終了要求なら False を返す。描画は1回だけ（fb0 モードで重いため）。"""
    screen.fill((10, 12, 20))
    w, h = screen.get_size()
    k = h / 1080
    F = lambda size, bold=False: (lambda f: (f.set_bold(bold), f)[1])(pygame.font.Font(BASE_FONT, max(12, int(size * k))))
    url = f"http://{ip}:8080" if ip else "http://<PiのIP>:8080"

    qr_size = int(h * 0.36)
    qr = make_qr_surface(url, max_size=qr_size) if ip else None
    text_w = w - (qr_size + int(160 * k) if qr else int(120 * k))
    x = int(80 * k)
    y = int(90 * k)

    def line(text, size, color, bold=False, gap=10):
        nonlocal y
        surf = F(size, bold).render(text, True, color)
        screen.blit(surf, (x, y))
        y += surf.get_height() + int(gap * k)

    line("スマホのテザリングで仮接続しました", 56, (255, 170, 60), True, 14)
    line(f"テザリング名「{ssid}」   この Pi の IP：{ip or '取得中'}", 30, (200, 200, 200), False, 40)
    line("現場の WiFi を設定する手順", 38, (255, 255, 255), True, 18)
    for step in (
        "① テザリング中のスマホで右の QR コードを読み取る",
        f"　（または ブラウザで {url} を開く）",
        "② 「WiFi 設定（パスワードが必要）」を押し、管理パスワードを入力",
        "③ 現場の WiFi を選び、WiFi のパスワードを入力して「WiFi を保存して再起動」",
        "④ 天気画面の左上の「仮接続中」が消えたら、テザリングをオフにする",
        "※ 管理パスワードは設置担当者に確認してください",
    ):
        line(step, 32, (230, 230, 230), False, 12)

    if qr:
        qx = w - qr.get_width() - int(100 * k)
        qy = int(h * 0.30)
        pygame.draw.rect(screen, (255, 255, 255), (qx - 12, qy - 12, qr.get_width() + 24, qr.get_height() + 24))
        screen.blit(qr, (qx, qy))

    foot = F(28).render(f"{seconds}秒後に天気画面に切り替わります（仮接続中は左上にラベルを表示）", True, (150, 150, 150))
    screen.blit(foot, ((w - foot.get_width()) // 2, h - foot.get_height() - int(60 * k)))
    present(screen)

    end = time.time() + seconds
    while time.time() < end:
        _wait_ms(500)
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                return False
    return True


CONN_LABELS = {
    "hotspot":  ("仮接続中", (230, 110, 0)),
    "ethernet": ("有線LAN接続", (30, 100, 200)),
}


def draw_conn_label(screen, height, kind: str):
    """天気画面の左上に接続状態ラベルを描く（テザリング＝仮接続中、有線のみ＝有線LAN接続）"""
    if kind not in CONN_LABELS:
        return
    text, color = CONN_LABELS[kind]
    f = pygame.font.Font(BASE_FONT, max(14, int(height * 0.032)))
    f.set_bold(True)
    t = f.render(text, True, (255, 255, 255))
    pad = 10
    rect = pygame.Rect(12, 12, t.get_width() + pad * 2, t.get_height() + pad)
    pygame.draw.rect(screen, color, rect, border_radius=8)
    screen.blit(t, (rect.x + pad, rect.y + pad // 2))


def show_no_dongle_screen(screen, hotspot_ssid: str = "", wired: str = ""):
    screen.fill((10, 12, 20))
    w, h = screen.get_size()
    lines = [
        ("ネットワークに接続できません", 42, (255, 80, 80), True),
        ("", 24, None, False),
    ]
    if wired == "no_ip":
        lines += [
            ("有線LAN：ケーブル接続済み・IP取得中（DHCP の応答がありません）", 30, (255, 215, 0), True),
            ("ルーター/ハブ側のケーブル・DHCP 設定を確認してください（IP が取れれば自動で天気画面になります）", 22, (160, 160, 160), False),
            ("", 24, None, False),
        ]
    else:
        lines += [("", 16, None, False)]
    if hotspot_ssid:
        lines += [
            ("スマホのテザリングをオンにしてください", 38, (255, 255, 255), True),
            ("", 12, None, False),
            (f"テザリング名「{hotspot_ssid}」（2.4GHz / WPA2）", 30, (255, 215, 0), True),
            ("つながると天気画面になります。「今日の天気」欄の右端のQRコードから現場のWiFiを設定できます（管理パスワードが必要）", 24, (160, 160, 160), False),
            ("", 36, None, False),
            ("または LANケーブルを接続（有線LANで天気を表示）／ USBドングルを接続（設定モード）", 26, (160, 160, 160), False),
        ]
    elif wired == "no_ip":
        lines += [
            ("または USBドングルを接続すると設定モードが起動します", 28, (200, 200, 200), False),
        ]
    else:
        lines += [
            ("LANケーブル または USBドングルを接続してください", 38, (255, 255, 255), True),
            ("", 24, None, False),
            ("LAN：有線でそのまま天気を表示（QRコードから WiFi を設定可能・管理パスワードが必要）", 26, (160, 160, 160), False),
            ("ドングル：自動で設定モードが起動します", 26, (160, 160, 160), False),
        ]
    total_h = sum(pygame.font.Font(BASE_FONT, size).get_height() + 8 if text else size
                  for text, size, _, _ in lines)
    y = (h - total_h) // 2
    for text, size, color, bold in lines:
        if not text:
            y += size
            continue
        f = pygame.font.Font(BASE_FONT, size)
        if bold: f.set_bold(True)
        s = f.render(text, True, color)
        screen.blit(s, ((w - s.get_width()) // 2, y))
        y += s.get_height() + 8
    present(screen)
