# 熱中症バッジ・警戒バナー・画面構成 実装メモ

raspi-weather-lite の天気サイネージに追加した「WBGTバッジ」「熱中症警戒アラートバナー」と、それに伴う画面構成の微調整についての解説です。他のセッション（メイン画面版 raspi-weather など）に同じ仕様を移植する際の参照用。

---

## 1. WBGTバッジ（ヘッダー右側）

ヘッダー右端に「熱中症」レベルを 3行（熱中症 / レベル / WBGT値）で表示するカラーバッジ。

### 仕様
- 表示位置: 時計の右隣、ヘッダー内に垂直中央揃え
- 内容（3行）:
  1. `熱中症`（小文字、ラベル）
  2. レベル文字（例: `注意`/`警戒`/`厳重警戒`/`危険`）— 大文字・太字
  3. `WBGT 28.5℃` のような値
- 背景色: レベルに応じて変化（`level_info["bg"]` / `level_info["fg"]`）
- **危険（WBGT ≥ 33）のみ 1秒ごとに背景を点滅**（通常色 ⇔ 深紅 `(180, 0, 0)`）

### 実装ポイント
`header.py` で **バッジを先に計測**して幅 `badge_reserve = bw + 24` を確保し、時計と2行目は残り幅 `available_w = width - badge_reserve` の中央に配置する。これで時計と重ならない。

```python
import time
from utils import JST, get_japanese_weekday, get_font

# ===== 0) WBGT バッジを先にレンダリング（サイズを知るため） =====
badge_data = None
badge_reserve = 0
if wbgt_level_info:
    f_small = get_font(base_font_path, int(height * 0.028))
    f_large = get_font(base_font_path, int(height * 0.045), bold=True)
    lbl_s = f_small.render("熱中症", True, wbgt_level_info["fg"])
    lvl_s = f_large.render(wbgt_level_info["label"], True, wbgt_level_info["fg"])
    val_s = f_small.render(f"WBGT {wbgt_level_info['value']:.1f}℃", True, wbgt_level_info["fg"])
    bw = max(lbl_s.get_width(), lvl_s.get_width(), val_s.get_width()) + 20
    inner_h = lbl_s.get_height() + lvl_s.get_height() + val_s.get_height() + 4
    bh = inner_h + 12
    badge_data = (lbl_s, lvl_s, val_s, bw, bh, inner_h)
    badge_reserve = bw + 24  # バッジ幅 + 左右マージン

# 時計・2行目はバッジを除いた領域の中央
available_w = width - badge_reserve
center_x = available_w // 2

# ===== 1) 大きい日付時刻 =====
title_surf = get_font(base_font_path, int(height * 0.14), bold=True).render(date_str, True, (0, 0, 0))
title_x = max(10, center_x - title_surf.get_width() // 2)
screen.blit(title_surf, (title_x, top_margin))

# ===== 3) バッジ描画（時計と垂直中央を揃える）=====
if badge_data:
    lbl_s, lvl_s, val_s, bw, bh, inner_h = badge_data
    bx = width - bw - 8
    title_center_y = top_margin + title_surf.get_height() // 2
    by = title_center_y - bh // 2
    if by < top_margin: by = top_margin
    if by + bh > header_h - 4: by = header_h - bh - 4

    # 危険レベルは1秒ごとに点滅
    if wbgt_level_info["label"] == "危険":
        blink_on = int(time.time()) % 2 == 0
        bg_color = wbgt_level_info["bg"] if blink_on else (180, 0, 0)
    else:
        bg_color = wbgt_level_info["bg"]
    pygame.draw.rect(screen, bg_color, (bx, by, bw, bh), border_radius=8)
    pygame.draw.rect(screen, wbgt_level_info["fg"], (bx, by, bw, bh), width=2, border_radius=8)

    ty = by + (bh - inner_h) // 2
    for surf in (lbl_s, lvl_s, val_s):
        screen.blit(surf, (bx + (bw - surf.get_width()) // 2, ty))
        ty += surf.get_height() + 2
```

