"""ファイルを安全に書く（safe_write.py）：電源が突然切れても前のファイルか新しいファイルが残る"""
import json
import os
import threading

import pytest

import safe_write


def test_write_json_replaces_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "sub" / "a.json"
    safe_write.write_json(str(p), {"x": "雨"})
    safe_write.write_json(str(p), {"x": 2}, indent=2)
    assert json.loads(p.read_text()) == {"x": 2}
    assert os.listdir(p.parent) == ["a.json"]


def test_failure_keeps_old_file(tmp_path):
    """書けない値で失敗しても、前のファイルはそのまま・一時ファイルも残らない"""
    p = tmp_path / "a.json"
    safe_write.write_json(str(p), {"ok": 1})
    with pytest.raises(TypeError):
        safe_write.write_json(str(p), {"bad": object()})
    assert json.loads(p.read_text()) == {"ok": 1}
    assert os.listdir(tmp_path) == ["a.json"]


def test_concurrent_writes(tmp_path):
    """同時に保存しても「.tmp が無い」で失敗しない（以前のスナップショット保存で出ていた）"""
    p = str(tmp_path / "s.json")
    errors = []

    def run(i):
        try:
            for _ in range(30):
                safe_write.write_json(p, {"i": i})
        except Exception as e:
            errors.append(e)
    ts = [threading.Thread(target=run, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and json.load(open(p))["i"] in range(4)
