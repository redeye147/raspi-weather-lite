"""
anim_icons.py
今の時間帯（今日の天気の青い枠の列）の天気アイコンだけを動かす。

  晴れ（100）        太陽の光がなめらかに回る（光 1 本分を 2 秒で回るとつなぎ目なく元に戻る）
  夜の晴れ（700・701） 月は動かさず、まわりの小さな星が 1 つずつ、ふわっと明るくなって消える
  雨（202・300・302） 雨粒が落ちる       大雨（306） 雨粒が多く・速く・太く・斜め
  雪（400）          雪がゆらゆら舞う   大雪（405） 雪が多く・速く・風で横に流れる
  それ以外（曇り・晴れ時々曇り・雷・高温の晴れなど）は動かさない

絵はアイコン 1 マスぶんを最初にまとめて作って使い回し、1 秒に FPS 回、そのマスだけを書き換える
（画面全体の描き直しは今までどおり 1 分に 1 回。Pi Zero でも負担は小さい）。
"""

import math
import os
import random

import pygame

from config import ICON_DIR

FPS = 6

KINDS = {
    "100": "sun",
    "700": "stars", "701": "stars",
    "202": "rain", "300": "rain", "302": "rain",
    "306": "heavyrain",
    "400": "snow",
    "405": "heavysnow",
}

# 100.png の光は 14 本（約 25.7 度ごとに同じ形）。光 1 本分回ると元の形に戻るので、くり返しにつなぎ目が出ない
SUN_SYMMETRY = 14
SUN_PERIOD_S = 2.0            # 光 1 本分を回る時間
WEATHER_PERIOD_S = 2.0        # 雨・雪のくり返し
STAR_EACH_S = 2.0             # 星 1 つが明るくなって消えるまで
# 月のアイコンの空いた所（左上を 0,0・幅と高さを 1 とした位置、星の大きさ＝高さに対する割合）。
# 絵から遠い所を自動で選んで決めた値（星が月や雲に重ならない）
STAR_SPOTS = {
    "700": [(0.061, 0.577, 0.099), (0.932, 0.859, 0.099), (0.932, 0.127, 0.099)],
    "701": [(0.061, 0.592, 0.099), (0.286, 0.155, 0.086)],
}

RAIN_COLOR = (20, 100, 225)
SNOW_FILL, SNOW_EDGE = (255, 255, 255), (140, 160, 195)
STAR_FILL, STAR_EDGE = (255, 200, 0), (200, 135, 0)


def kind_for(icon_code):
    return KINDS.get(str(icon_code))


def _raw(code):
    return pygame.image.load(os.path.join(ICON_DIR, f"{code}.png")).convert_alpha()


def _scaled(code, w, h):
    return pygame.transform.smoothscale(_raw(code), (w, h))


