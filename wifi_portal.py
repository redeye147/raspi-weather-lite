"""
wifi_portal.py
スマホ・ PCブラウザから空港設定・WiFi設定ができる Web UI（Flask）
ポート: 8080
"""

from flask import Flask, request, jsonify, redirect, make_response, session
import hmac
import secrets
import time
from functools import wraps
import json
import os
import subprocess

app = Flask(__name__)
# セッション鍵は起動ごとに作り直す（再起動するとパスワードの入力し直しになる）
app.secret_key = secrets.token_bytes(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                  PERMANENT_SESSION_LIFETIME=1800)

DEFAULT_ADMIN_PASSWORD = "1048"
_login_fail = {"count": 0, "until": 0.0}

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


def _admin_password() -> str:
    """WiFi 設定のパスワード。config.json の admin_password（無ければ初期値 1048）"""
    return str(_load_config().get("admin_password") or DEFAULT_ADMIN_PASSWORD)


def admin_required(f):
    """WiFi の設定・削除・並べ替え・スキャンはパスワード入力済みのセッションだけ許可"""
    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("admin"):
            return "パスワードを入力してください", 401
        return f(*a, **k)
    return wrapper


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
# 登録済み WiFi（NetworkManager の接続プロファイル）
# ==========================================
SETUP_HOTSPOT_CON = "setup-hotspot"


def _split_terse(line: str) -> list:
    """nmcli -t の1行を ':' で分割（値の中の '\:' はエスケープされた ':'）"""
    out, cur, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur += line[i + 1]; i += 2; continue
        if c == ":":
            out.append(cur); cur = ""
        else:
            cur += c
        i += 1
    out.append(cur)
    return out


