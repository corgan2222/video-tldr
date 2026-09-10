"""The HTTP face of the pipeline, for the extension: 127.0.0.1 only, one
job at a time, the same `run` the command line calls.

The contract, every answer JSON:

    POST /jobs {"url", "profile"}   202 the job; 400 when the URL is no video
                                    or the profile unknown (fast, thorough)
    GET  /jobs/<id>                 200 the job; 404
    POST /jobs/<id>/open            200 {"opened": ...}; 409 until it is done
    GET  /config                    200 {"settings", "choices", "stt_models",
                                         "profiles", "home", "log", "version"}
    PUT  /config {key: value}       200 {"settings", ...}; 400 on a wrong key
    GET  /models?llm=<backend>      200 {"models": [...]}; 400 with the reason
    GET  /log?lines=<n>             200 {"lines": [...]}, the tail of serve.log
    GET  /stats                     200 what earlier runs took, see run.stats

A job carries `id` (the video id), `url`, `profile`, `status` (queued,
running, done, error), `step` and `step_started` (the running or last
step) and, once it ran, what `run` returned: `title`, `model`, `stt`,
`steps` with seconds, `images`, `usd`, `written`, `error`.

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
import secrets
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, quote

from . import __version__, llm
from .config import (
    FORMATS,
    LANGUAGES,
    LLM_BACKENDS,
    MASK,
    PROFILES,
    SECRETS,
    STT_ENGINES,
    STT_MODELS,
    ConfigError,
    Settings,
    profile_overrides,
    store,
)
from .fetch import FetchError, video_id
from .llm import LlmError
from .run import run, stats

PORT = 8765
# Every request, every job step and every traceback, next to the data:
# the console scrolls away, this stays. Three files of a megabyte each.
LOG_NAME = "serve.log"
LOG_BYTES = 1_000_000
LOG_FILES = 3
LOG_LINES = 50
LOG_LINES_MAX = 500
EXTENSION_ORIGINS = ("moz-extension://", "chrome-extension://")
# What `open` starts, the first that the job wrote.
OPEN_ORDER = ["obsidian", "pdf", "docx", "md", "summary"]
Runner = Callable[..., dict]


class NotReady(Exception):
    """The job exists but has nothing to open yet."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def start(target: str) -> None:
    """Open a file or a URL the way a double click would."""
    if hasattr(os, "startfile"):
        os.startfile(target)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target])


