"""設定画面の「更新」ボタン（wifi_portal の /update/start・/update/status）"""
import subprocess

import pytest

import wifi_portal as wp


@pytest.fixture
def portal(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(wp, "UPDATE_LOG", str(tmp_path / "update.log"))
    monkeypatch.setattr(wp, "UPDATE_RC", str(tmp_path / "update.rc"))
    monkeypatch.setattr(wp, "_load_config", lambda: {})
    monkeypatch.setattr(wp, "_update_fail", {"count": 0, "until": 0.0})
    calls, state = [], {"active": "inactive"}

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(cmd, 0, state["active"] + "\n", "")
        if cmd[0] == "systemd-run":
            state["active"] = "active"
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "abc1234 10/05 20:00\n", "")
    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    wp.app.config["TESTING"] = True
    return wp.app.test_client(), calls, state, tmp_path


def test_wrong_password_is_rejected_and_nothing_runs(portal):
    client, calls, _, _ = portal
    r = client.post("/update/start", json={"password": "1048"})        # WiFi 設定のパスワードでは更新できない
    assert r.status_code == 403
    assert not any(c[0] == "systemd-run" for c in calls)


def test_lock_after_5_failures(portal):
    client, _, _, _ = portal
    for _ in range(5):
        client.post("/update/start", json={"password": "x"})
    r = client.post("/update/start", json={"password": wp.DEFAULT_UPDATE_PASSWORD})
    assert r.status_code == 429


def test_start_runs_update_sh_as_separate_unit(portal):
    """update.sh は wifi-portal 自身を再起動するので、別のサービス（systemd-run）として切り離して動かす"""
    client, calls, _, tmp = portal
    r = client.post("/update/start", json={"password": "10481048n"})
    assert r.status_code == 200
    run = next(c for c in calls if c[0] == "systemd-run")
    assert "--unit=signage-update" in run and "bash update.sh" in run[-1] and "< /dev/null" in run[-1]
    assert "更新前の版: abc1234" in (tmp / "update.log").read_text(encoding="utf-8")


def test_no_double_start(portal):
    client, _, state, _ = portal
    state["active"] = "active"
    r = client.post("/update/start", json={"password": "10481048n"})
    assert r.status_code == 409


def test_status_needs_update_password_session(portal):
    client, _, _, _ = portal
    assert client.get("/update/status").status_code == 401
    client.post("/login", json={"password": "1048"})                    # WiFi 設定のログインだけでは見られない
    assert client.get("/update/status").status_code == 401


def test_status_running_then_done(portal):
    client, _, state, tmp = portal
    client.post("/update/start", json={"password": "10481048n"})
    (tmp / "update.log").write_text("=== 更新 ===\n\x1b[1;33m[1/5] 確認中\x1b[0m\n", encoding="utf-8")
    st = client.get("/update/status").get_json()
    assert st["running"] and not st["done"] and "\x1b" not in st["log"] and "[1/5] 確認中" in st["log"]
    state["active"] = "inactive"
    (tmp / "update.rc").write_text("0\n")
    st = client.get("/update/status").get_json()
    assert st["done"] and st["ok"] and st["finished_ago"] < 60
    (tmp / "update.rc").write_text("1\n")
    st = client.get("/update/status").get_json()
    assert st["done"] and not st["ok"] and st["rc"] == 1


def test_update_password_from_config(portal, monkeypatch):
    client, _, _, _ = portal
    monkeypatch.setattr(wp, "_load_config", lambda: {"update_password": "zzz"})
    assert client.post("/update/start", json={"password": "10481048n"}).status_code == 403
    assert client.post("/update/start", json={"password": "zzz"}).status_code == 200


def test_session_key_is_kept_across_restart(tmp_path, monkeypatch):
    """更新で設定画面が再起動しても、ログイン状態（進み具合の表示）が続くように鍵をファイルに残す"""
    monkeypatch.setattr(wp, "CACHE_DIR", str(tmp_path))
    k1 = wp._session_key()
    assert wp._session_key() == k1 and len(k1) == 32
    assert oct((tmp_path / "portal_secret.key").stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("page", ["HTML", "DIAG_HTML"])
def test_page_javascript_has_no_syntax_error(page, tmp_path):
    """画面の JavaScript に構文エラーが無いこと（Python の文字列に書くので \\n のエスケープ漏れが起きやすい）"""
    import re
    import shutil
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い環境")
    js = "\n".join(re.findall(r"<script>(.*?)</script>", getattr(wp, page), re.S))
    f = tmp_path / "page.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
