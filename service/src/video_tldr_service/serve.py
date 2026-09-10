"""The HTTP face of the pipeline, for the extension: 127.0.0.1 only, one
job at a time, the same `run` the command line calls.

The contract, every answer JSON:

    POST /jobs {"url", "profile",   202 the job; 400 when the URL is no video,
                "options"}               the profile is not fast or thorough,
                                         or an option names a wrong key;
                                         413 when a body is far too big
    GET  /jobs/<id>                 200 the job; 404
    POST /jobs/<id>/open {"what"}   200 {"opened": ...}; 409 until it is done.
                                    what: obsidian, folder, or auto (default)
    POST /jobs/<id>/cancel          200 the job; 404; 409 once it is finished
    POST /bench {"url", "models",   202 a job with kind bench, whose `bench`
                 "repeat"}               holds the rows once it is done
    GET  /bench                     200 {"rows": [...]} of every bench so far
    GET  /config                    200 {"settings", "choices", "stt_models",
                                         "profiles", "home", "log", "version"}
    PUT  /config {key: value}       200 {"settings", ...}; 400 on a wrong
                                    key, and without a token on one that
                                    needs the machine (browser, a path, a
                                    vendor URL, a key)
    GET  /models?llm=<backend>      200 {"models": [...]}; 400 with the reason
    GET  /log?lines=<n>             200 {"lines": [...]}, the tail of serve.log
    GET  /stats                     200 what earlier runs took, see run.stats
    GET  /health                    200 {"service", "llm", "stt",
                                         "capabilities"}
    POST /pick {"kind", "start"}    200 {"path"}: a file or folder dialog on
                                    this desktop, empty when cancelled;
                                    409 while one dialog is already open
    POST /restart {"force"}         200 {"restarting": true}, then this
                                    process hands the port to a fresh one;
                                    409 while a job is on, unless force
    POST /shutdown {"force"}        200 {"stopping": true}, then this
                                    process ends and frees the port; 409
                                    while a job is on, unless force

A job carries `id` (the video id), `url`, `profile`, `options` (what the
popup set for this run), `status` (queued, running, done, error,
cancelled), `position` while it waits or runs, `step` and `step_started`
(the running or last step) and, once it ran, what `run` returned:
`title`, `model`, `stt`, `steps` with seconds, `images`, `usd`,
`written`, `error`.

Who gets in, after decision 0001: the Host header must read
127.0.0.1:<port>, an Origin header must be absent (curl, the command
line) or start with moz-extension:// or chrome-extension://, and
Authorization must carry the token from config.json. A web page's
simple request or navigation does reach the guard and stops there, at
the Origin check or at the token; no CORS headers go out, so a page can
never read an answer either.

One job at a time on purpose: two `frames` runs side by side both broke
in the clip download (2026-09-10).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote
from urllib.request import Request, urlopen

from . import __version__, llm
from .config import (
    CHOICES,
    FORMATS,
    MASK,
    PROFILES,
    SECRETS,
    STT_MODELS,
    ConfigError,
    Settings,
    over_http,
    profile_overrides,
    store,
)
from .documents import browser as find_browser
from .fetch import FetchError, video_folder, video_id
from .llm import LlmError
from .run import bench, needs_model, read_bench, run, stats
from .transcribe import stt_status

PORT = 8765
# Windows answers a bind inside a range it reserved for Hyper-V with this,
# not with "address in use", and the ranges move on every reboot: 8765 was
# free on 2026-09-09 and inside 8694-8793 a day later.
WSAEACCES = 10013
# Every request, every job step and every traceback, next to the data:
# the console scrolls away, this stays. Three files of a megabyte each.
LOG_NAME = "serve.log"
LOG_BYTES = 1_000_000
LOG_FILES = 3
LOG_LINES = 50
LOG_LINES_MAX = 500
# Long enough for the answer to reach the page before the socket closes.
RESTART_DELAY_SECONDS = 0.4
# The answer comes before the shutdown, so this waits for a reply, not for
# the process to be gone.
STOP_TIMEOUT_SECONDS = 5
EXTENSION_ORIGINS = ("moz-extension://", "chrome-extension://")
# A job body is a URL, a profile and nine switches, a settings save is a
# dozen short strings: kilobytes. A bigger Content-Length is turned away
# before the read, which would otherwise allocate whatever it claims.
MAX_BODY_BYTES = 64_000
# What `open` starts, the first that the job wrote.
OPEN_ORDER = ["obsidian", "pdf", "docx", "md", "summary"]
# What the popup's buttons ask for: the note, the folder, or that order.
OPEN_WHAT = ["auto", "obsidian", "folder"]
# tkinter is not thread safe: a second Tk from a second request thread
# takes the whole process with it. One dialog at a time, on a thread of
# its own, and the request gives up after this long — a dialog nobody
# answers would otherwise hold its request thread for good.
PICK_TIMEOUT_SECONDS = 120
_PICK_LOCK = threading.Lock()
Runner = Callable[..., dict]


class NotReady(Exception):
    """Everything that answers 409: the job exists but has nothing to open
    yet, a dialog is already open, or a job is still on while something
    asks this process to end."""


class TooLarge(Exception):
    """The request body is bigger than this service reads."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def start(target: str) -> None:
    """Open a file or a URL the way a double click would."""
    if hasattr(os, "startfile"):
        os.startfile(target)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target])


