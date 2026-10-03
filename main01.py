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
import signal
# SDL が SIGTERM/SIGINT を横取りして「QUIT イベント」に変えると、run_forever が main() を
# やり直してしまい systemd の停止（再起動・シャットダウン時）が 90 秒のタイムアウトまで待たされる。
# pygame を import する前に SDL のシグナル処理を無効にし、Python 側で即終了させる。
os.environ["SDL_NO_SIGNAL_HANDLERS"] = "1"
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

import json
import fb_display
from fb_display import init_display, present
from header import draw_header
from weather_draw import draw_weather
from fetch_wbgt import fetch_wbgt, WBGT_LEVELS
from screens import show_ap_screen, show_hotspot_announce, draw_conn_label, show_no_dongle_screen
from netstate import (
    get_connection_kind,
    is_network_connected,
    wired_cable_status,
    stop_ap_mode,
    is_ap_mode_active,
    has_wlan1,
    trigger_ap_mode,
    get_setup_hotspot_ssid,
)
from utils import get_sunrise_sunset_str, build_work_summary, JST, get_local_ip, make_qr_surface, get_target_datetimes
from utils import wait_ms as _wait_ms
from jma_alerts import get_overview_and_warning, active_warning_names

from config import AIRPORT_CONFIG, LOG_FILE, ICON_DIR, BASE_FONT

from fetch_weather import (
    fetch_weather_openmeteo,
    fetch_weather_jma,
    load_cached_weather
)


FETCH_TIMEOUT = 30

# 起動高速化：前回の表示データ（スナップショット）と、初回取得の後回し秒数
SNAPSHOT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "snapshot.json")
DEFER_INITIAL_FETCH_S = 20


def boot_log(msg: str) -> None:
    """起動からの経過秒数つきで journal とログに記録（起動直後の時刻ずれの影響を受けない）"""
    try:
        up = float(open("/proc/uptime").read().split()[0])
    except Exception:
        up = -1.0
    print(f"[boot] {up:.1f}s {msg}", flush=True)
    logging.info(f"[boot] 起動後 {up:.1f}s {msg}")


def wait_time_sync(timeout_s: float = 15) -> bool:
    """NTP で時刻同期済みになるまで最大 timeout_s 秒待つ（Pi は電池時計が無く起動直後は時刻がずれる）"""
    end = time.time() + timeout_s
    while True:
        try:
            r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                               capture_output=True, text=True, timeout=3)
            if r.stdout.strip() == "yes":
                return True
        except Exception:
            return False
        if time.time() >= end:
            return False
        time.sleep(1)


def _json_default(o):
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def save_snapshot(state: dict) -> None:
    """表示に必要なデータ一式を保存（取得・更新が成功したときだけ呼ぶ。SD 書込みを減らすため）"""
    try:
        os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
        tmp = SNAPSHOT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, default=_json_default, ensure_ascii=False)
        os.replace(tmp, SNAPSHOT_FILE)
    except Exception as e:
        logging.warning(f"スナップショット保存失敗: {e}")


def load_snapshot():
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            snap = json.load(f)
        for item in snap.get("hourly", []):
            if isinstance(item.get("datetime"), str):
                dt = datetime.datetime.fromisoformat(item["datetime"])
                item["datetime"] = dt.replace(tzinfo=JST) if dt.tzinfo is None else dt
        return snap
    except Exception:
        return None

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
# gitバージョン情報取得（起動敢1回）
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
    log_path = LOG_FILE
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


