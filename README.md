# raspi-weather-lite

空港向け天気サイネージ表示システムです。Raspberry Pi Zero W / Zero 2W / Pi 3 / Pi 4 に対応しています。

> 旧リポジトリ `raspi-weather` の機能はすべてこのリポジトリに統合済みです（`raspi-weather` は廃止・編集禁止）。開発・Pi のセットアップ／更新はこのリポジトリで行ってください。

![スクリーンショットイメージ](weather_icons/100.png)

## 概要

- JMA（気象庁）と Open-Meteo から天気データを取得し、HDMI ディスプレイにフルスクリーン表示
- 時間別天気に **日の出▲・日の入り▼マーク**、夜間（日の入り〜日の出）は**月アイコン**を表示（空港・季節ごとに自動計算）
- 今日の時間別天気（6〜翌9時）と1週間予報を表示
- 警報・注意報、作業注意情報（強風・豪雨・高温・凍結）をリアルタイム表示（発表から1日以上経った古い見出しは非表示）
- 警報欄の空きスペースに、気象庁の天気概況から**今日・明日の見通しを3行**で表示
- **熱中症リスク（WBGT）バッジ**をヘッダー右端に表示（環境省データを1時間ごとに取得）
- **熱中症警戒アラートバナー**：アラート発令時はヘッダー直下に赤帯を表示
- ブラウザから空港・WiFi を設定できる WiFi ポータル機能付き
- タイトルバーにWiFiポータルのQRコードを常時表示

## 対応空港

| キー | 空港名 |
|------|--------|
| `narita` | 成田国際空港 |
| `haneda` | 羽田空港 |
| `centrair` | 中部国際空港（デフォルト）|
| `kanku` | 関西国際空港 |
| `chitose` | 新千歳空港 |
| `fukuoka` | 福岡空港 |
| `naha` | 那覇空港 |

## 動作環境

- **ハードウェア**: Raspberry Pi Zero W / Zero 2W / Pi 3 / Pi 4
- **OS**: Raspberry Pi OS **Lite** 32-bit（**Bookworm / Trixie** 対応。Bullseye 以前は非対応。デスクトップ版は非推奨）
- **Python**: 3.11+
- **ディスプレイ**: HDMI接続（解像度不問、フルスクリーン表示）

## 設置環境の前提

設置先には次の設備がある前提とします。

| 設置先の設備 | 用途 | Pi 側で用意するもの |
|------|------|------|
| **有線 LAN（DHCP）** | 登録 WiFi が無いときの接続手段。WiFi 設定までの足がかり | USB-LAN アダプタ（Realtek RTL8152/8153 または ASIX チップ）＋ micro USB OTG 変換（Pi Zero の「USB」側端子に挿す） |
| **WiFi（DHCP）** | 通常の接続手段（登録済みなら自動接続・有線より優先） | **2.4GHz**・**WPA2 パスワード方式**であること（5GHz・ID が必要な WPA2-Enterprise・Web ログイン型は不可） |
| **HDMI 入力のディスプレイ** | 天気表示 | mini HDMI → HDMI ケーブル（または変換アダプタ）。DSI・USB 映像入力のディスプレイは使えない |
| **USB 電源** | Pi の電源 | **5V・2.5A 以上**（LAN アダプタにも Pi から給電するため） |

WiFi 設定用の USB ドングル・スマホのテザリングは、**有線 LAN が無い場所向けの予備手段**です。

### 現場での設置の流れ

1. LAN ケーブル・HDMI・電源をつなぐ → 有線 LAN で天気が表示される（左上に「有線LAN接続」）
   - その現場の WiFi を登録済みなら、WiFi で接続されラベルは出ない
2. 画面の QR コード（「今日の天気」欄の右端）を、同じ LAN の WiFi につないだスマホで読み取る
3. WiFi ポータル（「有線LANで接続中」と表示）で現場の WiFi を選び、パスワードを入力して「保存して再起動」
4. 再起動後は WiFi で接続（ラベルが消える）。LAN ケーブルはつないだままでも外しても可

> WiFi につながらないときは「トラブルシューティング → 現地で WiFi につながらない」を参照。

## セットアップ

### 1コマンドで完了

