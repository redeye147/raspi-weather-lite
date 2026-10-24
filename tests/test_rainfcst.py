"""降水短時間予報（fetch_rainfcst）：時刻一覧の読み方・1 時間ごとの雨"""
import datetime

import pygame

import fetch_rainfcst as rf
import fetch_thunder as ft

LAT, LON = 34.8583, 136.8053


def e(b, v, member="immed"):
    return {"basetime": b, "validtime": v, "member": member, "elements": ["rasrf"]}


def test_forecast_targets_hourly_up_to_6h():
    base = "20261024003000"
    times = [e("20261024002000", "20261024010000")] + [
        e(base, f"20261024{h:02d}{m:02d}00") for h in range(0, 9) for m in (0, 30) if f"{h:02d}{m:02d}" > "0030"]
    latest, valids = rf.forecast_targets(times)
    assert latest == (base, "immed", "rasrf")
    assert valids == [f"20261024{h:02d}0000" for h in range(1, 7)]       # 毎正時・6 時間先まで


def test_forecast_targets_skips_other_elements_and_offhour():
    """別の要素・毎正時でない予報しか無い新しい発表は飛ばす（Pi で「発表時刻が見つからない」になった）"""
    times = [{"basetime": "20261024120000", "validtime": f"20261024{h}0000", "member": "none",
              "elements": ["rasrf", "rasrf_point", "rasrf_nd"]} for h in (13, 14)]
    times += [{"basetime": "20261024121000", "validtime": "20261024131000", "member": "immed", "elements": ["rasrf"]},
              {"basetime": "20261024123000", "validtime": "20261024130000", "member": "none", "elements": ["slmcs"]}]
    assert rf.forecast_targets(times) == (("20261024120000", "none", "rasrf"), ["20261024130000", "20261024140000"])


def test_forecast_targets_empty():
    assert rf.forecast_targets([]) == (None, [])


def test_fetch_rainfcst(tmp_path):
    pygame.display.init()
    z = rf.ZOOMS[0]
    x, y = ft.to_global_px(LAT, LON, z)
    tile = (int(x) // 256, int(y) // 256)
    s = pygame.Surface((256, 256), pygame.SRCALPHA)
    s.fill((0, 0, 0, 0))
    s.set_at((int(x) % 256, int(y) % 256), (33, 140, 255, 255))
    p = tmp_path / "t.png"
    pygame.image.save(s, str(p))
    blank = pygame.Surface((256, 256), pygame.SRCALPHA)
    blank.fill((0, 0, 0, 0))
    pygame.image.save(blank, str(tmp_path / "b.png"))
    base = "20261024003000"
    times = [e(base, f"20261024{h:02d}0000") for h in range(1, 4)]
    urls = []

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
            urls.append(url)
            if url.endswith("targetTimes.json"):
                return Resp(data=times)
            if "/20261024030000/" in url:
                return Resp(404)                                             # この時刻はタイルなし → 分からない
            if f"/{z}/{tile[0]}/{tile[1]}.png" in url:
                return Resp(content=(p if "/20261024020000/" in url else tmp_path / "b.png").read_bytes())
            return Resp(404)
    r = rf.fetch_rainfcst(LAT, LON, session=Session())
    assert r["status"] == "ok"
    assert r["hours"] == {"2026-10-24T10:00": 0.0, "2026-10-24T11:00": 7.5}     # JST の時刻
    assert any("/rasrf/20261024003000/immed/20261024020000/surf/rasrf/" in u for u in urls)
    assert r["at"] == datetime.datetime(2026, 10, 24, 0, 30, tzinfo=datetime.timezone.utc)
