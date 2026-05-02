"""
wifi_portal.py
スマホ・PCブラウザから空港設定・WiFi設定ができる Web UI（Flask）
ポート: 8080
"""

from flask import Flask, request, jsonify, redirect, make_response
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


def _no_cache(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ==========================================
# WiFi スキャン（wlan0 指定、APモード中でも動作）
# ==========================================
def _scan_ssids() -> list:
    """wlan0 でWiFiスキャンを実行してSSIDリストを返す。"""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list", "ifname", "wlan0"],
            capture_output=True, text=True, timeout=10
        )
        return list(dict.fromkeys(
            s.strip() for s in result.stdout.strip().splitlines() if s.strip()
        ))
    except Exception:
        return []


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
  h3 { color: #aaddff; margin-top: 24px; margin-bottom: 4px; font-size: 16px; }
  label { font-size: 13px; color: #aaa; }
  #msg { margin-top: 16px; color: #10b981; font-weight: bold; }
  #manual-ssid { display: none; }
  .badge-connected { font-size: 13px; color: #10b981; margin-bottom: 4px; }
  .badge-disconnected { font-size: 13px; color: #ef4444; margin-bottom: 4px; }
  .section-box { background: #1e2233; border-radius: 10px; padding: 14px; margin-top: 12px; }
  .scanning { font-size: 13px; color: #888; }
</style>
</head><body>
<h2>天気サイネージ 設定</h2>
<p id="connected-badge"></p>

<div class="section-box">
  <h3>✈ 空港（天気表示場所）</h3>
  <select id="airport">
    <option value="narita">成田国際空港</option>
    <option value="haneda">羽田空港</option>
    <option value="centrair">中部国際空港</option>
    <option value="kanku">関西国際空港</option>
  </select>
</div>

<div class="section-box">
  <h3>📶 WiFi 設定</h3>
  <label>SSID</label>
  <p id="scan-status" class="scanning">🔄 スキャン中...</p>
  <select id="ssid-select" onchange="onSelectChange()" style="display:none">
  </select>
  <input id="manual-ssid" placeholder="SSIDを手入力">
  <label>パスワード</label>
  <input id="pw" type="password" placeholder="パスワード（未入力の場合はWiFiは変更しません）">
</div>

<button id="save-btn" onclick="save()">保存して再起動</button>
<p id="msg"></p>

<script>
let currentSsid = '';

async function init() {
  try {
    const st = await fetch('/status').then(r => r.json());
    currentSsid = st.ssid || '';
    const badge = document.getElementById('connected-badge');
    if (st.connected) {
      badge.className = 'badge-connected';
      badge.textContent = '現在のWiFi: ' + st.ssid;
    } else {
      badge.className = 'badge-disconnected';
      badge.textContent = 'WiFi未接続 — 以下からWiFiを設定してください';
    }
    if (st.airport) {
      document.getElementById('airport').value = st.airport;
    }
  } catch(e) {
    document.getElementById('msg').textContent = '接続エラー: ' + e;
  }
  loadSSIDs();
}

async function loadSSIDs() {
  const status = document.getElementById('scan-status');
  const sel    = document.getElementById('ssid-select');
  status.textContent = '🔄 スキャン中...';
  try {
    const ssids = await fetch('/scan').then(r => r.json());
    sel.innerHTML = '';
    if (ssids.length === 0 && !currentSsid) {
      status.textContent = '⚠️ SSIDが見つかりません。手入力を選択してください。';
      const manual = document.createElement('option');
      manual.value = '__manual__'; manual.textContent = '手入力';
      sel.appendChild(manual);
    } else {
      status.textContent = '';
      if (currentSsid) {
        const cur = document.createElement('option');
        cur.value = currentSsid;
        cur.textContent = currentSsid + ' (現在接続中)';
        sel.appendChild(cur);
      }
      ssids.filter(s => s !== currentSsid).forEach(ssid => {
        const opt = document.createElement('option');
        opt.value = ssid; opt.textContent = ssid;
        sel.appendChild(opt);
      });
      const manual = document.createElement('option');
      manual.value = '__manual__'; manual.textContent = '手入力（リストにない場合）';
      sel.appendChild(manual);
    }
    sel.style.display = 'block';
  } catch(e) {
    status.textContent = 'スキャン失敗。手入力で入力してください。';
    document.getElementById('manual-ssid').style.display = 'block';
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

async function save() {
  const airport = document.getElementById('airport').value;
  const ssid    = getSSID();
  const pw      = document.getElementById('pw').value.trim();
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.textContent = '保官中...';
  try {
    if (ssid && pw) {
      const res = await fetch('/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ ssid, pw, airport })
      });
      document.getElementById('msg').textContent = await res.text();
    } else {
      const res = await fetch('/save-airport', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ airport })
      });
      document.getElementById('msg').textContent = await res.text();
    }
  } catch(e) {
    document.getElementById('msg').textContent = 'エラー: ' + e;
    btn.disabled = false;
    btn.textContent = '保官して再起動';
  }
}

init();
</script>
</body></html>"""


# ==========================================
# キャプティブポータル自動検出（Android / iOS / Windows）
# ==========================================
@app.route("/generate_204")
@app.route("/gen_204")
@app.route("/hotspot-detect.html")
@app.route("/connecttest.txt")
@app.route("/ncsi.txt")
@app.route("/success.txt")
def captive_portal_redirect():
    return redirect("/", 302)


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
    subprocess.run(
        ["nmcli", "dev", "wifi", "connect", ssid, "password", pw]
    )
    subprocess.Popen(["bash", "-c", "sleep 3 && sudo reboot"])
    return "設定完了！Piが再起動します。しばらくお待ちください..."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
