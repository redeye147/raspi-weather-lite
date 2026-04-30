# raspi-weather-lite

Raspberry Pi Zero W 向けに最適化した空港向け天気サイネージ表示システムです。

![スクリーンショットイメージ](weather_icons/100.png)

## 概要

- JMA（気象庁）と Open-Meteo から天気データを取得し、HDMI ディスプレイにフルスクリーン表示
- 今日の時間別天気（6〜翌9時）と1週間予報を表示
- 警報・注意報、作業注意情報（強風・豪雨・高温・凍結）をリアルタイム表示
- ブラウザから空港・WiFi を設定できる WiFi ポータル機能付き
- タイトルバーにWiFiポータルのQRコードを常時表示

## 対応空港

| キー | 空港名 |
|------|--------|
| `narita` | 成田国際空港 |
| `haneda` | 羽田空港 |
| `centrair` | 中部国際空港（デフォルト）|
| `kanku` | 関西国際空港 |

## 動作環境

- **ハードウェア**: Raspberry Pi Zero W
- **OS**: Raspberry Pi OS Lite 32-bit（Bullseye / Bookworm）
- **Python**: 3.11+
- **ディスプレイ**: HDMI接続（解像度不問、フルスクリーン表示）

## セットアップ

### 1. 依存パッケージのインストール

```bash
sudo apt update
sudo apt install -y \
  python3-pygame python3-requests python3-psutil \
  python3-flask python3-pip \
  fonts-ipafont \
  xorg xinit x11-xserver-utils xdotool \
  network-manager

pip3 install "astral>=2.0" qrcode --break-system-packages
```

### 2. リポジトリのクローン

```bash
git clone https://github.com/redeye147/raspi-weather-lite.git
cd raspi-weather-lite
```

### 3. 設定ファイル

`config.json` で空港と更新間隔を指定します（WiFiポータルからも変更可能）。

```json
{
  "airport": "centrair",
  "interval_hours": 2.0
}
```

### 4. 自動起動設定（startx）

SSHではなくHDMIコンソールから自動的に天気画面を起動するため、`~/.profile` に以下を追記します。

```bash
# ~/.profile
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  startx
fi
```

`~/.xinitrc` を作成します。

```bash
#!/bin/bash
xset s off
xset -dpms
xset s noblank
exec python3 /home/pi/raspi-weather-lite/main01.py
```

raspi-config でコンソール自動ログインを有効にしておきます。

```bash
sudo raspi-config
# System Options → Boot / Auto Login → Console Autologin
```

### 5. WiFiポータル（systemd）

```bash
sudo cp wifi-portal.service /etc/systemd/system/
sudo systemctl enable wifi-portal
sudo systemctl start wifi-portal
```

`sudo reboot` なしで `reboot` を実行できるように権限を付与します。

```bash
echo 'pi ALL=(ALL) NOPASSWD: /sbin/reboot' | sudo tee /etc/sudoers.d/pi-reboot
```

## 使い方

### 天気画面

起動後、自動的にフルスクリーンで天気が表示されます。

- **上部**: 日付・時刻・日の出／日の入り時刻・空港名
- **中部**: 作業注意情報（強風 / 豪雨 / 高温 / 凍結）
- **今日の天気表**: 時間別の天気・降水量・気温・風速
  - タイトルバー右端にQRコード（WiFiポータルURL）
  - タイトルバー右に天気更新時刻 / IPアドレス末尾 / CPU使用率
- **下部**: 1週間予報 + 警報・注意報

通信エラー時はキャッシュデータを表示し、画面上部に赤いエラーバナーを表示します。

### WiFiポータル

Raspberry Pi と同じネットワークに接続したスマホ・PCのブラウザから設定できます。

```
http://<PiのIPアドレス>:8080
```

QRコードをスキャンすると直接アクセスできます。

- **空港変更**: ドロップダウンから選択して「保存して再起動」
- **WiFi変更**: SSIDをスキャン一覧から選択してパスワードを入力

## ファイル構成

```
raspi-weather-lite/
├── main01.py            # メインループ（起動・描画制御）
├── weather_draw.py      # 天気画面描画
├── header.py            # ヘッダー描画（日付・時刻・日の出）
├── fetch_weather.py     # 天気データ取得（Open-Meteo / JMA）
├── jma_alerts.py        # JMA警報・注意報取得
├── utils.py             # 共通ユーティリティ（フォントキャッシュ・QR生成など）
├── config.py            # 空港設定・定数
├── config.json          # 実行時設定（空港・更新間隔）
├── wifi_portal.py       # WiFi設定ポータル（Flask）
├── wifi-portal.service  # systemdユニットファイル
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

通常運用時のCPU使用率は 15〜20% 程度です。

## データソース

- **Open-Meteo**: 時間別気象データ（気温・降水量・風速）[無料・APIキー不要]
- **気象庁（JMA）**: 天気予報・週間予報・警報注意報 [無料]

## ライセンス

MIT
