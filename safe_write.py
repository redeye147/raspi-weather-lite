"""
safe_write.py
ファイルを「安全に」書く：電源が突然切れても、前のファイルか新しいファイルのどちらかが必ず残る。

普通に書くと、書いた直後（数十秒）はまだ SD カードに届いていないことがあり、
その間に電源が切れると中身が空・途中までのファイルになる（2026-10-25 の 112：テレビの USB 給電が途切れて
取っておいた予報が空になり、前の日の列が「？」になった）。

  1. 同じフォルダの一時ファイルに書く（スレッド・プロセスごとに別の名前）
  2. SD に書き終わるまで待つ（fsync）
  3. 本物のファイルと入れ替える（os.replace は一瞬で入れ替わる）
  4. 入れ替えたこともフォルダごと SD に書く
"""

import json
import os
import threading


def write_text(path, text, encoding="utf-8"):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):                 # 失敗したときの一時ファイルは残さない
            try:
                os.remove(tmp)
            except OSError:
                pass
    try:
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def write_json(path, obj, **kw):
    kw.setdefault("ensure_ascii", False)
    write_text(path, json.dumps(obj, **kw))