def dialog(kind: str, start: str = "") -> str:
    """The tkinter half of `pick`, only ever called on the pick thread."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "folder":
            chosen = filedialog.askdirectory(
                parent=root, initialdir=start or None, title="Choose the folder"
            )
        else:
            chosen = filedialog.askopenfilename(
                parent=root,
                initialdir=start or None,
                title="Choose the program",
                filetypes=[("Programs", "*.exe"), ("All files", "*.*")],
            )
    finally:
        root.destroy()
    return chosen or ""


def pick(kind: str, start: str = "") -> str:
    """A file or folder dialog on this desktop, for the options page: the
    browser's own dialog never tells an extension the full path. Empty
    when the dialog is cancelled, NotReady when one is already open or
    nobody answers this one."""
    if not _PICK_LOCK.acquire(blocking=False):
        raise NotReady("a dialog is already open on this desktop")
    chosen: list[str] = []
    failed: list[Exception] = []

    def ask() -> None:
        try:
            chosen.append(dialog(kind, start))
        except Exception as error:  # noqa: BLE001 - carried to the request
            failed.append(error)
        finally:
            _PICK_LOCK.release()

    # A daemon thread: a dialog still standing must not keep the process
    # from ending. It holds the lock until it closes, so the next request
    # is turned away instead of opening a second Tk.
    thread = threading.Thread(target=ask, daemon=True, name="pick")
    thread.start()
    thread.join(PICK_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise NotReady(f"the dialog got no answer in {PICK_TIMEOUT_SECONDS} seconds")
    if failed:
        raise failed[0]
    return chosen[0] if chosen else ""


def capability_light(found: dict) -> dict:
    """`capabilities` says what a model can do; the pages want a green or
    a red light and a reason. Green when it reads pictures and holds
    enough context, red with the reason when not, and green with a note
    when the server did not say."""
    reasons = []
    if found.get("vision") is False:
        reasons.append("takes no pictures, so they stay unlabelled")
    context = found.get("context")
    if context is not None and context < llm.MIN_CONTEXT:
        reasons.append(
            f"context {context} tokens is below {llm.MIN_CONTEXT}, "
            "the transcript and the model's own thinking will not fit"
        )
    detail = found.get("detail", "")
    if reasons:
        return {"ok": False, "detail": f"{detail} — {'; '.join(reasons)}"}
    return {"ok": True, "detail": detail, **found}


def browser_found() -> str:
    """The Chrome or Edge the PDF step would use when none is configured."""
    try:
        return find_browser("")
    except FetchError:
        return ""


class Service:
    """The jobs, and the one thread that works them off."""

    def __init__(
        self,
        home: Path | None,
        overrides: dict | None = None,
        runner: Runner = run,
        checker: Callable[[Settings], str | None] = llm.check,
    ) -> None:
        self.home = home
        self.overrides = overrides or {}
        self.runner = runner
        # What asks the backend before a job is queued. Injected like the
        # runner, so a test does not need the CLI or a server of its own.
        self.checker = checker
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.queue: queue.Queue[str] = queue.Queue()
        # The ids whose cancel arrived while they were running; the worker
        # asks this between two steps.
        self.cancelling: set[str] = set()
        self.token = self.read_token()
        self.log_path = self.settings().home / LOG_NAME
        self.log = self.open_log()
        threading.Thread(target=self.work, daemon=True, name="jobs").start()

    def settings(
        self, profile: str | None = None, options: dict | None = None
    ) -> Settings:
        # Loaded per use, not once: PUT /config changes the file underneath.
        # A profile sits on top of the file and under the command line; the
        # options of the one job win over both, they are what the popup
        # switched for this run.
        base = Settings.load(self.home, self.overrides)
        if not profile and not options:
            return base
        overrides = {**self.overrides, **(options or {})}
        if profile:
            overrides = {**profile_overrides(profile, base.config), **overrides}
        return Settings.load(self.home, overrides)

    def open_log(self) -> logging.Logger:
        # A fresh data directory: the token no longer creates it on the way.
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = logging.getLogger(f"video-tldr.serve.{id(self)}")
        log.setLevel(logging.INFO)
        log.propagate = False
        log.handlers.clear()
        line = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        to_file = RotatingFileHandler(
            self.log_path, maxBytes=LOG_BYTES, backupCount=LOG_FILES, encoding="utf-8"
        )
        to_file.setFormatter(line)
        to_console = logging.StreamHandler(sys.stderr)
        to_console.setFormatter(line)
        log.addHandler(to_file)
        log.addHandler(to_console)
        return log

    def log_tail(self, lines: int) -> list[str]:
        """The last `lines` of the log file, oldest first."""
        if not self.log_path.exists():
            return []
        with self.log_path.open(encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=lines)]

    def read_token(self) -> str:
        """The token from config.json, or empty: then the Host and Origin
        checks alone keep web pages out, and any extension in the browser
        may use the service (owner's choice, 2026-09-10). `video-tldr
        config --set token=<secret>` turns the check on."""
        return self.settings().config["token"]

    def config(self) -> dict:
        settings = self.settings()
        return {
            "settings": settings.shown(),
            # Every knob the pages offer as a list, so a value added here
            # shows up in the extension without a release of it. `formats`
            # is the one that is not a single choice but a comma list.
            "choices": {**{k: list(v) for k, v in CHOICES.items()}, "formats": FORMATS},
            # Speed class, error rate and languages per transcriber, for
            # the options page to label the choice with.
            "stt_models": STT_MODELS,
            "profiles": list(PROFILES),
            "default_models": llm.DEFAULT_MODELS,
            "browser_found": browser_found(),
            "home": str(settings.home),
            "log": str(self.log_path),
            "version": __version__,
        }

    def health(self) -> dict:
        """Four lights for the popup and the options page: the service
        itself, the language model, the transcriber, and what the model can
        do, so the popup warns about a model without vision before the run
        instead of after the frames step."""
        settings = self.settings()
        capabilities = getattr(
            llm,
            "capabilities",
            lambda _: {"vision": None, "context": None, "detail": "not checked"},
        )
        return {
            "service": {
                "ok": True,
                "detail": f"video-tldr service {__version__}, data under {settings.home}",
            },
            "llm": llm.status(settings),
            "stt": stt_status(settings),
            "capabilities": capability_light(capabilities(settings)),
        }

    def models(self, backend: str | None = None) -> list[str]:
        """What the backend accepts as `model`; `backend` looks past the
        stored choice, so the options page can list them before saving."""
        overrides = {**self.overrides, "llm": backend} if backend else self.overrides
        return llm.models(Settings.load(self.home, overrides))

    def update_config(self, values: dict) -> dict:
        # The options page sends back what GET /config showed it; a masked
        # secret must not overwrite the real one. The token is not written
        # either: this process keeps the one it started with, so a change
        # here would look accepted and lock the extension out until the
        # next start. `video-tldr config --set token=...` is the way.
        # What is left goes through the same list a job's options do, but
        # the token lifts it here: a caller that got past the Authorization
        # check is authenticated and may set what the command line may.
        # Without a token the bar stands, and the options page loses the
        # fields that name a program, a path or a vendor URL. It sends one
        # key per request, so it loses exactly those and shows for each one
        # the reason this answer gives (2026-09-10).
        store(
            self.home,
            over_http(
                {
                    k: v
                    for k, v in values.items()
                    if k != "token" and not (k in SECRETS and v == MASK)
                },
                token=self.token,
            ),
        )
        return self.config()

    def submit(
        self, url: str, profile: str = "fast", options: dict | None = None
    ) -> dict:
        vid = video_id(url)
        profile_overrides(profile, self.settings().config)  # names a wrong one
        # The switches of the popup travel per job. Checked here and not in
        # the worker: a wrong one is a 400 the popup can show, not a job
        # that fails a minute later.
        options = over_http(dict(options or {}))
        # The backend is asked once before the job goes into the queue: a
        # key the vendor refuses or a server that is not running is a 400
        # the popup shows now. Asked for on 2026-09-10, after a 401 ended
        # a run at `analyze`, with fetch and transcribe already paid for.
        settings = self.settings(profile, options)
        if needs_model(settings, vid, force=profile == "thorough"):
            trouble = self.checker(settings)
            if trouble:
                raise LlmError(trouble)
        return self.enqueue(vid, {"url": url, "profile": profile, "options": options})

    def submit_bench(self, url: str, models: list[str], repeat: int = 1) -> dict:
        """A bench of its own id, so it neither replaces nor joins the run
        of the same video."""
        if not models:
            raise ValueError("models must name at least one model")
        return self.enqueue(
            f"bench:{video_id(url)}",
            {"kind": "bench", "url": url, "models": models, "repeat": max(1, repeat)},
        )

    def enqueue(self, vid: str, fields: dict) -> dict:
        """Put a job in the queue, or hand back the one already there."""
        with self.lock:
            job = self.jobs.get(vid)
            if job and job["status"] in ("queued", "running"):
                return dict(job)
            job = {
                "id": vid,
                **fields,
                "status": "queued",
                "step": None,
                "step_started": None,
                "queued": now(),
            }
            self.jobs[vid] = job
        self.queue.put(vid)
        return dict(job)

    def waiting(self) -> list[str]:
        """The ids in the queue, in order; the deque behind it, read under
        its own lock."""
        with self.queue.mutex:
            return list(self.queue.queue)

    def job(self, vid: str) -> dict | None:
        with self.lock:
            job = dict(self.jobs[vid]) if vid in self.jobs else None
        if job is None:
            return None
        if job["status"] == "running":
            job["position"] = 0
        elif job["status"] == "queued":
            # Between the worker's get and its first update the job is
            # queued but out of the queue: it is the next one, hence 0.
            waiting = self.waiting()
            job["position"] = waiting.index(vid) if vid in waiting else 0
        return job

    def cancel(self, vid: str) -> dict:
        """Out of the queue, or a flag the worker sees between two steps."""
        with self.lock:
            # Read, taken out and marked under one lock: in between the
            # worker could pull the job, and its "running" would then
            # overwrite the "cancelled" and the job would run anyway.
            # `begin` is the other half, it refuses a cancelled job.
            job = self.jobs.get(vid)
            if job is None:
                raise KeyError(vid)
            status = job["status"]
            if status == "queued":
                with self.queue.mutex:
                    if vid in self.queue.queue:
                        self.queue.queue.remove(vid)
                job.update(status="cancelled", finished=now())
            elif status == "running":
                self.cancelling.add(vid)
            else:
                raise NotReady(f"job {vid} is {status}")
        self.log.info("job %s: cancelled while %s", vid, status)
        return self.job(vid)

    def busy(self) -> str | None:
        """The id of a job that is still queued or running. /restart and
        /shutdown ask before they end this process: half-written outputs
        and a job list that is gone with it are worse than a 409."""
        with self.lock:
            return next(
                (
                    vid
                    for vid, job in self.jobs.items()
                    if job["status"] in ("queued", "running")
                ),
                None,
            )

    def update(self, vid: str, **fields: object) -> None:
        with self.lock:
            self.jobs[vid].update(fields)

    def step(self, vid: str, name: str, detail: str | None = None) -> None:
        """What run reports: a step starting, or a step done with a line
        about it (seconds, model, tokens, pictures)."""
        if detail is None:
            self.log.info("job %s: %s", vid, name)
            self.update(vid, step=name, step_started=now())
        else:
            self.log.info("job %s: %s %s", vid, name, detail)

    def work(self) -> None:
        while True:
            vid = self.queue.get()
            try:
                self.work_one(vid)
            # Blind on purpose, and around the whole job: a failure in the
            # lines that read what the run returned used to end this
            # thread, and every later job then stayed queued for good.
            except Exception as error:
                self.log.exception("job %s: the worker itself failed", vid)
                self.update(
                    vid,
                    status="error",
                    error={
                        "step": None,
                        "message": f"{type(error).__name__}: {error}",
                    },
                    finished=now(),
                )

    def begin(self, vid: str) -> dict | None:
        """Mark the job running, or None when there is nothing to run: a
        cancel that arrived after the worker pulled the job out of the
        queue has already marked it cancelled, and "running" must not
        overwrite that."""
        with self.lock:
            job = self.jobs.get(vid)
            if job is None or job["status"] == "cancelled":
                return None
            job.update(status="running", started=now())
            return dict(job)

    def work_one(self, vid: str) -> None:
        job = self.begin(vid)
        if job is None:
            self.log.info("job %s: cancelled before it started", vid)
            return
        profile = job.get("profile")

        def tell(step: str, detail: str | None = None, vid: str = vid) -> None:
            self.step(vid, step, detail)

        try:
            if job.get("kind") == "bench":
                rows = bench(
                    job["url"],
                    self.settings(),
                    job["models"],
                    job["repeat"],
                    progress=tell,
                )
                self.log.info("job %s: bench wrote %s rows", vid, len(rows))
                self.update(vid, bench=rows, status="done", finished=now())
                return
            settings = self.settings(profile, job.get("options"))
            self.log.info(
                "job %s: running %s, profile %s, %s, stt %s",
                vid,
                job["url"],
                profile,
                llm.describe(settings),
                settings.config["stt"],
            )
            result = self.runner(
                job["url"],
                settings,
                force=profile == "thorough",
                progress=tell,
                should_stop=lambda vid=vid: vid in self.cancelling,
            )
        # Blind on purpose: a bug in a step must not leave the job on
        # "running" for the extension to poll forever.
        except Exception as error:
            self.cancelling.discard(vid)
            self.log.exception("job %s: crashed in %s", vid, self.job(vid)["step"])
            self.update(
                vid,
                status="error",
                error={
                    "step": self.job(vid)["step"],
                    "message": f"{type(error).__name__}: {error}",
                },
                finished=now(),
            )
            return
        self.cancelling.discard(vid)
        # run stops between two steps when the cancel flag is up and
        # says so in the error; the job then reads cancelled, not failed.
        status = "done"
        if result["error"]:
            cancelled = result["error"]["message"] == "cancelled"
            status = "cancelled" if cancelled else "error"
            self.log.error(
                "job %s: %s %s",
                vid,
                result["error"]["step"],
                "cancelled" if cancelled else f"failed: {result['error']['message']}",
            )
        else:
            self.log.info(
                "job %s: done in %ss, %s+%s tokens, %.3f USD, wrote %s",
                vid,
                result["seconds"],
                result["input"],
                result["output"],
                result["usd"],
                ", ".join(result["written"]),
            )
        self.update(vid, **result, status=status, finished=now())

    def open(self, vid: str, what: str = "auto") -> str:
        """Start what the job wrote and return what was started: the note in
        Obsidian, the folder the outputs went to, or the best file there is."""
        if what not in OPEN_WHAT:
            raise ValueError(f"what must be one of {', '.join(OPEN_WHAT)}")
        job = self.job(vid)
        if job is None:
            raise KeyError(vid)
        if what == "folder":
            # The video's own folder, there whatever the job did; the
            # library above it when the video has none yet.
            settings = self.settings(job.get("profile"), job.get("options"))
            folder = video_folder(settings, vid)
            if not folder.is_dir():
                folder = settings.library
            folder.mkdir(parents=True, exist_ok=True)
            start(str(folder))
            return str(folder)
        if job["status"] != "done":
            raise NotReady(f"job {vid} is {job['status']}")
        for kind in ["obsidian"] if what == "obsidian" else OPEN_ORDER:
            if kind in job["written"]:
                target = job["written"][kind]
                if kind == "obsidian":
                    target = f"obsidian://open?path={quote(target)}"
                start(target)
                return target
        raise NotReady(f"job {vid} wrote no {what if what != 'auto' else 'output'}")


def relaunch(home: Path | None, port: int, overrides: dict) -> None:
    """Start a fresh service and leave. Called after this one has let go
    of the port. The arguments are rebuilt rather than taken from
    `sys.argv`, so the new process is the same service no matter how this
    one was started."""
    args = [sys.executable, "-m", __package__ or "video_tldr_service"]
    if home:
        args += ["--home", str(home)]
    for name in ("llm", "model", "stt", "style"):
        if overrides.get(name):
            args += [f"--{name}", str(overrides[name])]
    args += ["serve", "--port", str(port)]
    subprocess.Popen(  # our own arguments, no shell
        args,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )


Relauncher = Callable[[Path | None, int, dict], None]


class Server(ThreadingHTTPServer):
    # HTTPServer sets SO_REUSEADDR, and on Windows that lets a second
    # `serve` bind a port that is already listening: it prints a token
    # and answers nothing (2026-09-10). Without it the second start fails.
    allow_reuse_address = False

    def __init__(
        self,
        service: Service,
        port: int = PORT,
        relauncher: Relauncher = relaunch,
    ) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.service = service
        self.relauncher = relauncher

    def restart(self) -> None:
        """Answer first, then hand the port to a fresh process. A whole
        process is what it takes: a CUDA start that failed once stays
        failed for the life of this one, and the DLL search path only
        grows (2026-09-10)."""
        self.end(self.relauncher)

    def stop(self) -> None:
        """Answer first, then end. An update cannot replace the installed
        script while Windows holds it open, so it asks for this first."""
        self.end(None)

    def end(self, relauncher: Relauncher | None) -> None:
        def swap() -> None:
            time.sleep(RESTART_DELAY_SECONDS)  # let the answer reach the page
            try:
                self.shutdown()
                self.server_close()
                if relauncher:
                    relauncher(
                        self.service.home,
                        self.server_address[1],
                        self.service.overrides,
                    )
            except Exception:
                # The socket is gone by now. A Popen that threw must not
                # leave this process alive without one: it would answer
                # nothing and hold the port's name in the task list.
                self.service.log.exception("the hand-over failed; ending anyway")
            finally:
                os._exit(0)

        threading.Thread(target=swap, daemon=True, name="end").start()


class Handler(BaseHTTPRequestHandler):
    server: Server
    # A connection that never finishes its request line would otherwise
    # hold its thread for good; no request here takes that long to send.
    timeout = 30

    def do_GET(self) -> None:
        self.route("GET")

    def do_POST(self) -> None:
        self.route("POST")

    def do_PUT(self) -> None:
        self.route("PUT")

    def log_message(self, format: str, *args: object) -> None:
        # http.server's own line ("GET /config HTTP/1.1" 200), into the file
        # too; the signature is the base class's.
        self.server.service.log.info(format, *args)

    def guard(self) -> str | None:
        """Why this request is turned away, or None."""
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            return f"Host must be {expected}"
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(EXTENSION_ORIGINS):
            return "only the extension and the command line may call this service"
        return None

    def authorised(self) -> bool:
        if not self.server.service.token:
            return True
        # Compared as bytes: http.server decodes headers as latin-1, and
        # compare_digest refuses a str with a non-ASCII character in it,
        # which killed the handler thread instead of answering 401.
        sent = self.headers.get("Authorization", "").encode("latin-1", "replace")
        expected = f"Bearer {self.server.service.token}".encode()
        return hmac.compare_digest(sent, expected)

    def may_end(self, service: Service) -> None:
        """Turn a /restart or /shutdown away while a job is on, unless the
        body carries {"force": true}. The way past it stays open because the
        installer needs it: it frees the port before it replaces the exe
        (`video-tldr stop`, see `stop` below), and that call cannot wait
        for a run to finish. It stays out of the answer below: that text
        reaches the options page word for word, and the page has no force
        button, so naming one would ask a reader for JSON they cannot
        send (2026-09-10)."""
        if self.body().get("force"):
            return
        running = service.busy()
        if running:
            raise NotReady(
                f"job {running} is not finished yet; wait for it, "
                "or cancel it and try again"
            )

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        # Checked downwards as well: a negative length is not greater than
        # the limit, and `read(-1)` reads to the end of the connection, so
        # that body would be as big as the sender likes and hold this
        # thread until it stops sending.
        if not 0 <= length <= MAX_BODY_BYTES:
            # Answered without reading the body, so the rest of it stays
            # unread and the connection ends with the answer.
            self.close_connection = True
            raise TooLarge(f"the body must be 0 to {MAX_BODY_BYTES} bytes")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise TypeError("the body must be one JSON object")
        return data

    def route(self, method: str) -> None:
        denied = self.guard()
        if denied:
            return self.reply(HTTPStatus.FORBIDDEN, {"error": denied})
        if not self.authorised():
            return self.reply(
                HTTPStatus.UNAUTHORIZED,
                {"error": "Authorization: Bearer <token>; it stands in config.json"},
            )
        path, _, query_text = self.path.partition("?")
        parts = [p for p in path.split("/") if p]
        query = parse_qs(query_text)
        service = self.server.service
        try:
            if method == "POST" and parts == ["jobs"]:
                body = self.body()
                url = body.get("url")
                if not isinstance(url, str):
                    raise ValueError("url missing")
                profile = body.get("profile") or "fast"
                if not isinstance(profile, str):
                    raise TypeError("profile must be a string")
                options = body.get("options") or {}
                if not isinstance(options, dict):
                    raise TypeError("options must be one JSON object")
                return self.reply(
                    HTTPStatus.ACCEPTED, service.submit(url, profile, options)
                )
            if method == "GET" and len(parts) == 2 and parts[0] == "jobs":
                job = service.job(parts[1])
                if job is None:
                    raise KeyError(parts[1])
                return self.reply(HTTPStatus.OK, job)
            if method == "POST" and len(parts) == 3 and parts[0] == "jobs":
                if parts[2] == "cancel":
                    return self.reply(HTTPStatus.OK, service.cancel(parts[1]))
                if parts[2] != "open":
                    raise KeyError(parts[2])
                what = self.body().get("what") or "auto"
                if not isinstance(what, str):
                    raise TypeError("what must be a string")
                return self.reply(
                    HTTPStatus.OK, {"opened": service.open(parts[1], what)}
                )
            if method == "POST" and parts == ["bench"]:
                body = self.body()
                models = body.get("models")
                if not isinstance(models, list) or not all(
                    isinstance(name, str) for name in models
                ):
                    raise TypeError("models must be a list of model names")
                repeat = body.get("repeat") or 1
                if not isinstance(repeat, int):
                    raise TypeError("repeat must be a number")
                return self.reply(
                    HTTPStatus.ACCEPTED,
                    service.submit_bench(str(body.get("url") or ""), models, repeat),
                )
            if method == "GET" and parts == ["bench"]:
                return self.reply(
                    HTTPStatus.OK, {"rows": read_bench(service.settings())}
                )
            if method == "GET" and parts == ["config"]:
                return self.reply(HTTPStatus.OK, service.config())
            if method == "PUT" and parts == ["config"]:
                return self.reply(HTTPStatus.OK, service.update_config(self.body()))
            if method == "GET" and parts == ["models"]:
                backend = query.get("llm", [None])[0]
                return self.reply(HTTPStatus.OK, {"models": service.models(backend)})
            if method == "GET" and parts == ["log"]:
                lines = min(int(query.get("lines", [LOG_LINES])[0]), LOG_LINES_MAX)
                return self.reply(HTTPStatus.OK, {"lines": service.log_tail(lines)})
            if method == "GET" and parts == ["stats"]:
                return self.reply(HTTPStatus.OK, stats(service.settings()))
            if method == "GET" and parts == ["health"]:
                return self.reply(HTTPStatus.OK, service.health())
            if method == "POST" and parts == ["restart"]:
                # Answered first, swapped after: see Server.restart.
                self.may_end(service)
                self.reply(HTTPStatus.OK, {"restarting": True})
                service.log.info("restart asked for")
                return self.server.restart()
            if method == "POST" and parts == ["shutdown"]:
                self.may_end(service)
                self.reply(HTTPStatus.OK, {"stopping": True})
                service.log.info("shutdown asked for")
                return self.server.stop()
            if method == "POST" and parts == ["pick"]:
                body = self.body()
                kind = body.get("kind")
                if kind not in ("file", "folder"):
                    raise ValueError("kind must be file or folder")
                chosen = pick(kind, str(body.get("start") or ""))
                return self.reply(HTTPStatus.OK, {"path": chosen})
            raise KeyError(self.path)
        except (FetchError, ConfigError, LlmError, ValueError, TypeError) as error:
            self.reply(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except KeyError as error:
            self.reply(HTTPStatus.NOT_FOUND, {"error": f"no such thing: {error}"})
        except NotReady as error:
            self.reply(HTTPStatus.CONFLICT, {"error": str(error)})
        except TooLarge as error:
            self.reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": str(error)})
        except OSError as error:
            # `open` on a file that was cleared away, or a URL scheme with
            # no handler: an answer with the reason, not a dropped socket.
            self.reply(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def reply(self, status: HTTPStatus, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def stop(token: str, port: int = PORT) -> str:
    """Ask a running service to end, and say which of three things happened:
    one took the request and is ending, nothing was listening, or something
    is on the port that did not confirm the stop. An installer calls this
    before it replaces the script, because Windows will not let it be
    overwritten while the process that runs it is alive, and it reads this
    line. The first two cases leave the port free and let it go on safely,
    so the third must read like neither of them. It forces, unlike the
    options page's button: the port has to be free, and whoever typed
    `video-tldr stop` on this machine means it."""
    request = Request(
        f"http://127.0.0.1:{port}/shutdown",
        data=json.dumps({"force": True}).encode(),
        method="POST",
        headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=STOP_TIMEOUT_SECONDS) as answer:
            answer.read()
    except HTTPError as error:
        # Caught before URLError, which it inherits from: a service that
        # turns the request away has answered, so it is running and still
        # holds the script. A wrong token read as "no service" before
        # 2026-09-10, and the installer then went on to replace a file
        # Windows keeps open.
        trouble = f"it refused the request: {error.code} {error.reason}"
    except URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            # Nothing listening is the normal case for an installer on a
            # fresh machine, and for a second `stop`. Not an error to
            # report, and the only case in which the script is free.
            return f"no service on port {port} ({error.reason})"
        # A connect that timed out or was cut says nothing about whether a
        # process holds the port; a firewall that drops the packets looks
        # the same from here.
        trouble = f"the connection failed: {error.reason}"
    except (OSError, HTTPException) as error:
        # urlopen lets these past URLError, measured 2026-09-10 by serving
        # the request from a socket that answered nothing and from one that
        # closed at once: a read that timed out arrives as TimeoutError, a
        # dropped line as ConnectionResetError, which is what
        # http.client.RemoteDisconnected is. HTTPException covers an answer
        # that is no HTTP answer. /shutdown replies first and ends its
        # process right after, so a line that breaks here may well have
        # taken the request.
        trouble = f"no answer came back: {type(error).__name__}: {error}"
    else:
        return f"service on port {port} is stopping"
    return f"a service on port {port} may still be running, {trouble}"


def serve(home: Path | None, overrides: dict | None = None, port: int = PORT) -> int:
    """Listen until Ctrl+C. The console says whether a token is set and
    where it stands, never what it says."""
    service = Service(home, overrides)
    server = Server(service, port)
    # Flushed: started by the task scheduler with stdout in a file, the
    # lines would otherwise sit in the buffer until the service stops.
    print(
        f"video-tldr service {__version__} listening on http://127.0.0.1:{port}, "
        f"data under {service.settings().home}, log in {service.log_path}",
        flush=True,
    )
    if service.token:
        # Not the token itself: the task scheduler starts this with stdout
        # in a file, and a secret in a file that nothing guards is no
        # secret. Whoever pastes it into the options page reads it there.
        print(
            f"a token is set; it stands in {service.settings().config_path} "
            "and belongs in the extension's options",
            flush=True,
        )
    else:
        print(
            "no token set: any extension in the browser may use the service; "
            "`video-tldr config --set token=<secret>` turns the check on",
            flush=True,
        )
    service.log.info("video-tldr service %s listening on port %s", __version__, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