OS を書き込んだ Pi に SSH 接続し、以下を実行するだけです。

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/redeye147/raspi-weather-lite/main/setup.sh)
```

空港を選択すると、パッケージインストール・クローン・自動起動・WiFiポータル登録まですべて自動で行います。最後に再起動すると天気画面が表示されます。

### 更新（セットアップ済みの Pi）

```bash
bash ~/raspi-weather-lite/update.sh
```

依存パッケージ確認 → `git pull` → systemd サービス更新 → watchdog 確認 まで行い、最後に再起動するか聞かれます（`y` で再起動）。
更新後は画面右下のバージョン表示（コミット日時）で反映を確認できます。

`config.json`（Pi ごとの空港設定）は `update.sh` が更新の前後で退避・復元するので、ポータルで空港を変えていても更新で消えたり衝突したりしません。

### OS書き込み時の準備（Raspberry Pi Imager）

Imager の「詳細設定」で以下を事前設定しておくと SSH で接続できます。

| 項目 | 設定値 |
|------|--------|
| ユーザー名 | `pi` |
| WiFi | SSID・パスワード |
| SSH | 有効（パスワード認証） |
| OS | Raspberry Pi OS **Lite** (32-bit) |

### 手動セットアップ（参考）

#### 依存パッケージ

```bash
sudo apt update
sudo apt install -y \
  python3-pygame python3-requests python3-psutil \
  python3-flask python3-pip \
  python3-pil python3-qrcode python3-pytz \
  fonts-ipafont \
  network-manager git

# apt に無い astral だけ pip で入れる（Trixie / Python 3.13 でのソースビルド失敗を避けるため）
# main01.service は root で動くので必ず sudo でシステム全体に入れる
sudo pip3 install "astral>=2.0" --prefer-binary --break-system-packages
```

#### リポジトリのクローン

```bash
git clone https://github.com/redeye147/raspi-weather-lite.git /home/pi/raspi-weather-lite
```

#### 設定ファイル

`config.json` で空港と更新間隔を指定します（WiFiポータルからも変更可能）。

```json
{
  "airport": "centrair",
  "interval_hours": 2.0
}
```

#### 自動起動設定（X不要・kmsdrm直接描画）

```bash
# コンソール自動ログイン
sudo raspi-config nonint do_boot_behaviour B2

# videoグループに追加（kmsdrm描画に必要）
sudo usermod -a -G video,render pi
```

天気画面は systemd の `main01.service`（root で `start.sh` → `main01.py`）で起動します。

```bash
chmod +x /home/pi/raspi-weather-lite/start.sh
sudo cp /home/pi/raspi-weather-lite/main01.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now main01
```

> ⚠️ `~/.profile` などから `main01.py` を起動する旧方式と併用しないでください（二重起動で画面の取り合い・CPU 過負荷になります）。`setup.sh` / `update.sh` は旧方式の起動行を自動でコメントアウトします。

#### WiFiポータル（systemd）

```bash
sudo cp /home/pi/raspi-weather-lite/wifi-portal.service /etc/systemd/system/
sudo systemctl enable wifi-portal
sudo systemctl start wifi-portal

