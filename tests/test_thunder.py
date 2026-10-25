"""雷ナウキャスト（fetch_thunder）：時刻一覧の読み方・距離と方向・色→活動度・表示の保持"""
import datetime
import os

import pytest

import fetch_thunder as ft
from utils import JST

LAT, LON = 34.8583, 136.8053          # 中部国際空港


def test_latest_analysis_picks_newest_observation_with_thns():
    times = [
        {"basetime": "20260820011000", "validtime": "20260820011000", "elements": ["thns", "trns"]},
        {"basetime": "20260820011000", "validtime": "20260820012000", "elements": ["thns", "trns"]},   # 予報
        {"basetime": "20260820010000", "validtime": "20260820010000", "elements": ["thns", "trns"]},
        {"basetime": "20260820012000", "validtime": "20260820012000", "elements": ["trns"]},           # 雷なし
    ]
    assert ft.latest_analysis(times) == ("20260820011000", "20260820011000")
    assert ft.latest_analysis([]) is None


@pytest.mark.parametrize("deg, name", [(0, "北"), (44, "北東"), (90, "東"), (180, "南"), (225, "南西"),
                                       (300, "北西"), (338, "北"), (359.9, "北")])
def test_direction_name(deg, name):
    assert ft.direction_name(deg) == name


def test_pixel_round_trip():
    x, y = ft.to_global_px(LAT, LON, 8)
    lat, lon = ft.from_global_px(x, y, 8)
    assert abs(lat - LAT) < 1e-9 and abs(lon - LON) < 1e-9


def test_distance_bearing_southwest():
    d, deg = ft.distance_bearing(LAT, LON, LAT - 0.1, LON - 0.1)
    assert 13 < d < 16 and ft.direction_name(deg) == "南西"


@pytest.mark.parametrize("rgb, level", [((242, 242, 0), 1), ((250, 245, 10), 1), ((255, 153, 0), 2),
                                        ((255, 40, 0), 3), ((180, 0, 104), 4), ((200, 0, 255), 4)])
def test_level_for_color(rgb, level):
    assert ft.level_for_color(rgb) == level