class Service:
    """The jobs, and the one thread that works them off."""

    def __init__(
        self, home: Path | None, overrides: dict | None = None, runner: Runner = run
    ) -> None:
        self.home = home
        self.overrides = overrides or {}
        self.runner = runner
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.queue: queue.Queue[str] = queue.Queue()
        self.token = self.ensure_token()
        self.log_path = self.settings().home / LOG_NAME
        self.log = self.open_log()
        threading.Thread(target=self.work, daemon=True, name="jobs").start()

    def settings(self, profile: str | None = None) -> Settings:
        # Loaded per use, not once: PUT /config changes the file underneath.
        # A profile sits on top of the file and under the command line.
        base = Settings.load(self.home, self.overrides)
        if not profile:
            return base
        overrides = {**profile_overrides(profile, base.config), **self.overrides}
        return Settings.load(self.home, overrides)

    def open_log(self) -> logging.Logger:
        log = logging.getLogger(f"corganshelper.serve.{id(self)}")
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

    def ensure_token(self) -> str:
        token = self.settings().config["token"]
        if not token:
            token = secrets.token_urlsafe(24)
            store(self.home, {"token": token})
        return token

    def config(self) -> dict:
        settings = self.settings()
        return {
            "settings": settings.shown(),
            "choices": {
                "llm": LLM_BACKENDS,
                "stt": STT_ENGINES,
                "formats": FORMATS,
                "language": list(LANGUAGES),
            },
            # Speed class, error rate and languages per transcriber, for
            # the options page to label the choice with.
            "stt_models": STT_MODELS,
            "profiles": list(PROFILES),
            "home": str(settings.home),
            "log": str(self.log_path),
            "version": __version__,
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
        # next start. `corganshelper config --set token=...` is the way.
        store(
            self.home,
            {
                k: v
                for k, v in values.items()
                if k != "token" and not (k in SECRETS and v == MASK)
            },
        )
        return self.config()

    def submit(self, url: str, profile: str = "fast") -> dict:
        vid = video_id(url)
        profile_overrides(profile, self.settings().config)  # names a wrong one
        with self.lock:
            job = self.jobs.get(vid)
            if job and job["status"] in ("queued", "running"):
                return dict(job)
            job = {
                "id": vid,
                "url": url,
                "profile": profile,
                "status": "queued",
                "step": None,
                "step_started": None,
                "queued": now(),
            }
            self.jobs[vid] = job
        self.queue.put(vid)
        return dict(job)

    def job(self, vid: str) -> dict | None:
        with self.lock:
            return dict(self.jobs[vid]) if vid in self.jobs else None

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
            job = self.job(vid)
            profile = job["profile"]
            self.update(vid, status="running", started=now())
            try:
                settings = self.settings(profile)
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
                    progress=lambda step, detail=None, vid=vid: self.step(
                        vid, step, detail
                    ),
                )
            # Blind on purpose: a bug in a step must not leave the job on
            # "running" for the extension to poll forever.
            except Exception as error:
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
                continue
            status = "error" if result["error"] else "done"
            if result["error"]:
                self.log.error(
                    "job %s: %s failed: %s",
                    vid,
                    result["error"]["step"],
                    result["error"]["message"],
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

    def open(self, vid: str) -> str:
        """Start the best file the job wrote and return what was started."""
        job = self.job(vid)
        if job is None:
            raise KeyError(vid)
        if job["status"] != "done":
            raise NotReady(f"job {vid} is {job['status']}")
        for kind in OPEN_ORDER:
            if kind in job["written"]:
                target = job["written"][kind]
                if kind == "obsidian":
                    target = f"obsidian://open?path={quote(target)}"
                start(target)
                return target
        raise NotReady(f"job {vid} wrote nothing to open")


class Server(ThreadingHTTPServer):
    # HTTPServer sets SO_REUSEADDR, and on Windows that lets a second
    # `serve` bind a port that is already listening: it prints a token
    # and answers nothing (2026-09-10). Without it the second start fails.
    allow_reuse_address = False

    def __init__(self, service: Service, port: int = PORT) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.service = service


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
        # Compared as bytes: http.server decodes headers as latin-1, and
        # compare_digest refuses a str with a non-ASCII character in it,
        # which killed the handler thread instead of answering 401.
        sent = self.headers.get("Authorization", "").encode("latin-1", "replace")
        expected = f"Bearer {self.server.service.token}".encode()
        return hmac.compare_digest(sent, expected)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
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
                {"error": "Authorization: Bearer <token>; serve prints the token"},
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
                return self.reply(HTTPStatus.ACCEPTED, service.submit(url, profile))
            if method == "GET" and len(parts) == 2 and parts[0] == "jobs":
                job = service.job(parts[1])
                if job is None:
                    raise KeyError(parts[1])
                return self.reply(HTTPStatus.OK, job)
            if method == "POST" and len(parts) == 3 and parts[0] == "jobs":
                if parts[2] != "open":
                    raise KeyError(parts[2])
                return self.reply(HTTPStatus.OK, {"opened": service.open(parts[1])})
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
            raise KeyError(self.path)
        except (FetchError, ConfigError, LlmError, ValueError, TypeError) as error:
            self.reply(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except KeyError as error:
            self.reply(HTTPStatus.NOT_FOUND, {"error": f"no such thing: {error}"})
        except NotReady as error:
            self.reply(HTTPStatus.CONFLICT, {"error": str(error)})
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


def serve(home: Path | None, overrides: dict | None = None, port: int = PORT) -> int:
    """Listen until Ctrl+C. The token goes to the console once, for the
    options page of the extension."""
    service = Service(home, overrides)
    server = Server(service, port)
    # Flushed: started by the task scheduler with stdout in a file, the
    # lines would otherwise sit in the buffer until the service stops.
    print(
        f"video-tldr service {__version__} listening on http://127.0.0.1:{port}, "
        f"data under {service.settings().home}, log in {service.log_path}",
        flush=True,
    )
    print(
        f"token: {service.token}  (paste it into the extension's options)",
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
