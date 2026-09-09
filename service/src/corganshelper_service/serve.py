"""The HTTP face of the pipeline, for the extension: 127.0.0.1 only, one
job at a time, the same `run` the command line calls.

The contract, every answer JSON:

    POST /jobs {"url": ...}     202 the job; 400 when the URL is no video
    GET  /jobs/<id>             200 the job; 404
    POST /jobs/<id>/open        200 {"opened": ...}; 409 until it is done
    GET  /config                200 {"settings", "choices", "home", "version"}
    PUT  /config {key: value}   200 {"settings", ...}; 400 on a wrong key

A job carries `id` (the video id), `url`, `status` (queued, running,
done, error), `step` (the running or last step) and, once it ran, what
`run` returned: `title`, `steps`, `images`, `usd`, `written`, `error`.

Who gets in, after decision 0001: the Host header must read
127.0.0.1:<port>, an Origin header must be absent (curl, the command
line) or start with moz-extension:// or chrome-extension://, and
Authorization must carry the token from config.json. No CORS headers go
out, so a web page fails its preflight before it reaches any of this.

One job at a time on purpose: two `frames` runs side by side both broke
in the clip download (2026-09-10).
"""

from __future__ import annotations

import hmac
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from . import __version__
from .analyze import LANGUAGES
from .config import (
    FORMATS,
    LLM_BACKENDS,
    MASK,
    SECRETS,
    STT_ENGINES,
    ConfigError,
    Settings,
    store,
)
from .fetch import FetchError, video_id
from .run import run

PORT = 8765
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
        threading.Thread(target=self.work, daemon=True, name="jobs").start()

    def settings(self) -> Settings:
        # Loaded per use, not once: PUT /config changes the file underneath.
        return Settings.load(self.home, self.overrides)

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
            "home": str(settings.home),
            "version": __version__,
        }

    def update_config(self, values: dict) -> dict:
        # The options page sends back what GET /config showed it; a masked
        # secret must not overwrite the real one.
        store(
            self.home,
            {k: v for k, v in values.items() if not (k in SECRETS and v == MASK)},
        )
        return self.config()

    def submit(self, url: str) -> dict:
        vid = video_id(url)
        with self.lock:
            job = self.jobs.get(vid)
            if job and job["status"] in ("queued", "running"):
                return dict(job)
            job = {
                "id": vid,
                "url": url,
                "status": "queued",
                "step": None,
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

    def work(self) -> None:
        while True:
            vid = self.queue.get()
            url = self.job(vid)["url"]
            self.update(vid, status="running", started=now())
            try:
                result = self.runner(
                    url,
                    self.settings(),
                    progress=lambda step, vid=vid: self.update(vid, step=step),
                )
            # Blind on purpose: a bug in a step must not leave the job on
            # "running" for the extension to poll forever.
            except Exception as error:  # noqa: BLE001
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
    def __init__(self, service: Service, port: int = PORT) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.service = service


class Handler(BaseHTTPRequestHandler):
    server: Server

    def do_GET(self) -> None:
        self.route("GET")

    def do_POST(self) -> None:
        self.route("POST")

    def do_PUT(self) -> None:
        self.route("PUT")

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
        sent = self.headers.get("Authorization", "")
        return hmac.compare_digest(sent, f"Bearer {self.server.service.token}")

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
        parts = [p for p in self.path.partition("?")[0].split("/") if p]
        service = self.server.service
        try:
            if method == "POST" and parts == ["jobs"]:
                url = self.body().get("url")
                if not isinstance(url, str):
                    raise ValueError("url missing")
                return self.reply(HTTPStatus.ACCEPTED, service.submit(url))
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
            raise KeyError(self.path)
        except (FetchError, ConfigError, ValueError, TypeError) as error:
            self.reply(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except KeyError as error:
            self.reply(HTTPStatus.NOT_FOUND, {"error": f"no such thing: {error}"})
        except NotReady as error:
            self.reply(HTTPStatus.CONFLICT, {"error": str(error)})

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
        f"corganshelper {__version__} listening on http://127.0.0.1:{port}, "
        f"data under {service.settings().home}",
        flush=True,
    )
    print(
        f"token: {service.token}  (paste it into the extension's options)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
