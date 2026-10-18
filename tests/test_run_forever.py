"""表示プログラムの再起動（main01.run_forever）：失敗が続くと間隔を延ばし、ログファイルにも残す"""
import logging

import pytest

import main01


def test_backoff_and_log_when_start_keeps_failing(monkeypatch, caplog):
    """2026-10-11 の 132：HDMI 未検出で 5 秒おきに起動失敗を繰り返し、ログファイルには何も残っていなかった"""
    sleeps = []

    def boom():
        raise RuntimeError("/dev/fb0 を開けない（描画先なし）")

    def fake_sleep(sec):
        sleeps.append(sec)
        if len(sleeps) >= 12:
            raise KeyboardInterrupt
    monkeypatch.setattr(main01, "main", boom)
    monkeypatch.setattr(main01.time, "sleep", fake_sleep)
    monkeypatch.setattr(main01.traceback, "print_exc", lambda: None)
    with caplog.at_level(logging.ERROR), pytest.raises(KeyboardInterrupt):
        main01.run_forever()
    assert sleeps[:6] == [5, 10, 20, 40, 60, 60]
    logged = [r.getMessage() for r in caplog.records if "表示プログラムが停止" in r.getMessage()]
    assert len(logged) == 2                       # 1 回目と 11 回目だけ（同じエラーを毎回は書かない）
    assert "描画先なし" in logged[0] and "1回目" in logged[0] and "11回目" in logged[1]


def test_display_attached_restarts_at_once_without_counting_failure(monkeypatch, caplog):
    """画面なしで動いている間に HDMI がつながったら、失敗とは数えず 2 秒後に作り直す（ERROR を残さない）"""
    sleeps, runs = [], []

    def main():
        runs.append(1)
        if len(runs) == 1:
            raise main01.DisplayAttached("画面出力の状態が変わった")
        raise KeyboardInterrupt
    monkeypatch.setattr(main01, "main", main)
    monkeypatch.setattr(main01.time, "sleep", sleeps.append)
    with caplog.at_level(logging.INFO), pytest.raises(KeyboardInterrupt):
        main01.run_forever()
    assert sleeps == [2] and len(runs) == 2
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
