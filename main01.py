#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main01.py
- flip/update は main 側で 1回だけ
- KEN画像は main 側で常時表示（12時は ken6）
- KENロードは display確立（set_mode）後に実行（surface invalid 対策）
- 天気取得はバックグラウンドスレッドで実行（メインループのハング防止）
- 起動時スプラッシュ画面（フェードイン/アウト・ローディングステップ・バージョン表示）
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pygame
import argparse
import datetime
import time
import shutil
import logging
import logging.handlers
import traceback
import threading
import socket
import requests
import psutil
import subprocess

from header import draw_header
from weather_draw import draw_weather
from fetch_wbgt import fetch_wbgt, WBGT_LEVELS
from utils import get_sunrise_sunset_str, build_work_summary, JST, get_local_ip, make_qr_surface
from jma_alerts import get_overview_and_warning

from config import AIRPORT_CONFIG, LOG_FILE, ICON_DIR

from fetch_weather import (
    fetch_weather_openmeteo,
    fetch_weather_jma,
    load_cached_weather
)

BASE_FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"

FETCH_TIMEOUT = 30

socket.setdefaulttimeout(15)

# 全角文字はIPAフォントに確実に含まれる
_SPINNER = ["｜", "／", "―", "＼"]


# ==========================================================
# バックグラウンド天気取得クラス
# ==========================================================
class WeatherFetcher:
    def __init__(self, cfg, args):
        self._cfg = cfg
        self._args = args
        self._thread = None
        self._result = None
        self._ok = False
        self._event = threading.Event()
        self._started_at = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._result = None
        self._ok = False
        self._event.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            cfg, args = self._cfg, self._args
            if args.jma:
                hourly, om_daily = fetch_weather_openmeteo(cfg["latitude"], cfg["longitude"])
                _, jma_daily = fetch_weather_jma(cfg["office_code"], cfg["area_codes"])
                om_map = {d["date"]: d for d in om_daily}
                daily = []
                for d in jma_daily[:5]:
                    od = om_map.get(d.get("date"))
                    if od:
                        if d.get("pop") in ("-%", "", None):
                            d["pop"] = od.get("pop")
                        if d.get("temp") in ("-/-", "", None):
                            d["temp"] = od.get("temp")
                    daily.append(d)
            else:
                hourly, daily = fetch_weather_openmeteo(cfg["latitude"], cfg["longitude"])
            self._result = (hourly, daily)
            self._ok = True
        except Exception as e:
            logging.error(f"WeatherFetcher error: {e}")
            self._ok = False
        finally:
            self._event.set()

    def poll(self):
        if self._thread is None:
            return False, None, None, None
        if self._event.is_set():
            self._thread = None
            if self._ok and self._result:
                return True, self._result[0], self._result[1], True
            return True, None, None, False
        if time.time() - self._started_at > FETCH_TIMEOUT:
            logging.error(f"WeatherFetcher: タイムアウト ({FETCH_TIMEOUT}秒) スレッドを放棄")
            self._thread = None
            return True, None, None, False
        return False, None, None, None

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()


# ==========================================================
# gitバージョン情報取得（起動時1回）
# ==========================================================
def get_git_version_str():
    try:
        cwd = os.path.dirname(os.path.abspath(__file__))
        env = os.environ.copy()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "safe.directory"
        env["GIT_CONFIG_VALUE_0"] = cwd
        hash_ = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, stderr=subprocess.DEVNULL, env=env
        ).decode().strip()
        ts = subprocess.check_output(
            ["git", "log", "-1", "--format=%ct"],
            cwd=cwd, stderr=subprocess.DEVNULL, env=env
        ).decode().strip()
        date_ = datetime.datetime.fromtimestamp(int(ts), JST).strftime("%Y-%m-%d %H:%M")
        return f"{hash_}  {date_}"
    except Exception:
        return ""


