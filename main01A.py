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

from header import draw_header
from weather_draw import draw_weather
from utils import get_sunrise_sunset_str, build_work_summary, JST
from jma_alerts import get_overview_and_warning

from config import AIRPORT_CONFIG, LOG_FILE, ICON_DIR

from fetch_weather import (
    fetch_weather_openmeteo,
    fetch_weather_jma,
    load_cached_weather
)

BASE_FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"

# ==========================================================
# 天気コード　　を取り出す関数
# ==========================================================
def _pick_weather_code(item: dict):
    """hourly/daily の dict から '天気コード' らしき値を拾う（キー名揺れ対応）"""
    for k in ("code", "weather_code", "wx_code", "jma_code", "weathercode"):
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None

def print_weather_codes(hourly: list, daily: list, label: str = ""):
    """時間天気（セルごと）と週間（日ごと）の天気コードをターミナルへ表示"""
    ts = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 60)
    print(f"[{ts}] WEATHER CODES {label}".strip())
    print("-" * 60)

    # 時間天気（セルごと）
    print("[HOURLY] time -> code")
    if not hourly:
        print("  (no hourly data)")
    else:
        for i, h in enumerate(hourly):
            t = h.get("time") or h.get("dt") or h.get("datetime") or f"idx={i}"
            c = _pick_weather_code(h)
            print(f"  {t} -> {c}")

    # 週間（日ごと）
    print("[DAILY] date -> code")
    if not daily:
        print("  (no daily data)")
    else:
        for i, d in enumerate(daily):
            day = d.get("date") or d.get("day") or f"idx={i}"
            c = _pick_weather_code(d)
            print(f"  {day} -> {c}")

    print("=" * 60 + "\n")

