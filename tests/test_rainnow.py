"""降水ナウキャスト（fetch_rainnow）：時刻一覧の読み方・色→雨の強さ・空港のまわりの最大"""
import datetime

import pygame
import pytest

import fetch_rainnow as fr
import fetch_thunder as ft
from utils import JST

LAT, LON = 34.8583, 136.8053


@pytest.mark.parametrize("rgb, mmh", [((242, 242, 255), 0.5), ((160, 210, 255), 3.0), ((33, 140, 255), 7.5),
                                      ((0, 65, 255), 15.0), ((250, 245, 0), 25.0), ((255, 153, 0), 40.0),
                                      ((255, 40, 0), 65.0), ((180, 0, 104), 80.0)])
def test_mmh_for_color(rgb, mmh):
    assert fr.mmh_for_color(rgb) == mmh


def test_analysis_and_forecasts_every_15_minutes():
    def e(b, v, el=("hrpns",)):
        return {"basetime": b, "validtime": v, "elements": list(el)}
    n1 = [e("20261024010000", "20261024010000"), e("20261024005500", "20261024005500")]
    n2 = [e("20261024010000", f"202610240{1 + m // 60}{m % 60:02d}00") for m in range(5, 125, 5)]
    latest, fcs = fr.analysis_and_forecasts([n1, n2])
    assert latest == ("20261024010000", "20261024010000")
    assert fcs == ["20261024011500", "20261024013000", "20261024014500", "20261024020000"]   # 60 分先まで・15 分おき


def test_no_analysis():
    assert fr.analysis_and_forecasts([[{"basetime": "1", "validtime": "1", "elements": ["thns"]}]]) == (None, [])


class FakeTile:
    def __init__(self, pixels=None):
        self.pixels = pixels or {}

    def get_at(self, p):
        return self.pixels.get(p, (0, 0, 0, 0))


def _tiles(points, z=fr.ZOOM):
    tiles = {}
    for lat, lon, rgb in points:
        x, y = ft.to_global_px(lat, lon, z)
        tiles.setdefault((int(x) // 256, int(y) // 256), FakeTile()).pixels[(int(x) % 256, int(y) % 256)] = (*rgb, 255)
    return tiles


def test_max_near_airport_ignores_far_rain():
    assert fr.max_mmh_near(LAT, LON, {}) == 0                                     # タイル無し＝雨なし
    near = _tiles([(LAT + 0.005, LON, (160, 210, 255)), (LAT, LON + 0.005, (33, 140, 255))])  # 約 0.5km
    assert fr.max_mmh_near(LAT, LON, near) == 7.5                                 # いちばん強い区分
    far = _tiles([(LAT + 0.05, LON, (255, 40, 0))])                               # 約 5.5km：範囲外
    assert fr.max_mmh_near(LAT, LON, far) == 0


def test_fetch_rainnow_now_and_ahead(tmp_path):
    """今は弱い雨、45 分後に強い雨 → now 3mm/h・max 25mm/h。タイルが無い時刻は雨なし"""
    pygame.display.init()
    x, y = ft.to_global_px(LAT, LON, fr.ZOOM)
    tile = (int(x) // 256, int(y) // 256)

    def png(rgb):
        s = pygame.Surface((256, 256), pygame.SRCALPHA)
        s.fill((0, 0, 0, 0))
        s.set_at((int(x) % 256, int(y) % 256), (*rgb, 255))
        p = tmp_path / f"{rgb}.png"
        pygame.image.save(s, str(p))
        return p.read_bytes()
    base = "20261024010000"
    times = [{"basetime": base, "validtime": base, "elements": ["hrpns"]}] + [
        {"basetime": base, "validtime": f"202610240{1 + m // 60}{m % 60:02d}00", "elements": ["hrpns"]}
        for m in range(5, 65, 5)]
    tiles = {base: png((160, 210, 255)), "20261024014500": png((250, 245, 0))}

    class Resp:
        def __init__(self, status=200, data=None, content=b""):
            self.status_code, self._data, self.content = status, data, content

        def json(self):
            return self._data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class Session:
        def get(self, url, **kw):
            if url == fr.TIMES_URLS[0]:
                return Resp(data=times)
            if url == fr.TIMES_URLS[1]:
                return Resp(status=404)
            valid = url.split("/none/")[1].split("/")[0]
            if url.endswith(f"/{fr.ZOOM}/{tile[0]}/{tile[1]}.png") and valid in tiles:
                return Resp(content=tiles[valid])
            return Resp(status=404)
    r = fr.fetch_rainnow(LAT, LON, session=Session())
    assert r["status"] == "ok" and r["now_mmh"] == 3.0 and r["max_mmh"] == 25.0
    assert r["at"] == datetime.datetime(2026, 10, 24, 10, 0, tzinfo=JST)


def test_is_fresh():
    at = datetime.datetime(2026, 10, 24, 10, 0, tzinfo=JST)
    assert fr.is_fresh({"status": "ok", "at": at}, at + datetime.timedelta(minutes=20))
    assert not fr.is_fresh({"status": "ok", "at": at}, at + datetime.timedelta(minutes=21))
    assert not fr.is_fresh(None, at)
