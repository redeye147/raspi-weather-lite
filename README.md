# raspi-weather-lite

空港向け天気サイネージ表示システムです。Raspberry Pi Zero W / Zero 2W / Pi 3 / Pi 4 に対応しています。

![スクリーンショットイメージ](weather_icons/100.png)

## 概要

- JMA（気象庁）と Open-Meteo から天気データを取得し、HDMI ディスプレイにフルスクリーン表示
- 今日の時間別天気（6〜翌9時）と1週間予報を表示
- 警報・注意報、作業注意情報（強風・豪雨・高温・凍結）をリアルタイム表示
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
- **OS**: Raspberry Pi OS Lite 32-bit（Bookworm 推奨）
- **Python**: 3.11+
- **ディスプレイ**: HDMI接続（解像度不問、フルスクリーン表示）

## セットアップ

### 1コマンドで完了

OS を書き込んだ Pi に SSH 接続し、以下を実行するだけです。

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/redeye147/raspi-weather-lite/main/setup.sh)
```

空港を選択すると、パッケージインストール・クローン・自動起動・WiFiポータル登録まですべて自動で行います。最後に再起動すると天気画面が表示されます。

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
  fonts-ipafont \
  network-manager git

pip3 install "astral>=2.0" qrcode pillow pytz --break-system-packages
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

`~/.profile` に追記します。

```bash
if [ "$(tty)" = "/dev/tty1" ]; then
    export SDL_VIDEODRIVER=kmsdrm
    exec python3 /home/pi/raspi-weather-lite/main01.py
fi
```

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
  - タイトルバー右端にQRコード（WiFiポータルURL）
  - タイトルバー右に天気更新時刻 / IPアドレス末尾 / CPU使用率
- **下部**: 1週間予報 + 警報・注意報
- **右下**: git バージョン情報（コミットハッシュ・日時）

通信エラー時はキャッシュデータを表示し、画面上部に赤いエラーバナーを表示します。

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

---

### WBGTバッジ

環境省「熱中症予防情報サイト」の WBGT 予測値を1時間ごとに取得し、ヘッダー右端にバッジ表示します。

| WBGT | レベル | バッジ色 |
|------|--------|----------|
| 33℃以上 | **危険**（1秒点滅） | 紫 |
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

## ファイル構成

```
raspi-weather-lite/
├── setup.sh             # 1コマンドセットアップスクリプト
├── main01.py            # メインループ（起動・描画制御）
├── main01.service       # systemdユニットファイル
├── weather_draw.py      # 天気画面描画・アラートバナー
├── header.py            # ヘッダー描画（日付・時刻・WBGTバッジ）
├── fetch_weather.py     # 天気データ取得（Open-Meteo / JMA）
├── fetch_wbgt.py        # WBGT取得（環境省）・WBGT_LEVELS定義
├── jma_alerts.py        # JMA警報・注意報取得
├── utils.py             # 共通ユーティリティ（フォントキャッシュ・QR生成など）
├── config.py            # 空港設定・定数
├── config.json          # 実行時設定（空港・更新間隔）
├── wifi_portal.py       # WiFi設定ポータル（Flask）
├── wifi-portal.service  # systemdユニットファイル
├── wifi_setup/          # WiFi 設定モード（AP + キャプティブポータル）
└── weather_icons/       # 天気アイコン画像
```

## Pi Zero W 向け最適化

シングルコア 1GHz / 512MB RAM の制約に対応するため以下の最適化を実施しています。

| 最適化 | 内容 |
|--------|------|
| フォントキャッシュ | `get_font(path, size, bold)` でキャッシュ、毎フレームの `Font()` 生成を廃止 |
| アイコンキャッシュ | `(path, w, h)` キーでスケール済みサーフェスをキャッシュ |
| dirty flag 描画 | 分・CPU・天気更新があった時だけ再描画（10秒スリープ）|
| 日の出計算 | 日付変更時のみ再計算 |
| スクロール廃止 | 作業サマリーを静的テキスト表示に変更 |
| 点滅最適化 | 危険レベル時のみ1秒ループ、それ以外は10秒スリープ |

通常運用時のCPU使用率は 15〜20% 程度です。

## データソース

- **Open-Meteo**: 時間別気象データ（気温・降水量・風速）[無料・APIキー不要]
- **気象庁（JMA）**: 天気予報・週間予報・警報注意報 [無料]
- **環境省 WBGT**: 熱中症予防情報（WBGT予測値・警戒アラート）[無料]

## ライセンス

MIT