def _saved_wifi() -> list:
    """登録済み WiFi の一覧（設定用テザリングは最後、ほかは優先度の高い順）"""
    r = subprocess.run(["nmcli", "-t", "-f", "UUID,TYPE,NAME,AUTOCONNECT-PRIORITY,ACTIVE", "connection", "show"],
                       capture_output=True, text=True, timeout=10)
    items = []
    for line in r.stdout.splitlines():
        f = _split_terse(line)
        if len(f) < 5 or f[1] != "802-11-wireless":
            continue
        uuid, _, name, prio, active = f[:5]
        try:
            ssid = subprocess.run(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", uuid],
                                  capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            ssid = ""
        items.append({
            "uuid": uuid, "name": name, "ssid": ssid or name,
            "priority": int(prio) if prio.lstrip("-").isdigit() else 0,
            "active": active == "yes",
            "hotspot": name == SETUP_HOTSPOT_CON,
        })
    items.sort(key=lambda x: (x["hotspot"], -x["priority"], x["ssid"].lower()))
    return items


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
  button.sub-btn { background: #374151; }
  h2 { color: #FFD700; }
  h3 { color: #aaddff; margin-top: 24px; margin-bottom: 4px; font-size: 16px; }
  label { font-size: 13px; color: #aaa; }
  .msg { margin-top: 12px; font-weight: bold; }
  #manual-ssid { display: none; }
  .badge-connected { font-size: 13px; color: #10b981; margin-bottom: 4px; }
  .badge-disconnected { font-size: 13px; color: #ef4444; margin-bottom: 4px; }
  .section-box { background: #1e2233; border-radius: 10px; padding: 14px; margin-top: 12px; }
  .section-box input, .section-box select { background: #2a3048; }
  .scanning { font-size: 13px; color: #888; }
  .hidden { display: none !important; }
  .wifi-row { display: flex; align-items: center; gap: 6px; padding: 8px 0; border-bottom: 1px solid #2c3350; }
  .wifi-row .nm { flex: 1; min-width: 0; font-size: 15px; overflow-wrap: anywhere; }
  .wifi-row .sub { font-size: 12px; color: #888; }
  .wifi-row button { flex: none; width: auto; margin: 0; padding: 8px 12px; font-size: 14px; }
  .wifi-row button.del { background: #b91c1c; }
  .wifi-row button:disabled { background: #444; color: #888; }
  .tag { font-size: 11px; padding: 2px 6px; border-radius: 6px; margin-left: 4px; }
  .tag-on { background: #065f46; color: #a7f3d0; }
  .tag-hs { background: #7c2d12; color: #fed7aa; }
  #confirm-bg { position: fixed; inset: 0; background: rgba(0,0,0,.65); display: flex;
                align-items: center; justify-content: center; padding: 20px; }
  #confirm-box { background: #1e2233; border: 2px solid #b91c1c; border-radius: 12px; padding: 18px; max-width: 360px; width: 100%; }
  #confirm-box .row { display: flex; gap: 10px; }
  #confirm-box .row button { flex: 1; }
  #confirm-ok { background: #b91c1c; }
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
    <option value="chitose">新千歳空港</option>
    <option value="fukuoka">福岡空港</option>
    <option value="naha">那覇空港</option>
  </select>
  <button id="airport-btn" onclick="saveAirport()">空港を保存して再起動</button>
  <p id="airport-msg" class="msg"></p>
</div>

<button id="wifi-open-btn" class="sub-btn" onclick="openWifi()">🔒 WiFi 設定（パスワードが必要）</button>
<button class="sub-btn" onclick="location.href='/diag'">🩺 診断（本体の状態を見る・パスワードが必要）</button>

<div id="login-box" class="section-box hidden">
  <h3>🔒 管理パスワード</h3>
  <input id="admin-pw" type="password" inputmode="numeric" placeholder="パスワード" onkeydown="if(event.key==='Enter')login()">
  <button onclick="login()">開く</button>
  <p id="login-msg" class="msg"></p>
</div>

<div id="wifi-area" class="hidden">
  <div class="section-box">
    <h3>📶 WiFi 設定</h3>
    <label>SSID</label>
    <p id="scan-status" class="scanning">🔄 スキャン中...</p>
    <select id="ssid-select" onchange="onSelectChange()" style="display:none"></select>
    <input id="manual-ssid" placeholder="SSIDを手入力">
    <label>パスワード</label>
    <input id="pw" type="password" placeholder="WiFi のパスワード">
    <button id="save-btn" onclick="saveWifi()">WiFi を保存して再起動</button>
    <p id="msg" class="msg"></p>
  </div>

  <div class="section-box">
    <h3>📋 登録済み WiFi（上ほど優先して接続）</h3>
    <p class="scanning">▲▼で優先順を変更、削除で登録を消去（接続中の WiFi は削除できません）。
    パスワードを間違えて登録した WiFi は、削除してから上の「WiFi 設定」で登録し直してください。</p>
    <div id="saved-list"><p class="scanning">読み込み中...</p></div>
    <p id="saved-msg" class="msg"></p>
  </div>
</div>

<div id="confirm-bg" class="hidden">
  <div id="confirm-box">
    <p id="confirm-text" style="font-size:16px;line-height:1.6;white-space:pre-line"></p>
    <div class="row">
      <button class="sub-btn" onclick="closeConfirm(false)">キャンセル</button>
      <button id="confirm-ok" onclick="closeConfirm(true)">削除する</button>
    </div>
  </div>
</div>

<script>
let currentSsid = '';
let saved = [];
let confirmResolve = null;

function esc(t) {
  return String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function setMsg(id, text, ok) {
  const m = document.getElementById(id);
  m.textContent = text; m.style.color = ok ? '#10b981' : '#ef4444';
}
async function post(url, body) {
  const res = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                credentials: 'same-origin', body: JSON.stringify(body)});
  return {ok: res.ok, status: res.status, text: await res.text()};
}

async function init() {
  try {
    const st = await fetch('/status').then(r => r.json());
    currentSsid = st.ssid || '';
    const badge = document.getElementById('connected-badge');
    if (st.connected) {
      badge.className = 'badge-connected';
      badge.textContent = '現在のWiFi: ' + st.ssid;
    } else if (st.wired) {
      badge.className = 'badge-connected';
      badge.textContent = '有線LANで接続中';
    } else {
      badge.className = 'badge-disconnected';
      badge.textContent = 'WiFi未接続';
    }
    if (st.airport) document.getElementById('airport').value = st.airport;
    if (st.admin) showWifi();
  } catch(e) {
    setMsg('airport-msg', '接続エラー: ' + e, false);
  }
}

async function saveAirport() {
  const btn = document.getElementById('airport-btn');
  btn.disabled = true; btn.textContent = '保存中...';
  try {
    const r = await post('/save-airport', {airport: document.getElementById('airport').value});
    setMsg('airport-msg', r.text, r.ok);
    if (!r.ok) { btn.disabled = false; btn.textContent = '空港を保存して再起動'; }
  } catch(e) {
    setMsg('airport-msg', 'エラー: ' + e, false);
    btn.disabled = false; btn.textContent = '空港を保存して再起動';
  }
}

function openWifi() {
  document.getElementById('wifi-open-btn').classList.add('hidden');
  document.getElementById('login-box').classList.remove('hidden');
  document.getElementById('admin-pw').focus();
}

async function login() {
  const r = await post('/login', {password: document.getElementById('admin-pw').value});
  if (r.ok) { showWifi(); } else { setMsg('login-msg', r.text, false); }
}

function showWifi() {
  document.getElementById('wifi-open-btn').classList.add('hidden');
  document.getElementById('login-box').classList.add('hidden');
  document.getElementById('wifi-area').classList.remove('hidden');
  loadSSIDs();
  loadSaved();
}

async function loadSSIDs() {
  const status = document.getElementById('scan-status');
  const sel    = document.getElementById('ssid-select');
  status.textContent = '🔄 スキャン中...';
  try {
    const ssids = await fetch('/scan', {credentials: 'same-origin'}).then(r => r.json());
    sel.innerHTML = '';
    status.textContent = ssids.length || currentSsid ? '' : '⚠️ SSIDが見つかりません。手入力を選択してください。';
    if (currentSsid) {
      const cur = document.createElement('option');
      cur.value = currentSsid; cur.textContent = currentSsid + ' (現在接続中)';
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
    sel.style.display = 'block';
    onSelectChange();
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
  return sel.value === '__manual__' ? document.getElementById('manual-ssid').value : sel.value;
}

async function saveWifi() {
  const ssid = getSSID().trim();
  const pw   = document.getElementById('pw').value.trim();
  if (!ssid || !pw) { setMsg('msg', 'SSID とパスワードを入力してください', false); return; }
  const btn = document.getElementById('save-btn');
  btn.disabled = true; btn.textContent = '保存中...';
  try {
    const r = await post('/save', {ssid, pw, airport: document.getElementById('airport').value});
    setMsg('msg', r.text, r.ok);
    if (!r.ok) { btn.disabled = false; btn.textContent = 'WiFi を保存して再起動'; }
  } catch(e) {
    setMsg('msg', 'エラー: ' + e, false);
    btn.disabled = false; btn.textContent = 'WiFi を保存して再起動';
  }
}

async function loadSaved() {
  const box = document.getElementById('saved-list');
  try {
    const res = await fetch('/wifi/list', {credentials: 'same-origin'});
    if (!res.ok) { box.innerHTML = '<p class="scanning">パスワードの有効期限切れです。再読み込みしてください</p>'; return; }
    saved = await res.json();
  } catch(e) {
    box.innerHTML = '<p class="scanning">読み込み失敗</p>'; return;
  }
  const normal = saved.filter(w => !w.hotspot);
  box.innerHTML = '';
  if (saved.length === 0) { box.innerHTML = '<p class="scanning">登録なし</p>'; return; }
  saved.forEach(w => {
    const i = normal.indexOf(w);
    const row = document.createElement('div');
    row.className = 'wifi-row';
    row.innerHTML =
      '<div class="nm">' + esc(w.ssid) +
      (w.active ? '<span class="tag tag-on">接続中</span>' : '') +
      (w.hotspot ? '<span class="tag tag-hs">設定用テザリング</span>' : '') +
      (w.name !== w.ssid ? '<div class="sub">登録名: ' + esc(w.name) + '</div>' : '') + '</div>';
    const up = document.createElement('button'); up.textContent = '▲';
    const dn = document.createElement('button'); dn.textContent = '▼';
    const del = document.createElement('button'); del.textContent = '削除'; del.className = 'del';
    up.disabled = w.hotspot || i <= 0;
    dn.disabled = w.hotspot || i < 0 || i >= normal.length - 1;
    del.disabled = w.active;
    up.onclick = () => move(i, -1);
    dn.onclick = () => move(i, +1);
    del.onclick = () => removeWifi(w);
    row.append(up, dn, del);
    box.appendChild(row);
  });
}

async function move(i, d) {
  const normal = saved.filter(w => !w.hotspot);
  const j = i + d;
  if (j < 0 || j >= normal.length) return;
  [normal[i], normal[j]] = [normal[j], normal[i]];
  const r = await post('/wifi/order', {uuids: normal.map(w => w.uuid)});
  setMsg('saved-msg', r.text, r.ok);
  loadSaved();
}

// ブラウザ標準の confirm() は QR 読取アプリ内ブラウザ等で表示されないことがあるため、画面内の確認表示を使う
function askConfirm(text) {
  document.getElementById('confirm-text').textContent = text;
  document.getElementById('confirm-bg').classList.remove('hidden');
  return new Promise(resolve => { confirmResolve = resolve; });
}
function closeConfirm(ok) {
  document.getElementById('confirm-bg').classList.add('hidden');
  if (confirmResolve) { confirmResolve(ok); confirmResolve = null; }
}

async function removeWifi(w) {
  const ok = await askConfirm('「' + w.ssid + '」の登録を削除します。\\nこの WiFi には自動でつながらなくなります。本当に削除しますか？');
  if (!ok) { setMsg('saved-msg', '削除を取り消しました', true); return; }
  const r = await post('/wifi/delete', {uuid: w.uuid});
  setMsg('saved-msg', r.text, r.ok);
  loadSaved();
}

init();
</script>
</body></html>"""


DIAG_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>天気サイネージ 診断</title>
<style>
  body { font-family: sans-serif; padding: 16px; background: #1a1a2e; color: white; margin: 0; }
  h2 { color: #FFD700; margin: 4px 0 2px; }
  .sub { font-size: 13px; color: #aaa; }
  input { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: none;
          background: #2a3048; color: white; font-size: 16px; box-sizing: border-box; }
  button { width: 100%; padding: 12px; background: #3b82f6; color: white; border: none;
           border-radius: 8px; font-size: 16px; margin-top: 8px; cursor: pointer; }
  button.sub-btn { background: #374151; }
  .box { background: #1e2233; border-radius: 10px; padding: 12px; margin-top: 12px; }
  .hidden { display: none !important; }
  .overall { font-size: 20px; font-weight: bold; padding: 12px; border-radius: 10px; margin-top: 12px; }
  .ov-ok { background: #065f46; } .ov-warn { background: #854d0e; } .ov-bad { background: #991b1b; }
  .row { display: flex; gap: 8px; padding: 9px 0; border-bottom: 1px solid #2c3350; align-items: flex-start; }
  .row:last-child { border-bottom: none; }
  .dot { flex: none; width: 14px; height: 14px; border-radius: 50%; margin-top: 3px; }
  .ok .dot { background: #10b981; } .info .dot { background: #64748b; }
  .warn .dot { background: #f59e0b; } .bad .dot { background: #ef4444; }
  .nm { flex: none; width: 7.5em; font-size: 14px; color: #cbd5e1; }
  .val { flex: 1; min-width: 0; font-size: 14px; overflow-wrap: anywhere; }
  .det { font-size: 12px; color: #fbbf24; margin-top: 2px; }
  .bad .det { color: #fca5a5; }
  .ok .det, .info .det { color: #94a3b8; }
  .code { font-size: 11px; color: #94a3b8; }
  .log { font-family: monospace; font-size: 11px; color: #cbd5e1; white-space: pre-wrap;
         overflow-wrap: anywhere; border-bottom: 1px solid #2c3350; padding: 4px 0; }
  .msg { color: #ef4444; font-weight: bold; }
</style>
</head><body>
<h2>🩺 天気サイネージ 診断</h2>
<div class="sub" id="head">見るだけのページです（設定は変わりません）</div>

<div id="login-box" class="box hidden">
  <div>🔒 管理パスワード</div>
  <input id="admin-pw" type="password" inputmode="numeric" placeholder="パスワード" onkeydown="if(event.key==='Enter')login()">
  <button onclick="login()">開く</button>
  <p id="login-msg" class="msg"></p>
</div>

<div id="area" class="hidden">
  <div id="overall" class="overall"></div>
  <div class="box" id="items"></div>
  <div class="box"><div class="sub">直近の警告・エラー（新しい順・最大10件）</div><div id="problems"></div></div>
  <div class="sub" id="foot" style="margin-top:10px"></div>
  <button onclick="load()">🔄 再診断</button>
</div>
<button class="sub-btn" onclick="location.href='/'">← 設定画面に戻る</button>

<script>
function esc(t) {
  return String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
async function login() {
  const res = await fetch('/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
              credentials: 'same-origin', body: JSON.stringify({password: document.getElementById('admin-pw').value})});
  if (res.ok) { load(); } else { document.getElementById('login-msg').textContent = await res.text(); }
}
async function load() {
  const res = await fetch('/diag/data', {credentials: 'same-origin'});
  if (res.status === 401) {
    document.getElementById('login-box').classList.remove('hidden');
    document.getElementById('area').classList.add('hidden');
    return;
  }
  document.getElementById('login-box').classList.add('hidden');
  document.getElementById('area').classList.remove('hidden');
  document.getElementById('overall').textContent = '診断中...';
  const d = await res.json();
  const ov = document.getElementById('overall');
  const label = {ok: '🟢 正常', warn: '🟡 注意あり', bad: '🔴 異常あり'}[d.overall];
  ov.className = 'overall ov-' + d.overall;
  ov.textContent = label + (d.codes.length ? '　' + d.codes.join(' / ') : '');
  document.getElementById('head').textContent = d.airport + ' / ' + d.ip;
  document.getElementById('items').innerHTML = d.items.map(i =>
    '<div class="row ' + i.level + '"><div class="dot"></div><div class="nm">' + esc(i.name) +
    '<div class="code">' + esc(i.code) + '</div></div><div class="val">' + esc(i.value) +
    (i.detail ? '<div class="det">' + esc(i.detail) + '</div>' : '') + '</div></div>').join('');
  document.getElementById('problems').innerHTML = d.problems.length
    ? d.problems.map(l => '<div class="log">' + esc(l) + '</div>').join('')
    : '<div class="sub">なし</div>';
  document.getElementById('foot').textContent = '版: ' + d.version + '　診断: ' + d.checked_at;
}
load();
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
    try:
        dev = subprocess.run(["nmcli", "-t", "-f", "TYPE,STATE", "device"],
                             capture_output=True, text=True, timeout=5).stdout
        wired = any(l.startswith("ethernet:connected") for l in dev.splitlines())
    except Exception:
        wired = False
    cfg = _load_config()
    return _no_cache(jsonify({
        "connected": connected,
        "ssid": ssid,
        "wired": wired,
        "admin": bool(session.get("admin")),
        "airport": cfg.get("airport", "centrair")
    }))


@app.route("/diag")
def diag_page():
    return _no_cache(make_response(DIAG_HTML))


@app.route("/diag/data")
@admin_required
def diag_data():
    """診断結果（見るだけ）。ログの中身・IP などが含まれるのでパスワード入力済みのときだけ返す"""
    import diagnostics
    return _no_cache(jsonify(diagnostics.diagnose()))


@app.route("/login", methods=["POST"])
def login():
    now = time.time()
    if now < _login_fail["until"]:
        return f"失敗が続いたため {int(_login_fail['until'] - now)} 秒間ロック中です", 429
    pw = str((request.get_json(silent=True) or {}).get("password", ""))
    if hmac.compare_digest(pw.encode(), _admin_password().encode()):
        _login_fail["count"] = 0
        session.permanent = True
        session["admin"] = True
        return "OK"
    _login_fail["count"] += 1
    if _login_fail["count"] >= 5:   # 5 回失敗で 60 秒ロック（4 桁の総当たり対策）
        _login_fail["count"] = 0
        _login_fail["until"] = now + 60
        return "パスワードが違います（5回失敗したため60秒ロックします）", 403
    return "パスワードが違います", 403


@app.route("/scan")
@admin_required
def scan():
    return _no_cache(jsonify(_scan_ssids()))


@app.route("/wifi/list")
@admin_required
def wifi_list():
    try:
        return _no_cache(jsonify(_saved_wifi()))
    except Exception as e:
        app.logger.error(f"wifi list: {e}")
        return _no_cache(jsonify([]))


@app.route("/wifi/delete", methods=["POST"])
@admin_required
def wifi_delete():
    uuid = (request.get_json(silent=True) or {}).get("uuid", "")
    target = next((w for w in _saved_wifi() if w["uuid"] == uuid), None)
    if not target:
        return "対象の WiFi が見つかりません", 404
    if target["active"]:
        return "接続中の WiFi は削除できません（ネットワークが切れるため）", 400
    r = subprocess.run(["nmcli", "connection", "delete", "uuid", uuid], capture_output=True, text=True, timeout=15)
    app.logger.info(f"wifi delete {target['ssid']}: rc={r.returncode} {r.stderr.strip()}")
    if r.returncode != 0:
        return f"削除失敗: {r.stderr.strip() or r.stdout.strip()}", 500
    return f"「{target['ssid']}」を削除しました"


@app.route("/wifi/order", methods=["POST"])
@admin_required
def wifi_order():
    """登録済み WiFi（設定用テザリング以外）の優先度を、並び順どおりに 100, 90, 80 … と付け直す"""
    uuids = (request.get_json(silent=True) or {}).get("uuids", [])
    known = {w["uuid"] for w in _saved_wifi() if not w["hotspot"]}
    if not isinstance(uuids, list) or len(uuids) != len(set(uuids)) or set(uuids) != known:
        return "一覧が最新ではありません。画面を再読み込みしてください", 409
    for n, uuid in enumerate(uuids):
        prio = max(10, 100 - n * 10)
        subprocess.run(["nmcli", "connection", "modify", "uuid", uuid,
                        "connection.autoconnect-priority", str(prio)],
                       capture_output=True, text=True, timeout=15)
    return "優先順を保存しました（次に WiFi を探すときから有効）"


@app.route("/save-airport", methods=["POST"])
def save_airport():
    data = request.get_json()
    airport = data.get("airport", "centrair").strip()
    _save_config({"airport": airport})
    subprocess.Popen(["bash", "-c", "sleep 3 && reboot"])
    return "空港を変更しました。Piが再起動します。しばらくお待ちください..."


_reboot_scheduled = False


@app.route("/save", methods=["POST"])
@admin_required
def save():
    global _reboot_scheduled
    if _reboot_scheduled:
        return "再起動中です。しばらくお待ちください...", 200

    data = request.get_json()
    ssid    = data.get("ssid",    "").strip()
    pw      = data.get("pw",      "").strip()
    airport = data.get("airport", "centrair").strip()
    if not ssid:
        return "SSIDを入力してください", 400
    _save_config({"airport": airport})

    # すでに同じSSIDに接続済なら nmcli 再接続をスキップ
    try:
        current_ssid = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, timeout=3
        ).stdout.strip()
    except Exception:
        current_ssid = ""

    if current_ssid != ssid:
        result = subprocess.run(
            ["nmcli", "dev", "wifi", "connect", ssid, "password", pw],
            capture_output=True, text=True, timeout=30
        )
        app.logger.info(f"nmcli connect: rc={result.returncode} out={result.stdout.strip()} err={result.stderr.strip()}")
        if result.returncode != 0:
            return f"WiFi接続失敗: {result.stderr.strip() or result.stdout.strip()}", 500
    else:
        app.logger.info(f"Already connected to {ssid}, skipping nmcli reconnect")

    _reboot_scheduled = True
    subprocess.Popen(["bash", "-c", "sleep 5 && reboot"])
    return "設定完了！Piが再起動します。しばらくお待ちください..."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