echo 'pi ALL=(ALL) NOPASSWD: /sbin/reboot' | sudo tee /etc/sudoers.d/pi-reboot
```

---

## Pi Zero W + Debian Trixie 向け追加設定

Debian Trixie（Python 3.13 / pygame 2.6.1 / SDL 2.32.4 / Mesa 25.x）環境では、
`vc4-kms-v3d` と SDL の EGL 実装が非互換のため、以下の追加設定が必要です。

### 必要パッケージの追加インストール

```bash
sudo apt install -y libegl-mesa0 libegl1 libgl1-mesa-dri fonts-ipafont
sudo pip3 install astral --break-system-packages
```

### `/boot/firmware/config.txt` の変更

`vc4-kms-v3d` を `vc4-fkms-v3d` に変更します（EGL/KMS 互換性のため）。

```bash
sudo sed -i 's/vc4-kms-v3d/vc4-fkms-v3d/' /boot/firmware/config.txt
```

### `/boot/firmware/cmdline.txt` への追記

起動時のコンソールカーソル点滅を非表示にします（1行の末尾に追加）。

```
vt.global_cursor_default=0
```

### systemd サービス設定

`/etc/systemd/system/main01.service` を作成・配置します。

```bash
sudo cp /home/pi/raspi-weather-lite/main01.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable main01.service
sudo systemctl start main01.service
```

`main01.service` の内容（`User=root` と SDL 環境変数が必要）：

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
ExecStartPre=/bin/sh -c 'printf "\033[?25l" > /dev/tty1'
ExecStart=/usr/bin/python3 /home/pi/raspi-weather-lite/main01.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> **Note**: `User=root` は DRM デバイスへのアクセス権確保のために必要です。
> `vc4-fkms-v3d` + `libegl-mesa0` の組み合わせで SDL kmsdrm が正常に動作します。

---

## 使い方

### 天気画面

起動後、自動的にフルスクリーンで天気が表示されます。

- **ヘッダー左**: 日付・時刻・日の出／日の入り時刻・空港名
- **ヘッダー右**: WBGTバッジ（熱中症リスクレベルをカラー表示）
- **アラートバナー**: 熱中症警戒アラート発令時はヘッダー直下に赤帯を表示
- **作業注意情報**: 強風 / 豪雨 / 高温 / 凍結の警告
- **今日の天気表**: 時間別の天気・降水量・気温・風速
  - 時刻行に日の出▲・日の入り▼マーク、夜間の列は月アイコン
  - タイトルバー右端にQRコード（WiFiポータルURL）
  - タイトルバー右に天気更新時刻 / IPアドレス末尾 / CPU使用率
- **下部**: 1週間予報 + 警報・注意報（空きスペースに今日・明日の天気概況を3行）
- **右下**: git バージョン情報（コミットハッシュ・日時）

通信エラー時はキャッシュデータを表示し、画面上部に赤いエラーバナーを表示します。

---

### 警報・注意報 / 天気概況

気象庁の警報・注意報データ（`bosai/warning`）と天気概況（`bosai/forecast/overview_forecast`）を1時間ごとに取得し、空港所在の市区町村で**発表・継続中**のものを右下の枠に表示します。

| 表示 | 色 | 条件 |
|------|----|------|
| 大雨特別警報 など | **赤** | 特別警報・警報が1つ以上 |
| 濃霧注意報 など | **オレンジ** | 注意報のみ |
| 発表なし | 黒 | 発表中のものがない（解除済みは除外） |
| 取得失敗（通信エラー） | 灰 | 気象庁への接続に失敗 |

- 複数ある場合は **特別警報 → 警報 → 注意報** の順に ` / ` 区切りで表示
- 警報・注意報の発表中のみ、気象庁の見出し文を最大2行表示（発表から1日以上経った見出しは非表示）

#### 天気概況（3行表示）

枠の残りスペースに、気象庁の天気概況（府県単位の解説文。成田なら千葉県）から **今日・明日の見通しだけ** を最大3行で表示します。

- 冒頭の現況説明（「千葉県は、高気圧に覆われて晴れています」など）と地方全体の解説は省き、「２７日は、…」「２８日は、…」で始まる段落だけを使用
- 3行を超える分は末尾を「…」で省略。文字は警報より小さい灰色で、区切り線の下に表示
- 表示の優先順位は **① 警報・注意報（全部表示）→ ② 見出し文（発表中のみ2行）→ ③ 天気概況（3行）**。警報が多い日は天気概況が短くなるか非表示
- 行数は `weather_draw.py` の `OVERVIEW_MAX_LINES`（既定 `3`）で変更可能
- 天気概況は予報更新（毎日5・11・17時頃）のデータで、枠下の「予報更新」時刻がその発表時刻です。取得済みデータを使うため通信は増えません

表示例：

```
==　警報・注意報　==
濃霧注意報
千葉県では、２７日朝まで濃い霧による視程障害に注意してください。
────────────────────────────
【天気概況】２７日は、高気圧に覆われて晴れ
ますが、気圧の谷や湿った空気の影響により、
夕方から曇りとなるでしょう。２８日は、気…
予報更新：2026-09-27 05:00
```
- 気象庁 JSON はコードのみを返すため、`jma_alerts.py` の `WARNING_CODES` でコード→名称に変換します（特別警報・警報・注意報の全約30種）。表にないコードは「警報コードNN」と表示し、コード体系の変更に気付けるようにしています

| 空港 | 監視する市区町村（コード） |
|------|------|
| 成田 | 成田市（1221100） |
| 羽田 | 大田区（1311100） |
| 中部 | 常滑市（2321600） |
| 関西 | 泉佐野市（2721300） |
| 新千歳 | 千歳市（0122400） |
| 福岡 | 福岡市（4013000） |
| 那覇 | 那覇市（4720100） |

---

### 気温の色分け

#### 時間別天気（今日の天気表）

| 文字色 | 条件 |
|--------|------|
| **紫** | 34℃以上（猛暑日） |
| **赤** | 30〜33℃（真夏日） |
| 黒 | 6〜29℃（通常） |
| **水色** | 0〜5℃（低温注意） |
| **濃い青** | 0℃未満（氷点下） |

#### 週間予報（最高気温）

| 文字色 | 条件 |
|--------|------|
| **紫** | 34℃以上（猛暑日） |
| **赤** | 30〜33℃（真夏日） |
| **オレンジ** | 28〜29℃（高温注意） |
| 黒 | 27℃以下（通常） |

---

### 風速の色分け

| 文字色 | 条件 |
|--------|------|
| **赤**（太字） | 15 m/s 以上（強風） |
| **紫**（太字） | 10〜14 m/s |
| **青**（太字） | 5〜9 m/s |
| 黒 | 5 m/s 未満 |

---

### 降水量の色分け

| 文字色 | 条件 |
|--------|------|
| **青**（太字） | 3 mm/h 以上 |
| 黒 | 3 mm/h 未満 |

---

### 高温時の天気アイコン切替

快晴（コード `100`）の時間帯で気温が高い場合、通常の晴れアイコンから自動的に専用アイコンへ切り替わります。

| アイコン | コード | 切替条件 |
|:--------:|--------|----------|
| ![晴れ（通常）](weather_icons/100.png) | `100` | 気温 30℃未満（通常の晴れ） |
| ![晴れ（真夏日）](weather_icons/1000.png) | `1000` | 気温 **30℃以上**（真夏日） |
| ![晴れ（猛暑日）](weather_icons/1000A.png) | `1000A` | 気温 **34℃以上**（猛暑日） |

> アイコン切替は「快晴（コード100）」の時間帯のみ適用されます。曇りや雨など他の天気コードは切替対象外です。

### 夜間の月アイコン

時間別天気で、各列の時刻が **日の入り以降〜日の出前** のとき、晴れ系アイコン（`1xx`）を月アイコン（`7xx` = `1xx` + 600）に切り替えます。
日の出・日の入りは選択中の空港の緯度経度で日付ごとに計算するため、季節と空港に合わせて自動で変わります。

| 例 | 月アイコンになる列 |
|----|----|
| 中部・夏至 | 21・00・03 |
| 中部・秋分〜冬 | 18・21・00・03（冬至頃は 06 も） |
| 那覇・秋〜冬 | 06・21・00・03（冬至頃は 18 も） |

| 昼 | 夜 | 例 |
|----|----|----|
| `100` 晴れ | `700` | ![700](weather_icons/700.png) |
| `101` 晴れ時々曇り | `701` | ![701](weather_icons/701.png) |
| `102`〜`181` | `702`〜`781` | |

曇り（`2xx`）・雨（`3xx`）・雪（`4xx`）は昼夜共通です。週間予報は対象外です。

### 日の出・日の入りマーク

時間別天気の「時刻」行に、日の出を **▲（オレンジ）**、日の入りを **▼（紺）** で実際の時刻の位置に表示します（時刻を小さく併記）。

| 表示 | 三角マーク | 併記時刻 |
|------|-----------|----------|
| 日の出 ▲ | 明るいオレンジ `(230, 120, 0)` | 濃いオレンジ・太字 `(185, 75, 0)`（白背景でのコントラスト比 5.2） |
| 日の入り ▼ | 紺 `(40, 40, 140)` | 紺・太字 |

色は `weather_draw.py` の `SUNRISE_COLOR` / `SUNRISE_TEXT_COLOR` / `SUNSET_COLOR` で変更できます。

```
時刻 │ 06 │ 09 │ 12 │ 15   17:28▼│ 18 │ 21 │ 00 │ 03   05:30▲│ 06 │ 09
```

- 各列の左端をその列の時刻とみなし、列の間を比例配分した位置に描画（例：17:28 は 15時列の右寄り＝18時の少し手前）
- 月アイコンと同じ日の出・日の入り計算（選択空港の緯度経度・日付ごと）を使うため、マークと月アイコンの切替位置は一致
- 表の範囲外（例：夏の日の出 04:30 は先頭の 06時より前）は表示しない。翌日の日の出も表示
- 時刻の数字と重なる場合はマークを少し右へ寄せ、併記時刻は空いている側に置く（置けなければ省略）
- 空港ごとの例（9/27）：新千歳 ▼17:22、成田 ▼17:28、中部 ▼17:42、福岡 ▼18:08、那覇 ▼18:20（福岡・那覇は 18時列の中に表示され、18時列は太陽のまま）
- 計算は日付・座標ごとにキャッシュするため CPU 負荷はほぼ増えない

---

### WBGTバッジ

環境省「熱中症予防情報サイト」の WBGT 予測値を1時間ごとに取得し、ヘッダー右端にバッジ表示します。

| WBGT | レベル | バッジ色 |
|------|--------|----------|
| 33℃以上 | **危険** | 紫 |
| 31〜33℃ | 厳重警戒 | 赤 |
| 28〜31℃ | 警戒 | オレンジ |
| 25〜28℃ | 注意 | 黄 |
| 25℃未満 | 表示なし | — |

熱中症警戒アラート発令時はヘッダー直下に赤帯バナーを追加表示します。

#### テスト用オプション

```bash
# WBGT値を指定してバッジ表示をテスト
sudo SDL_VIDEODRIVER=kmsdrm python3 main01.py --wbgt-test 35

