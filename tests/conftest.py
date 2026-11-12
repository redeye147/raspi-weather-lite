"""テスト共通の準備。Pi 以外（PC・CI）で実行する前提で、画面・音声は使わない設定にする。"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pytest


@pytest.fixture(autouse=True)
def _fresh_pygame_fonts():
    """pygame.quit() のあとに前のテストのフォント（キャッシュ）を使うと Segmentation fault で落ちるので、
    テストごとにキャッシュを空にして始める（本番の main() 開始時と同じ）"""
    import utils
    utils.clear_font_cache()
    yield


@pytest.fixture(autouse=True)
def _card_file_in_tmp(tmp_path, monkeypatch):
    """カード表示のデータ（fetch_weather.CARD_FILE）をテストの一時フォルダに書く（リポジトリの cache/ を汚さない）"""
    import fetch_weather
    monkeypatch.setattr(fetch_weather, "CARD_FILE", str(tmp_path / "card.json"))
    monkeypatch.setattr(fetch_weather, "CARD", {"hours": [], "pops6": {}})
    yield


@pytest.fixture(autouse=True)
def _quick_session_is_patched_session(monkeypatch):
    """気象庁モデルの 1 回目に使う「やり直しなし」の通信（fetch_weather.SESS_QUICK）を、テストでは SESS と同じにする
    （テストは SESS.get を差し替えて通信の代わりにしているので）"""
    import fetch_weather
    monkeypatch.setattr(fetch_weather, "SESS_QUICK", None)
    yield
