"""
wifi_portal.py
スマホ・ PCブラウザから空港設定・WiFi設定ができる Web UI（Flask）
ポート: 8080
"""

from flask import Flask, request, jsonify, redirect, make_response, session, send_file
import hmac
import secrets
import time
from functools import wraps
import json
import os
import subprocess

import safe_write

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
def _hostname() -> str:
    """Pi の名前（例 raspi2w）。子機は「名前.local」で探せる（mDNS。IP アドレスが変わってもつながる）"""
    import socket
    try:
        return socket.gethostname().split(".")[0]
    except OSError:
        return ""


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"airport": "centrair", "interval_hours": 1.0}


def _save_config(updates: dict) -> None:
    cfg = _load_config()
    cfg.update(updates)
    safe_write.write_json(CONFIG_PATH, cfg, indent=2)    # 電源が突然切れても設定が消えないように


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
    r"""nmcli -t の1行を ':' で分割（値の中の '\:' はエスケープされた ':'）"""
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
    <option value="narita">成田空港</option>
    <option value="haneda">羽田空港</option>
    <option value="centrair">中部空港</option>
    <option value="kanku">関西空港</option>
    <option value="chitose">新千歳空港</option>
    <option value="fukuoka">福岡空港</option>
    <option value="naha">那覇空港</option>
  </select>
  <button id="airport-btn" onclick="saveAirport()">空港を保存して再起動</button>
  <p id="airport-msg" class="msg"></p>
</div>

<div class="section-box">
  <h3>📋 今日の天気の表の形</h3>
  <select id="layout">
    <option value="fixed">今まで（朝6時〜翌朝9時。今の時間帯の列を観測で置き換え）</option>
    <option value="insert">今を割り込ませる（6〜24時は朝6時から、0〜6時は前日18時から。今の時間帯の右に「今」）</option>
    <option value="now">今から並べる（今・今の時間帯の残り・その先）</option>
  </select>
  <button id="layout-btn" onclick="saveLayout()">表の形を保存（表示プログラムを再起動）</button>
  <p id="layout-msg" class="msg"></p>
</div>

<button id="wifi-open-btn" class="sub-btn" onclick="openWifi()">🔒 WiFi 設定（パスワードが必要）</button>
<button class="sub-btn" onclick="openNow()">📱 子機用のページ（今の天気。スマホ・タブレットで開いておく）</button>
<p id="now-url" class="msg" style="word-break:break-all"></p>
<button class="sub-btn" onclick="location.href='/diag'">🩺 診断（本体の状態を見る・パスワードが必要）</button>
<button class="sub-btn" onclick="location.href='/shots'">📷 画面のスクリーンショット（パスワードが必要）</button>

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
    if (st.table_layout) document.getElementById('layout').value = st.table_layout;
    if (st.hostname) {
      nowUrl = 'http://' + st.hostname + '.local:8080/now';
      document.getElementById('now-url').textContent =
        '子機では ' + nowUrl + ' を開いてホーム画面に追加すると、現場が変わって IP アドレスが変わってもつながります';
    }
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

let nowUrl = '/now';
function openNow() { location.href = nowUrl; }