# アラートバナーも強制表示
sudo SDL_VIDEODRIVER=kmsdrm python3 main01.py --wbgt-test 35 --wbgt-alert
```

### WiFiポータル

Raspberry Pi と同じネットワークに接続したスマホ・PCのブラウザから設定できます。

```
http://<PiのIPアドレス>:8080
```

QRコードをスキャンすると直接アクセスできます。

- **空港変更**: ドロップダウンから選択して「保存して再起動」
- **WiFi変更**: SSIDをスキャン一覧から選択してパスワードを入力

### WiFi 設定モード（オフライン時の AP 起動）

WiFi 未設定の Pi に **USB WiFi ドングル** を挿しておくと、起動時に WiFi 接続できなかった場合のみ
ドングル（`wlan1`）を AP にして、スマホから直接設定できる**キャプティブポータル**を起動します。

詳しくは [`wifi_setup/README.md`](wifi_setup/README.md) を参照。

```bash
cd /home/pi/raspi-weather-lite/wifi_setup
chmod +x install.sh
./install.sh
```

- AP SSID: `WeatherSetup` / PW: `setup1234`
- ポータル URL: `http://192.168.50.1/`（接続後ブラウザが自動で開く）
- ハードウェア例: 10Gtek WD-1513B (RTL8710BU, VID:PID `0bda:b711`)