### 過去のハマりポイント
| 症状 | 原因 | 対策 |
|------|------|------|
| バッジ内のテキストが下にはみ出す | `bh = header_h - y2 - 4` のように固定値で計算していた | `bh = inner_h + 12` のように実テキスト高さから算出 |
| バッジが時計と重なる | バッジをヘッダー下端に固定し、時計は全幅中央に配置していた | バッジを先に計測→ `available_w` を時計の中央計算に使う |

### 点滅の負荷について
- 1秒ごとの再描画は Pi Zero W でも CPU 10〜15% 程度で問題なし
- `危険` 時のみ点滅、その他のレベルは静止
- 詳細は §3「点滅とメインループ」参照

---

## 2. 熱中症警戒アラートバナー（ヘッダー直下）

WBGT が高い日の朝に環境省から発表される「熱中症警戒アラート」を受信した場合のみ、ヘッダー直下に幅いっぱいの赤帯を表示する。

### 仕様
- 高さ: `ALERT_BANNER_H = 44` px（固定定数）
- 背景: 濃赤 `(160, 0, 0)`、上下に明赤 `(255, 60, 60)` のライン
- テキスト: `熱中症警戒アラート発令中 ─ こまめな水分補給を！日陰で休憩を！`（淡黄色 `(255, 255, 180)`）
- 表示位置: ヘッダー直下（`y = header_h`）

### 実装（`weather_draw.py`）

```python
ALERT_BANNER_H = 44

def draw_alert_banner(screen, width, header_h, base_font_path):
    """ヘッダー直下に熱中症警戒アラートバナーを表示。"""
    bh = ALERT_BANNER_H
    by = header_h
    pygame.draw.rect(screen, (160, 0, 0), (0, by, width, bh))
    pygame.draw.line(screen, (255, 60, 60), (0, by), (width, by), 3)
    pygame.draw.line(screen, (255, 60, 60), (0, by + bh - 1), (width, by + bh - 1), 2)
    f = get_font(base_font_path, 26, bold=True)
    text = "熱中症警戒アラート発令中 ─ こまめな水分補給を！日陰で休憩を！"
    s = f.render(text, True, (255, 255, 180))
    screen.blit(s, ((width - s.get_width()) // 2, by + (bh - s.get_height()) // 2))
```

### draw_weather() 側でバナー分のオフセット
バナーを描いた場合、その下にある「作業注意情報」「今日の天気」テーブルがバナーに被るので、`y_offset` を `ALERT_BANNER_H + 2` だけ下にずらす：

```python
y_offset = int(height * 0.25)  # ヘッダー高さからスタート
if wbgt_alert:
    y_offset += ALERT_BANNER_H + 2  # ← バナー分シフト
```

### 過去のハマりポイント
| 症状 | 原因 | 対策 |
|------|------|------|
| 「今日の天気」白背景がバナーと重なる | `y_offset = header_h` で固定だった | `wbgt_alert` 時は `y_offset += ALERT_BANNER_H + 2` |
| 「作業注意報」がバナーと重なる | 同上 | 同上 |
| 最下部の週間予報が見切れる | バナー分のオフセットを底まで伝播していなかった | `y_offset += sum(row_heights) + 8`（従来 +40 → +8）に縮小し、全体を上に寄せる |

---

## 3. 点滅とメインループ（main01.py）

危険レベルのバッジ点滅は「1秒ごとに再描画」が必要だが、通常のメインループは 10秒間隔で待機している。点滅状態が変わった時だけ `needs_redraw` を立てる仕組みで実装。

### 主な変更点

```python
# 初期化（main() 内）
last_blink_state = -1

while True:
    now = datetime.datetime.now(JST)
    needs_redraw = False
    # ... 通常の更新判定 ...

    # 危険レベル時はバッジ点滅のため1秒ごとに再描画
    is_danger = wbgt_level_info is not None and wbgt_level_info.get("label") == "危険"
    if is_danger:
        cur_blink = int(time.time()) % 2
        if cur_blink != last_blink_state:
            needs_redraw = True
            last_blink_state = cur_blink

    if not needs_redraw:
        # ...
        pygame.time.wait(1000 if is_danger else 10000)  # ← 危険時は1秒に短縮
        continue

    # 描画...

    pygame.time.wait(1000 if is_danger else 10000)  # ← ループ末尾も同様
```

