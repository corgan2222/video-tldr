"""What the autostart command hands to the task scheduler.

The scheduler itself is not called: a test that registers a logon task
would leave one behind on the machine that ran it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from video_tldr_service import autostart


class Fake:
    """Stands in for schtasks and remembers the arguments it was given."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, self.returncode, "", self.stderr)


@pytest.fixture
def scheduler(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setattr(autostart.subprocess, "run", fake)
    monkeypatch.setattr(
        autostart, "command_path", lambda: Path(r"C:\bin\video-tldr.exe")
    )
    return fake


def test_on_registers_a_logon_task(scheduler):
    message = autostart.enable(None)
    assert scheduler.calls[0][:5] == ["schtasks", "/create", "/tn", "video-tldr", "/tr"]
    assert "/sc" in scheduler.calls[0]
    assert scheduler.calls[0][scheduler.calls[0].index("/sc") + 1] == "onlogon"
    # /f replaces an older task instead of failing on the second run.
    assert "/f" in scheduler.calls[0]
    assert "serve" in message


def test_a_port_reaches_the_task(scheduler):
    autostart.enable(9765)
    command = scheduler.calls[0][scheduler.calls[0].index("/tr") + 1]
    assert command.endswith("serve --port 9765")


def test_off_deletes_the_task(scheduler):
    assert autostart.disable() == "autostart off"
    assert scheduler.calls[0] == ["schtasks", "/delete", "/tn", "video-tldr", "/f"]


def test_off_is_quiet_when_there_is_no_task(monkeypatch):
    fake = Fake(returncode=1, stderr="ERROR: The system cannot find the file")
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setattr(autostart.subprocess, "run", fake)
    assert autostart.disable() == "autostart off"


def test_a_refusal_is_an_error(monkeypatch):
    fake = Fake(returncode=1, stderr="ERROR: Access is denied.")
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setattr(autostart.subprocess, "run", fake)
    with pytest.raises(autostart.AutostartError, match="Access is denied"):
        autostart.disable()


def test_status_reads_the_task(scheduler):
    assert autostart.status() == "autostart on"
    assert scheduler.calls[0] == ["schtasks", "/query", "/tn", "video-tldr"]


def test_elsewhere_it_says_so(monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    with pytest.raises(autostart.AutostartError, match="Windows only"):
        autostart.status()