### 有線 LAN で使う（USB-LAN アダプタ）

Pi Zero W / Zero 2 W には LAN 端子が無いため、**USB-LAN アダプタ＋ micro USB OTG 変換**（または LAN 付き拡張ボード）で有線接続できます。
**Realtek RTL8152/8153** または **ASIX** チップのものはドライバ不要で、Pi Zero の「USB」側の端子に挿せば NetworkManager が DHCP で自動接続します。

| 状況 | 動作 |
|------|------|
| 登録済み WiFi がある | WiFi に接続（有線も同時につながっていても **WiFi 優先**。有線の経路優先度を下げる設定を `setup.sh` / `update.sh` が配置） |
| 登録 WiFi が無く、有線 LAN が DHCP でつながった | **有線 LAN で天気を表示**。左上に「有線LAN接続」ラベル。設定モード（AP）には入らない |
| どちらも無い | 「LANケーブル または USBドングルを接続してください」画面（テザリング登録済みならテザリング案内） |

有線でつながったら、画面の QR コードをスマホ（同じ LAN の WiFi に接続）で読み取り、WiFi ポータルで現場の WiFi を設定できます（ポータルには「有線LANで接続中」と表示）。
WiFi 設定後は再起動で WiFi に切り替わり、ラベルが消えます。LAN ケーブルは外して構いません。

### 未登録の WiFi 環境で使う（スマホのテザリングで設定）

ドングルが無くても、**設定用のスマホテザリング**を全台に登録しておけば、現場でスマホのテザリングをオンにするだけで Pi がつながり、現場の WiFi を設定できます。

**事前準備（各 Pi で1回）**

```bash
bash ~/raspi-weather-lite/wifi_setup/add_setup_hotspot.sh <テザリングのSSID>
# パスワードは入力を求められる（リポジトリやコマンド履歴に残さないため）
```

`setup-hotspot` という名前・優先度 -10 で登録されるため、登録済みの現場 WiFi がある場所ではそちらが優先されます。
登録後は `export_wifi.sh` の書き出しにも含まれるので、他の Pi へは「WiFi プロファイルの引き継ぎ」の手順でも配れます。

**現場での手順**

1. スマホのテザリングを **登録した SSID・パスワード**、**2.4GHz**、**WPA2-Personal** でオンにする
   （iPhone は「設定 → 一般 → 情報 → 名前」が SSID になる。「互換性を優先」をオン）
2. Pi の電源を入れる（起動済みでも可。WiFi が見つからない間は画面にテザリング名が表示される）
3. Pi がテザリングにつながると **「スマホのテザリングで仮接続しました」画面が30秒**表示される（手順と大きな QR コード付き）。その後、天気画面の**左上に「仮接続中」**ラベルが付いた状態になる
4. テザリング中のスマホで QR コード（案内画面、または「今日の天気」欄の右端）を読み取り、WiFi ポータルで現場の WiFi を選んでパスワードを入力し保存 → Pi が再起動して現場の WiFi につながる
5. 左上の「仮接続中」が消えたら、テザリングをオフにする

> テザリング接続かどうかは、NetworkManager の使用中の接続名が `setup-hotspot` かで判定（起動時と 30 秒ごとの WiFi チェック時）。動作中にテザリングへ切り替わった場合も案内画面を表示します。

> ⚠️ テザリングの SSID・パスワードは公開リポジトリに書かないでください（`add_setup_hotspot.sh` は実行時に入力します）。
> WiFi が切り替わって IP が変わると、画面の QR コードは自動で新しい URL に更新されます。

### WiFi プロファイルの引き継ぎ（複数台セットアップ）

