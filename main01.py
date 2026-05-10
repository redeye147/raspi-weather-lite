#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main01.py
E61c 完全互換100%版（整理版）
- flip/update は main 側で 1回だけ
- KEN画像は main 側で常時表示（12時は ken6）
- KENロードは display確立（set_mode）後に実行（surface invalid 対策）
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
import requests
import psutil
import subprocess

from header import draw_header
from weather_draw import draw_weather
from utils import get_sunrise_sunset_str, build_work_summary, JST, get_local_ip, make_qr_surface
from jma_alerts import get_overview_and_warning

from config import AIRPORT_CONFIG, LOG_FILE, ICON_DIR

from fetch_weather import (
    fetch_weather_openmeteo,
    fetch_weather_jma,
    load_cached_weather
)

BASE_FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"

# ==========================================================
# gitバージョン情報取得（起動時1回）
# ==========================================================
def get_git_version_str():
    try:
        cwd = os.path.dirname(os.path.abspath(__file__))
        hash_ = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, stderr=subprocess.DEVNULL
        ).decode().strip()
        date_ = subprocess.check_output(
            ["git", "log", "-1", "--format=%ci"],
            cwd=cwd, stderr=subprocess.DEVNULL
        ).decode().strip()[:16]
        return f"{hash_}  {date_}"
    except Exception:
        return ""

# ==========================================================
# ログローテーション（E61cと同等）
# ==========================================================
def setup_logging():
    log_path = "/home/pi/raspi-weather-lite/displayraspi_log.txt"
    handler = logging.handlers.TimedRotatingFileHandler(
        log_path,
        when="midnight",
        backupCount=7,
        encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if root_logger.handlers:
        root_logger.handlers.clear()
    root_logger.addHandler(handler)

# ==========================================================
# WiFi接続確認
# ==========================================================
def is_wifi_connected() -> bool:
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True, text=True, timeout=3
        )
        return bool(result.stdout.strip())
    except Exception:
        return True


# ==========================================================
# APモードアクティブ確認
# ==========================================================
def is_ap_mode_active() -> bool:
    """start_ap.sh が /run/wifi-setup/state を作成・stop_ap.sh が削除する。"""
    return os.path.exists("/run/wifi-setup/state")