async function saveLayout() {
  const btn = document.getElementById('layout-btn');
  btn.disabled = true;
  try {
    const r = await post('/save-layout', {table_layout: document.getElementById('layout').value});
    setMsg('layout-msg', r.text, r.ok);
  } catch(e) {
    setMsg('layout-msg', 'エラー: ' + e, false);
  }
  btn.disabled = false;
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


NOW_HTML = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>今の天気</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #fff; color: #000;
    font-family: -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif; }
  /* 間隔は gap を使わず margin で空ける（flex の gap は iOS 14.5 から。iOS 12 の古い iPad でも同じ見た目に） */
  body { display: flex; flex-direction: column; padding: 2vmin 3vmin; }
  body > * + * { margin-top: 1.5vmin; }
  #head { display: flex; justify-content: space-between; align-items: baseline; font-size: 3.2vmin; }
  #head b { font-size: 4.4vmin; }
  #stale { color: #c00; font-weight: bold; }
  #peer { color: #888; font-size: 0.7em; margin-left: 1.5vmin; }
  /* 設定画面へのリンク（サイネージの QR は子機用のページへ来るので、設定はここから） */
  #setlink { color: #555; font-size: 0.75em; text-decoration: none; border: 1px solid #bbb; border-radius: 1vmin;
    padding: 0.3vmin 1.2vmin; margin-left: 1.5vmin; white-space: nowrap; }
  #main { flex: 1; display: flex; min-height: 0; }
  #main > * + * { margin-left: 2vmin; }
  .card { border: 2px solid #bbb; border-radius: 1.5vmin; padding: 1.5vmin; display: flex; flex-direction: column;
    align-items: center; justify-content: space-around; }
  #now { flex: 1.5; border: 0.8vmin solid #0068dc; }
  #ahead { flex: 2; display: flex; }
  #ahead > * + * { margin-left: 1.5vmin; }
  #ahead .card { flex: 1; }
  .label { font-size: 3.6vmin; font-weight: bold; }
  /* 列の日付（日付が変わった列は濃い色の札にして、今日か明日か一目で分かるように） */
  .dayl { font-size: 2.6vmin; color: #666; white-space: nowrap; }
  .dayl.next { color: #fff; background: #333; border-radius: 0.8vmin; padding: 0.2vmin 1vmin; font-weight: bold; }
  .dayl.sat { color: #0000ff; } .dayl.sun { color: #ff0000; }
  .dayl.next.sat { background: #0000c8; color: #fff; } .dayl.next.sun { background: #d00000; color: #fff; }
  #now .dayl { font-size: 3.6vmin; color: #0068dc; font-weight: bold; }
  #now .label { font-size: 4.6vmin; color: #0068dc; }
  .icon { width: 90%; max-height: 40%; object-fit: contain; }
  .row { font-size: 3.6vmin; white-space: nowrap; }
  #now .row { font-size: 4.6vmin; }
  #now .icon { max-height: 21%; }
  .unit { font-size: 0.55em; }
  .strong { color: #0000ff; font-weight: bold; }
  .wind { display: flex; align-items: center; }
  .wind > * + * { margin-left: 1vmin; }
  .arrow { width: 1.2em; height: 1.2em; }
  #alerts { display: flex; flex-direction: column; }
  #alerts > * + * { margin-top: 1vmin; }
  .band { padding: 1vmin 2vmin; border-radius: 1vmin; font-size: 3.6vmin; font-weight: bold; }
  .thunder-near { background: #a00000; color: #fff; }
  .thunder-watch { background: #ffd200; color: #000; }
  .warning { color: #ff0000; } .advisory { color: #cc5500; } .none { color: #000; font-weight: normal; }
  .warnbox { border: 2px solid #bbb; }
  .headline { font-size: 2.8vmin; font-weight: normal; color: #000; margin-top: 0.5vmin; }
  .card, #ahead { min-height: 0; overflow: hidden; }
  /* 1 週間の天気（土日の作業の予定用。土は青・日は赤、背景も薄く色を付ける） */
  #week { display: flex; height: 24vh; min-height: 0; }
  #week > * + * { margin-left: 1vmin; }
  #week:empty { display: none; }
  .day { flex: 1; border: 2px solid #bbb; border-radius: 1.2vmin; display: flex; flex-direction: column;
    align-items: center; justify-content: space-around; padding: 0.6vmin; min-width: 0; overflow: hidden; }
  .day.sat { background: #eef4ff; border-color: #7aa0ff; } .day.sun { background: #fff0f0; border-color: #ff8a8a; }
  .day .d { font-size: 2.8vmin; font-weight: bold; white-space: nowrap; }
  .day.sat .d { color: #0000ff; } .day.sun .d { color: #ff0000; }
  .day img { width: 80%; max-height: 38%; object-fit: contain; }
  .day .p, .day .t { font-size: 2.6vmin; white-space: nowrap; }
  .rel { display: inline-block; font-size: 0.75em; font-weight: bold; color: #fff; border-radius: 0.4em;
    padding: 0 0.3em; margin-left: 0.3em; }
  .rel-A { background: #e62814; } .rel-B { background: #f0e100; color: #282828; } .rel-C { background: #46aaff; }
  #wtitle { font-size: 2.6vmin; font-weight: bold; margin-bottom: -0.8vmin; }
  #wtitle:empty { display: none; }
  @media (orientation: portrait) {
    #week { height: 17vh; }
    .day .wd { display: block; text-align: center; }
    .day .d { font-size: 2.4vmin; text-align: center; } .day .p, .day .t { font-size: 2.3vmin; }
    .day img { max-height: 30%; }
    #main { flex-direction: column; } #now { flex: 1.3; } #ahead { flex: 1; }
    #main > * + * { margin-left: 0; margin-top: 2vmin; }
    #now .icon { max-height: 28%; } #ahead .icon { max-height: 26%; }
    #ahead .row { font-size: 3.2vmin; } #ahead .label { font-size: 3.4vmin; }
  }
</style></head><body>
<div id="head"><span><b id="airport">--</b></span><span><span id="stale"></span> <span id="time">--</span> 更新<span id="peer"></span><a id="setlink" href="/">⚙ 設定</a></span></div>
<div id="alerts"></div>
<div id="main">
  <div id="now" class="card"></div>
  <div id="ahead"></div>
</div>
<div id="wtitle"></div>
<div id="week"></div>
<script>
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function arrow(c) {
  if (c.calm) return '<span style="color:#999;font-weight:bold">---</span>';
  if (c.wind_dir == null) return '';
  // 風が吹いていく向き（北風なら下向き）。画面の矢印と同じ形
  return '<svg class="arrow" viewBox="-50 -50 100 100"><g transform="rotate(' + c.wind_dir + ')">' +
    '<polygon points="0,44 22,-44 0,-5 -22,-44" fill="' + c.arrow_color + '" stroke="#000" stroke-width="6" stroke-linejoin="round"/></g></svg>';
}
let today = '';
function dayLine(c, isNow) {
  if (!c.day_label) return '';
  const cls = (!isNow && c.day !== today ? ' next' : '') + (c.weekday === '土' ? ' sat' : c.weekday === '日' ? ' sun' : '');
  return '<div class="dayl' + cls + '">' + esc(c.day_label) + '（' + esc(c.weekday) + '）</div>';
}
function card(c, isNow) {
  if (!c) return '';
  const pop = c.pop == null ? '--' : c.pop.toFixed(1);
  return dayLine(c, isNow) + '<div class="label">' + esc(c.label) + '</div>' +
    '<img class="icon" src="/icon/' + esc(c.icon) + '.png" alt="">' +
    '<div class="row"><span class="' + (c.pop_strong ? 'strong' : '') + '">' + pop + '</span><span class="unit"> mm/h</span></div>' +
    '<div class="row" style="color:' + c.temp_color + '">' + (c.temp == null ? '--' : c.temp) + '<span class="unit">℃</span></div>' +
    '<div class="row wind"><span style="color:' + c.wind_color + ';' + (c.wind >= 9 ? 'font-weight:bold' : '') + '">' +
    (c.wind == null ? '--' : c.wind) + '<span class="unit"> m/s</span></span>' + arrow(c) + '</div>';
}
async function load() {
  try {
    const r = await fetch('/now.json', {cache: 'no-store'});
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    document.getElementById('airport').textContent = d.airport + (d.icao ? '（' + d.icao + '）' : '');
    document.getElementById('time').textContent = d.time;
    today = d.today || '';
    // どの親（Pi）を見ているか：P＝親（サイネージの Pi）・C＝この子機。IP アドレスの最後の数字
    const pe = d.peer || {};
    document.getElementById('peer').textContent = pe.parent || pe.child ? 'P' + (pe.parent || '?') + '／C' + (pe.child || '?') : '';
    const age = Date.now() / 1000 - d.written_at;
    document.getElementById('stale').textContent = age > 300 ? '更新が止まっています' : '';
    document.getElementById('now').innerHTML = card(d.now, true);
    document.getElementById('ahead').innerHTML = d.ahead.map(c => '<div class="card">' + card(c) + '</div>').join('');
    let a = '';
    if (d.thunder) a += '<div class="band ' + (d.thunder.kind === 'near' ? 'thunder-near' : 'thunder-watch') + '">⚡ ' +
      (d.thunder.kind === 'near' ? '雷接近' : '雷注意') + '　空港の' + esc(d.thunder.dir) + ' ' + d.thunder.km + 'km（' + esc(d.thunder.at) + ' 解析）</div>';
    a += '<div class="band warnbox"><span class="' + d.warning_level + '">' + esc(d.warning) + '</span>' +
      (d.headline ? '<div class="headline">' + esc(d.headline) + '</div>' : '') + '</div>';
    document.getElementById('alerts').innerHTML = a;
    const wk = d.week || [];
    document.getElementById('wtitle').textContent = wk.length ? '1 週間の天気（降水確率・最高／最低気温。A・B・C は予報の確からしさ）' : '';
    document.getElementById('week').innerHTML = wk.map(w =>
      '<div class="day ' + w.weekend + '"><div class="d">' + esc(w.label) + '<span class="wd">（' + esc(w.weekday) + '）</span></div>' +
      '<img src="/icon/' + esc(w.icon) + '.png" alt="">' +
      '<div class="p">' + (w.pop == null ? '--' : w.pop) + '%' + (w.rel ? '<span class="rel rel-' + w.rel + '">' + w.rel + '</span>' : '') + '</div>' +
      '<div class="t"><span style="color:' + w.tmax_color + (w.tmax >= 28 ? ';font-weight:bold' : '') + '">' +
      (w.tmax == null ? '--' : w.tmax) + '</span>／<span>' + (w.tmin == null ? '--' : w.tmin) + '</span>℃</div></div>'
    ).join('');
  } catch (e) {
    document.getElementById('stale').textContent = 'サイネージにつながりません';
  }
}
load();
setInterval(load, 60000);
</script></body></html>
"""


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
  <div class="box"><div class="sub">直近の警告・エラー（新しい順・最大20件。同じ内容はまとめて回数を表示）</div><div id="problems"></div></div>
  <div class="box"><div class="sub">予報の精度（予報と空港の観測のずれ）</div><div id="accuracy"></div>
    <div class="sub" style="margin-top:8px"><a href="/diag/verify.csv" style="color:#7fb8ff">記録をダウンロード（CSV・最大 4 か月分）</a></div></div>
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
  document.getElementById('accuracy').innerHTML = (d.accuracy || []).length
    ? d.accuracy.map(l => '<div class="log">' + esc(l) + '</div>').join('')
    : '<div class="sub">まだ記録がありません（毎時 00 分の観測ごとに記録。数日〜数週間で傾向がわかります）</div>';
  document.getElementById('foot').textContent = '版: ' + d.version + '　診断: ' + d.checked_at;
}
load();
</script>
</body></html>"""


SHOTS_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>天気サイネージ スクリーンショット</title>
<style>
  body { font-family: sans-serif; padding: 16px; background: #1a1a2e; color: white; margin: 0; }
  h2 { color: #FFD700; margin: 4px 0 2px; }
  .sub { font-size: 13px; color: #aaa; }
  input { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: none;
          background: #2a3048; color: white; font-size: 16px; box-sizing: border-box; }
  button { width: 100%; padding: 12px; background: #3b82f6; color: white; border: none;
           border-radius: 8px; font-size: 16px; margin-top: 8px; cursor: pointer; }
  button:disabled { background: #444; color: #999; }
  button.sub-btn { background: #374151; }
  .box { background: #1e2233; border-radius: 10px; padding: 12px; margin-top: 12px; }
  .hidden { display: none !important; }
  .msg { font-weight: bold; margin-top: 8px; }
  img { width: 100%; border-radius: 6px; border: 1px solid #333; background: #fff; }
  .shot { margin-top: 12px; }
  .shot a { color: #93c5fd; font-size: 13px; }
</style>
</head><body>
<h2>📷 スクリーンショット</h2>
<div class="sub">天気画面の今の表示を撮って保存します（最新 10 枚まで。古いものから自動で消えます）</div>

<div id="login-box" class="box hidden">
  <div>🔒 管理パスワード</div>
  <input id="admin-pw" type="password" inputmode="numeric" placeholder="パスワード" onkeydown="if(event.key==='Enter')login()">
  <button onclick="login()">開く</button>
  <p id="login-msg" class="msg" style="color:#ef4444"></p>
</div>

<div id="area" class="hidden">
  <button id="take-btn" onclick="take()">📷 今の画面を撮る</button>
  <p id="msg" class="msg"></p>
  <div class="box"><div class="sub" id="where"></div><div id="list"></div></div>
</div>
<button class="sub-btn" onclick="location.href='/'">← 設定画面に戻る</button>

<script>
function esc(t) {
  return String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function setMsg(text, ok) {
  const m = document.getElementById('msg');
  m.textContent = text; m.style.color = ok ? '#10b981' : '#ef4444';
}
async function login() {
  const res = await fetch('/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
              credentials: 'same-origin', body: JSON.stringify({password: document.getElementById('admin-pw').value})});
  if (res.ok) { load(); } else { document.getElementById('login-msg').textContent = await res.text(); }
}
async function load() {
  const res = await fetch('/shots/list', {credentials: 'same-origin'});
  if (res.status === 401) {
    document.getElementById('login-box').classList.remove('hidden');
    document.getElementById('area').classList.add('hidden');
    return;
  }
  document.getElementById('login-box').classList.add('hidden');
  document.getElementById('area').classList.remove('hidden');
  const d = await res.json();
  document.getElementById('where').textContent = '保存先: ' + d.folder + '（' + d.shots.length + ' / ' + d.max + ' 枚）';
  document.getElementById('list').innerHTML = d.shots.length ? d.shots.map(n =>
    '<div class="shot"><a href="/shots/file/' + esc(n) + '" target="_blank">' + esc(n) + '</a>' +
    '<a href="/shots/file/' + esc(n) + '" target="_blank"><img loading="lazy" src="/shots/file/' + esc(n) + '"></a></div>').join('')
    : '<p class="sub">まだありません</p>';
}
async function take() {
  const btn = document.getElementById('take-btn');
  btn.disabled = true; btn.textContent = '撮影中…（最大20秒）';
  setMsg('', true);
  try {
    const res = await fetch('/shots/take', {method: 'POST', credentials: 'same-origin'});
    const text = await res.text();
    if (res.ok) { setMsg('✓ ' + text, true); } else { setMsg(text, false); }
  } catch (e) {
    setMsg('エラー: ' + e, false);
  }
  btn.disabled = false; btn.textContent = '📷 今の画面を撮る';
  load();
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
        "airport": cfg.get("airport", "centrair"),
        "table_layout": cfg.get("table_layout", "fixed"),
        "hostname": _hostname(),
    }))


@app.route("/now")
def now_page_html():
    """子機用のページ（使っていないスマホ・タブレットで開いておく）。パスワード不要（画面と同じ天気の情報だけ）"""
    return _no_cache(make_response(NOW_HTML))


@app.route("/now.json")
def now_page_data():
    import now_page
    d = now_page.read()
    if d is None:
        return "まだデータがありません（表示プログラムが動いていない）", 503
    d["peer"] = _peer_numbers(request.remote_addr)
    return _no_cache(jsonify(d))


def _ip_tail(addr) -> str:
    """IP アドレスの最後の数字（192.168.1.112 → 112）。IPv6 は最後の区切り"""
    addr = str(addr or "")
    if addr.startswith("::ffff:"):
        addr = addr[7:]
    if "." in addr:
        return addr.rsplit(".", 1)[-1]
    return addr.rsplit(":", 1)[-1] if ":" in addr else ""


def _peer_numbers(child_addr) -> dict:
    """子機用のページの隅に出す「どの親（Pi）を見ているか」：親と子機の IP アドレスの最後の数字。
    親の IP は、子機へ返事をするときに使う自分の IP（WiFi と有線の両方があっても、子機と同じ側）"""
    import socket
    parent = ""
    try:
        fam = socket.AF_INET6 if ":" in str(child_addr) and not str(child_addr).startswith("::ffff:") else socket.AF_INET
        target = str(child_addr)[7:] if str(child_addr).startswith("::ffff:") else str(child_addr)
        with socket.socket(fam, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))                 # 送りはしない。子機へ向かうときの自分の IP を調べるだけ
            parent = s.getsockname()[0]
    except (OSError, ValueError):
        pass
    return {"parent": _ip_tail(parent), "child": _ip_tail(child_addr), "host": _hostname()}


@app.route("/icon/<name>.png")
def weather_icon(name):
    """天気のアイコン（子機用のページで使う）。weather_icons の中の番号の名前だけ"""
    import re as _re
    from config import ICON_DIR
    if not _re.fullmatch(r"\d{3,4}A?", name):
        return "not found", 404
    path = os.path.join(ICON_DIR, f"{name}.png")
    if not os.path.exists(path):
        return "not found", 404
    resp = make_response(send_file(path, mimetype="image/png"))
    resp.headers["Cache-Control"] = "max-age=86400"
    return resp


@app.route("/diag")
def diag_page():
    return _no_cache(make_response(DIAG_HTML))


@app.route("/diag/data")
@admin_required
def diag_data():
    """診断結果（見るだけ）。ログの中身・IP などが含まれるのでパスワード入力済みのときだけ返す"""
    import diagnostics
    return _no_cache(jsonify(diagnostics.diagnose()))


@app.route("/diag/verify.csv")
@admin_required
def diag_verify_csv():
    """予報の精度の記録（予報と空港の観測を並べたもの。最大 4 か月分）を CSV でダウンロード。
    PC に集めて、空港ごと・季節ごとに Excel などで比べる用"""
    import socket
    import verify
    from config import AIRPORT_CONFIG
    text, n = verify.export_csv()
    cfg = _load_config()
    icao = (AIRPORT_CONFIG.get(cfg.get("airport", "centrair"), {}) or {}).get("icao", "")
    name = f"verify_{socket.gethostname()}_{icao}_{time.strftime('%Y%m%d')}.csv"
    resp = make_response("\ufeff" + text)              # Excel で文字化けしないように BOM を付ける
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    resp.headers["X-Rows"] = str(n)
    return _no_cache(resp)


@app.route("/shots")
def shots_page():
    return _no_cache(make_response(SHOTS_HTML))


@app.route("/shots/list")
@admin_required
def shots_list():
    import screenshots
    return _no_cache(jsonify({"folder": screenshots.SCREENSHOT_DIR, "max": screenshots.MAX_SCREENSHOTS,
                              "shots": screenshots.list_shots()}))


@app.route("/shots/take", methods=["POST"])
@admin_required
def shots_take():
    """今の画面を撮る（表示プログラムに依頼。最大 20 秒待つ）。最新 10 枚を超えた古いものは消す"""
    import screenshots
    try:
        dest, how = screenshots.take()
    except Exception as e:
        return f"撮れませんでした（表示プログラムが止まっている可能性）: {e}", 500
    return f"保存しました: {os.path.basename(dest)}（{how}）"


@app.route("/shots/file/<name>")
@admin_required
def shots_file(name):
    import screenshots
    if not screenshots.NAME_RE.match(name):            # フォルダの外のファイルは返さない
        return "not found", 404
    path = os.path.join(screenshots.SCREENSHOT_DIR, name)
    if not os.path.exists(path):
        return "not found", 404
    return _no_cache(send_file(path, mimetype="image/png"))


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


@app.route("/save-layout", methods=["POST"])
def save_layout():
    """今日の天気の表の形（table_cols.LAYOUTS）。空港と同じくパスワードは不要。表示プログラムだけ起動し直す（数十秒）"""
    data = request.get_json() or {}
    layout = str(data.get("table_layout", "fixed")).strip()
    if layout not in ("fixed", "insert", "now"):
        return "表の形が正しくありません", 400
    _save_config({"table_layout": layout})
    subprocess.Popen(["bash", "-c", "sleep 2 && systemctl restart main01"])
    return "表の形を変更しました。数十秒で画面が切り替わります。"


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