設定済みの Pi に保存されている WiFi（SSID・パスワード）を、別の Pi にまとめてコピーできます。

```bash
# ① 設定済みの Pi で書き出す
bash ~/raspi-weather-lite/wifi_setup/export_wifi.sh

# ② 新しい Pi で取得して取り込む（<設定済みPiのIP> は Mac で `ping -c 1 raspi-weather.local` などで確認）
mkdir -p ~/raspi-weather-lite/wifi_setup/profiles
scp 'pi@<設定済みPiのIP>:~/raspi-weather-lite/wifi_setup/profiles/*.nmconnection' ~/raspi-weather-lite/wifi_setup/profiles/
bash ~/raspi-weather-lite/wifi_setup/install.sh
```

- `install.sh` の出力に「追加: 〜」と出れば取り込み完了。同じ名前のプロファイルが既にある場合はスキップ（上書きしない）
- `nmcli connection show` で登録済み WiFi を確認できます

> ⚠️ `wifi_setup/profiles/` には WiFi パスワードが平文で含まれます。このリポジトリは**公開**なので `.gitignore` で除外済みです。絶対にコミットしないでください。

## ファイル構成

```
raspi-weather-lite/
├── setup.sh             # 1コマンドセットアップスクリプト
├── update.sh            # 更新スクリプト（git pull・サービス更新・watchdog）
├── start.sh             # 表示モード自動判定して main01.py を起動
├── main01.py            # メインループ（起動・描画制御）
├── fb_display.py        # 描画モード自動判定（kmsdrm → /dev/fb0 フォールバック）
├── main01.service       # systemdユニットファイル
├── weather_draw.py      # 天気画面描画・アラートバナー
├── header.py            # ヘッダー描画（日付・時刻・WBGTバッジ）
├── fetch_weather.py     # 天気データ取得（Open-Meteo / JMA）
├── fetch_wbgt.py        # WBGT取得（環境省）・WBGT_LEVELS定義
├── jma_alerts.py        # JMA警報・注意報取得
├── utils.py             # 共通ユーティリティ（フォントキャッシュ・QR生成など）
├── config.py            # 空港設定・定数
├── config.json          # 実行時設定（空港・更新間隔）※Pi ごとに書き換わる。変更をコミットしない
├── wifi_portal.py       # WiFi設定ポータル（Flask）
├── wifi-portal.service  # systemdユニットファイル
├── wifi_setup/          # WiFi 設定モード（AP + キャプティブポータル）
│   ├── install.sh       #   導入スクリプト（profiles/ があれば WiFi も取り込み）
│   ├── export_wifi.sh   #   保存済み WiFi を profiles/ に書き出し（別 Pi への引き継ぎ用）
│   ├── add_setup_hotspot.sh # 設定用スマホテザリングを登録（未登録 WiFi 環境での設定用）
│   └── nm-wired-lower-priority.conf # 有線 LAN の経路優先度を WiFi より下げる設定
└── weather_icons/       # 天気アイコン画像
```

## Pi Zero W 向け最適化

シングルコア 1GHz / 512MB RAM の制約に対応するため以下の最適化を実施しています。

| 最適化 | 内容 |
|--------|------|
| フォントキャッシュ | `get_font(path, size, bold)` でキャッシュ、毎フレームの `Font()` 生成を廃止 |
| アイコンキャッシュ | `(path, w, h)` キーでスケール済みサーフェスをキャッシュ |
| dirty flag 描画 | 分替わり・データ更新時だけ再描画（10秒スリープ）。CPU 表示は測定のみで再描画のきっかけにしない（次の分替わりで反映）|
| 時計の分替わり同期 | スリープは最大10秒だが、分替わりをまたぐときは次の :00 直後に起きて再描画。時計表示の遅れは最大約12秒 → 描画時間分（1〜2秒）のみ。描画回数は変わらないため CPU 負荷はほぼ不変 |
| 朝6時の定時取得 | 時間別の表は 6 時で「今日の 6 時〜」に切り替わるため、6:00 に天気を取り直す（23:50 の定時取得と同じ仕組み）。夜間は取得を先送りするため、これが無いと次の取得が 7:50 頃になり、それまで前日の列が残っていた。失敗時は 30 分後に再試行 |
| 起動の高速化（スナップショット） | 取得が成功するたびに表示データ一式と状態（取得時刻・表の開始日）を `cache/snapshot.json` に保存。起動時は時刻同期を最大3秒確認し、同期済みなら**同じ空港・2時間以内・同じ日の表**のとき前回データで即表示（取得も省略）。未同期（再起動直後に多い）なら前回データでまず表示し、裏ですぐ取り直して差し替える。警報・WBGT は1時間以内なら前回値、古ければ起動20秒後に取得 |
| 軽量スプラッシュ | fb0 モードではフェード（計38回の全面描画）を省略し、取得待ち中の再描画を5秒に1回に（取得スレッドに CPU を譲る） |
| 起動時間の記録 | `journalctl -u main01 -b \| grep "\[boot\]"` で起動からの経過秒数（main01 開始／描画初期化／時刻同期／スナップショット判定／スプラッシュ／天気画面表示）を確認できる |
| 日の出計算 | 日付変更時のみ再計算 |
| スクロール廃止 | 作業サマリーを静的テキスト表示に変更 |
| 点滅廃止 | WBGT 危険バッジは紫固定。常時10秒スリープ |
| 起動経路の一本化 | 天気画面は systemd の `main01.service` だけで起動。`~/.profile` からの旧起動は `setup.sh` / `update.sh` が自動で無効化（二重起動による画面の取り合い・fb0 フォールバックを防止）|
| 再起動ループ防止 | `main01.service` は `RestartSec=30`、10分で5回失敗したら再起動を停止（`StartLimitBurst=5`）。起動失敗が続いても CPU を食い潰さない |
| 依存ライブラリ | astral 等は root の python3 から import できるようシステム全体に導入（`update.sh` が root で確認）|