# ==========================================================
# WiFi / AP 関連
# ==========================================================
def _ms_until_next_check(max_ms: int = 10000) -> int:
    """最大 max_ms 待つが、分替わりをまたぐ場合は次の :00 直後に起きる（時計表示の遅れ防止）"""
    now = datetime.datetime.now(JST)
    to_next_min = (60 - now.second) * 1000 - now.microsecond // 1000 + 50
    return max(50, min(max_ms, to_next_min))


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
    boot_log("main01 開始")
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
    parser.add_argument("--render",
                        choices=["auto", "kmsdrm", "fb0", "x11"], default="auto",
                        help="描画モード（既定: auto = kmsdrm を試し失敗時に fb0 へフォールバック）")
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

    # 描画モードを自動判定（auto: kmsdrm を検証 → 失敗時 offscreen+fb0）
    screen = init_display(args.render)
    boot_log(f"描画初期化完了 mode={fb_display.RENDER_MODE}")

    if not pygame.display.get_init():
        driver = os.environ.get("SDL_VIDEODRIVER", "(unset)")
        raise RuntimeError(
            f"pygame display init failed (SDL_VIDEODRIVER={driver}). "
            "DRM デバイスが使用中か、ドライバが見つかりません。"
        )

    pygame.display.set_caption("Weather Signage")
    width, height = screen.get_size()

    if args.test_case is not None:
        if args.test_case == 3:
            show_ap_screen(screen)
        else:
            show_no_dongle_screen(screen, get_setup_hotspot_ssid())
        while True:
            _wait_ms(200)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    pygame.quit(); return

    if not is_network_connected() or is_ap_mode_active():
        hotspot_ssid = get_setup_hotspot_ssid()
        last_screen = None
        connected_streak = 0
        wait_start = time.time()
        last_state = None
        while True:
            connected = is_network_connected()
            ap = is_ap_mode_active()
            # 待機中の状態が変わったときだけ記録（画面を見ていなくても後でログで確認できるように）
            state = (f"接続={'あり' if connected else 'なし'} LANケーブル={'あり' if wired_cable_status() else 'なし'} "
                     f"設定モード={'中' if ap else '-'} ドングル={'あり' if has_wlan1() else 'なし'}")
            if state != last_state:
                boot_log(f"ネットワーク待機 {state}")
                last_state = state
            if connected and not ap:
                boot_log(f"ネットワーク待機終了（{time.time() - wait_start:.0f}秒待機）")
                break
            if is_ap_mode_active():
                # 設定モード中でも有線/WiFi で IP が取れたら（2回連続＝約10秒）自動で設定モードを終える
                connected_streak = connected_streak + 1 if connected else 0
                if connected_streak == 2:
                    boot_log("設定モード中に接続を検出 → 設定モードを終了")
                    stop_ap_mode()
                show_ap_screen(screen)
                last_screen = "ap"
            elif has_wlan1():
                trigger_ap_mode()
                show_ap_screen(screen)
                last_screen = "ap"
            else:
                # 画面が変わるときだけ描き直す（fb0 では全面描画が重いため）
                cur = ("nodongle", wired_cable_status())
                if cur != last_screen:
                    show_no_dongle_screen(screen, hotspot_ssid, cur[1])
                    last_screen = cur
            _wait_ms(5000)
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

    # 設定用テザリングで仮接続している場合は、手順を 30 秒案内してから天気画面へ
    conn_kind = get_connection_kind()
    boot_log(f"接続 {conn_kind or '未接続'}")
    on_hotspot = conn_kind == "hotspot"
    if on_hotspot:
        logging.info("設定用テザリングで仮接続中")
        if not show_hotspot_announce(screen, _local_ip, get_setup_hotspot_ssid()):
            pygame.quit(); return

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
        "kanku":    {"pref": "270000", "city": "2721300"},
        "chitose":  {"pref": "016000", "city": "0122400"},
        "fukuoka":  {"pref": "400000", "city": "4013000"},
        "naha":     {"pref": "471000", "city": "4720100"},
    }
    def fetch_warning_data(airport_key: str):
        info = AIRPORT_WARNING[airport_key]
        url = f"https://www.jma.go.jp/bosai/warning/data/warning/{info['pref']}.json"
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logging.warning(f"警報取得失敗: {e}")
            return "警報取得失敗", ""
        headline = data.get("headlineText", "")
        warning_list = active_warning_names(data, (info["city"],))
        if not warning_list:
            return "警報・注意報なし", headline
        return " / ".join(warning_list), headline

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    jma_cache_path = os.path.join(BASE_DIR, f"jma_{airport}.json")

    # ── 起動高速化：前回スナップショットの利用判定 ─────────────
    # 時刻同期は最大3秒だけ確認（再起動直後は同期に十数秒かかることがあり、待つと起動が遅くなる）
    synced = wait_time_sync(3)
    now_ts = time.time()
    snap = load_snapshot()
    if snap and snap.get("airport") != airport:
        snap = None
    table_start = get_target_datetimes()[0].strftime("%Y-%m-%dT%H")
    if synced:
        # 時刻が正しい：同じ空港・interval 以内・同じ日の表なら前回データで表示し、取得も省略
        weather_fresh = bool(
            snap and snap.get("hourly")
            and now_ts - snap.get("weather_at", 0) < args.interval_hours * 3600
            and snap.get("table_start") == table_start
        )
        kick_fetch = False
    else:
        # 時刻が未確定：新しさは判断できないが、前回データがあればまず表示し、すぐ裏で取り直す
        weather_fresh = bool(snap and snap.get("hourly"))
        kick_fetch = weather_fresh
    jma_fresh = bool(synced and snap and now_ts - snap.get("jma_at", 0) < 3600)
    wbgt_fresh = bool(synced and snap and now_ts - snap.get("wbgt_at", 0) < 3600)
    boot_log(f"時刻同期{'済' if synced else '未'} スナップショット 天気={'利用' if weather_fresh else '不可'}"
             f"{'（裏で即取得）' if kick_fetch else ''} 警報={'利用' if jma_fresh else '後で取得'} "
             f"WBGT={'利用' if wbgt_fresh else '後で取得'}")

    # 警報・天気概況：新しければ前回値。古い/無ければ前回値（あれば）を仮表示し、起動 20 秒後に取得
    snap_or = lambda k, d: (snap.get(k, d) if snap else d)
    warning_text  = snap_or("warning_text", "取得中…")
    headline_text = snap_or("headline_text", "")
    updated_text  = snap_or("updated_text", "")
    overview_text = snap_or("overview_text", "")
    jma_at = snap_or("jma_at", 0.0)
    last_jma_update = jma_at if jma_fresh else now_ts - 3600 + DEFER_INITIAL_FETCH_S

    fetcher = WeatherFetcher(cfg, args)
    if weather_fresh:
        # 前回データで即表示（スプラッシュ省略）。次回の定期取得は前回取得から interval 後
        hourly, daily = snap["hourly"], snap["daily"]
        weather_at = snap["weather_at"]
        last_weather_update = datetime.datetime.fromtimestamp(weather_at, JST)
        weather_updated_text = snap_or("weather_updated_text", last_weather_update.strftime("天気更新 %H:%M"))
        fetch_ok = True
        logging.info("前回スナップショットで即表示")
    else:
        # ── スプラッシュ表示 + 初回天気取得 ──────────────────
        boot_log("スプラッシュ開始（天気取得）")
        splash_hourly, splash_daily, fetch_ok = run_splash(
            screen, width, height, BASE_FONT,
            airport_label, git_version_str, fetcher
        )
        weather_at = time.time()
        last_weather_update = datetime.datetime.now(JST)
        weather_updated_text = last_weather_update.strftime("天気更新 %H:%M")
        if splash_hourly is not None:
            hourly, daily = splash_hourly, splash_daily
            logging.info("初回天気取得成功")
        else:
            hourly, daily = (snap["hourly"], snap["daily"]) if snap and snap.get("hourly") else load_cached_weather()
            fetch_ok = False
            logging.warning("スプラッシュ中断またはフェッチ失敗: キャッシュ使用")
        boot_log(f"スプラッシュ終了（取得{'成功' if fetch_ok else '失敗'}）")

    last_time_update_minute = -1
    xdotool = shutil.which("xdotool")
    needs_redraw = False
    last_drawn_minute = -1
    last_wifi_check = time.time()
    _sunrise_date = None
    sunrise_str, sunset_str = "", ""

    # WBGT 初期化（新しければ前回値。無ければ起動 20 秒後に取得）
    wbgt_alert = args.wbgt_alert or bool(snap_or("wbgt_alert", False) and wbgt_fresh)
    wbgt_level_info = snap_or("wbgt_level_info", None) if wbgt_fresh else None
    wbgt_at = snap_or("wbgt_at", 0.0)
    if args.wbgt_test is not None:
        v = args.wbgt_test
        for threshold, label, bg, fg in WBGT_LEVELS:
            if v >= threshold:
                wbgt_level_info = {"label": label, "bg": bg, "fg": fg, "value": v}
                break
        wbgt_alert = wbgt_alert or (v >= 33)
        logging.info(f"WBGT テストモード: value={v} level={wbgt_level_info and wbgt_level_info['label']}")
    if args.wbgt_test is not None:
        last_wbgt_update = time.time()
    else:
        last_wbgt_update = wbgt_at if wbgt_fresh else time.time() - 3600 + DEFER_INITIAL_FETCH_S

    def _save_state():
        save_snapshot({
            "airport": airport, "saved_at": time.time(),
            "weather_at": weather_at, "jma_at": jma_at, "wbgt_at": wbgt_at,
            "table_start": (hourly[0]["datetime"].strftime("%Y-%m-%dT%H")
                            if hourly and isinstance(hourly[0].get("datetime"), datetime.datetime) else ""),
            "hourly": hourly, "daily": daily, "weather_updated_text": weather_updated_text,
            "warning_text": warning_text, "headline_text": headline_text,
            "updated_text": updated_text, "overview_text": overview_text,
            "wbgt_alert": wbgt_alert, "wbgt_level_info": wbgt_level_info,
        })

    if fetch_ok and not weather_fresh:
        _save_state()
    _first_draw_logged = False
    _fetch_pending = False
    if kick_fetch:
        fetcher.start()
        _fetch_pending = True
        logging.info("時刻未同期のため前回データを表示しつつ天気を即取得")

    work_summary = build_work_summary(hourly)

    # ==========================================================
    # メインループ
    # ==========================================================
    while True:
        now = datetime.datetime.now(JST)
        needs_redraw = False

        if is_ap_mode_active():
            logging.warning("APモード検出: 設定画面を表示")
            show_ap_screen(screen)
            connected_streak = 0
            while is_ap_mode_active():
                _wait_ms(5000)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit(); return
                # 設定モード中でも有線/WiFi で IP が取れたら（2回連続）自動で設定モードを終える
                connected_streak = connected_streak + 1 if is_network_connected() else 0
                if connected_streak == 2:
                    logging.info("設定モード中に接続を検出 → 設定モードを終了")
                    stop_ap_mode()
                show_ap_screen(screen)
            logging.info("APモード終了: 通常画面に復帰")
            needs_redraw = True
            continue

        if time.time() - last_wifi_check >= 30:
            last_wifi_check = time.time()
            _kind = get_connection_kind()
            if not _kind and has_wlan1() and not is_ap_mode_active():
                logging.warning("ネットワーク切断検出 → AP モード自動起動")
                trigger_ap_mode()
            if _kind != conn_kind:
                boot_log(f"接続の種類が変化: {conn_kind or '未接続'} → {_kind or '未接続'}"
                         f"{'（有線ケーブルあり・IP なし）' if not _kind and wired_cable_status() else ''}")
                conn_kind = _kind
                needs_redraw = True
            _hs = _kind == "hotspot"
            if _hs != on_hotspot:
                logging.info("設定用テザリングで仮接続" if _hs else "設定用テザリングから通常の WiFi に切替")
                if _hs and not show_hotspot_announce(screen, get_local_ip(), get_setup_hotspot_ssid()):
                    pygame.quit(); return
                on_hotspot = _hs
                needs_redraw = True

        if time.time() - last_cpu_update >= 10:
            cpu = psutil.cpu_percent(interval=None)
            cpu_text = f"{cpu:.0f}%"
            last_cpu_update = time.time()
            # CPU 表示のためだけに再描画しない（全面再描画は Pi Zero W で重い）。次の分替わりで反映

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

        # 6:00 定時取得：時間別の表は 6 時で「今日の 6 時〜」に切り替わるが、夜間は取得を
        # 先送りするため次の定期取得が 7:50 頃になる。それまで前日の列が残らないよう取り直す。
        # 6:00〜6:09 の間に 1 日 1 回（起動直後などで 6 時以降のデータが既にあれば不要）。
        if now.hour == 6 and now.minute < 10:
            today_str = now.strftime("%Y-%m-%d")
            fetched_after_6 = last_weather_update.date() == now.date() and last_weather_update.hour >= 6
            if (getattr(main, "_updated_0600_date", "") != today_str
                    and not _fetch_pending and not fetched_after_6):
                fetcher.start()
                _fetch_pending = True
                main._updated_0600_date = today_str
                logging.info("6:00定時取得開始")

        # WBGT 更新（1時間ごと、テスト時はスキップ）
        if args.wbgt_test is None and time.time() - last_wbgt_update > 3600:
            try:
                _, wbgt_alert, wbgt_level_info = fetch_wbgt(airport)
                if args.wbgt_alert:
                    wbgt_alert = True
                last_wbgt_update = wbgt_at = time.time()
                needs_redraw = True
                _save_state()
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
                overview_text = jma_data.get("overview", "")
                last_jma_update = jma_at = time.time()
                needs_redraw = True
                _save_state()
                logging.info(f"JMA更新完了: {warning_text}")
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
                    weather_at = time.time()
                    _save_state()
                    logging.info("天気取得完了")
                else:
                    last_weather_update = now - datetime.timedelta(hours=args.interval_hours) \
                                              + datetime.timedelta(minutes=30)
                    fetch_ok = False
                    logging.error("天気取得失敗またはタイムアウト。30分後に再試行")
                needs_redraw = True

        if now.date() != _sunrise_date:
            sunrise_str, sunset_str = get_sunrise_sunset_str(cfg["latitude"], cfg["longitude"])
            _sunrise_date = now.date()
            needs_redraw = True

        # WiFi が切り替わって IP が変わったら QR（設定画面 URL）を作り直す
        _cur_ip = get_local_ip()
        if _cur_ip and _cur_ip != _local_ip:
            qr_surf = make_qr_surface(f"http://{_cur_ip}:8080", max_size=54)
            logging.info(f"IP 変更 {_local_ip or '-'} → {_cur_ip}: QR を更新")
            _local_ip = _cur_ip
            needs_redraw = True

        if not needs_redraw:
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    pygame.quit(); return
            _wait_ms(_ms_until_next_check())
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
            latitude=cfg["latitude"], longitude=cfg["longitude"],
            overview_text=overview_text,
        )

        draw_header(
            screen, width, height, BASE_FONT,
            airport_label, sunrise_str, sunset_str, "", "",
            wbgt_level_info=wbgt_level_info,
        )

        draw_conn_label(screen, height, conn_kind)

        if ken_img is not None:
            margin = 30
            screen.blit(ken_img,
                (width - ken_img.get_width() - margin,
                 height - ken_img.get_height() - margin))

        if git_surf is not None:
            screen.blit(git_surf,
                (width - git_surf.get_width() - 8,
                 height - git_surf.get_height() - 4))

        present(screen)
        last_drawn_minute = now.minute
        if not _first_draw_logged:
            boot_log("天気画面を表示")
            _first_draw_logged = True

        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit(); return

        _wait_ms(_ms_until_next_check())


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


def _on_sigterm(signum, frame):
    print(f"signal {signum} 受信: 終了します", flush=True)
    raise SystemExit(0)   # run_forever は Exception しか捕まえないので、そのまま終了する


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _on_sigterm)
    run_forever()