def test_tiles_cover_search_area():
    tiles = ft.tiles_for(LAT, LON, ft.SEARCH_KM)
    cx, cy = ft.to_global_px(LAT, LON, ft.ZOOM)
    assert (int(cx) // 256, int(cy) // 256) in tiles
    assert 1 <= len(tiles) <= 4


class FakeTile:
    """get_at だけの画像。pixels = {(px, py): (r, g, b, a)}、ほかは透明"""
    def __init__(self, pixels=None):
        self.pixels = pixels or {}

    def get_at(self, p):
        return self.pixels.get(p, (0, 0, 0, 0))


def _tiles_with(points):
    """points = [(lat, lon, rgb)] を置いたタイル群"""
    tiles = {t: FakeTile() for t in ft.tiles_for(LAT, LON, ft.SEARCH_KM)}
    for lat, lon, rgb in points:
        x, y = ft.to_global_px(lat, lon, ft.ZOOM)
        tiles.setdefault((int(x) // 256, int(y) // 256), FakeTile()).pixels[(int(x) % 256, int(y) % 256)] = (*rgb, 255)
    return tiles


def test_nearest_thunder_finds_closest_level2_or_more():
    tiles = _tiles_with([
        (LAT - 0.04, LON - 0.04, ft.LEVEL_COLORS[1]),     # 約 6km 南西：活動度 1（可能性のみ）は数えない
        (LAT + 0.08, LON, ft.LEVEL_COLORS[2]),            # 約 9km 北：雷あり
        (LAT, LON + 0.15, ft.LEVEL_COLORS[4]),            # 約 14km 東：激しい雷
    ])
    hit = ft.nearest_thunder(LAT, LON, tiles)
    assert hit["dir"] == "北" and 8 < hit["km"] < 10
    assert hit["level"] == 2 and hit["max_level"] == 4


def test_nearest_thunder_ignores_far_and_transparent():
    tiles = _tiles_with([(LAT + 0.3, LON, ft.LEVEL_COLORS[3])])      # 約 33km 北：範囲外
    assert ft.nearest_thunder(LAT, LON, tiles) is None
    assert ft.nearest_thunder(LAT, LON, {}) is None                  # タイルが無い（404）＝雷なし


def _result(km, minute, d="南西"):
    at = datetime.datetime(2026, 8, 20, 10, minute, tzinfo=JST)
    return {"status": "ok", "at": at, "hit": None if km is None else {"km": km, "dir": d, "level": 2}}


def _now(minute):
    return datetime.datetime(2026, 8, 20, 10, 0, tzinfo=JST) + datetime.timedelta(minutes=minute)


def test_state_near_watch_and_hold():
    st = ft.ThunderState()
    st.update(_result(None, 0))
    assert st.current(_now(2)) is None
    st.update(_result(18, 10))
    assert st.current(_now(12))["kind"] == "watch"
    st.update(_result(6, 20))
    cur = st.current(_now(22))
    assert cur["kind"] == "near" and cur["km"] == 6
    st.update(_result(15, 30))                        # 10km より遠のいても 20 分は「雷接近」のまま。距離は最新
    cur = st.current(_now(32))
    assert cur["kind"] == "near" and cur["km"] == 15
    st.update(_result(None, 40))                      # 雷なし
    assert st.current(_now(39))["kind"] == "near"     # 10:20 の接近から 20 分以内
    assert st.current(_now(45))["kind"] == "watch"    # 接近は解除、10:30 の 15km から 20 分以内
    assert st.current(_now(51)) is None               # すべて解除


def test_state_ignores_errors():
    st = ft.ThunderState()
    st.update(_result(5, 0))
    st.update({"status": "error", "error": "timeout"})
    assert st.current(_now(5))["kind"] == "near"


def test_banner_text():
    t, b = ft.banner_text({"kind": "near", "km": 5.6, "dir": "南西", "at": _now(20)})
    assert t == "雷接近" and "南西 6km" in b and "10:20 解析" in b and "中止" in b
    t, b = ft.banner_text({"kind": "watch", "km": 0.3, "dir": "北", "at": _now(20)})
    assert t == "雷注意" and "北 1km" in b


class FakeResp:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code, self._json, self.content = status, json_data, content

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_thunder_with_png_tiles(monkeypatch, tmp_path):
    """実際の PNG を読み込む経路：雷のあるタイルを 1 枚だけ返し、ほかは 404。
    雷を見つけたら、その解析のタイル画像とまとめを残す（色と活動度の対応を確かめる用）"""
    import json
    import os
    import pygame
    monkeypatch.setattr(ft, "EVIDENCE_DIR", str(tmp_path / "ev"))
    x, y = ft.to_global_px(LAT + 0.08, LON, ft.ZOOM)
    target = (int(x) // 256, int(y) // 256)
    surf = pygame.Surface((256, 256), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    surf.set_at((int(x) % 256, int(y) % 256), (*ft.LEVEL_COLORS[3], 255))
    png = tmp_path / "t.png"
    pygame.image.save(surf, str(png))
    times = [{"basetime": "20260820011000", "validtime": "20260820011000", "elements": ["thns"]}]
    urls = []

    class Session:
        def get(self, url, headers=None, timeout=None):
            urls.append(url)
            if url == ft.TIMES_URL:
                return FakeResp(json_data=times)
            if url.endswith(f"/{ft.ZOOM}/{target[0]}/{target[1]}.png"):
                return FakeResp(content=png.read_bytes())
            return FakeResp(status=404)

    r = ft.fetch_thunder(LAT, LON, session=Session())
    assert r["status"] == "ok"
    assert r["at"] == datetime.datetime(2026, 8, 20, 10, 10, tzinfo=JST)
    assert r["hit"]["dir"] == "北" and r["hit"]["level"] == 3
    assert all("/20260820011000/none/20260820011000/surf/thns/" in u for u in urls[1:])
    assert r["hit"]["rgba"] == (*ft.LEVEL_COLORS[3], 255)
    files = sorted(os.listdir(tmp_path / "ev"))
    assert files == sorted([f"thns_20260820_1010_{target[0]}_{target[1]}.png", "thns_20260820_1010.json"])
    saved = json.load(open(tmp_path / "ev" / "thns_20260820_1010.json"))
    assert saved["hit"]["level"] == 3 and saved["hit"]["colors"][0][2] == 3
    assert "活動度 3" in ft.describe_hit(r["hit"])


def test_evidence_keeps_latest_only(tmp_path):
    d = str(tmp_path)
    hit = {"km": 5.0, "dir": "北", "level": 2, "rgba": (255, 153, 0, 255), "colors": []}
    for m in range(0, 60, 10):
        assert ft.save_evidence(f"20260820{1 + m // 60:02d}{m:02d}00", {(1, 2): b"png"}, hit, base_dir=d, keep=3)
    assert not ft.save_evidence("20260820015000", {(1, 2): b"png"}, hit, base_dir=d, keep=3)   # 同じ解析は 1 回だけ
    stamps = sorted({n[5:18] for n in os.listdir(d)})
    assert stamps == ["20260820_1030", "20260820_1040", "20260820_1050"]