通常運用時のCPU使用率は 20% 以下が目安です（画面右上の CPU 表示や `top` で確認）。

#### CPU 過負荷対策の経緯（2026-09）

Pi Zero W で CPU が常時 50〜80% になっていた事例の調査結果です。

| 項目 | 内容 |
|------|------|
| 症状 | `top` の合計 CPU は約 63% だが、プロセス一覧の合計は約 7% しかない |
| 原因 | `main01.service`（root）が `No module named 'astral'` で起動失敗→10秒後に再起動を無限に繰り返し、1回あたり約7秒の CPU を消費（短命プロセスのため `top` に出ない）。astral が pi のユーザー領域にしか入っておらず root から見えなかった。実際の表示は `~/.profile` から pi で起動した別インスタンスが担っていた |
| 対策 | astral をシステム全体に導入 / 起動経路を systemd に一本化 / 再起動ループに上限 / CPU 表示更新だけでの全面再描画を廃止（10秒毎→分替わり毎） |
| 実測結果 | 下表 |
| 追加で見つかった原因 | 旧リポジトリの `raspi-weather.service`（pi で main01.py を起動）と `~/.profile` の `startx` が残り、二重起動・X11 モード（1024×768）になっていた → `update.sh` で自動無効化 |

実測結果（`top` 60秒平均の us+sy。いずれも 1920×1080・fb0 モード）：

| 機種 | 対策前 | 対策後 | 主な効果 |
|------|--------|--------|----------|
| Pi Zero W（1コア ARMv6） | 63%（load 1.0） | **5.5%**（load 0.06） | 再起動ループ・二重起動の解消 ＋ 再描画 1/6 |
| Pi Zero 2 W（4コア ARMv8） | 約2% | **0.6%**（load 0.00〜0.07） | 再描画 1/6（fb0 変換回数の削減） |

> 同じ画面・描画方式でも Zero W と Zero 2 W で約10倍の差があるのは CPU 性能差（1コア→4コア、世代差）と、Zero 2 W の使用率が4コア平均で表示されるため。画面の物理サイズ（インチ）は負荷に関係せず、解像度（画素数）が効きます。

調べ方は「トラブルシューティング → CPU 使用率が高い」を参照。

## トラブルシューティング

### `update.sh` が `divergent branches` で止まる

Pi 上に GitHub に無いコミットや変更がある状態です。`config.json` と実行権限の差分は `update.sh` が自動で処理するため、通常は起きません（`update.sh` / `setup.sh` は `git config core.fileMode false` を設定し、`chmod +x start.sh` などの実行権限の違いを変更扱いしないようにしています）。
それでも止まる場合は、Pi 固有の `config.json`（空港設定）を退避してから GitHub に合わせます。

```bash
cd ~/raspi-weather-lite
git log --oneline origin/main..HEAD      # Pi だけにあるコミットを確認
mkdir -p ~/pi-backup && cp config.json ~/pi-backup/
git branch backup-before-sync            # 念のため今の状態を保存
git reset --hard origin/main
cp ~/pi-backup/config.json config.json
bash update.sh
```

### `sudo apt autoremove` で pytz が消える

`python3-pytz` / `python3-tz` が「不要」と表示されることがありますが、天気表示に必要です。先に手動インストール扱いにしておいてください。

```bash
sudo apt-mark manual python3-pytz python3-tz
```

### 警報・注意報が表示されない

気象庁が実際に何を発表しているか、Pi 上で直接確認できます（成田の例。他空港は URL の `120000` と市区町村コードを置き換え）。