# ==========================================================
# APモード案内画面（QRコード2枚）
# ==========================================================
def show_ap_screen(screen):
    import json as _json

    ssid       = "WeatherSetup"
    password   = "setup1234"
    portal_url = "http://192.168.50.1/"

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

    qr_size = 160
    gap     = 80
    qr_y    = title_y + title_surf.get_height() + 24
    left_x  = (w - qr_size * 2 - gap) // 2
    right_x = left_x + qr_size + gap

    if wifi_qr:
        screen.blit(wifi_qr, (left_x, qr_y))
    if url_qr:
        screen.blit(url_qr, (right_x, qr_y))

    font_label = pygame.font.Font(BASE_FONT, 22)
    label_y = qr_y + qr_size + 6
    for x, text in [(left_x, "① WiFi接続"), (right_x, "② 設定ページ")]:
        s = font_label.render(text, True, (180, 220, 255))
        screen.blit(s, (x + (qr_size - s.get_width()) // 2, label_y))

    info_y = label_y + font_label.get_height() + 20
    for text, color, bold in [
        (f"SSID: {ssid}",      (255, 255, 255), True),
        (f"PW:   {password}",  (200, 200, 200), False),
        ("",                    (0,   0,   0),  False),
        (f"URL: {portal_url}", (100, 200, 255), True),
    ]:
        if not text:
            info_y += 12
            continue
        f = pygame.font.Font(BASE_FONT, 26)
        if bold:
            f.set_bold(True)
        s = f.render(text, True, color)
        screen.blit(s, ((w - s.get_width()) // 2, info_y))
        info_y += s.get_height() + 4

    pygame.display.flip()


# ==========================================================
# ドングル未接続案内画面
# ==========================================================
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

    total_h = 0
    for text, size, _, _ in lines:
        if text:
            total_h += pygame.font.Font(BASE_FONT, size).get_height() + 8
        else:
            total_h += size

    y = (h - total_h) // 2
    for text, size, color, bold in lines:
        if not text:
            y += size
            continue
        f = pygame.font.Font(BASE_FONT, size)
        if bold:
            f.set_bold(True)
        s = f.render(text, True, color)
        screen.blit(s, ((w - s.get_width()) // 2, y))
        y += s.get_height() + 8

    pygame.display.flip()


# ==========================================================
# KEN画像ロード（display確立後に実行すること）
# ==========================================================
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
    parser.add_argument("--airport", choices=["narita", "haneda", "centrair", "kanku"], default=_default_airport)
    parser.add_argument("--jma", action="store_true", default=True)
    parser.add_argument("--interval-hours", type=float, default=_default_interval)
    parser.add_argument("--no-hdmi-refresh", action="store_true")
    parser.add_argument("--test-case", type=int, choices=[3, 4], default=None,
                        help="テスト用: 3=QR設定画面, 4=ドングル未接続画面 を強制表示（ESCで終了）")
    args, unknown = parser.parse_known_args()

    airport = args.airport
    cfg = AIRPORT_CONFIG.get(airport)
    if not cfg:
        raise ValueError("未対応 airport")

    AIRPORT_LABELS = {"narita": "成田空港", "haneda": "羽田空港", "centrair": "中部国際空港", "kanku": "関西国際空港"}
    airport_label = AIRPORT_LABELS.get(airport, airport)
    logging.info(f"起動: airport={airport} interval={args.interval_hours}h")

    # -------------------------
    # pygame 初期化
    # -------------------------
    os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
    os.environ["SDL_VIDEO_CENTERED"] = "0"
    os.environ["SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS"] = "0"

    pygame.init()
    pygame.font.init()
    pygame.mouse.set_visible(False)

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Weather Signage")

    width, height = screen.get_size()

    # -------------------------
    # テストモード（--test-case 3 or 4）
    # -------------------------
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

    # -------------------------
    # WiFi接続チェック（4ケース分岐）
    # ケース1,2: WiFi OK → そのまま天気表示へ
    # ケース3: WiFi NG + APモードあり(ドングルあり) → QR設定画面
    # ケース4: WiFi NG + APモードなし(ドングルなし) → ドングル未接続案内画面
    # -------------------------
    if not is_wifi_connected() or is_ap_mode_active():
        while True:
            if is_wifi_connected() and not is_ap_mode_active():
                break
            if is_ap_mode_active():
                show_ap_screen(screen)
            else:
                show_no_dongle_screen(screen)
            pygame.time.wait(5000)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return

    # --- CPU表示（10秒更新）---
    cpu_text = "--"
    last_cpu_update = 0
    psutil.cpu_percent(interval=None)

    icon_cache = {}

    git_version_str = get_git_version_str()
    if git_version_str:
        git_font = pygame.font.Font(BASE_FONT, 16)
        git_surf = git_font.render(git_version_str, True, (150, 150, 150))
    else:
        git_surf = None

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
        ken_img = None
        ken_key_last = None

    HEADERS = {"User-Agent": "Mozilla/5.0"}

    AIRPORT_WARNING = {
        "narita":   {"pref": "120000", "city": "1221100"},
        "haneda":   {"pref": "130000", "city": "1311100"},
        "centrair": {"pref": "230000", "city": "2321600"},
        "kanku":    {"pref": "270000", "city": "2722000"},
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
        "43": "雷注意報",
        "44": "暴風警報",
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

    fetch_ok = True
    try:
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

        last_weather_update = datetime.datetime.now(JST)
        weather_updated_text = last_weather_update.strftime("天気更新 %H:%M")
        logging.info("初回天気取得成功")

    except Exception as e:
        logging.error(f"Initial fetch failed: {e}")
        hourly, daily = load_cached_weather()
        last_weather_update = datetime.datetime.now(JST)
        weather_updated_text = last_weather_update.strftime("天気更新 %H:%M")
        fetch_ok = False

    last_time_update_minute = -1
    xdotool = shutil.which("xdotool")

    needs_redraw = False
    last_drawn_minute = -1
    _sunrise_date = None
    sunrise_str, sunset_str = "", ""
    work_summary = build_work_summary(hourly)

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
                        pygame.quit()
                        return
                show_ap_screen(screen)
            needs_redraw = True
            continue

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
                print("KEN switched:", ken_key, flush=True)
            except Exception as e:
                print("KEN switch error:", ken_key, repr(e), flush=True)
                ken_img = None
                ken_key_last = None

        if now.hour == 23 and now.minute == 50:
            today_str = now.strftime("%Y-%m-%d")
            if getattr(main, "_updated_2350_date", "") != today_str:
                try:
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

                    logging.info("23:50定時更新実施")
                    weather_updated_text = now.strftime("天気更新 %H:%M")
                    work_summary = build_work_summary(hourly)
                    main._updated_2350_date = today_str
                    needs_redraw = True
                except Exception as e:
                    logging.error(f"23:50更新失敗: {e}")

        if time.time() - last_jma_update > 3600:
            try:
                new_warn, new_head = fetch_warning_data(airport)
                warning_text = new_warn
                last_jma_update = time.time()
                needs_redraw = True
            except Exception as e:
                logging.error(f"JMA更新失敗: {e}")

        if (now - last_weather_update).total_seconds() >= args.interval_hours * 3600:
            if 5 < now.hour <= 23:
                try:
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
                        warning_text, headline_text = fetch_warning_data(airport)

                    last_weather_update = now
                    weather_updated_text = now.strftime("天気更新 %H:%M")
                    work_summary = build_work_summary(hourly)
                    fetch_ok = True
                    needs_redraw = True

                except Exception as e:
                    logging.error(f"Periodic fetch failed: {e}")
                    fetch_ok = False
                    needs_redraw = True
            else:
                pygame.time.wait(60000)

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
                    pygame.quit()
                    return
            pygame.time.wait(10000)
            continue

        draw_weather(
            screen, width, height,
            hourly, daily, icon_cache, BASE_FONT,
            warning_text, headline_text, updated_text,
            weather_updated_text, airport_label,
            sunrise_str, sunset_str, work_summary, cpu_text,
            fetch_ok=fetch_ok, qr_surf=qr_surf
        )

        draw_header(
            screen, width, height, BASE_FONT,
            airport_label, sunrise_str, sunset_str, "", ""
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
                pygame.quit()
                return

        pygame.time.wait(10000)


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
        time.sleep(backoff)


if __name__ == "__main__":
    run_forever()
