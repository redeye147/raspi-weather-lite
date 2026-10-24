"""今の時間帯の天気アイコンを動かす（anim_icons・main01._wait_animating）"""
import os

import pygame
import pytest

import anim_icons


@pytest.fixture(autouse=True)
def display():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.display.set_mode((1, 1))
    anim_icons._cache.clear()
    yield


@pytest.mark.parametrize("code, kind, n", [
    ("100", "sun", 12), ("101", "sunpart", 12), ("102", "sunpart", 12), ("104", "sunpart", 12),
    ("700", "stars", 36), ("701", "stars", 24),
    ("300", "rain", 12), ("302", "rain", 12), ("306", "heavyrain", 12),
    ("400", "snow", 12), ("405", "heavysnow", 12),
])
def test_frames_for_animated_icons(code, kind, n):
    assert anim_icons.kind_for(code) == kind
    frames = anim_icons.frames_for(code, 147, 71)
    assert len(frames) == n and all(f.get_size() == (147, 71) for f in frames)
    assert pygame.image.tobytes(frames[0], "RGBA") != pygame.image.tobytes(frames[1], "RGBA")


@pytest.mark.parametrize("code", ["200", "350", "1000", "1000A", "999", "209"])
def test_other_icons_stay_still(code):
    """曇り・雷・高温の晴れなどは動かさない"""
    assert anim_icons.frames_for(code, 147, 71) is None


def test_sun_loop_is_seamless():
    """太陽は光 1 本分回ると元に戻る：最後の絵の次（最初の絵）へのつながりが、隣り合う絵どうしと同じくらい小さい"""
    import numpy as np
    def on_white(x):                                       # 画面と同じく白い地に置いて比べる（透明な所の色は比べない）
        s = pygame.Surface(x.get_size())
        s.fill((255, 255, 255))
        s.blit(x, (0, 0))
        return pygame.surfarray.array3d(s).astype(int)
    f = [on_white(x) for x in anim_icons.frames_for("100", 147, 71)]
    steps = [np.abs(f[i + 1] - f[i]).mean() for i in range(len(f) - 1)]
    wrap = np.abs(f[0] - f[-1]).mean()
    assert wrap < max(steps) * 1.2


def test_stars_one_at_a_time_and_moon_still():
    """星は 1 つずつ光る（同時に 2 つ光らない）。月の部分はどの絵でも同じ"""
    import numpy as np
    frames = [pygame.surfarray.array3d(x).astype(int) for x in anim_icons.frames_for("700", 147, 71)]
    base = pygame.surfarray.array3d(anim_icons._scaled("700", 147, 71)).astype(int)
    for f in frames:
        changed = np.argwhere(np.abs(f - base).sum(axis=2) > 30)
        if len(changed):
            span = changed.max(axis=0) - changed.min(axis=0)
            assert span.max() < 40, "離れた 2 か所が同時に光っている"
    moon = (slice(50, 100), slice(10, 60))                 # 月のあたり（星を置かない所）
    assert all(np.array_equal(f[moon], frames[0][moon]) for f in frames)


def test_heavy_rain_has_more_drops_than_rain():
    import numpy as np
    def blue(code):
        a = pygame.surfarray.array3d(anim_icons.frames_for(code, 147, 71)[3])
        return int(np.all(a == anim_icons.RAIN_COLOR, axis=2).sum())
    assert blue("306") > blue("300") * 2


def test_wait_animating_redraws_only_the_icon_cell(monkeypatch):
    import main01
    import weather_draw
    screen = pygame.Surface((400, 300))
    screen.fill((10, 20, 30))
    rects, waits = [], []
    monkeypatch.setattr(main01, "ANIMATE", True)
    monkeypatch.setattr(weather_draw, "current_anim", {"rect": (50, 40, 147, 71), "icon_code": "300"})
    monkeypatch.setattr(main01, "present_rect", lambda s, r: rects.append(tuple(r)) or True)
    monkeypatch.setattr(main01, "_wait_ms", lambda ms: waits.append(ms))
    t = [1000.0]
    monkeypatch.setattr(main01.time, "monotonic", lambda: t[0])

    def wait(ms):
        waits.append(ms)
        t[0] += ms / 1000
    monkeypatch.setattr(main01, "_wait_ms", wait)
    main01._wait_animating(screen, 1000)
    assert anim_icons.FPS <= len(rects) <= anim_icons.FPS + 1 and set(rects) == {(50, 40, 147, 71)}
    assert screen.get_at((10, 10))[:3] == (10, 20, 30)          # マスの外は描き直さない


def test_wait_animating_just_waits_when_nothing_to_animate(monkeypatch):
    import main01
    import weather_draw
    waits = []
    monkeypatch.setattr(main01, "ANIMATE", True)
    monkeypatch.setattr(weather_draw, "current_anim", {"rect": (0, 0, 147, 71), "icon_code": "200"})
    monkeypatch.setattr(main01, "_wait_ms", waits.append)
    main01._wait_animating(pygame.Surface((10, 10)), 5000)
    assert waits == [5000]


@pytest.mark.parametrize("code", ["101", "102", "104"])
def test_sunpart_rotates_sun_only(code):
    """晴れ時々曇りなど：左の太陽は回り、右の雲・傘・雪の結晶は動かない。止まった絵ともほぼ同じ"""
    import numpy as np
    def arr(x):
        s = pygame.Surface(x.get_size())
        s.fill((255, 255, 255))
        s.blit(x, (0, 0))
        return pygame.surfarray.array3d(s).astype(int)
    f = [arr(x) for x in anim_icons.frames_for(code, 150, 90)]
    still = arr(pygame.image.load(os.path.join(anim_icons.ICON_DIR, f"{code}.png")).convert_alpha())
    left = slice(0, 60)                                    # 太陽の円の所
    right = slice(100, 150)                                # 雲・傘・雪の結晶の所（太陽の光は届かない）
    assert np.abs(f[0][left] - f[3][left]).mean() > 1     # 太陽は回る
    assert np.abs(f[0][right] - f[3][right]).mean() < 0.5  # 右側は動かない
    assert np.abs(f[0][right] - still[right]).mean() < 2   # 右側は元の絵のまま
