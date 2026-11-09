"""前回の起動の終わり方（突然の電源断を知らせる）：bootcheck.py"""
import types

import bootcheck

ABRUPT = """Nov 09 header
2026-11-09T07:13:08+0900 raspi2w wpa_supplicant[542]: wlan0: WPA: Group rekeying completed
2026-11-09T07:17:01+0900 raspi2w CRON[2664]: pam_unix(cron:session): session opened for user root
2026-11-09T07:17:01+0900 raspi2w CRON[2664]: pam_unix(cron:session): session closed for user root
"""
CLEAN = """2026-11-09T05:30:01+0900 raspi2w systemd-logind[400]: The system will reboot now!
2026-11-09T05:30:02+0900 raspi2w systemd[1]: Stopped target multi-user.target - Multi-User System.
2026-11-09T05:30:04+0900 raspi2w systemd[1]: Reached target reboot.target - System Reboot.
2026-11-09T05:30:04+0900 raspi2w systemd-journald[200]: Journal stopped
"""


def _run(out, code=0):
    return lambda *a, **k: types.SimpleNamespace(returncode=code, stdout=out)


def test_abrupt_power_loss_is_reported():
    info = bootcheck.previous_boot(_run(ABRUPT))
    assert info["clean"] is False and info["last"].strftime("%H:%M") == "07:17"
    assert "突然電源が切れて" in bootcheck.message(info) and "11/09 07:17" in bootcheck.message(info)


def test_clean_reboot_is_not_reported():
    info = bootcheck.previous_boot(_run(CLEAN))
    assert info["clean"] is True and bootcheck.message(info) is None


def test_no_previous_boot_or_error():
    assert bootcheck.previous_boot(_run("", code=1)) is None
    assert bootcheck.previous_boot(_run("-- No entries --\n")) is None
    assert bootcheck.message(None) is None

    def boom(*a, **k):
        raise OSError("no journalctl")
    assert bootcheck.previous_boot(boom) is None


def test_check_once_writes_warning_only_once(tmp_path, caplog):
    done = tmp_path / "x" / "done"
    with caplog.at_level("INFO"):
        assert "突然電源" in bootcheck.check_once(_run(ABRUPT), done_file=str(done))
        assert bootcheck.check_once(_run(ABRUPT), done_file=str(done)) is None     # 同じ起動では 1 回だけ
    assert sum("突然電源" in r.message and r.levelname == "WARNING" for r in caplog.records) == 1
