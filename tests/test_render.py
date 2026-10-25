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
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    blue[:margin_x + col_w] = False                          # 見出しの列（黒い文字が縦に並ぶ）は除く
    cols = np.where(blue.sum(axis=1) > h * 0.1)[0]          # 縦に長く続く線（枠の左右。色は NOW_FRAME_COLOR）
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
    # 日の入り▼は、昼↔夜の移り変わりの途中（15 時の列の右端）では夜用の明るい色になることがある
    for colors, col in (((weather_draw.SUNRISE_COLOR,), 7),
                        ((weather_draw.SUNSET_COLOR, weather_draw.SUNSET_ON_NIGHT), 3)):     # 03 の列・15 の列
        color = colors
        near = np.any([np.all(arr == np.array(c), axis=2) for c in colors], axis=0)
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
    # 表の下の風速の色の帯（赤の区切りもある）は除く：帯の上端＝灰（0 m/s の色）がある最初の行
    legend_top = np.where(np.all(arr == weather_draw.wind_arrow_color(0), axis=2).any(axis=0))[0].min()
    red[:, legend_top:] = False
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    row_h = int(h * 0.055)                                   # 風速の行の高さ
    ys = np.where(red.any(axis=0))[0]
    assert len(ys) and ys.max() - ys.min() < row_h           # 矢印は 1 行（風速の行）の高さに収まる
    for i in range(10):
        x = margin_x + (1 + i) * col_w
        assert red[x + 1:x + col_w - 1].sum() > 20, f"{w}×{h}: {i} 列目に矢印が無い"


@pytest.mark.parametrize("speed", [0, 3, 4, 5, 6, 9, 15, 20])
def test_wind_text_color_matches_arrow_band(speed):
    """数字の色：5 m/s 未満は黒。5 以上は矢印と同じ区切り（黄だけ文字を濃く。白地で読めるように）"""
    from weather_draw import wind_arrow_color, wind_text_color
    a, t = wind_arrow_color(speed), wind_text_color(speed)
    if speed < 5:
        assert t == (0, 0, 0)
    elif speed == 9:
        assert t != a and sum(t) < sum(a)
    else:
        assert t == a


