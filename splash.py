"""
splash.py
起動時のスプラッシュ画面（初回の天気取得中の表示）。
main01.py から移動（中身は変更なし）。
"""

import time

import pygame

import fb_display
from fb_display import present
from fetch_weather import FETCH_TIMEOUT
from utils import wait_ms as _wait_ms

# 全角文字はIPAフォントに確実に含まれる
_SPINNER = ["｜", "／", "―", "＼"]


# ==========================================================
# スプラッシュ画面
# ==========================================================
def _draw_splash_frame(screen, width, height, base_font,
                       airport_label, git_version_str, steps):
    """
    スプラッシュ1フレームを描画して flip する。
    steps: list of (label: str, status: 'done'|'active'|'pending')
    """
    screen.fill((10, 12, 20))

    # ── タイトル ────────────────────────────────
    f_title = pygame.font.Font(base_font, 54)
    f_title.set_bold(True)
    t = f_title.render("天気サイネージ", True, (255, 215, 0))
    title_y = int(height * 0.17)
    screen.blit(t, ((width - t.get_width()) // 2, title_y))

    # ── 空港名 ───────────────────────────────
    f_airport = pygame.font.Font(base_font, 34)
    a = f_airport.render(airport_label, True, (160, 210, 255))
    screen.blit(a, ((width - a.get_width()) // 2,
                    title_y + t.get_height() + 12))

    # ── ステップリスト ─────────────────────────
    f_step = pygame.font.Font(base_font, 26)
    spinner = _SPINNER[int(time.time() * 4) % len(_SPINNER)]
    step_x = (width - 460) // 2
    step_y = int(height * 0.50)
    last_bottom = step_y

    for label, status in steps:
        if status == "done":
            icon  = "✓"
            color = (80, 210, 80)
        elif status == "active":
            dots  = "." * (int(time.time() * 2) % 4)
            label = label.rstrip(".") + dots
            icon  = spinner
            color = (255, 210, 50)
        else:
            icon  = "・"
            color = (70, 75, 90)

        s = f_step.render(f"  {icon}   {label}", True, color)
        screen.blit(s, (step_x, step_y))
        last_bottom = step_y + s.get_height()
        step_y = last_bottom + 12

    # ── プログレスバー（active ステップがある間だけ表示）─
    has_active = any(st == "active" for _, st in steps)
    if has_active:
        elapsed  = time.time() - _draw_splash_frame._fetch_start
        progress = min(elapsed / FETCH_TIMEOUT, 0.95)
        bar_w, bar_h = 460, 14
        bar_x = (width - bar_w) // 2
        bar_y = last_bottom + 22
        pygame.draw.rect(screen, (35, 40, 60),
                         (bar_x, bar_y, bar_w, bar_h), border_radius=7)
        fill_w = int(bar_w * progress)
        if fill_w > 0:
            pygame.draw.rect(screen, (55, 130, 255),
                             (bar_x, bar_y, fill_w, bar_h), border_radius=7)
        f_pct = pygame.font.Font(base_font, 20)
        pct_s = f_pct.render(f"{int(progress * 100)}%", True, (110, 150, 220))
        screen.blit(pct_s, (bar_x + bar_w + 14, bar_y - 2))

    # ── バージョン情報（右下）────────────────────
    if git_version_str:
        f_ver = pygame.font.Font(base_font, 16)
        v = f_ver.render(git_version_str, True, (75, 80, 100))
        screen.blit(v, (width - v.get_width() - 14,
                        height - v.get_height() - 12))

    present(screen)

# フェッチ開始時刻をモジュールレベルで共有するための属性
_draw_splash_frame._fetch_start = 0.0


def _fade(screen, width, height, base_font, airport_label,
          git_version_str, steps, to_black: bool,
          steps_count=18, delay_ms=28):
    """フェードイン（to_black=False）またはフェードアウト（to_black=True）。
    fb0 モードは1回の描画が重い（Pi Zero W で1〜2秒）ため、フェードせず最終フレームだけ描く。"""
    if fb_display.RENDER_MODE == "fb0":
        if to_black:
            screen.fill((0, 0, 0))
            present(screen)
        else:
            _draw_splash_frame(screen, width, height, base_font, airport_label, git_version_str, steps)
        return
    veil = pygame.Surface((width, height))
    veil.fill((0, 0, 0))
    for i in range(steps_count + 1):
        _draw_splash_frame(screen, width, height, base_font,
                           airport_label, git_version_str, steps)
        alpha = int(255 * i / steps_count) if to_black \
                else int(255 * (steps_count - i) / steps_count)
        veil.set_alpha(alpha)
        screen.blit(veil, (0, 0))
        present(screen)
        _wait_ms(delay_ms)


def run_splash(screen, width, height, base_font,
              airport_label, git_version_str, fetcher):
    """
    スプラッシュを表示しながら初回天気取得を実行する。
    戻り値: (hourly, daily, fetch_ok)
    ESC が押された場合は (None, None, False)。
    """
    steps = [
        ("システム起動",        "done"),
        ("WiFi 接続確認",       "done"),
        ("天気データ取得中",   "active"),
    ]

    # フェードイン
    _draw_splash_frame._fetch_start = time.time()
    fetcher.start()
    _fade(screen, width, height, base_font, airport_label,
          git_version_str, steps, to_black=False)

    # 取得完了待ちループ（200ms 間隔で完了確認。再描画は fb0 では5秒に1回＝取得スレッドに CPU を譲る）
    hourly = daily = None
    fetch_ok = False
    redraw_every = 5.0 if fb_display.RENDER_MODE == "fb0" else 0.2
    last_frame = time.time()   # フェードイン直後に描画済み
    while True:
        done, h, d, ok = fetcher.poll()
        if time.time() - last_frame >= redraw_every:
            _draw_splash_frame(screen, width, height, base_font,
                               airport_label, git_version_str, steps)
            last_frame = time.time()
        if done:
            hourly, daily, fetch_ok = h, d, bool(ok)
            break
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None, None, False
        _wait_ms(200)

    # 完了ステップを表示して0.8秒待つ
    if fetch_ok:
        steps[2] = ("天気データ取得完了", "done")
    else:
        steps[2] = ("取得失敗（キャッシュ使用）", "done")
    _draw_splash_frame(screen, width, height, base_font,
                       airport_label, git_version_str, steps)
    _wait_ms(800)

    # フェードアウト
    _fade(screen, width, height, base_font, airport_label,
          git_version_str, steps, to_black=True)

    return hourly, daily, fetch_ok