### ポイント
- `last_blink_state` が `-1` で初期化されているので、初回は必ず描画される
- `int(time.time()) % 2` は 0 or 1 を 1秒ごとに切り替える
- **危険でない時は従来通り 10秒間隔** → 余計な CPU を使わない

---

## 4. JMA 発表時間の毎時更新（main01.py）

警報・注意報の `発表時間` が起動時から更新されない問題があった。`get_overview_and_warning()` を毎時の JMA 更新タイミングで再取得して `updated_text` / `headline_text` を更新する。

```python
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
        last_jma_update = time.time()
        needs_redraw = True
    except Exception as e:
        logging.error(f"JMA更新失敗: {e}")
```

従来は `fetch_warning_data()` だけ呼んでいたため、`updated_text` は起動時の値のまま固定されていた（→ 数日経つと「発表時間」が古いまま表示される）。

---

## 5. 画面構成の微調整まとめ（`weather_draw.py`）

| 項目 | 変更前 | 変更後 | 目的 |
|------|-------|-------|------|
| バナー有り時の y_offset | バナーと内容が重なる | `y_offset += ALERT_BANNER_H + 2` | 重なり解消 |
| row_heights | `[0.06, 0.03, 0.08, 0.04, 0.04, 0.06]` | `[0.055, 0.030, 0.075, 0.040, 0.040, 0.055]` | 微縮小（バナー有り時のはみ出し対策） |
| summary 後の余白 | `+8` | `+4` | 縦詰め |
| title_bar_h | `62/34` (QR有/無) | `54/30` | 縦詰め |
| title_bar 後の余白 | `+8` | `+4` | 縦詰め |
| 時間別テーブル後の余白 | `+40` | `+8` | **最下部が見切れていたのを修正** |
| 週見出し後の余白 | `+10` | `+4` | 縦詰め |
| 風速単位 | `m` | `m/s` | 単位正確化 |
| 日付フォーマット | `5月17日 (日) 12:00` | `5月17日(日)12:00` | スペース削除で詰める（`header.py`） |

---

## 6. main01.service への対策（参考）

KMS/DRM で SDL kmsdrm を使う systemd サービスは **logind セッションが必要**。サービスを `User=pi` のまま起動すると EGL 初期化が失敗する。

対策（いずれか）:
- **`User=root` に変更**（最速）
- `raspi-config` で **Console Autologin** を有効化（pi が tty1 に自動ログインしてセッションを作成）

```ini
[Unit]
Description=Weather Signage Display
After=network.target wifi-setup-auto.service
Wants=wifi-setup-auto.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/home/pi/raspi-weather-lite
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=SDL_AUDIODRIVER=dummy
ExecStart=/usr/bin/python3 /home/pi/raspi-weather-lite/main01.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Bookworm では SDL 2.26.5 で EGL 失敗
Pi Zero W Rev 1.1 + Raspberry Pi OS Bookworm（SDL 2.26.5）では kmsdrm の EGL 初期化が失敗するバグあり。**Trixie へ dist-upgrade（SDL 2.32.4）すれば解決**する。

```bash
sudo sed -i 's/bookworm/trixie/g' /etc/apt/sources.list /etc/apt/sources.list.d/*.list
sudo apt update && sudo apt full-upgrade -y && sudo reboot
# 完了後: Python 3.13.5 / SDL 2.32.4 / pygame 2.6.1 で kmsdrm 動作確認済み
```

---

## 関連ファイル

- `header.py` — バッジ描画、時計・2行目レイアウト
- `weather_draw.py` — バナー描画、`y_offset` 制御、行間調整
- `main01.py` — 点滅メインループ、JMA毎時更新
- `fetch_wbgt.py` — WBGT 取得、`WBGT_LEVELS` 定義（バッジの色とラベル）
- `main01.service` — systemd ユニット（要 `User=root`）