```bash
cd ~/raspi-weather-lite && python3 -c "
import requests; from jma_alerts import active_warning_names
d=requests.get('https://www.jma.go.jp/bosai/warning/data/warning/120000.json',timeout=10).json()
for at in d['areaTypes']:
    for a in at['areas']:
        if a['code'] in ('1221100','120010'): print(a['code'], a['warnings'])
print('表示:', active_warning_names(d, ('1221100',)))"
```

`表示:` の内容が画面右下に出ます。`[]` なら発表なし。

> 2026-09 以前の版はコード表が気象庁とずれており（雷・大雨注意報・洪水注意報・濃霧などが未登録）、警報・注意報が常に「発表なし」になっていました。`update.sh` で最新版に更新してください。

### CPU 使用率が高い（50% 以上）

Pi Zero W で常時 50% を超える場合、`main01.service` が起動失敗→再起動を繰り返している可能性があります（`top` に出ない短命プロセスとして CPU を消費）。

```bash
journalctl -u main01 -b --no-pager | tail -15      # エラー内容を確認
systemctl status main01 --no-pager | grep Active   # "since …; 8s ago" のように毎回新しいなら再起動ループ
```

- `ModuleNotFoundError: No module named 'astral'` → astral が pi ユーザーにしか入っていない（root から見えない）。`bash ~/raspi-weather-lite/update.sh` で自動修正されます（手動なら `sudo pip3 install "astral>=2.0" --break-system-packages`）
- `ps -eo user,args | grep main01.py` で **pi と root の2つ**が見える → 旧方式との二重起動。`update.sh` で以下を自動で無効化し一本化します
  - `~/.profile` 等からの `main01.py` 起動行
  - 旧リポジトリ `raspi-weather` の `raspi-weather.service`（pi で起動）
  - `~/.profile` / `~/.bash_profile` の `startx`（X サーバーが画面を掴むと kmsdrm で直接描画できず、`mode=x11` の低解像度表示になる）
  - どこから起動しているかは `systemctl status <pi側のPID>` で確認できます
- 修正後は再起動してください。確認方法：

```bash
top -b -n 2 -d 10 | awk '/^top -/{n++} n==2' | head -4   # %Cpu(s) の us+sy が 20% 前後なら OK
ps -eo user,args | grep [m]ain01.py                        # root の1行だけなら一本化 OK
vcgencmd get_throttled                                     # 0x0 以外なら電源不足でクロック低下
```

> 旧版の `update.sh` は更新中も古い手順のまま動くため、最初の1回は `cd ~/raspi-weather-lite && git pull --ff-only && bash update.sh` で実行すると確実です。

### 起動後もコンソール画面のまま（天気が出ない）

起動直後は HDMI の画面出力（`/dev/dri`・`/dev/fb0`）の準備が main01 より遅れることがあります。main01 は装置が現れるまで最大90秒待ち、それでも無ければ5秒後にやり直します。
ずっと出ない場合は HDMI ケーブル・ディスプレイの電源・入力切替を確認し、`sudo systemctl restart main01` を試してください。
`journalctl -u main01 -b --no-pager | grep display` で「画面出力の装置がまだ無い → 待機」が続いていれば、HDMI が認識されていません。

### 現地で WiFi につながらない

パスワード間違い以外に、次の原因がよくあります。

| 原因 | 対処 |
|------|------|
| 5GHz しか無い（Buffalo なら SSID に「-A-」） | 2.4GHz の SSID（Buffalo なら「-G-」）を選ぶ |
| ID とパスワードが必要（WPA2-Enterprise） | 非対応。有線 LAN を使う |
| Web ログイン・同意が必要（ゲスト WiFi 等） | 非対応。有線 LAN を使う |
| 登録機器しか使えない（MAC アドレス制限） | 管理者に Pi の登録を依頼 |
| 国設定が JP でない（12・13ch が使えない） | `iw reg get` で `country JP` を確認 |

持ち帰ってから原因を調べるには：

```bash
journalctl -u NetworkManager --since "-2 days" --no-pager | grep -iE "reason|secrets|ssid-not-found|auth" | tail -20
```

`no-secrets` / `secrets required` ならパスワード違い、`ssid-not-found` なら SSID が見えていない（5GHz・電波が届かない）。

### `update.sh: command not found`

`bash ~/raspi-weather-lite/update.sh` のように `bash` を付けて実行してください。

## データソース

- **Open-Meteo**: 時間別気象データ（気温・降水量・風速）[無料・APIキー不要]
- **気象庁（JMA）**: 天気予報・週間予報・警報注意報 [無料]
- **環境省 WBGT**: 熱中症予防情報（WBGT予測値・警戒アラート）[無料]

## ライセンス

MIT