# ==========================================================
# ログローテーション（E61cと同等）
# ==========================================================
def setup_logging():
    log_path = "/home/pi/project02/displayraspi_log.txt"  # ←書ける場所に固定
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

    # 多重登録防止
    if root_logger.handlers:
        root_logger.handlers.clear()
    root_logger.addHandler(handler)

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

    parser = argparse.ArgumentParser()
    parser.add_argument("--airport", choices=["narita", "haneda", "centrair"], default="centrair")
    parser.add_argument("--jma", action="store_true")
    parser.add_argument("--interval-hours", type=float, default=2.0)
    parser.add_argument("--no-hdmi-refresh", action="store_true")
    args, unknown = parser.parse_known_args()

    print("JMA FLAG:", args.jma, flush=True)

    airport = args.airport
    cfg = AIRPORT_CONFIG.get(airport)
    if not cfg:
        raise ValueError("未対応 airport")

    AIRPORT_LABELS = {"narita": "成田空港", "haneda": "羽田空港", "centrair": "中部国際空港"}
    airport_label = AIRPORT_LABELS.get(airport, airport)

    print("AIRPORT KEY:", airport, flush=True)
    print("AIRPORT LABEL:", airport_label, flush=True)

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
    #screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.NOFRAME)
    pygame.display.set_caption("Weather Signage")
    
    width, height = screen.get_size()

    # --- CPU表示（10秒更新） ---
    cpu_text = "--"          # 表示用（例: "23%"）
    last_cpu_update = 0
    # psutilは最初の1回だけ“初期化”しておくと値が安定
    psutil.cpu_percent(interval=None)

    # --- CPU率を10秒ごとに更新 ---
    if time.time() - last_cpu_update >= 10:
        cpu = psutil.cpu_percent(interval=None)   # ブロックしない
        cpu_text = f"{cpu:.0f}%"
        last_cpu_update = time.time()

    icon_cache = {}

    # -------------------------
    # KEN画像（display確立後にロード）
    # -------------------------
    KEN1_PATH = os.path.join(ICON_DIR, "ken1.png")
    KEN6_PATH = os.path.join(ICON_DIR, "ken6.png")

    # ★ 追加（ここ）
    print("CONFIG FILE =", __file__, flush=True)
    print("ICON_DIR =", ICON_DIR, flush=True)
    print("KEN1_PATH =", KEN1_PATH, flush=True)
    print("KEN6_PATH =", KEN6_PATH, flush=True)

    ken_img = None
    ken_key_last = None

    # 起動時は ken1 をロード
    ken_key_last = "ken1"
    try:
        ken_img = load_ken_image(KEN1_PATH, scale_h=100)
    except Exception as e:
        print("KEN load error:", KEN1_PATH, repr(e), flush=True)
        ken_img = None
        ken_key_last = None

    # =========================
    # 警報取得（市町村コード版）
    # =========================
    HEADERS = {"User-Agent": "Mozilla/5.0"}

    AIRPORT_WARNING = {
        "narita":  {"pref": "120000", "city": "1221100"},
        "haneda":  {"pref": "130000", "city": "1311100"},
        "centrair": {"pref": "230000", "city": "2321600"},
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

    # -------------------------
    # JMA初回取得（overview/warning）
    # -------------------------
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    jma_cache_path = os.path.join(BASE_DIR, f"jma_{airport}.json")

    jma_data = get_overview_and_warning(
        office_code=cfg["office_code"],
        area_codes=cfg["area_codes"],
        cache_json_path=jma_cache_path
    )

    # ---- get_overview_and_warning の直後に追加 ----
    try:
        warning_text, headline_text = fetch_warning_data(airport)
        last_jma_update = time.time()
    except Exception as e:
        logging.error(f"初回警報取得失敗: {e}")

    # 概況と発表時刻は overview から
    headline_text = jma_data.get("headline", "")
    updated_text  = jma_data.get("updated", "")

    # 警報・注意報は warning JSON（fetch_warning_data）を唯一のソースにする
    warning_text, _headline_from_warning = fetch_warning_data(airport)
    # ※ headline は overview の方を使うなら上書きしない

    last_jma_update = time.time()
    weather_updated_text = ""

    # -------------------------
    # 初回天気取得
    # -------------------------
    try:
        if args.jma:
            hourly, om_daily = fetch_weather_openmeteo()
            print("DEBUG HOURLY LEN:", len(hourly), flush=True)

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
            hourly, daily = fetch_weather_openmeteo()
            print("DEBUG HOURLY LEN (UPDATE):", len(hourly), flush=True)

        last_weather_update = datetime.datetime.now(JST)
        weather_updated_text = last_weather_update.strftime("天気更新 %H:%M")

        #天気コード
        print_weather_codes(hourly, daily, label="(initial)")

    except Exception as e:
        print("=== FETCH FAILED ===", flush=True)
        print("ERROR:", e, flush=True)

        logging.error(f"Initial fetch failed: {e}")
        hourly, daily = load_cached_weather()
        last_weather_update = datetime.datetime.now(JST)
        weather_updated_text = last_weather_update.strftime("天気更新 %H:%M")

    last_time_update_minute = -1
    xdotool = shutil.which("xdotool")

    # ==========================================================
    # メインループ
    # ==========================================================
    while True:
        now = datetime.datetime.now(JST)

        # -------------------------
        # 1分ごとヘッダー更新（画面焼き付き防止）
        # -------------------------
        if now.minute != last_time_update_minute:
            last_time_update_minute = now.minute
            if xdotool:
                os.system("xdotool key Shift_L")

        # -------------------------
        # KEN画像（12時だけ ken6 に切替）
        # -------------------------
        ken_key = "ken6" if now.hour == 12 else "ken1"
        if ken_key != ken_key_last:
            try:
                path = KEN6_PATH if ken_key == "ken6" else KEN1_PATH
                ken_img = load_ken_image(path, scale_h=100)
                ken_key_last = ken_key
                print("KEN switched:", ken_key, flush=True)
            except Exception as e:
                print("KEN switch error:", ken_key, repr(e), flush=True)
                ken_img = None
                ken_key_last = None

        # -------------------------
        # 23:50 定時更新
        # -------------------------
        if now.hour == 23 and now.minute == 50:
            today_str = now.strftime("%Y-%m-%d")
            if getattr(main, "_updated_2350_date", "") != today_str:
                try:
                    if args.jma:
                        hourly, om_daily = fetch_weather_openmeteo()
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
                        hourly, daily = fetch_weather_openmeteo()

                    logging.info("23:50定時更新実施")
                    weather_updated_text = now.strftime("天気更新 %H:%M")
                    main._updated_2350_date = today_str
                except Exception as e:
                    logging.error(f"23:50更新失敗: {e}")

        # -------------------------
        # JMAアラート1時間更新
        # -------------------------
        if time.time() - last_jma_update > 3600:
            try:
                new_warn, new_head = fetch_warning_data(airport)
                warning_text = new_warn
                # headline_text は overview優先なら更新しない / warning優先なら new_head を入れる
                last_jma_update = time.time()
            except Exception as e:
                logging.error(f"JMA更新失敗: {e}")
                # warning_text は変更しない
        # -------------------------
        # 定期更新（interval-hours）
        # -------------------------
        if (now - last_weather_update).total_seconds() >= args.interval_hours * 3600:
            if 4 < now.hour <= 23:
                try:
                    if args.jma:
                        hourly, om_daily = fetch_weather_openmeteo()
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
                        hourly, daily = fetch_weather_openmeteo()

                        # 任意：警報も合わせて更新したい場合
                        warning_text, headline_text = fetch_warning_data(airport)

                    last_weather_update = now
                    weather_updated_text = now.strftime("天気更新 %H:%M")

                except Exception as e:
                    logging.error(f"Periodic fetch failed: {e}")
            else:
                pygame.time.wait(60000)

        # -------------------------
        # 表示用計算
        # -------------------------
        sunrise_str, sunset_str = get_sunrise_sunset_str(cfg["latitude"], cfg["longitude"])
        work_summary = build_work_summary(hourly)

        #print("DEBUG warning_text passed to draw_weather:", warning_text, flush=True)
        #print("PASS warning_text:", warning_text, flush=True)
        # -------------------------
        # 描画（flipはここで1回だけ）
        # -------------------------
        draw_weather(
            screen,
            width,
            height,
            hourly,
            daily,
            icon_cache,
            BASE_FONT,
            warning_text,
            headline_text,
            updated_text,
            weather_updated_text,
            airport_label,
            sunrise_str,
            sunset_str,
            work_summary,
            cpu_text
        )

        draw_header(
            screen, width, height, BASE_FONT,
            airport_label,
            sunrise_str, sunset_str,
            "",   # weather_updated_text（ヘッダーには出さない）
            ""    # cpu_text（ヘッダーには出さない）
        )

        # KEN（右下）
        if ken_img is not None:
            margin = 30
            screen.blit(
                ken_img,
                (width - ken_img.get_width() - margin,
                 height - ken_img.get_height() - margin)
            )

        pygame.display.flip()

        # -------------------------
        # ESC終了
        # -------------------------
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                return

        pygame.time.wait(2000)


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