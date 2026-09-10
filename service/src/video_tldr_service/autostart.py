"""Start the service at logon, or take that back.

Windows only, through the task scheduler. A scheduled task is visible in
a tool the user already knows, survives an update of the program it
starts, and needs no administrator. The alternatives lose one of those:
the Run key in the registry hides the entry from anyone who looks for a
task, and a shortcut in the startup folder is a file nobody finds again.

Nothing here runs the service. It registers the same `video-tldr serve`
the user would type, which keeps the command line the only entry point.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

TASK = "video-tldr"


class AutostartError(RuntimeError):
    """schtasks refused, or this is not Windows."""


def command_path() -> Path:
    """The installed `video-tldr` command, the one the task will run.

    Not sys.executable: that is the Python inside the environment, and a
    task that calls it would break as soon as uv rebuilds the venv.
    """
    found = shutil.which("video-tldr")
    if not found:
        raise AutostartError(
            "video-tldr is not on the PATH; install it first, "
            "or run the installer with -Root"
        )
    return Path(found)


def _schtasks(*args: str) -> subprocess.CompletedProcess[str]:
    if sys.platform != "win32":
        raise AutostartError(
            "autostart is Windows only for now; elsewhere a systemd user "
            "unit or a launch agent does the same job"
        )
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def enable(port: int | None = None) -> str:
    """Register the task, replacing one that is already there."""
    command = f'"{command_path()}" serve'
    if port:
        command += f" --port {port}"
    # ponytail: the service keeps its console window while it runs. Hiding
    # it needs a wrapper (a .vbs, or a windowless build); worth it only if
    # someone says the window is in the way.
    done = _schtasks("/create", "/tn", TASK, "/tr", command, "/sc", "onlogon", "/f")
    if done.returncode != 0:
        raise AutostartError((done.stderr or done.stdout).strip())
    return f"autostart on: {command}"


def disable() -> str:
    """Remove the task. Missing is not an error: this is what off means."""
    done = _schtasks("/delete", "/tn", TASK, "/f")
    if (
        done.returncode != 0
        and "cannot find" not in (done.stderr + done.stdout).lower()
    ):
        raise AutostartError((done.stderr or done.stdout).strip())
    return "autostart off"


def status() -> str:
    done = _schtasks("/query", "/tn", TASK)
    if done.returncode != 0:
        return "autostart off"
    return "autostart on"