# ---------------------------------------------------------------- 見出し（降水量・気温・風速）の横の絵
@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_label_icons_fit_in_label_column(w, h):
    """絵は文字と同じ大きさ（22px 以内）で、見出しの列からはみ出さない"""
    import weather_draw
    from utils import get_font
    col_w = int((w - int(w * 0.05) * 2) // 11)
    for label, name in weather_draw.LABEL_ICONS.items():
        icon = weather_draw._label_icon(name, weather_draw.LABEL_FONT_SIZE, {})
        assert icon is not None, name
        assert max(icon.get_size()) == weather_draw.LABEL_FONT_SIZE
        text_w = get_font(BASE_FONT, weather_draw.LABEL_FONT_SIZE).size(label)[0]
        assert 5 + text_w + 4 + icon.get_width() < col_w, f"{w}×{h}: 「{label}」の絵が列からはみ出す"


def test_label_icons_line_up():
    """「降水量」「気　温」「風　速」は同じ幅なので、右の絵が縦一列にそろう"""
    import weather_draw
    from utils import get_font
    f = get_font(BASE_FONT, weather_draw.LABEL_FONT_SIZE)
    assert len({f.size(label)[0] for label in weather_draw.LABEL_ICONS}) == 1


# ---------------------------------------------------------------- 時刻の行の昼夜の色・風速の数字と矢印
@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_time_row_day_night_colors(w, h):
    """時刻の行のマス：06・09・12・15 時は黄→白、18・21・00・03 時は紺→青のグラデーション（日の出・日の入りに関係なく固定）。
    夜のマスの時刻の数字は白"""
    import weather_draw
    screen = pygame.Surface((w, h))
    hourly = _hourly()
    draw_weather(screen, w, h, hourly, _daily(), {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    # 時刻の行の位置：昼の上端の色（黄）の行を探す
    first_x = margin_x + col_w + 3                                # 06 時のマスの左端（上の端は数字が無い）
    near = lambda px, c: np.abs(px.astype(int) - np.array(c)).max(axis=-1) <= 12     # 枠の下のグラデーションの上端
    ys = np.where(near(arr[first_x], weather_draw.TIME_DAY_TOP))[0]
    assert len(ys), f"{w}×{h}: 時刻の行の昼の色が無い"
    top_y = ys.min()
    for i, item in enumerate(hourly):
        x = margin_x + (1 + i) * col_w + 3                        # 左端：昼↔夜の移り変わりは列の右へ向かって起きる
        night = item["hour"] in weather_draw.NIGHT_HOURS
        want = weather_draw.TIME_NIGHT_TOP if night else weather_draw.TIME_DAY_TOP
        assert near(arr[x, top_y], want), f"{w}×{h}: {item['hour']} 時のマスの色が違う"
        if night:
            cell = arr[x + 2:x + 40, top_y:top_y + int(h * 0.030)]
            assert np.all(cell == weather_draw.TIME_NIGHT_TEXT, axis=2).any(), f"{w}×{h}: {item['hour']} 時の数字が白でない"


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_wind_arrow_does_not_touch_two_digit_number(w, h):
    """2 桁の風速（11 m/s）でも、矢印が数字・単位に重ならない（数字は濃い黄、矢印は黄で区別できる）"""
    import weather_draw
    hourly = _hourly()
    for it in hourly:
        it.update(wind_val=11, wind="11 m/s", wind_dir=270)            # 西風 → 右向き（いちばん左に寄る向き）
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, hourly, _daily(), {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    text = np.all(arr == weather_draw.wind_text_color(11), axis=2)
    arrow = np.all(arr == weather_draw.wind_arrow_color(11), axis=2)
    tys = np.where(text.any(axis=0))[0]                     # 風速の行だけを見る（表の下の色の帯の黄は除く）
    keep = np.zeros(arrow.shape[1], bool)
    keep[max(0, tys.min() - 15):tys.max() + 12] = True
    arrow &= keep[None, :]
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    for i in range(10):
        x = margin_x + (1 + i) * col_w
        tx = np.where(text[x:x + col_w].any(axis=1))[0]
        ax = np.where(arrow[x:x + col_w].any(axis=1))[0]
        assert len(tx) and len(ax), f"{w}×{h}: {i} 列目"
        assert ax.min() > tx.max(), f"{w}×{h}: {i} 列目で矢印が数字に重なる"


def test_wind_number_bold_from_9():
    import weather_draw
    assert weather_draw.WIND_BOLD_FROM == 9


@pytest.mark.parametrize("w, h", RESOLUTIONS)
@pytest.mark.parametrize("wind_dir", [135, None])
def test_calm_wind_shows_dashes_not_arrow(w, h, wind_dir):
    """風速 0 m/s は風向に意味が無いので、矢印（灰）を描かず「---」（静穏）を描く。風向のデータが無くても「---」"""
    import weather_draw
    hourly = _hourly()
    for it in hourly:
        it.update(wind_val=0, wind="0 m/s", wind_dir=wind_dir)
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, hourly, _daily(), {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    circle = np.all(arr == weather_draw.CALM_MARK_COLOR, axis=2)
    # 灰色の矢印は無い：灰（0 m/s の色）があるのは、表の下の色の帯（高さ 20）の中だけ
    gys = np.where(np.all(arr == weather_draw.wind_arrow_color(0), axis=2).any(axis=0))[0]
    assert gys.max() - gys.min() <= 22
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    for i in range(10):
        x = margin_x + (1 + i) * col_w
        assert circle[x:x + col_w].sum() > 10, f"{w}×{h}: {i} 列目に「---」が無い"


def test_night_mix_changes_smoothly_in_dusk_and_dawn_columns():
    """15 時の列の中で昼→夜、03 時の列の中で夜→昼になめらかに移り、ほかの列は一色"""
    import weather_draw
    hourly = _hourly()                                            # 06 09 12 15 18 21 00 03 06 09
    mix = lambda i, f: weather_draw.night_mix(hourly, i, f)
    assert mix(0, 0.5) == mix(2, 0.9) == 0.0 and mix(4, 0.5) == mix(6, 0.9) == 1.0
    assert mix(3, 0.0) == 0.0 and 0.4 < mix(3, 0.5) < 0.6 and mix(3, 1.0) == 1.0   # 15 時：昼 → 夜
    assert mix(7, 0.0) == 1.0 and mix(7, 1.0) == 0.0                               # 03 時：夜 → 昼
    vals = [mix(3, k / 20) for k in range(21)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))                             # 途中で戻らない


def test_time_row_background_is_reused_until_columns_shift():
    """時刻の行の背景は 1 回作ったら使い回し、列の並び（昼夜の並び）が変わったときだけ作り直す（Pi Zero の負担を増やさない）"""
    import weather_draw
    weather_draw._time_row_cache.clear()
    hourly = _hourly()                                             # 06 09 12 15 18 21 00 03 06 09
    a = weather_draw._time_row_surface(hourly, 150, 30)
    assert weather_draw._time_row_surface(hourly, 150, 30) is a     # 毎分の描き直しでは作り直さない
    shifted = hourly[1:] + hourly[:1]                               # 3 時間後：09 12 15 18 21 00 03 06 09 06
    b = weather_draw._time_row_surface(shifted, 150, 30)
    assert b is not a and b.get_size() == (1500, 30)
    assert b.get_at((5, 0))[:3] == weather_draw.TIME_DAY_TOP        # 上端の色はそのまま


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_header_sun_icons_instead_of_text(w, h):
    """2 行目の「日の出」「日の入り」は文字ではなく絵（オレンジ・紺）。時刻の数字はそのまま"""
    import header
    for name in ("sunrise", "sunset"):
        assert header._sun_label_icon(name, 40) is not None
    screen = pygame.Surface((w, h))
    screen.fill((255, 255, 255))
    draw_header(screen, w, h, BASE_FONT, "成田空港", "05:47", "16:59", "", "")
    arr = pygame.surfarray.array3d(screen)
    band = arr[:, int(h * 0.15):int(h * 0.25)].astype(int)
    r, g, b = band[..., 0], band[..., 1], band[..., 2]
    # 小さい画面では線が細く、縁がなめらかに薄まるので、色合いで探す
    assert ((r - b > 100) & (g < 200) & (r > 200)).sum() > 10         # 日の出の絵（オレンジ）
    assert ((b - r > 40) & (b - g > 40)).sum() > 10                   # 日の入りの絵（紺）


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_variable_wind_shows_dashes(w, h):
    """実況で風向が変動（VRB）のときは、矢印の代わりに「---」（向きなし）。ほかの列は矢印"""
    import weather_draw
    hourly = _hourly()
    hourly[1] = dict(hourly[1], wind_val=1, wind="1 m/s", wind_dir=None, wind_variable=True, observed=True)
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, hourly, _daily(), {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    dashes = np.all(arr == weather_draw.CALM_MARK_COLOR, axis=2)
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    x = margin_x + 2 * col_w
    vrb, normal = dashes[x:x + col_w].sum(), dashes[x - col_w:x].sum()
    # 2 列目（VRB）に「---」。1 列目（風向あり）は矢印の縁の点が数個まじるだけ
    assert vrb > 20 and vrb > normal * 4


@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_weekly_reliability_badges_and_legend(w, h):
    """降水確率の右に信頼度の札（A 赤・B 黄・C 水色）。題名の右に説明。信頼度の無い日は札なし。列からはみ出さない"""
    import weather_draw
    daily = [dict(d, rel=r) for d, r in zip(_daily(), ["", "A", "B", "C", "A"])]
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, _hourly(), daily, {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    margin_x = int(w * 0.05)
    col_w = int((w - margin_x * 2) // 11)
    for i, rel in enumerate(["", "A", "B", "C", "A"]):
        x = margin_x + (1 + i) * col_w
        cells = {r: np.all(arr[x + 1:x + col_w - 1, int(h * 0.75):] == c, axis=2).sum()
                 for r, c in weather_draw.REL_COLORS.items()}
        if rel:
            assert cells[rel] > 50, f"{w}×{h}: {i} 列目に {rel} の札が無い"
        else:
            assert sum(cells.values()) == 0
    # 説明は表のすぐ下（表より下に C の色がある）
    table_bottom = max(np.where(np.all(arr == (160, 160, 160), axis=2).any(axis=0))[0])
    legend = np.all(arr[:, table_bottom:] == weather_draw.REL_COLORS["C"], axis=2)
    assert legend.sum() > 30, f"{w}×{h}: 表の下に信頼度の説明が無い"


@pytest.mark.parametrize("w, h", RESOLUTIONS)
@pytest.mark.parametrize("banners", ["thunder", "heat", "both"])
def test_reliability_legend_fits_with_banners(w, h, banners):
    """雷・熱中症の帯で表が下にずれても、信頼度の説明が表の下に描かれ、画面からはみ出さない"""
    import weather_draw
    daily = [dict(d, rel=r) for d, r in zip(_daily(), ["", "A", "B", "C", "A"])]
    thunder = {"kind": "near", "km": 6.0, "dir": "南西", "at": datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST)}
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, _hourly(), daily, {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", wbgt_level_info=level_for(33.5),
                 wbgt_alert=banners in ("heat", "both"), now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST),
                 thunder=thunder if banners in ("thunder", "both") else None)
    arr = pygame.surfarray.array3d(screen)
    table_bottom = max(np.where(np.all(arr == (160, 160, 160), axis=2).any(axis=0))[0])
    c = np.all(arr[:, table_bottom:] == weather_draw.REL_COLORS["C"], axis=2)
    assert c.sum() > 30, f"{w}×{h} {banners}: 説明が無い"
    ys = np.where(c.any(axis=0))[0] + table_bottom
    assert ys.max() < h - 1                                               # 画面の中


def test_reliability_colors_match_wind_legend():
    """信頼度の色は風速の色の帯と同じ：A 赤・B 黄・C 水色"""
    import weather_draw
    assert weather_draw.REL_COLORS == {"A": weather_draw.wind_arrow_color(18), "B": weather_draw.wind_arrow_color(8),
                                       "C": weather_draw.wind_arrow_color(1)}
@pytest.mark.parametrize("w, h", RESOLUTIONS)
def test_wind_color_legend_below_today_table(w, h):
    """今日の天気の表のすぐ下・右端に、風速の矢印の色の帯（6 区切り）。表の右端からはみ出さない"""
    import weather_draw
    screen = pygame.Surface((w, h))
    draw_weather(screen, w, h, _hourly(), _daily(), {}, BASE_FONT, "警報・注意報なし", "", "", "天気更新 10:24",
                 "成田空港", "05:44", "17:09", "", "3%", now=datetime.datetime(2026, 10, 11, 5, 0, tzinfo=JST))
    arr = pygame.surfarray.array3d(screen)
    margin_x = int(w * 0.05)
    right = margin_x + int((w - margin_x * 2) // 11) * 11
    gray = np.all(arr == weather_draw.wind_arrow_color(0), axis=2)        # 0 m/s の区切り（灰）
    assert gray.sum() > 50
    for speed in (3, 6, 9, 15, 20):
        c = np.all(arr == weather_draw.wind_arrow_color(speed), axis=2)
        xs = np.where(c.any(axis=1))[0]
        assert len(xs) and xs.max() <= right, f"{w}×{h}: {speed} m/s の区切りが無い・はみ出す"


def test_wrap_text_keeps_closing_paren_off_line_start():
    """「（突風・ひょう\n）」のように閉じかっこが行の先頭に来ない（行頭禁則）"""
    import pygame
    import weather_draw
    from config import BASE_FONT
    pygame.font.init()
    font = weather_draw.get_font(BASE_FONT, 24, bold=True)
    text = "大雨警報 / 洪水警報 / 雷注意報（突風・ひょう） / 強風注意報"
    for w in range(200, 700, 7):
        lines = weather_draw._wrap_text(text, font, w)
        assert "".join(lines) == text
        assert all(not l.startswith(("）", "・", "ょ")) for l in lines[1:]), (w, lines)


@pytest.mark.parametrize("size", [(1920, 1080), (1366, 768), (1280, 720)])
def test_overview_fits_with_many_warnings(size, monkeypatch):
    """警報・注意報が多くても、天気概況が少なくとも 1 行は欄の中に出る（警報・注意報との間は 1 行あける）"""
    import weather_draw
    W, H = size
    drawn = []
    real = weather_draw._wrap_text
    monkeypatch.setattr(weather_draw, "_wrap_text", lambda t, f, w: (drawn.append(t), real(t, f, w))[1])
    s = pygame.Surface((W, H))
    many = "大雨特別警報 / 大雨警報 / 洪水警報 / 暴風警報 / 波浪警報 / 高潮警報 / 雷注意報（突風・ひょう） / 濃霧注意報 / 乾燥注意報"
    weather_draw.draw_weather(s, W, H, _hourly(), _daily()[:5], {}, BASE_FONT, many, "見出し" * 20, "2026-10-25 11:00",   # 画面は 5 日分
                              "天気更新 11:37", "中部国際空港", "06:06", "17:06", "", "",
                              overview_text="２５日の東海地方は、前線や湿った空気の影響によりおおむね雨となるでしょう。",
                              now=datetime.datetime(2026, 10, 25, 12, 0, tzinfo=JST))
    assert any(t.startswith("【天気概況】") for t in drawn)
