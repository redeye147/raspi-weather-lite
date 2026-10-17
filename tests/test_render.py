"""画面の描画テスト（weather_draw.draw_weather・header.draw_header）

3 つの解像度で、普段の画面と「いちばん詰まる」画面（熱中症アラート・危険バッジ・長い警報と概況・
通信エラー・航空気象の帯）を描き、例外が出ないことと、下端・右端からはみ出さないことを確かめる。
"""
import datetime
import os

import numpy as np
import pygame
import pytest

import aviation
from config import BASE_FONT
from fetch_wbgt import level_for
from header import draw_header
from utils import JST, make_qr_surface
from weather_draw import draw_weather

pytestmark = pytest.mark.skipif(not os.path.exists(BASE_FONT), reason=f"フォントが無い: {BASE_FONT}")

RESOLUTIONS = [(1920, 1080), (1366, 768), (1280, 720)]


@pytest.fixture(scope="module", autouse=True)
def display():
    pygame.display.init()
    pygame.font.init()
    yield


def _hourly():
    base = datetime.datetime(2026, 10, 11, 6, tzinfo=JST)
    codes = ["100", "101", "200", "300", "313", "400", "100", "101", "302", "200"]
    out = []
    for i in range(10):
        dt = base + datetime.timedelta(hours=3 * i)
        out.append(dict(datetime=dt, date=dt.strftime("%-m/%-d"), hour=dt.strftime("%H"), code=codes[i],
                        pop="12.5mm", temp_val=-12.3, temp="-12.3℃", wind_val=24.6, wind="24.6 m/s", wind_dir=45 * i))
    return out


def _daily():
    # 実データの形式は「最高/最低」（fetch_weather.py）。描くときに「35℃／-10℃」になる。いちばん長くなる値で
    return [dict(day=f"10/{11 + i}({'日月火水木金土'[i]})", code="313", pop="100%", temp="-10/-15", date="")
            for i in range(7)]


SCENARIOS = {
    "普段": dict(warning_text="警報・注意報なし", headline_text="", overview_text="　晴れ。",
                 wbgt=None, alert=False, fetch_ok=True, metar=None),
    "いちばん詰まる": dict(
        warning_text="大雨特別警報 / 暴風警報 / 波浪警報 / 高潮警報 / 洪水警報 / 雷注意報 / 濃霧注意報 / 乾燥注意報",
        headline_text="千葉県では、１２日夜遅くまで土砂災害や低い土地の浸水、河川の増水や氾濫に厳重に警戒してください。" * 2,
        overview_text="　台風第１９号が関東地方に接近しています。" * 6,
        wbgt=33.5, alert=True, fetch_ok=False,
        metar="RJAA 110300Z 18035G55KT 0800 +TSRA BR FEW005CB BKN010 OVC020 18/17 Q0985",
        thunder={"kind": "near", "km": 9.6, "dir": "北東", "at": datetime.datetime(2026, 10, 11, 12, 10, tzinfo=JST)}),
}


def _render(w, h, sc):
    screen = pygame.Surface((w, h))
    wbgt = level_for(sc["wbgt"])
    draw_weather(screen, w, h, _hourly(), _daily(), {}, BASE_FONT,
                 sc["warning_text"], sc["headline_text"], "2026-10-11 05:00", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3% / 53℃",
                 fetch_ok=sc["fetch_ok"], qr_surf=make_qr_surface("http://192.168.11.13:8080", max_size=54),
                 wbgt_level_info=wbgt, wbgt_alert=sc["alert"], latitude=35.76, longitude=140.38,
                 overview_text=sc["overview_text"], thunder=sc.get("thunder"))
    metar = aviation.parse_metar(sc["metar"], datetime.datetime(2026, 10, 11, 3, 10, tzinfo=datetime.timezone.utc)) \
        if sc["metar"] else None
    draw_header(screen, w, h, BASE_FONT, "成田空港", "05:44", "17:09", "", "",
                wbgt_level_info=wbgt, aviation_metar=metar, fetch_error=not sc["fetch_ok"])
    return screen


def _content_box(screen):
    """白以外の画素がある範囲 (最下行, 最右列)。横いっぱいの赤帯（通信エラー・熱中症アラート）は右端まで
    描くのが正しいので、右端は帯の行を除いて調べる"""
    arr = pygame.surfarray.array3d(screen)            # (幅, 高さ, 3)
    nonwhite = np.any(arr != 255, axis=2)
    rows = np.where(nonwhite.any(axis=0))[0]
    full_width = nonwhite.sum(axis=0) > screen.get_width() * 0.8
    cols = np.where(nonwhite[:, ~full_width].any(axis=1))[0]
    return int(rows.max()), int(cols.max())


