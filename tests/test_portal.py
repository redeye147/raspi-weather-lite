"""設定画面（wifi_portal）：画面の JavaScript、パスワードと保護、登録済み WiFi の読み取り"""
import re
import shutil
import subprocess

import pytest

import wifi_portal as wp


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wp, "_load_config", lambda: {"airport": "narita"})
    monkeypatch.setattr(wp, "_login_fail", {"count": 0, "until": 0.0})
    wp.app.config["TESTING"] = True
    return wp.app.test_client()


# ---------------------------------------------------------------- 画面の JavaScript
@pytest.mark.parametrize("page", ["HTML", "DIAG_HTML"])
def test_page_javascript_has_no_syntax_error(page, tmp_path):
    """画面の JavaScript は Python の文字列の中に書くので、\\n のエスケープ漏れ 1 つで全部動かなくなる
    （更新ボタンの開発中に実際に起きた）。node で構文だけ確かめる"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い環境")
    js = "\n".join(re.findall(r"<script>(.*?)</script>", getattr(wp, page), re.S))
    assert js.strip()
    f = tmp_path / "page.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_pages_are_served_without_password(client):
    assert "天気サイネージ 設定" in client.get("/").get_data(as_text=True)
    assert "天気サイネージ 診断" in client.get("/diag").get_data(as_text=True)


# ---------------------------------------------------------------- パスワードと保護
@pytest.mark.parametrize("url", ["/scan", "/wifi/list", "/diag/data"])
def test_protected_reads_need_login(client, url):
    assert client.get(url).status_code == 401


@pytest.mark.parametrize("url", ["/wifi/delete", "/wifi/order", "/save"])
def test_protected_writes_need_login(client, url):
    assert client.post(url, json={}).status_code == 401


def test_login_then_diag(client, monkeypatch):
    import diagnostics
    monkeypatch.setattr(diagnostics, "diagnose", lambda: {"overall": "ok", "items": []})
    assert client.post("/login", json={"password": "0000"}).status_code == 403
    assert client.post("/login", json={"password": "1048"}).status_code == 200
    r = client.get("/diag/data")
    assert r.status_code == 200 and r.get_json()["overall"] == "ok"


def test_password_from_config(client, monkeypatch):
    monkeypatch.setattr(wp, "_load_config", lambda: {"admin_password": "5678"})
    assert client.post("/login", json={"password": "1048"}).status_code == 403
    assert client.post("/login", json={"password": "5678"}).status_code == 200


def test_lock_after_5_failures(client):
    for _ in range(4):
        assert client.post("/login", json={"password": "x"}).status_code == 403
    assert "60秒ロック" in client.post("/login", json={"password": "x"}).get_data(as_text=True)
    assert client.post("/login", json={"password": "1048"}).status_code == 429     # 正しくてもロック中


# ---------------------------------------------------------------- 登録済み WiFi の読み取り（nmcli -t）
@pytest.mark.parametrize("line, fields", [
    ("abc:802-11-wireless:office:10:yes", ["abc", "802-11-wireless", "office", "10", "yes"]),
    (r"abc:802-11-wireless:my\:wifi:0:no", ["abc", "802-11-wireless", "my:wifi", "0", "no"]),   # SSID に ':'
    (r"abc:802-11-wireless:a\\b:0:no", ["abc", "802-11-wireless", r"a\b", "0", "no"]),
])
def test_split_terse(line, fields):
    assert wp._split_terse(line) == fields


def test_saved_wifi_order_and_flags(monkeypatch):
    show = "\n".join([
        "u1:802-11-wireless:office:10:no",
        "u2:802-11-wireless:setup-hotspot:-10:no",
        "u3:802-3-ethernet:Wired connection 1:-999:yes",          # 有線は一覧に出さない
        r"u4:802-11-wireless:Buffalo-G-52B8:100:yes",
        r"u5:802-11-wireless:my\:home:10:no",
    ])
    ssid = {"u1": "office", "u2": "MyPhone", "u4": "Buffalo-G-52B8", "u5": "my:home"}

    def fake_run(cmd, *a, **k):
        if cmd[:2] == ["nmcli", "-t"]:
            return subprocess.CompletedProcess(cmd, 0, show + "\n", "")
        return subprocess.CompletedProcess(cmd, 0, ssid[cmd[-1]] + "\n", "")
    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    items = wp._saved_wifi()
    assert [w["ssid"] for w in items] == ["Buffalo-G-52B8", "my:home", "office", "MyPhone"]   # 優先度順、テザリングは最後
    assert items[0]["active"] and not items[1]["active"]
    assert items[-1]["hotspot"] and not any(w["hotspot"] for w in items[:-1])


def test_cannot_delete_active_wifi(client, monkeypatch):
    client.post("/login", json={"password": "1048"})
    monkeypatch.setattr(wp, "_saved_wifi", lambda: [{"uuid": "u4", "ssid": "Buffalo", "active": True, "hotspot": False}])
    calls = []
    monkeypatch.setattr(wp.subprocess, "run", lambda cmd, *a, **k: calls.append(cmd))
    r = client.post("/wifi/delete", json={"uuid": "u4"})
    assert r.status_code == 400 and not calls                 # 接続中は消さない（nmcli を呼ばない）
