# WiFi 設定モード（USB ドングル方式）

Pi Zero W / Pi Zero 2 の内蔵 WiFi（wlan0）を AP モードに切り替える方式は不安定なため、
**外付け USB WiFi ドングル（wlan1）を AP 専用に使う**構成です。
ドングルを挿すと自動で設定モードに入り、スマホから WiFi 設定できます。

## 動作概要

USBドングルは**常時挿しっぱなし**で運用。起動時のWi-Fi接続状態で
自動的に「天気表示」または「設定モード」のどちらかに分岐します。

```
[起動]
  ↓
[NetworkManager → wlan0が既知WiFiへ接続試行]
  ↓
[wifi-setup-auto.service が接続を待機（最大120秒）]
  ├ ステップ1: nm-online -t 60 でNetworkManager完了待ち
  ├ ステップ2: iwgetid + ip addr を2秒間隔で最大60秒ポーリング
  ├ Wi-Fi接続OK  → 何もしない（=天気表示へ進む）
  └ Wi-Fi接続NG  → systemctl start wifi-setup-mode
                     ↓
                   [start_ap.sh]
                     ├ wlan1 に 192.168.50.1/24
                     ├ hostapd 起動 (SSID: WeatherSetup, PW: setup1234)
                     ├ dnsmasq 起動 (DHCP + DNSキャプティブポータル)
                     ├ iptables: 80 → 8080 (Flask) リダイレクト
                     └ /run/wifi-setup/state にAP情報JSON出力
                     ↓
                   [Pi本体画面]    [スマホ]
                   ├ 大きなQR2枚 ─ ① WeatherSetupに自動接続
                   │              ─ ② ブラウザ自動起動 → http://192.168.50.1/
                     ↓
                   [Web UIで設定 → 再起動]
                     ↓
                   [起動時チェックでWiFi接続OK]
                     ↓
                   [天気表示へ復帰]
```

### USB抜去時の挙動

USBドングルを抜くと udev ルールにより、もし設定モード中なら停止します（安全装置）。
ただし通常運用では USB は挿しっぱなしのため発火しません。

## ハードウェア

- **USB WiFi ドングル**: 10Gtek WD-1513B（Realtek RTL8710BU, VID:PID = `0bda:b711`）
- 他のドングルを使う場合は `99-wifi-setup-usb.rules` の VID:PID を書き換える

## ファイル構成

| ファイル | 説明 |
|---|---|
| `start_ap.sh` | AP起動（hostapd + dnsmasq + iptables） |
| `stop_ap.sh` | AP停止 |
| `hostapd-setup.conf` | AP設定（SSID/PW/チャンネル） |
| `dnsmasq-setup.conf` | DHCP + DNS（キャプティブポータル用） |
| `check_wifi_on_boot.sh` | 起動時のWi-Fi接続待ち＆設定モード自動起動判定 |
| `wifi-setup-mode.service` | 設定モード本体（hostapd+dnsmasq起動の oneshot） |
| `wifi-setup-auto.service` | 起動時自動分岐（boot→ check_wifi_on_boot.sh） |
| `99-wifi-setup-usb.rules` | USB抜去時の安全停止用 udev ルール |
| `nm-unmanage-wlan1.conf` | NetworkManager に wlan1 を触らせない設定 |
| `install.sh` | 一括導入スクリプト |

## インストール

```bash
cd /home/pi/raspi-weather-lite/wifi_setup
chmod +x install.sh
./install.sh
```

## 動作確認

### 手動でAPモード起動
```bash
sudo systemctl start wifi-setup-mode
sudo systemctl status wifi-setup-mode
```

スマホで `WeatherSetup` (PW: `setup1234`) に接続。Android なら自動でキャプティブポータルが開く。
開かない場合は手動で `http://192.168.50.1/` にアクセス。

### 手動停止
```bash
sudo systemctl stop wifi-setup-mode
```

### 起動時の自動判定をテスト
通常運用は再起動 → `wifi-setup-auto` が最大120秒WiFi接続を待機して判定。
ログ確認：
```bash
journalctl -t wifi-setup-auto -n 20
journalctl -u wifi-setup-mode -f
```

期待ログ：
- WiFi接続成功時：
  ```
  Waiting for NetworkManager to come online (nm-online -t 60)...
  nm-online finished (rc=0)
  wlan0 connected: SSID='your-ssid' IP=192.168.x.x/24 (poll=0s)
  ```
- WiFi接続失敗時：`wlan0 not connected after ~120s total - entering setup mode`

## カスタマイズ

### AP の SSID／パスワード変更
`hostapd-setup.conf` の `ssid=` と `wpa_passphrase=` を編集。
**公共設置の場合**、起動毎にランダム生成するよう `start_ap.sh` を改造することを推奨。

### USB 機器を変更
`lsusb` で VID:PID を確認し、`99-wifi-setup-usb.rules` を更新：
```
sudo udevadm control --reload-rules
```

## トラブル時

| 症状 | 確認 |
|---|---|
| `wlan1` が出ない | `lsusb`、`dmesg \| tail` で USB 認識を確認 |
| AP に接続できない | `journalctl -t wifi-setup` で hostapd ログを確認 |
| 接続できるが IP 取れない | dnsmasq が動いているか `pgrep -a dnsmasq` |
| ブラウザが portal を開かない | `http://192.168.50.1/` を手動入力 |
| Web UI から接続できない | `wlan0` が NetworkManager 管理下か `nmcli device status` |

## 既知の制限

- **wlan0 が AP 中にスキャンする際、一瞬切断される**ことがある（同一無線チップ制約）
  → スキャン結果は `/tmp/ssid_list.json` にキャッシュし、portal 起動時のみスキャン
- 公共設置時は AP パスワードのランダム化を推奨（現状は固定 `setup1234`）

## raspi-weather-lite における連携状況

本ディレクトリは [raspi-weather](https://github.com/redeye147/raspi-weather)
本家から移植した独立した systemd サービス群です。
**AP モード自体は単独で完結して動作します**が、Web UI 側（`wifi_portal.py`）と
本体表示側（`main01.py`）との連携は本家版より簡略化されています。

| 項目 | 本家 raspi-weather | raspi-weather-lite |
|------|-------------------|--------------------|
| 起動時の AP 自動分岐 | ○ `wifi-setup-auto.service` | ○（移植済み） |
| ドングル挿抜の検知 | ○ udev | ○（移植済み） |
| `wifi_portal.py` の設定モード認識 | ○ `/run/wifi-setup/state` を見て UI 切替 | △ 未対応（通常 UI のまま動作） |
| `main01.py` の設定モード安全停止 | ○ 30秒毎チェック | △ 未対応 |
| Web UI のキャプティブポータル応答 | ○ Android/iOS 検知URL対応 | △ 未対応（直接URL入力で利用可） |

連携を強化する場合は、本家 `wifi_portal.py` の以下を移植することを検討：
- `in_setup_mode()` / `/run/wifi-setup/state` の参照
- `/generate_204`, `/hotspot-detect.html` などキャプティブ検知ルート
- `errorhandler(404)` での `redirect("/")`