@pytest.mark.parametrize("w, h", RESOLUTIONS)
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_screen_fits(w, h, name):
    screen = _render(w, h, SCENARIOS[name])
    bottom, right = _content_box(screen)
    assert bottom < h - 1, f"{w}×{h}「{name}」: 下端まで描いている（はみ出しの可能性）bottom={bottom}"
    assert right < w - 1, f"{w}×{h}「{name}」: 右端まで描いている right={right}"


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_alert_and_fetch_error_are_drawn(w, h):
    """熱中症アラートの赤帯と通信エラーの赤帯が実際に描かれている（白で上書きされていない）"""
    arr = pygame.surfarray.array3d(_render(w, h, SCENARIOS["いちばん詰まる"]))
    red = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 60) & (arr[:, :, 2] < 60)
    red_rows = np.where(red.sum(axis=0) > w * 0.8)[0]                # 横いっぱいの赤い行
    assert len(red_rows) > 0
    assert red_rows.min() < h * 0.05                                  # 最上部の通信エラーの帯
    assert red_rows.max() > h * 0.25                                  # ヘッダーの下の熱中症アラートの帯


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_warning_box_text_stays_inside_box(w, h):
    """警報の一覧が長くても、枠の下（＝画面の下）に文字がはみ出さない（1280×720 で見出しが画面外に出ていた）"""
    screen = _render(w, h, SCENARIOS["いちばん詰まる"])
    arr = pygame.surfarray.array3d(screen)
    gray_border = np.all(arr == (120, 120, 120), axis=2)                 # 警報の枠線の色
    box_rows = np.where(gray_border.sum(axis=0) > 100)[0]                 # 枠の上辺・下辺（横線）
    assert len(box_rows) >= 2
    box_bottom = box_rows.max()
    box_cols = np.where(gray_border.any(axis=1))[0]
    below = np.any(arr[box_cols.min():box_cols.max() + 1, box_bottom + 1:] != 255, axis=2)
    assert not below.any(), f"{w}×{h}: 警報の枠の下に文字がある"


@pytest.mark.parametrize("w, h", RESOLUTIONS)
@pytest.mark.parametrize("hi, lo", [(25, 17), (35, -10), (-10, -15)])
def test_weekly_temperature_fits_column(w, h, hi, lo):
    """週間の気温「-10℃／-15℃」が隣の列にはみ出さない（列に入るまで文字を小さくする）。普段の値は 22 のまま"""
    from utils import get_font
    from weather_draw import week_temp_font_size
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // (1 + 10))             # 時間別 10 列 + 見出し列（draw_weather と同じ）
    size = week_temp_font_size(BASE_FONT, hi, lo, True, col_w - 10)
    width = (get_font(BASE_FONT, size, bold=True).size(f"{hi}℃")[0] + get_font(BASE_FONT, size).size("／")[0]
             + get_font(BASE_FONT, size).size(f"{lo}℃")[0])
    assert width <= col_w - 10
    if (hi, lo) == (25, 17) and w == 1920:
        assert size == 22                                     # 1920×1080 の普段の値は今までどおり