# ==========================================================
# ログローテーション
# ==========================================================
def setup_logging():
    log_path = "/home/pi/raspi-weather-lite/displayraspi_log.txt"
    handler = logging.handlers.TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=7, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if root_logger.handlers:
        root_logger.handlers.clear()
    root_logger.addHandler(handler)


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

    # ── タイトル ──────────────────────────────────
    f_title = pygame.font.Font(base_font, 54)
    f_title.set_bold(True)
    t = f_title.render("天気サイネージ", True, (255, 215, 0))
    title_y = int(height * 0.17)
    screen.blit(t, ((width - t.get_width()) // 2, title_y))

    # ── 空港名 ────────────────────────────────────
    f_airport = pygame.font.Font(base_font, 34)
    a = f_airport.render(airport_label, True, (160, 210, 255))
    screen.blit(a, ((width - a.get_width()) // 2,
                    title_y + t.get_height() + 12))

    # ── ステップリスト ─────────────────────────────
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

    # ── バージョン情報（右下）────────────────────────
    if git_version_str:
        f_ver = pygame.font.Font(base_font, 16)
        v = f_ver.render(git_version_str, True, (75, 80, 100))
        screen.blit(v, (width - v.get_width() - 14,
                        height - v.get_height() - 12))

    pygame.display.flip()

# フェッチ開始時刻をモジュールレベルで共有するための属性
_draw_splash_frame._fetch_start = 0.0


def _fade(screen, width, height, base_font, airport_label,
          git_version_str, steps, to_black: bool,
          steps_count=18, delay_ms=28):
    """フェードイン（to_black=False）またはフェードアウト（to_black=True）。"""
    veil = pygame.Surface((width, height))
    veil.fill((0, 0, 0))
    for i in range(steps_count + 1):
        _draw_splash_frame(screen, width, height, base_font,
                           airport_label, git_version_str, steps)
        alpha = int(255 * i / steps_count) if to_black \
                else int(255 * (steps_count - i) / steps_count)
        veil.set_alpha(alpha)
        screen.blit(veil, (0, 0))
        pygame.display.flip()
        pygame.time.wait(delay_ms)


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

    # 取得完了待ちループ（200ms間隔で再描画）
    hourly = daily = None
    fetch_ok = False
    while True:
        done, h, d, ok = fetcher.poll()
        _draw_splash_frame(screen, width, height, base_font,
                           airport_label, git_version_str, steps)
        if done:
            hourly, daily, fetch_ok = h, d, bool(ok)
            break
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None, None, False
        pygame.time.wait(200)

    # 完了ステップを表示して0.8秒待つ
    if fetch_ok:
        steps[2] = ("天気データ取得完了", "done")
    else:
        steps[2] = ("取得失敗（キャッシュ使用）", "done")
    _draw_splash_frame(screen, width, height, base_font,
                       airport_label, git_version_str, steps)
    pygame.time.wait(800)

    # フェードアウト
    _fade(screen, width, height, base_font, airport_label,
          git_version_str, steps, to_black=True)

    return hourly, daily, fetch_ok


# ==========================================================
# WiFi / AP 関連
# ==========================================================
def is_wifi_connected() -> bool:
    try:
        result = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=3)
        return bool(result.stdout.strip())
    except Exception:
        return True


def is_ap_mode_active() -> bool:
    return os.path.exists("/run/wifi-setup/state")


def has_wlan1() -> bool:
    return os.path.exists("/sys/class/net/wlan1")


_last_ap_trigger_time = 0.0

def trigger_ap_mode() -> bool:
    global _last_ap_trigger_time
    if time.time() - _last_ap_trigger_time < 60:
        return False
    try:
        subprocess.Popen(
            ["sudo", "systemctl", "start", "wifi-setup-mode"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _last_ap_trigger_time = time.time()
        logging.info("wifi-setup-mode 自動起動をトリガ")
        return True
    except Exception as e:
        logging.error(f"wifi-setup-mode 起動失敗: {e}")
        return False


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
    ]:
        if not text:
            info_y += 12
            continue
        f = pygame.font.Font(BASE_FONT, 26)
        if bold: f.set_bold(True)
        s = f.render(text, True, color)
        screen.blit(s, ((w - s.get_width()) // 2, info_y))
        info_y += s.get_height() + 4
    pygame.display.flip()


def show_no_dongle_screen(screen):
    screen.fill((10, 12, 20))
    w, h = screen.get_size()
    lines = [
        ("WiFiに接続できません", 42, (255, 80, 80), True),
        ("", 40, None, False),
        ("USBドングルを接続してください", 38, (255, 255, 255), True),
        ("", 24, None, False),
        ("ドングルを挿すと自動で設定モードが起動します", 26, (160, 160, 160), False),
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
    pygame.display.flip()


def load_ken_image(path: str, scale_h: int = 100) -> pygame.Surface:
    img = pygame.image.load(path).convert_alpha()
    w, h = img.get_size()
    if h <= 0:
        raise ValueError(f"Invalid image size: {img.get_size()} for {path}")
    scale_w = int(w * (scale_h / h))
    return pygame.transform.smoothscale(img, (scale_w, scale_h))


# ==========================================================
# メイン
# ==========================================================
def main():
    print("=== MAIN START ===", flush=True)
    setup_logging()

    import json as _json
    _cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    _default_airport = "centrair"
    _default_interval = 2.0
    try:
        _cfg = _json.load(open(_cfg_path))
        _default_airport = _cfg.get("airport", "centrair")
        _default_interval = float(_cfg.get("interval_hours", 2.0))
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--airport",
        choices=["narita", "haneda", "centrair", "kanku", "chitose", "fukuoka", "naha"],
        default=_default_airport)
    parser.add_argument("--jma", action="store_true", default=True)
    parser.add_argument("--interval-hours", type=float, default=_default_interval)
    parser.add_argument("--no-hdmi-refresh", action="store_true")
    parser.add_argument("--test-case", type=int, choices=[3, 4], default=None,
                        help="テスト用: 3=QR設定画面, 4=ドングル未接続画面 を強制表示（ESCで終了）")
    parser.add_argument("--wbgt-test", type=float, default=None, metavar="WBGT",
                        help="WBGT値(℃)を指定してバッジをテスト（例: --wbgt-test 35）")
    parser.add_argument("--wbgt-alert", action="store_true",
                        help="熱中症警戒アラートバナーを強制表示")
    args, unknown = parser.parse_known_args()

    airport = args.airport
    cfg = AIRPORT_CONFIG.get(airport)
    if not cfg:
        raise ValueError("未対応 airport")

    AIRPORT_LABELS = {
        "narita":   "成田空港",
        "haneda":   "羽田空港",
        "centrair": "中部国際空港",
        "kanku":    "関西国際空港",
        "chitose":  "新千歳空港",
        "fukuoka":  "福岡空港",
        "naha":     "那覇空港",
    }
    airport_label = AIRPORT_LABELS.get(airport, airport)
    logging.info(f"起動: airport={airport} interval={args.interval_hours}h")

    os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
    os.environ["SDL_VIDEO_CENTERED"] = "0"
    os.environ["SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS"] = "0"

    pygame.init()
    pygame.font.init()

    if not pygame.display.get_init():
        driver = os.environ.get("SDL_VIDEODRIVER", "(unset)")
        raise RuntimeError(
            f"pygame display init failed (SDL_VIDEODRIVER={driver}). "
            "DRM デバイスが使用中か、ドライバが見つかりません。"
        )

    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Weather Signage")
    width, height = screen.get_size()

    if args.test_case is not None:
        if args.test_case == 3:
            show_ap_screen(screen)
        else:
            show_no_dongle_screen(screen)
        while True:
            pygame.time.wait(200)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    pygame.quit(); return

    if not is_wifi_connected() or is_ap_mode_active():
        while True:
            if is_wifi_connected() and not is_ap_mode_active():
                break
            if is_ap_mode_active():
                show_ap_screen(screen)
            elif has_wlan1():
                trigger_ap_mode()
                show_ap_screen(screen)
            else:
                show_no_dongle_screen(screen)
            pygame.time.wait(5000)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); return

    cpu_text = "--"
    last_cpu_update = 0
    psutil.cpu_percent(interval=None)
    icon_cache = {}

    git_version_str = get_git_version_str()
    git_surf = None
    if git_version_str:
        git_font = pygame.font.Font(BASE_FONT, 16)
        git_surf = git_font.render(git_version_str, True, (150, 150, 150))

    _local_ip = get_local_ip()
    qr_surf = make_qr_surface(f"http://{_local_ip}:8080", max_size=54) if _local_ip else None
    _qr_date = None

    KEN1_PATH = os.path.join(ICON_DIR, "ken1.png")
    KEN6_PATH = os.path.join(ICON_DIR, "ken6.png")
    ken_img = None
    ken_key_last = "ken1"
    try:
        ken_img = load_ken_image(KEN1_PATH, scale_h=100)
    except Exception as e:
        print("KEN load error:", KEN1_PATH, repr(e), flush=True)
        ken_key_last = None

    HEADERS = {"User-Agent": "Mozilla/5.0"}
    AIRPORT_WARNING = {
        "narita":   {"pref": "120000", "city": "1221100"},
        "haneda":   {"pref": "130000", "city": "1311100"},
        "centrair": {"pref": "230000", "city": "2321600"},
        "kanku":    {"pref": "270000", "city": "2722000"},
        "chitose":  {"pref": "016000", "city": "0122400"},
        "fukuoka":  {"pref": "400000", "city": "4013000"},
        "naha":     {"pref": "471000", "city": "4720100"},
    }
    MONITOR_CODES = {
        "02": "大雨警報", "03": "大雨注意報", "04": "洪水警報", "05": "洪水注意報",
        "12": "大雪警報", "13": "大雪注意報", "15": "強風注意報", "16": "波浪注意報",
        "21": "乾燥注意報", "33": "濃霧注意報", "43": "雷注意報", "44": "暴風警報",
    }

    def fetch_warning_data(airport_key: str):
        info = AIRPORT_WARNING[airport_key]
        url = f"https://www.jma.go.jp/bosai/warning/data/warning/{info['pref']}.json"
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            data = r.json()
        except Exception:
            return "警報取得失敗", ""
        warning_list = []
        headline = data.get("headlineText", "")
        for area_type in data.get("areaTypes", []):
            for area in area_type.get("areas", []):
                if area.get("code") == info["city"]:
                    for w in area.get("warnings", []):
                        code = str(w.get("code"))
                        status = w.get("status", "")
                        if code in MONITOR_CODES and "解除" not in status:
                            warning_list.append(MONITOR_CODES[code])
        if not warning_list:
            return "警報・注意報なし", headline
        return " / ".join(warning_list), headline

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    jma_cache_path = os.path.join(BASE_DIR, f"jma_{airport}.json")

    jma_data = get_overview_and_warning(
        office_code=cfg["office_code"],
        area_codes=cfg["area_codes"],
        cache_json_path=jma_cache_path
    )
    headline_text = jma_data.get("headline", "")
    updated_text  = jma_data.get("updated", "")

    try:
        warning_text, _ = fetch_warning_data(airport)
    except Exception as e:
        logging.error(f"初回警報取得失敗: {e}")
        warning_text = "警報取得失敗"
    last_jma_update = time.time()
    weather_updated_text = ""

    # ── スプラッシュ表示 + 初回天気取得 ──────────────────
    fetcher = WeatherFetcher(cfg, args)
    splash_hourly, splash_daily, fetch_ok = run_splash(
        screen, width, height, BASE_FONT,
        airport_label, git_version_str, fetcher
    )
    if splash_hourly is not None:
        hourly, daily = splash_hourly, splash_daily
        last_weather_update = datetime.datetime.now(JST)
        weather_updated_text = last_weather_update.strftime("天気更新 %H:%M")
        logging.info("初回天気取得成功")
    else:
        hourly, daily = load_cached_weather()
        last_weather_update = datetime.datetime.now(JST)
        weather_updated_text = last_weather_update.strftime("天気更新 %H:%M")
        fetch_ok = False
        logging.warning("スプラッシュ中断またはフェッチ失敗: キャッシュ使用")

    last_time_update_minute = -1
    xdotool = shutil.which("xdotool")
    needs_redraw = False
    last_drawn_minute = -1
    last_wifi_check = time.time()
    _sunrise_date = None
    sunrise_str, sunset_str = "", ""

    # WBGT 初期化
    wbgt_alert = args.wbgt_alert
    wbgt_level_info = None
    if args.wbgt_test is not None:
        v = args.wbgt_test
        for threshold, label, bg, fg in WBGT_LEVELS:
            if v >= threshold:
                wbgt_level_info = {"label": label, "bg": bg, "fg": fg, "value": v}
                break
        wbgt_alert = wbgt_alert or (v >= 33)
        logging.info(f"WBGT テストモード: value={v} level={wbgt_level_info and wbgt_level_info['label']}")
    last_wbgt_update = 0.0 if args.wbgt_test is None else time.time()
    last_blink_state = -1

    work_summary = build_work_summary(hourly)
    _fetch_pending = False

    # ==========================================================
    # メインループ
    # ==========================================================
    while True:
        now = datetime.datetime.now(JST)
        needs_redraw = False

        if is_ap_mode_active():
            show_ap_screen(screen)
            while is_ap_mode_active():
                pygame.time.wait(5000)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit(); return
                show_ap_screen(screen)
            needs_redraw = True
            continue

        if time.time() - last_wifi_check >= 30:
            last_wifi_check = time.time()
            if not is_wifi_connected() and has_wlan1() and not is_ap_mode_active():
                logging.warning("WiFi切断検出 → AP モード自動起動")
                trigger_ap_mode()

        if time.time() - last_cpu_update >= 10:
            cpu = psutil.cpu_percent(interval=None)
            cpu_text = f"{cpu:.0f}%"
            last_cpu_update = time.time()
            needs_redraw = True

        if now.minute != last_drawn_minute:
            needs_redraw = True
            last_time_update_minute = now.minute
            if xdotool:
                subprocess.run([xdotool, "key", "Shift_L"], capture_output=True)

        ken_key = "ken6" if now.hour == 12 else "ken1"
        if ken_key != ken_key_last:
            try:
                path = KEN6_PATH if ken_key == "ken6" else KEN1_PATH
                ken_img = load_ken_image(path, scale_h=100)
                ken_key_last = ken_key
                needs_redraw = True
            except Exception:
                ken_img = None
                ken_key_last = None

        if now.hour == 23 and now.minute == 50:
            today_str = now.strftime("%Y-%m-%d")
            if getattr(main, "_updated_2350_date", "") != today_str and not _fetch_pending:
                fetcher.start()
                _fetch_pending = True
                main._updated_2350_date = today_str
                logging.info("23:50定時取得開始")

        # WBGT 更新（1時間ごと、テスト時はスキップ）
        if args.wbgt_test is None and time.time() - last_wbgt_update > 3600:
            try:
                _, wbgt_alert, wbgt_level_info = fetch_wbgt(airport)
                if args.wbgt_alert:
                    wbgt_alert = True
                last_wbgt_update = time.time()
                needs_redraw = True
            except Exception as e:
                logging.error(f"WBGT更新失敗: {e}")

        if time.time() - last_jma_update > 3600:
            try:
                new_warn, _ = fetch_warning_data(airport)
                warning_text = new_warn
                jma_data = get_overview_and_warning(
                    office_code=cfg["office_code"],
                    area_codes=cfg["area_codes"],
                    cache_json_path=jma_cache_path,
                )
                headline_text = jma_data.get("headline", "")
                updated_text  = jma_data.get("updated", "")
                last_jma_update = time.time()
                needs_redraw = True
            except Exception as e:
                logging.error(f"JMA更新失敗: {e}")

        if not _fetch_pending and (now - last_weather_update).total_seconds() >= args.interval_hours * 3600:
            if 5 < now.hour <= 23:
                fetcher.start()
                _fetch_pending = True
                logging.info("定期天気取得開始")
            else:
                last_weather_update = now

        if _fetch_pending:
            done, new_hourly, new_daily, ok = fetcher.poll()
            if done:
                _fetch_pending = False
                if ok and new_hourly is not None:
                    hourly = new_hourly
                    daily = new_daily
                    last_weather_update = now
                    weather_updated_text = now.strftime("天気更新 %H:%M")
                    work_summary = build_work_summary(hourly)
                    fetch_ok = True
                    logging.info("天気取得完了")
                else:
                    last_weather_update = now - datetime.timedelta(hours=args.interval_hours) \
                                              + datetime.timedelta(minutes=30)
                    fetch_ok = False
                    logging.error("天気取得失敗またはタイムアウト。30分後に再試行")
                needs_redraw = True

        # 危険レベル時はバッジ点滅のため１秒ごとに再描画
        is_danger = wbgt_level_info is not None and wbgt_level_info.get("label") == "危険"
        if is_danger:
            cur_blink = int(time.time()) % 2
            if cur_blink != last_blink_state:
                needs_redraw = True
                last_blink_state = cur_blink

        if now.date() != _sunrise_date:
            sunrise_str, sunset_str = get_sunrise_sunset_str(cfg["latitude"], cfg["longitude"])
            _sunrise_date = now.date()
            needs_redraw = True

        if now.date() != _qr_date:
            _cur_ip = get_local_ip()
            if _cur_ip:
                qr_surf = make_qr_surface(f"http://{_cur_ip}:8080", max_size=54)
            _qr_date = now.date()

        if not needs_redraw:
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    pygame.quit(); return
            pygame.time.wait(1000 if is_danger else 10000)
            continue

        draw_weather(
            screen, width, height,
            hourly, daily, icon_cache, BASE_FONT,
            warning_text, headline_text, updated_text,
            weather_updated_text, airport_label,
            sunrise_str, sunset_str, work_summary, cpu_text,
            fetch_ok=fetch_ok, qr_surf=qr_surf,
            wbgt_level_info=wbgt_level_info,
            wbgt_alert=wbgt_alert,
        )

        draw_header(
            screen, width, height, BASE_FONT,
            airport_label, sunrise_str, sunset_str, "", "",
            wbgt_level_info=wbgt_level_info,
        )

        if ken_img is not None:
            margin = 30
            screen.blit(ken_img,
                (width - ken_img.get_width() - margin,
                 height - ken_img.get_height() - margin))

        if git_surf is not None:
            screen.blit(git_surf,
                (width - git_surf.get_width() - 8,
                 height - git_surf.get_height() - 4))

        pygame.display.flip()
        last_drawn_minute = now.minute

        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit(); return

        pygame.time.wait(1000 if is_danger else 10000)


def run_forever():
    backoff = 5
    while True:
        try:
            main()
            print("main() exited unexpectedly. restarting...", flush=True)
        except KeyboardInterrupt:
            print("KeyboardInterrupt: exiting.", flush=True)
            raise
        except Exception:
            print("FATAL ERROR", flush=True)
            traceback.print_exc()
        try:
            pygame.quit()
        except Exception:
            pass
        time.sleep(backoff)


if __name__ == "__main__":
    run_forever()
