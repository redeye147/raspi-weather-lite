#!/usr/bin/env python3
"""
tools/screenshot.py
天気サイネージの今の画面を PNG で保存する（設定画面の「📷 スクリーンショット」と同じ処理）。

使い方（Pi で）:
    sudo python3 ~/raspi-weather-lite/tools/screenshot.py            # ~/raspi-weather-lite/screenshots/ に保存
    sudo python3 ~/raspi-weather-lite/tools/screenshot.py ~/写真     # 指定したフォルダに保存

どちらのフォルダも、最新 10 枚を超えた古いものは自動で消す。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import screenshots  # noqa: E402


def main(argv) -> int:
    folder = os.path.abspath(os.path.expanduser(argv[1])) if len(argv) > 1 else screenshots.SCREENSHOT_DIR
    print("表示プログラムに画面の保存を依頼中…（最大20秒）")
    try:
        dest, how = screenshots.take(folder)
    except Exception as e:
        print(f"保存できませんでした: {e}")
        print("（表示プログラムが止まっていて、fb0 方式でもない場合は撮れません。sudo で実行しているかも確認）")
        return 1
    print(f"保存しました（{how}）: {dest}")
    print(f"このフォルダには最新 {screenshots.MAX_SCREENSHOTS} 枚まで残します（古いものは自動で削除）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
