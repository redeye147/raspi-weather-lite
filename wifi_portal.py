""" 
wifi_portal.py
スマホ・PCブラウザから空港設定・WiFi設定ができる Web UI（Flask）
ポート: 8080
"""

from flask import Flask, request, jsonify, make_response
import json
import os
import subprocess

app = Flask(__name__)

CONFIG_PATH = "/home/pi/raspi-weather-lite/config.json"


# ==========================================
# config.json ヘルパー
# ==========================================
def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"airport": "centrair", "interval_hours": 2.0}


def _save_config(updates: dict) -> None:
    cfg = _load_config()
    cfg.update(updates)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ==========================================
# キャッシュ無効ヘルパー
# ==========================================
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


# ==========================================
# SSIDスキャン
# ==========================================
def _scan_ssids() -> list:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
            capture_output=True, text=True, timeout=10
        )
        ssids = list(dict.fromkeys(
            s.strip() for s in result.stdout.strip().splitlines() if s.strip()
        ))
        with open("/tmp/ssid_list.json", "w") as f:
            json.dump(ssids, f)
        return ssids
    except Exception:
        return []


_scan_ssids()


# ==========================================
# HTML
# ==========================================
HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>天気サイネージ 設定</title>
<style>
  body { font-family: sans-serif; padding: 20px; background: #1a1a2e; color: white; }
  select, input { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: none;
          background: #1e2233; color: white; font-size: 16px; box-sizing: border-box; }
  button { width: 100%; padding: 14px; background: #3b82f6; color: white;
           border: none; border-radius: 8px; font-size: 16px; margin-top: 8px; cursor: pointer; }
  button:active { background: #2563eb; }
  h2 { color: #FFD700; }
  label { font-size: 13px; color: #aaa; }
  #msg { margin-top: 16px; font-weight: bold; }
  #msg.ok  { color: #10b981; }
  #msg.err { color: #ef4444; }
  #manual-ssid { display: none; }
  #wifi-section { display: none; }
  #connected-badge { font-size: 14px; margin-bottom: 12px; }
</style>
</head><body>
<h2>天気サイネージ 設定</h2>
<p id="connected-badge"></p>

<label>空港（表示場所）</label>
<select id="airport">
  <option value="narita">成田国際空港</option>
  <option value="haneda">羽田空港</option>
  <option value="centrair">中部国際空港</option>
  <option value="kanku">関西国際空港</option>
</select>

<div id="wifi-section">
  <label>WiFi SSID</label>
  <select id="ssid-select" onchange="onSelectChange()">
    <option value="">— 読み込み中... —</option>
  </select>
  <input id="manual-ssid" placeholder="SSIDを手入力">
  <label>パスワード</label>
  <input id="pw" type="password" placeholder="パスワード">
</div>

<button id="save-btn" onclick="save()">保存して再起動</button>
<p id="msg"></p>

<script>
let wifiConnected = false;

async function init() {
  try {
    const st = await fetch('/status').then(r => r.json());
    wifiConnected = st.connected;
    const badge = document.getElementById('connected-badge');
    if (wifiConnected) {
      badge.style.color = '#10b981';
      badge.textContent = '接続中: ' + st.ssid;
      document.getElementById('wifi-section').style.display = 'none';
    } else {
      badge.style.color = '#ef4444';
      badge.textContent = 'WiFi未接続';
      document.getElementById('wifi-section').style.display = 'block';
      loadSSIDs();
    }
    if (st.airport) document.getElementById('airport').value = st.airport;
  } catch(e) {
    showMsg('接続エラー: ' + e, true);
  }
}

async function loadSSIDs() {
  try {
    const ssids = await fetch('/scan').then(r => r.json());
    const sel = document.getElementById('ssid-select');
    ssids.forEach(ssid => {
      const opt = document.createElement('option');
      opt.value = ssid; opt.textContent = ssid;
      sel.appendChild(opt);
    });
    const manual = document.createElement('option');
    manual.value = '__manual__';
    manual.textContent = '手入力（リストにない場合）';
    sel.appendChild(manual);
  } catch(e) {
    showMsg('スキャン失敗: ' + e, true);
  }
}

function onSelectChange() {
  const val = document.getElementById('ssid-select').value;
  document.getElementById('manual-ssid').style.display = val === '__manual__' ? 'block' : 'none';
}

function getSSID() {
  const sel = document.getElementById('ssid-select');
  return sel.value === '__manual__'
    ? document.getElementById('manual-ssid').value
    : sel.value;
}

function showMsg(text, isError) {
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = isError ? 'err' : 'ok';
}

async function save() {
  const airport = document.getElementById('airport').value;
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.textContent = '保存中...';
  try {
    let res;
    if (wifiConnected) {
      res = await fetch('/save-airport', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ airport })
      });
    } else {
      res = await fetch('/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ ssid: getSSID(), pw: document.getElementById('pw').value, airport })
      });
    }
    const text = await res.text();
    showMsg(text, !res.ok);
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = '保存して再起動';
    }
  } catch(e) {
    showMsg('エラー: ' + e, true);
    btn.disabled = false;
    btn.textContent = '保存して再起動';
  }
}

init();
</script>
</body></html>"""


# ==========================================
# API エンドポイント
# ==========================================
@app.route("/")
def index():
    return _no_cache(make_response(HTML))


@app.route("/status")
def status():
    try:
        result = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, timeout=3
        )
        ssid = result.stdout.strip()
        connected = bool(ssid)
    except Exception:
        ssid = ""
        connected = False
    cfg = _load_config()
    return _no_cache(jsonify({
        "connected": connected,
        "ssid": ssid,
        "airport": cfg.get("airport", "centrair")
    }))


@app.route("/scan")
def scan():
    return _no_cache(jsonify(_scan_ssids()))


@app.route("/save-airport", methods=["POST"])
def save_airport():
    data = request.get_json()
    airport = data.get("airport", "centrair").strip()
    _save_config({"airport": airport})
    subprocess.Popen(["bash", "-c", "sleep 3 && sudo reboot"])
    return "空港を変更しました。Piが再起動します。しばらくお待ちください..."


@app.route("/save", methods=["POST"])
def save():
    data = request.get_json()
    ssid    = data.get("ssid",    "").strip()
    pw      = data.get("pw",      "").strip()
    airport = data.get("airport", "centrair").strip()
    if not ssid:
        return "SSIDを入力してください", 400
    _save_config({"airport": airport})
    result = subprocess.run(
        ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", pw],
        capture_output=True, text=True, timeout=30
    )
    app.logger.info(f"nmcli connect: rc={result.returncode} out={result.stdout.strip()} err={result.stderr.strip()}")
    if result.returncode != 0:
        return f"WiFi接続失敗: {result.stderr.strip() or result.stdout.strip()}", 500
    subprocess.Popen(["bash", "-c", "sleep 5 && sudo reboot"])
    return "設定完了！Piが再起動します。しばらくお待ちください..."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