def _sun_frames(code, w, h):
    """元の絵（150×90）の中で太陽だけを回してから縮める（縮めたあとに回すと形がゆがんでガタつく）"""
    src = _raw(code)
    r = src.get_bounding_rect(min_alpha=40)
    side = max(r.w, r.h)
    sq = pygame.Rect(0, 0, side, side)
    sq.center = r.center
    part = pygame.Surface((side, side), pygame.SRCALPHA)
    part.blit(src, (0, 0), sq)
    n = max(1, round(SUN_PERIOD_S * FPS))
    frames = []
    for k in range(n):
        # 半コマずらして回す：0 度の絵だけ回転のなめらか処理を通らず形がくっきりして、くり返しの切れ目が目立つのを防ぐ
        rot = pygame.transform.rotozoom(part, -(k + 0.5) * (360 / SUN_SYMMETRY) / n, 1.0)
        out = pygame.Surface(src.get_size(), pygame.SRCALPHA)
        out.blit(rot, (sq.centerx - rot.get_width() // 2, sq.centery - rot.get_height() // 2))
        frames.append(pygame.transform.smoothscale(out, (w, h)))
    return frames


def _rain_frames(code, w, h, heavy):
    base = _scaled(code, w, h)
    n = max(1, round(WEATHER_PERIOD_S * FPS))
    count, speed, width, length, slant = (19, 2, 3, 13, 0.3) if heavy else (7, 1, 2, 9, 0.15)   # 雨粒の数は 2026-10 に 8 割に（24→19・9→7）
    rnd = random.Random(1)
    drops = [(rnd.uniform(0.05, 1.0) * w, rnd.uniform(0, 1)) for _ in range(count)]
    frames = []
    for k in range(n):
        f = base.copy()
        for x0, p in drops:
            y = ((p + speed * k / n) % 1.0) * (h + length) - length
            x = x0 - (y + length) * slant
            pygame.draw.line(f, RAIN_COLOR, (x, y), (x - length * slant, y + length), width)
        frames.append(f)
    return frames


def _snow_frames(code, w, h, heavy):
    base = _scaled(code, w, h)
    n = max(1, round(WEATHER_PERIOD_S * FPS))
    count, speed, wind = (28, 2, 0.45) if heavy else (10, 1, 0.0)
    rad = max(2, round(h * 0.055))
    rnd = random.Random(2)
    flakes = [(rnd.uniform(0, 1) * w, rnd.uniform(0, 1), rnd.uniform(0, 6.28)) for _ in range(count)]
    frames = []
    for k in range(n):
        f = base.copy()
        for x0, p, ph in flakes:
            q = (p + speed * k / n) % 1.0
            x = (x0 - q * wind * w) % w + 4 * math.sin(ph + k * 2 * math.pi / n)   # 大雪は風で横に流れる
            y = q * h
            pygame.draw.circle(f, SNOW_FILL, (int(x), int(y)), rad)
            pygame.draw.circle(f, SNOW_EDGE, (int(x), int(y)), rad, 1)
        frames.append(f)
    return frames


def _sparkle(surf, cx, cy, r, a):
    """4 方向に光る小さな星（a：明るさ 0〜1）"""
    if r < 1 or a <= 0.03:
        return
    size = int(r * 4) + 4
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    pts = [(c, c - 2 * r), (c + r * 0.35, c - r * 0.35), (c + 2 * r, c), (c + r * 0.35, c + r * 0.35),
           (c, c + 2 * r), (c - r * 0.35, c + r * 0.35), (c - 2 * r, c), (c - r * 0.35, c - r * 0.35)]
    alpha = int(255 * a)
    pygame.draw.polygon(s, (*STAR_FILL, alpha), pts)
    pygame.draw.polygon(s, (*STAR_EDGE, alpha), pts, 1)
    pygame.draw.circle(s, (255, 255, 220, alpha), (int(c), int(c)), max(1, int(r * 0.45)))
    surf.blit(s, (cx - c, cy - c))


def _star_frames(code, w, h):
    """月は動かさず、星が 1 つずつ順番に、ふわっと明るくなってふわっと消える"""
    base = _scaled(code, w, h)
    spots = STAR_SPOTS.get(code, [])
    each = max(1, round(STAR_EACH_S * FPS))
    frames = []
    for k in range(each * max(1, len(spots))):
        f = base.copy()
        if spots:
            n, local = divmod(k, each)
            fx, fy, fs = spots[n]
            a = math.sin(math.pi * local / each) ** 2            # 0 → 1 → 0 をなめらかに
            r = fs * h
            _sparkle(f, fx * w, fy * h, r * (0.85 + 0.15 * a), a)
        frames.append(f)
    return frames


_cache = {}


def frames_for(icon_code, w, h):
    """アニメーションの絵の並び（無ければ None）。同じアイコン・大きさは作り直さない"""
    kind = kind_for(icon_code)
    if kind is None or w <= 0 or h <= 0:
        return None
    key = (str(icon_code), w, h)
    if key not in _cache:
        try:
            if kind == "sun":
                frames = _sun_frames(icon_code, w, h)
            elif kind == "stars":
                frames = _star_frames(icon_code, w, h)
            elif kind in ("rain", "heavyrain"):
                frames = _rain_frames(icon_code, w, h, kind == "heavyrain")
            else:
                frames = _snow_frames(icon_code, w, h, kind == "heavysnow")
        except Exception:
            frames = None
        _cache.clear()                         # 今の時間帯の 1 つだけ覚えておく（メモリを使いすぎない）
        _cache[key] = frames
    return _cache[key]
