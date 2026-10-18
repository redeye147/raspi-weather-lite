"""
netretry.py
ネットの一時的な失敗（DNS が一瞬引けない・つながらない・時間切れ）への対処。

- get_with_retry: 失敗したら数秒あけて 1 回だけ取り直す（一瞬の失敗はこれでほぼ消える）
- FailureLog: 1 回だけの失敗は INFO にとどめ、15 分以上続いたときだけ WARNING を 1 回出す
  （診断ページの「直近の警告・エラー」が一時的な失敗で埋まらないように）
"""

import logging
import time

import requests

NETWORK_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
RETRY_WAIT_S = 3
WARN_AFTER_S = 15 * 60


def get_with_retry(url, session=requests, wait=RETRY_WAIT_S, sleep=time.sleep, **kwargs):
    """session.get(url) を、通信の失敗なら wait 秒あけて 1 回だけ取り直す（HTTP のエラー応答は取り直さない）"""
    try:
        return session.get(url, **kwargs)
    except NETWORK_ERRORS as e:
        logging.info(f"通信失敗 → {wait}秒後に取り直し: {e}")
        sleep(wait)
        return session.get(url, **kwargs)


class FailureLog:
    """取得の失敗・成功を受けて、ログの重さを決める。
    failed(): 失敗が warn_after_s 秒以上続いたら WARNING を 1 回。それまでは INFO
    ok():     成功。続いていた失敗を解除（WARNING を出していたら回復も WARNING で残す）"""

    def __init__(self, name, warn_after_s=WARN_AFTER_S, clock=time.time):
        self.name = name
        self.warn_after_s = warn_after_s
        self.clock = clock
        self.first_fail = None
        self.warned = False

    def failed(self, err):
        now = self.clock()
        if self.first_fail is None:
            self.first_fail = now
        minutes = int((now - self.first_fail) // 60)
        if not self.warned and now - self.first_fail >= self.warn_after_s:
            self.warned = True
            logging.warning(f"{self.name}取得失敗（{minutes}分以上続いている）: {err}")
        else:
            logging.info(f"{self.name}取得失敗（一時的・{minutes}分）: {err}")

    def ok(self):
        if self.first_fail is not None:
            minutes = int((self.clock() - self.first_fail) // 60)
            (logging.warning if self.warned else logging.info)(f"{self.name}取得が回復（{minutes}分ぶり）")
        self.first_fail = None
        self.warned = False