# ---------------------------------------------------------------- 今の時間帯の強調
@pytest.mark.parametrize("hh, mm, day, col", [
    (6, 0, 11, 0), (10, 30, 11, 1), (11, 59, 11, 1), (12, 0, 11, 2), (23, 59, 11, 5),
    (0, 0, 12, 6), (8, 59, 12, 8), (9, 0, 12, 9), (11, 59, 12, 9),     # 最後の列（09）は 12 時まで
    (5, 59, 11, None), (12, 0, 12, None),                                # 表の範囲外
])
def test_current_slot_index(hh, mm, day, col):
    from weather_draw import current_slot_index
    assert current_slot_index(_hourly(), datetime.datetime(2026, 10, day, hh, mm, tzinfo=JST)) == col


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_current_slot_frame_is_drawn(w, h):
    """今の時間帯の列（10:30 → 09 の列）だけが、太い青い枠で囲まれる"""
    import weather_draw
    screen = pygame.Surface((w, h))
    sc = SCENARIOS["普段"]
    draw_weather(screen, w, h, _hourly(), _daily(), {}, BASE_FONT, sc["warning_text"], "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", latitude=35.76, longitude=140.38,
                 now=datetime.datetime(2026, 10, 11, 10, 30, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    blue = np.all(arr == weather_draw.NOW_FRAME_COLOR, axis=2)
    cols = np.where(blue.sum(axis=1) > h * 0.1)[0]          # 縦に長く続く青い線（枠の左右）
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    left = margin_x + 2 * col_w                               # 見出し列 + 06 の列 の右
    assert len(cols) >= 2 * weather_draw.NOW_FRAME_WIDTH
    assert cols.min() == left and cols.max() <= left + col_w


# ---------------------------------------------------------------- 日の出▲・日の入り▼が次の列の数字に食い込まない
@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_sun_marks_stay_inside_their_column(w, h, monkeypatch):
    """日の出 05:58・日の入り 17:58（境目の直前）でも、▲▼とラベルは自分の列（03・15）の中に収まり、
    次の列の「06」「18」に重ならない（2026-10-14 の 110 で ▲ が「06」に食い込んでいた）"""
    import weather_draw
    monkeypatch.setattr(weather_draw, "sun_times", lambda d, lat, lon: (
        datetime.datetime(d.year, d.month, d.day, 5, 58, tzinfo=JST),
        datetime.datetime(d.year, d.month, d.day, 17, 58, tzinfo=JST)))
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, _hourly(), _daily(), {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "中部国際空港", "05:58", "17:58", "", "3%", latitude=34.86, longitude=136.81,
                 now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))       # 枠は描かない時刻
    arr = pygame.surfarray.array3d(screen).astype(int)
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    # 時刻の行（印とラベルがある行）だけを見る：天気アイコンの橙色と区別するため、▲▼の色そのものの画素
    for color, col in ((weather_draw.SUNRISE_COLOR, 7), (weather_draw.SUNSET_COLOR, 3)):     # 03 の列・15 の列
        near = np.all(arr == np.array(color), axis=2)
        xs = np.where(near.any(axis=1))[0]
        assert len(xs), f"{color} の印が無い"
        next_col_left = margin_x + (1 + col) * col_w + col_w
        assert xs.max() < next_col_left, f"{w}×{h}: 印が次の列（x={next_col_left}〜）に食い込んでいる（最大 x={xs.max()}）"


# ---------------------------------------------------------------- 雷の帯
@pytest.mark.parametrize("w, h", RESOLUTIONS)
@pytest.mark.parametrize("kind", ["near", "watch"])
def test_thunder_banner_is_drawn_above_heat_alert(w, h, kind):
    """雷の帯がヘッダーの直下に、熱中症アラートの帯はその下に描かれ、どちらも画面に収まる"""
    import weather_draw
    sc = dict(SCENARIOS["いちばん詰まる"], thunder={"kind": kind, "km": 18.4, "dir": "南西",
                                                      "at": datetime.datetime(2026, 10, 11, 12, 10, tzinfo=JST)})
    screen = _render(w, h, sc)
    arr = pygame.surfarray.array3d(screen)
    bg = weather_draw.THUNDER_STYLE[kind]["bg"]
    rows = np.where(np.all(arr == bg, axis=2).sum(axis=0) > w * 0.5)[0]
    assert len(rows), "雷の帯が無い"
    header_h = int(h * 0.25)
    assert header_h <= rows.min() < header_h + weather_draw.ALERT_BANNER_H
    heat = np.where(np.all(arr == (160, 0, 0), axis=2).sum(axis=0) > w * 0.5)[0]
    if kind == "watch":
        assert heat.min() > rows.max()                               # 熱中症アラートは雷の下
    else:                                                            # 同じ赤：2 本ぶんの高さがある
        assert heat.max() - heat.min() > weather_draw.ALERT_BANNER_H_DOUBLE * 1.5
    bottom, _ = _content_box(screen)
    assert bottom < h - 1


# ---------------------------------------------------------------- 風向の矢印
@pytest.mark.parametrize("deg, tip", [(0, "下"), (90, "左"), (180, "上"), (270, "右")])
def test_wind_arrow_points_downwind(deg, tip):
    """北風（0 度）は南へ吹くので下向き。東風は左、南風は上、西風は右"""
    from weather_draw import wind_arrow_points
    (tx, ty) = wind_arrow_points(100, 100, 40, deg)[0]
    assert {"下": ty > 110, "上": ty < 90, "左": tx < 90, "右": tx > 110}[tip]


@pytest.mark.parametrize("deg", range(0, 360, 15))
def test_wind_arrow_fits_its_circle(deg):
    from weather_draw import wind_arrow_points
    assert all(((x - 100) ** 2 + (y - 100) ** 2) ** 0.5 <= 20.01 for x, y in wind_arrow_points(100, 100, 40, deg))


@pytest.mark.parametrize("speed, color", [(0, (205, 210, 205)), (3, (70, 170, 255)), (7, (70, 0, 255)),
                                          (8, (240, 225, 0)), (17, (240, 140, 20)), (18, (230, 40, 20))])
def test_wind_arrow_color(speed, color):
    from weather_draw import wind_arrow_color
    assert wind_arrow_color(speed) == color


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_wind_arrows_drawn_inside_wind_cells(w, h):
    """風速 24 m/s（いちばん長い数字）でも、矢印（赤）が全部の列で風速の行の中に描かれる"""
    import weather_draw
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, _hourly(), _daily(), {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    red = np.all(arr == weather_draw.wind_arrow_color(24), axis=2)
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    row_h = int(h * 0.055)                                   # 風速の行の高さ
    ys = np.where(red.any(axis=0))[0]
    assert len(ys) and ys.max() - ys.min() < row_h           # 矢印は 1 行（風速の行）の高さに収まる
    for i in range(10):
        x = margin_x + (1 + i) * col_w
        assert red[x + 1:x + col_w - 1].sum() > 20, f"{w}×{h}: {i} 列目に矢印が無い"
