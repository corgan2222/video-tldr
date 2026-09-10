import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from video_tldr_service import serve as module
from video_tldr_service.config import Settings, store
from video_tldr_service.fetch import video_folder, work_folder
from video_tldr_service.serve import Server, Service

URL = "https://youtu.be/x_x_x_x_x_x"
SECOND_URL = "https://youtu.be/aaaaaaaaaaa"
THIRD_URL = "https://youtu.be/bbbbbbbbbbb"


class Runner:
    """Stands in for run: waits at the gate, then answers like run does."""

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.calls = 0
        self.fail = None
        self.seen: list[tuple] = []
        self.configs: list[dict] = []
        self.written = {"summary": "C:/w/summary.md", "obsidian": "C:/v/n.md"}

    def __call__(
        self, url, settings, progress=None, force=False, should_stop=None, **kwargs
    ):
        self.calls += 1
        self.seen.append((settings.config["stt"], settings.config["model"], force))
        self.configs.append(dict(settings.config))
        if progress:
            progress("fetch")
            progress("fetch", "0.1s, A video, 1 caption tracks")
        self.gate.wait(timeout=5)
        if self.fail:
            raise self.fail
        if should_stop and should_stop():
            # What run does when the flag went up between two steps.
            return {
                **self.result(url, settings),
                "error": {"step": "analyze", "message": "cancelled"},
            }
        return self.result(url, settings)

    def result(self, url, settings):
        return {
            "id": "x_x_x_x_x_x",
            "url": url,
            "title": "A video",
            "model": "claude:sonnet",
            "stt": settings.config["stt"],
            "step": "render",
            "steps": {"fetch": 0.1},
            "seconds": 0.1,
            "images": 0,
            "input": 0,
            "output": 0,
            "usd": 0.0,
            "written": dict(self.written),
            "error": None,
        }


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def service(tmp_path, runner):
    # With a token set, so the tests below see the check; without one the
    # service answers everyone on 127.0.0.1 (test below). The backend
    # check answers "all well" here; the two tests about it set their own.
    store(tmp_path, {"token": "secret"})
    return Service(tmp_path, runner=runner, checker=lambda _: None)


@pytest.fixture
def server(service):
    # Port 0: the kernel picks a free one, so parallel test runs never meet.
    server = Server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def call(server, method, path, body=None, token=None, headers=None):
    """Status and JSON of one request, with the token unless told not to."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}{path}", data=data, method=method
    )
    if token is not False:
        request.add_header("Authorization", f"Bearer {token or server.service.token}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_for(server, vid, status):
    for _ in range(100):
        _, job = call(server, "GET", f"/jobs/{vid}")
        if job["status"] == status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job never became {status}: {job}")


def test_without_a_token_in_config_json_nobody_needs_one(tmp_path, runner):
    open_service = Service(tmp_path / "open", runner=runner)
    server = Server(open_service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert open_service.token == ""
        assert call(server, "GET", "/config", token=False)[0] == 200
        assert call(server, "GET", "/config", token="anything")[0] == 200
        # Host and Origin still keep web pages out.
        page = {"Origin": "https://evil.example"}
        assert call(server, "GET", "/config", headers=page, token=False)[0] == 403
    finally:
        server.shutdown()
        server.server_close()


def test_without_the_token_nothing_answers(server):
    assert call(server, "GET", "/config", token=False)[0] == 401
    assert call(server, "GET", "/config", token="wrong")[0] == 401
    assert call(server, "POST", "/jobs", {"url": URL}, token=False)[0] == 401


def test_a_web_page_and_a_foreign_host_are_turned_away(server):
    page = {"Origin": "https://evil.example"}
    assert call(server, "GET", "/config", headers=page)[0] == 403
    host = {"Host": f"localhost:{server.server_port}"}
    code, answer = call(server, "GET", "/config", headers=host)
    assert code == 403
    assert "Host must be 127.0.0.1" in answer["error"]


def test_the_extension_origins_get_in(server):
    for origin in ("moz-extension://1234", "chrome-extension://abcd"):
        code, answer = call(server, "GET", "/config", headers={"Origin": origin})
        assert code == 200
        assert "Access-Control-Allow-Origin" not in answer


def test_a_job_runs_once_from_queued_to_done(server, runner):
    runner.gate.clear()
    code, job = call(server, "POST", "/jobs", {"url": URL})
    assert code == 202
    assert (job["id"], job["status"], job["profile"]) == (
        "x_x_x_x_x_x",
        "queued",
        "fast",
    )

    # A second click on the same video joins the running job.
    assert call(server, "POST", "/jobs", {"url": URL})[1]["id"] == job["id"]
    job = wait_for(server, job["id"], "running")
    assert job["step"] == "fetch"
    assert job["step_started"]
    assert call(server, "POST", f"/jobs/{job['id']}/open")[0] == 409

    runner.gate.set()
    job = wait_for(server, job["id"], "done")
    assert job["title"] == "A video"
    assert job["written"]["obsidian"] == "C:/v/n.md"
    assert job["finished"]
    assert runner.calls == 1
    # fast: captions when there are any, the stored model, cached results kept.
    assert runner.seen == [("auto", "", False)]


def test_thorough_redoes_everything_with_the_large_whisper_and_the_best_model(
    server, runner
):
    code, job = call(server, "POST", "/jobs", {"url": URL, "profile": "thorough"})
    assert code == 202
    wait_for(server, job["id"], "done")

    assert runner.seen == [("whisper-large", "opus", True)]
    code, answer = call(server, "POST", "/jobs", {"url": URL, "profile": "quick"})
    assert code == 400
    assert "profile must be one of fast, thorough" in answer["error"]


def test_a_backend_that_refuses_the_key_stops_the_job_at_the_gate(server, runner):
    """Asked for on 2026-09-10: a 401 arrived after fetch and transcribe
    had already run, and the popup showed it as a failed step."""
    server.service.checker = lambda _: "openai: the server did not accept the key"

    code, answer = call(server, "POST", "/jobs", {"url": URL})

    assert code == 400
    assert answer["error"] == "openai: the server did not accept the key"
    assert runner.calls == 0
    assert call(server, "GET", f"/jobs/{'x_x_x_x_x_x'}")[0] == 404


def test_a_video_whose_model_steps_are_cached_needs_no_backend(server, runner):
    """Every answer of the model is on disk, so the run asks no server;
    a check at the gate must not turn such a job away."""
    asked = []
    server.service.checker = lambda _: asked.append(1) or "lmstudio: no answer"
    work = work_folder(server.service.settings(), "x_x_x_x_x_x")
    work.mkdir(parents=True)
    for name in ("analysis.json", "enrich.json", "frames.json"):
        (work / name).write_text("{}", encoding="utf-8")

    code, job = call(server, "POST", "/jobs", {"url": URL})

    assert code == 202
    assert asked == []
    wait_for(server, job["id"], "done")
    # A video with nothing on disk is the other case: that one is asked.
    code, answer = call(server, "POST", "/jobs", {"url": SECOND_URL})
    assert code == 400 and asked == [1]
    assert answer["error"] == "lmstudio: no answer"


def test_open_starts_the_note_in_obsidian_first(server, runner, monkeypatch):
    started = []
    monkeypatch.setattr(module, "start", started.append)
    code, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "done")

    code, answer = call(server, "POST", f"/jobs/{job['id']}/open")

    assert code == 200
    assert answer["opened"] == "obsidian://open?path=C%3A/v/n.md"
    assert started == [answer["opened"]]


def test_the_options_of_one_job_beat_the_profile_and_a_wrong_one_is_a_400(
    server, runner
):
    options = {"style": "caveman", "timestamps": "off", "cleanup": "on"}

    code, job = call(server, "POST", "/jobs", {"url": URL, "options": options})

    assert code == 202
    assert job["options"] == options
    wait_for(server, job["id"], "done")
    assert runner.configs[0]["style"] == "caveman"
    assert runner.configs[0]["timestamps"] == "off"
    assert runner.configs[0]["cleanup"] == "on"
    # Left out: the run keeps what config.json says.
    assert runner.configs[0]["condensed"] == "off"

    body = {"url": URL, "options": {"colour": "blue"}}
    code, answer = call(server, "POST", "/jobs", body)
    assert code == 400
    assert "unknown setting colour" in answer["error"]
    body = {"url": URL, "options": {"style": "pirate"}}
    code, answer = call(server, "POST", "/jobs", body)
    assert code == 400
    assert "style must be one of" in answer["error"]
    assert call(server, "POST", "/jobs", {"url": URL, "options": "caveman"})[0] == 400

    # A job says how to summarise, not which program to run, where to
    # write, or where the API key travels. Those are the machine owner's,
    # through the settings page or the command line. This service has a
    # token set, and these stay 400 anyway: a job is the road a foreign
    # extension in the browser takes, so the bar there is not the token's
    # to lift.
    for key, value in (
        ("browser", r"C:\Windows\System32\calc.exe"),
        ("download_dir", r"C:\Users\someone\Startup"),
        ("openai_base_url", "https://elsewhere.example/v1"),
        ("openai_api_key", "sk-whatever"),
        ("pdf_template", r"C:\x\evil.html"),
    ):
        code, answer = call(
            server, "POST", "/jobs", {"url": URL, "options": {key: value}}
        )
        assert code == 400, key
        assert f"{key} may not be set over HTTP" in answer["error"]
        assert "video-tldr config --set" in answer["error"]


def test_a_waiting_job_says_how_many_are_ahead_of_it(server, runner):
    runner.gate.clear()
    first = call(server, "POST", "/jobs", {"url": URL})[1]["id"]
    wait_for(server, first, "running")
    second = call(server, "POST", "/jobs", {"url": SECOND_URL})[1]["id"]
    third = call(server, "POST", "/jobs", {"url": THIRD_URL})[1]["id"]

    assert call(server, "GET", f"/jobs/{first}")[1]["position"] == 0
    assert call(server, "GET", f"/jobs/{second}")[1]["position"] == 0
    assert call(server, "GET", f"/jobs/{third}")[1]["position"] == 1

    runner.gate.set()
    done = wait_for(server, first, "done")
    assert "position" not in done


def test_a_queued_job_leaves_the_queue_when_it_is_cancelled(server, runner):
    runner.gate.clear()
    first = call(server, "POST", "/jobs", {"url": URL})[1]["id"]
    wait_for(server, first, "running")
    waiting = call(server, "POST", "/jobs", {"url": SECOND_URL})[1]["id"]

    code, job = call(server, "POST", f"/jobs/{waiting}/cancel")

    assert (code, job["status"]) == (200, "cancelled")
    runner.gate.set()
    wait_for(server, first, "done")
    assert runner.calls == 1
    assert call(server, "GET", f"/jobs/{waiting}")[1]["status"] == "cancelled"
    # Nothing to cancel, and nothing to cancel any more.
    assert call(server, "POST", "/jobs/nope/cancel")[0] == 404
    code, answer = call(server, "POST", f"/jobs/{first}/cancel")
    assert code == 409
    assert "is done" in answer["error"]


def test_a_running_job_stops_between_two_steps(server, runner):
    runner.gate.clear()
    _, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "running")

    code, answer = call(server, "POST", f"/jobs/{job['id']}/cancel")
    assert (code, answer["status"]) == (200, "running")
    runner.gate.set()

    job = wait_for(server, job["id"], "cancelled")
    assert job["error"] == {"step": "analyze", "message": "cancelled"}


def test_open_takes_the_note_the_folder_or_what_there_is(
    server, runner, monkeypatch, tmp_path
):
    started = []
    monkeypatch.setattr(module, "start", started.append)
    _, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "done")

    code, answer = call(server, "POST", f"/jobs/{job['id']}/open", {"what": "obsidian"})
    assert (code, answer["opened"]) == (200, "obsidian://open?path=C%3A/v/n.md")

    settings = Settings.load(tmp_path)
    # This run left no folder behind, so the library above it opens.
    code, answer = call(server, "POST", f"/jobs/{job['id']}/open", {"what": "folder"})
    assert (code, answer["opened"]) == (200, str(settings.library))

    # With the video's own folder there, that one opens.
    work_folder(settings, "x_x_x_x_x_x").mkdir(parents=True)
    _, answer = call(server, "POST", f"/jobs/{job['id']}/open", {"what": "folder"})
    assert answer["opened"] == str(video_folder(settings, "x_x_x_x_x_x"))
    assert started[-1] == answer["opened"]

    assert call(server, "POST", f"/jobs/{job['id']}/open", {"what": "email"})[0] == 400


def test_open_obsidian_says_so_when_the_job_wrote_no_note(server, runner, monkeypatch):
    monkeypatch.setattr(module, "start", lambda target: None)
    runner.written = {"summary": "C:/w/summary.md"}
    _, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "done")

    code, answer = call(server, "POST", f"/jobs/{job['id']}/open", {"what": "obsidian"})

    assert code == 409
    assert "wrote no obsidian" in answer["error"]
    # Without a wish the summary is opened instead.
    assert call(server, "POST", f"/jobs/{job['id']}/open")[0] == 200


def test_a_bench_runs_through_the_same_queue_and_keeps_its_rows(
    server, monkeypatch, tmp_path
):
    rows = [{"model": "qwen", "run": 1, "seconds": 12.0, "output": 40}]
    seen = []

    def fake_bench(url, settings, models, repeat, progress=None):
        seen.append((url, models, repeat))
        if progress:
            progress("bench qwen 1")
        return rows

    monkeypatch.setattr(module, "bench", fake_bench)

    code, job = call(
        server, "POST", "/bench", {"url": URL, "models": ["qwen"], "repeat": 2}
    )

    assert code == 202
    assert (job["id"], job["kind"], job["status"]) == (
        "bench:x_x_x_x_x_x",
        "bench",
        "queued",
    )
    job = wait_for(server, job["id"], "done")
    assert job["bench"] == rows
    assert seen == [(URL, ["qwen"], 2)]
    assert call(server, "POST", "/bench", {"url": URL, "models": []})[0] == 400
    assert call(server, "POST", "/bench", {"url": URL, "models": "qwen"})[0] == 400
    assert call(server, "POST", "/bench", {"url": "https://example.org"})[0] == 400


def test_bench_hands_back_every_row_measured_so_far(server, tmp_path):
    assert call(server, "GET", "/bench")[1] == {"rows": []}
    (tmp_path / "bench.json").write_text(
        json.dumps([{"model": "qwen", "run": 1}]), "utf-8"
    )

    code, answer = call(server, "GET", "/bench")

    assert (code, answer) == (200, {"rows": [{"model": "qwen", "run": 1}]})


def test_a_bad_url_and_an_unknown_job_are_errors_with_a_reason(server):
    code, answer = call(server, "POST", "/jobs", {"url": "https://example.org"})
    assert code == 400
    assert "not a YouTube video URL" in answer["error"]
    assert call(server, "POST", "/jobs", {})[0] == 400
    assert call(server, "GET", "/jobs/nope")[0] == 404
    assert call(server, "GET", "/nothing")[0] == 404


def test_a_body_far_bigger_than_a_job_is_refused_before_it_is_read(server, runner):
    """Content-Length is what the read would allocate, so the limit is
    checked on the header, not on what arrives. These requests send no body
    at all and only claim one: an answer instead of a request that hangs
    until its timeout is the proof that the header alone decided. A body
    that really arrived and stayed unread would also make the answer racy,
    because the close after it sends a RST."""
    for claimed in (module.MAX_BODY_BYTES + 1, 99_999_999, -1):
        code, answer = call(
            server, "POST", "/jobs", headers={"Content-Length": str(claimed)}
        )

        # A negative length is not greater than the limit, and `read(-1)`
        # reads to the end of the connection: unbounded, in memory.
        assert code == 413, claimed
        assert str(module.MAX_BODY_BYTES) in answer["error"]
    assert runner.calls == 0
    # The limit leaves room for every body the extension really sends.
    assert call(server, "POST", "/jobs", {"url": URL})[0] == 202


def test_serve_says_a_token_is_set_without_saying_which(tmp_path, monkeypatch, capsys):
    """The task scheduler starts the service with stdout in a file; the
    token must not end up in it."""
    store(tmp_path, {"token": "s3cret-token-value"})

    class Quiet:
        """A server that ends the moment it would listen."""

        def __init__(self, service, port):
            self.service = service

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(module, "Server", Quiet)

    assert module.serve(tmp_path, port=0) == 0

    printed = capsys.readouterr().out
    assert "s3cret-token-value" not in printed
    assert "a token is set" in printed
    assert "config.json" in printed


def test_a_crash_inside_run_ends_the_job_as_an_error(server, runner):
    runner.fail = RuntimeError("boom")
    _, job = call(server, "POST", "/jobs", {"url": URL})

    job = wait_for(server, job["id"], "error")

    assert job["error"] == {"step": "fetch", "message": "RuntimeError: boom"}


def test_config_is_read_and_written_through_the_service(server, tmp_path):
    code, answer = call(server, "GET", "/config")
    assert code == 200
    assert answer["settings"]["language"] == "de"
    assert answer["settings"]["token"] == "********"
    assert answer["choices"]["llm"][0] == "claude"
    assert answer["profiles"] == ["fast", "thorough"]
    assert answer["home"] == str(tmp_path.resolve())

    # The options page sends back what it was shown, masks included.
    code, answer = call(
        server, "PUT", "/config", {"language": "en", "token": "********"}
    )
    assert code == 200
    assert answer["settings"]["language"] == "en"
    assert Settings.load(tmp_path).config["token"] == server.service.token

    code, answer = call(server, "PUT", "/config", {"colour": "blue"})
    assert code == 400
    assert "unknown setting colour" in answer["error"]
    code, answer = call(server, "PUT", "/config", {"model": 5})
    assert code == 400
    assert "every setting is a string" in answer["error"]


def test_with_a_token_the_options_page_saves_every_field_it_shows(server, tmp_path):
    """A caller that got past the Authorization check is authenticated and
    may set what the command line may, so the program, the paths and the
    vendor URLs are stored. The page sends one key per request; this body
    holds them together to show that the token lifts the bar for every one
    of them (2026-09-10)."""
    whole_page = {
        "language": "en",
        "browser": r"C:\Program Files\Chrome\chrome.exe",
        "download_dir": str(tmp_path / "out"),
        "pdf_template": str(tmp_path / "look.html"),
        "obsidian_vault": str(tmp_path / "vault"),
        "obsidian_folder": "Clips",
        "openai_base_url": "https://api.openai.com/v1",
        "anthropic_api_key": "sk-fake",
        "openai_api_key": "********",
        "token": "********",
    }

    code, answer = call(server, "PUT", "/config", whole_page)

    assert code == 200
    assert answer["settings"]["browser"].endswith("chrome.exe")
    stored = Settings.load(tmp_path).config
    assert stored["download_dir"] == str(tmp_path / "out")
    assert stored["obsidian_vault"] == str(tmp_path / "vault")
    assert stored["anthropic_api_key"] == "sk-fake"
    # A masked secret counts as "keep it", and so does the token.
    assert stored["openai_api_key"] == ""
    assert stored["token"] == server.service.token
    # A wrong value is still a 400, token or no token.
    assert call(server, "PUT", "/config", {"stt": "loud"})[0] == 400


def test_without_a_token_config_keeps_the_program_and_the_key_off_the_wire(
    tmp_path, runner
):
    """Without a token any extension in the browser may call this service,
    so then the fields that name a program to start, a place to write or
    where the API key travels are refused, and the answer names both ways
    in: the command line on this machine, or a token."""
    open_service = Service(tmp_path, runner=runner)
    server = Server(open_service, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert open_service.token == ""
        for key, value in (
            ("browser", r"C:\Windows\System32\calc.exe"),
            ("download_dir", r"C:\Users\someone\Startup"),
            ("pdf_template", r"C:\x\evil.html"),
            ("obsidian_vault", r"C:\x\vault"),
            ("openai_base_url", "https://elsewhere.example/v1"),
            ("lmstudio_url", "https://elsewhere.example/v1"),
            ("ollama_url", "https://elsewhere.example/v1"),
            ("openai_api_key", "sk-whatever"),
            ("anthropic_api_key", "sk-whatever"),
        ):
            code, answer = call(server, "PUT", "/config", {key: value}, token=False)
            assert code == 400, key
            assert f"{key} may not be set over HTTP" in answer["error"]
            assert "video-tldr config --set" in answer["error"]
            assert "or a token set there" in answer["error"]
            assert Settings.load(tmp_path).config[key] != value

        # The page sends one key per request, so a refusal costs it that
        # key alone. A caller that does join several still gets the whole
        # body refused, barred key and switches together.
        body = {"style": "noslop", "browser": "x.exe"}
        assert call(server, "PUT", "/config", body, token=False)[0] == 400
        assert Settings.load(tmp_path).config["style"] == "normal"
        # The fields that only say how to summarise still save, and so does
        # the subfolder inside the vault.
        body = {"style": "noslop", "obsidian_folder": "Clips"}
        assert call(server, "PUT", "/config", body, token=False)[0] == 200
        stored = Settings.load(tmp_path).config
        assert (stored["style"], stored["obsidian_folder"]) == ("noslop", "Clips")
    finally:
        server.shutdown()
        server.server_close()


def test_a_token_sent_to_config_is_not_written(server, tmp_path):
    # This process would keep its own token anyway; the file must not drift.
    code, _ = call(server, "PUT", "/config", {"token": "new"})

    assert code == 200
    assert Settings.load(tmp_path).config["token"] == server.service.token


def test_a_non_ascii_authorization_header_is_a_401_not_a_dead_thread(server):
    # http.server hands the header over as latin-1 text; compare_digest
    # refuses such a str and killed the handler thread (2026-09-10).
    code, answer = call(server, "GET", "/config", token="tüken")

    assert code == 401
    assert "Bearer" in answer["error"]


def test_open_answers_with_the_reason_when_the_file_is_gone(server, monkeypatch):
    def gone(target):
        raise FileNotFoundError(f"no such file: {target}")

    monkeypatch.setattr(module, "start", gone)
    _, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "done")

    code, answer = call(server, "POST", f"/jobs/{job['id']}/open")

    assert code == 500
    assert "no such file" in answer["error"]


def test_a_second_serve_on_the_same_port_fails_instead_of_answering_nothing(
    server, service
):
    with pytest.raises(OSError):
        Server(service, server.server_port)


def test_models_lists_what_a_backend_offers_and_says_why_not(server, monkeypatch):
    code, answer = call(server, "GET", "/models")
    assert code == 200
    assert "sonnet" in answer["models"]
    assert call(server, "GET", "/models?llm=claude")[1] == answer
    assert call(server, "GET", "/models?llm=nonsense")[0] == 400

    def unreachable(settings):
        raise module.LlmError(f"{settings.config['llm']}: no server")

    monkeypatch.setattr(module.llm, "models", unreachable)
    code, answer = call(server, "GET", "/models?llm=ollama")
    assert code == 400
    assert answer["error"] == "ollama: no server"

    # The options page labels the transcribers with this table.
    _, config = call(server, "GET", "/config")
    assert config["stt_models"]["parakeet"]["speed"] == "fast"


def test_the_log_names_every_request_and_what_a_job_did(server, runner, tmp_path):
    _, config = call(server, "GET", "/config")
    assert config["log"] == str(tmp_path.resolve() / "serve.log")
    _, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "done")
    runner.fail = RuntimeError("boom")
    _, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "error")

    log = (tmp_path / "serve.log").read_text(encoding="utf-8")

    assert '"GET /config HTTP/1.1" 200' in log
    assert "running https://youtu.be/x_x_x_x_x_x, profile fast, claude:sonnet" in log
    assert "job x_x_x_x_x_x: fetch\n" in log
    assert "job x_x_x_x_x_x: fetch 0.1s, A video, 1 caption tracks" in log
    assert "done in 0.1s, 0+0 tokens, 0.000 USD, wrote summary, obsidian" in log
    assert "crashed in fetch" in log and "RuntimeError: boom" in log

    # The popup shows the tail of the same file.
    code, answer = call(server, "GET", "/log?lines=3")
    assert code == 200
    assert len(answer["lines"]) == 3
    code, answer = call(server, "GET", "/log?lines=30")
    assert any("RuntimeError: boom" in line for line in answer["lines"])


def test_health_shows_four_lights_and_config_the_defaults(server, monkeypatch):
    monkeypatch.setattr(
        module.llm, "status", lambda settings: {"ok": True, "detail": "claude CLI"}
    )
    monkeypatch.setattr(
        module, "stt_status", lambda settings: {"ok": False, "detail": "no GPU"}
    )
    monkeypatch.setattr(
        module.llm,
        "capabilities",
        lambda settings: {"vision": True, "context": 200000, "detail": "sonnet"},
        raising=False,
    )

    code, answer = call(server, "GET", "/health")

    assert code == 200
    assert answer["service"]["ok"] is True
    assert "video-tldr service" in answer["service"]["detail"]
    assert answer["llm"] == {"ok": True, "detail": "claude CLI"}
    assert answer["stt"] == {"ok": False, "detail": "no GPU"}
    assert answer["capabilities"]["vision"] is True
    _, config = call(server, "GET", "/config")
    assert config["default_models"]["claude"] == "sonnet"
    assert isinstance(config["browser_found"], str)


def test_health_says_not_checked_while_the_backend_cannot_tell(server, monkeypatch):
    # `capabilities` is younger than the rest of llm; a service that runs
    # against an older module must still answer the popup.
    monkeypatch.delattr(module.llm, "capabilities", raising=False)

    code, answer = call(server, "GET", "/health")

    assert code == 200
    # Nothing known is not a red light: the run may well work.
    assert answer["capabilities"]["ok"] is True
    assert answer["capabilities"]["detail"] == "not checked"


def test_the_capability_light_turns_red_with_the_reason_in_it(server, monkeypatch):
    def blind(settings):
        return {"vision": False, "context": 8192, "detail": "tiny-7b"}

    monkeypatch.setattr(module.llm, "capabilities", blind)

    _, answer = call(server, "GET", "/health")

    assert answer["capabilities"]["ok"] is False
    detail = answer["capabilities"]["detail"]
    assert "takes no pictures" in detail
    assert "context 8192 tokens is below 32768" in detail

    monkeypatch.setattr(
        module.llm,
        "capabilities",
        lambda settings: {"vision": True, "context": 32768, "detail": "big"},
    )
    assert call(server, "GET", "/health")[1]["capabilities"]["ok"] is True


def test_pick_opens_a_dialog_on_this_desktop_and_returns_the_path(server, monkeypatch):
    asked = []

    def fake_pick(kind, start=""):
        asked.append((kind, start))
        return "D:/Vaults/Notes" if kind == "folder" else ""

    monkeypatch.setattr(module, "pick", fake_pick)

    code, answer = call(server, "POST", "/pick", {"kind": "folder", "start": "D:/"})
    assert (code, answer) == (200, {"path": "D:/Vaults/Notes"})
    code, answer = call(server, "POST", "/pick", {"kind": "file"})
    assert (code, answer) == (200, {"path": ""})
    assert asked == [("folder", "D:/"), ("file", "")]
    assert call(server, "POST", "/pick", {"kind": "anything"})[0] == 400


def test_stats_come_from_the_runs_in_the_work_folder(server, tmp_path):
    code, answer = call(server, "GET", "/stats")
    assert (code, answer["runs"]) == (200, 0)

    folder = work_folder(Settings.load(tmp_path), "v_v_v_v_v_v")
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(
        json.dumps(
            {"model": "claude:sonnet", "stt": "auto", "steps": {"analyze": 70.0}}
        ),
        "utf-8",
    )
    code, answer = call(server, "GET", "/stats")
    assert answer["runs"] == 1
    assert answer["steps"] == {"analyze": 70.0}
    assert answer["models"]["claude:sonnet"]["seconds"] == 70.0


def test_restart_answers_first_and_then_hands_over_the_port(service, monkeypatch):
    """The owner has no console for the service, so the options page needs
    a button: a process that lost CUDA or filled its DLL search path is
    only cured by a fresh one (2026-09-10)."""
    handed: list[tuple] = []
    # The thread ends the process right after handing over; in a test it
    # must stop at the hand-over.
    monkeypatch.setattr(module.os, "_exit", lambda code: None)
    server = Server(service, 0, relauncher=lambda *args: handed.append(args))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    try:
        code, answer = call(server, "POST", "/restart")
        assert (code, answer) == (200, {"restarting": True})
        for _ in range(100):
            if handed:
                break
            time.sleep(0.05)
        assert handed == [(service.home, port, service.overrides)]
    finally:
        server.server_close()


def test_stop_ends_the_process_without_handing_over_the_port(service, monkeypatch):
    """An update cannot replace the installed script while Windows holds it
    open, so the installer asks for this first. Unlike restart, nothing
    takes the port afterwards."""
    handed: list[tuple] = []
    ended: list[int] = []
    monkeypatch.setattr(module.os, "_exit", lambda code: ended.append(code))
    server = Server(service, 0, relauncher=lambda *args: handed.append(args))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        code, answer = call(server, "POST", "/shutdown")
        assert (code, answer) == (200, {"stopping": True})
        for _ in range(100):
            if ended:
                break
            time.sleep(0.05)
        assert ended == [0]
        assert handed == []
    finally:
        server.server_close()


def test_stop_says_so_when_no_service_listens():
    """The ordinary case for an installer on a fresh machine, and for a
    second stop. It must not look like a failure."""
    # Port 1 is never listening here; the message names the port it tried.
    assert "no service on port 1" in module.stop("", port=1)


def throwing(error):
    """A stand-in for urlopen that fails the way the real one does."""

    def urlopen(request, timeout=None):
        raise error

    return urlopen


def test_stop_tells_a_service_that_refused_the_request_from_none(monkeypatch):
    """HTTPError is a subclass of URLError, so a wrong token used to read
    "no service on port 8765 (Unauthorized)" while the service was running
    and holding its script. The installer reads this line: it went on to
    replace a file Windows keeps open, and the uv step then failed with
    nothing said about why (2026-09-10)."""
    refused = urllib.error.HTTPError(
        "http://127.0.0.1:8765/shutdown", 401, "Unauthorized", {}, None
    )
    monkeypatch.setattr(module, "urlopen", throwing(refused))
    said = module.stop("wrong", port=8765)
    assert "401 Unauthorized" in said
    assert "may still be running" in said
    # Neither of the two other cases: the port is not free, and nothing is
    # on its way out.
    assert "no service" not in said
    assert "is stopping" not in said


def test_stop_tells_a_refused_connection_from_one_that_never_got_through(monkeypatch):
    """Both arrive as URLError, and the reason behind it is the difference:
    refused means nothing holds the port, anything else means the installer
    cannot tell. A dropped packet and a hung service look the same from
    here, so only the refusal may read as the free port."""
    monkeypatch.setattr(
        module,
        "urlopen",
        throwing(urllib.error.URLError(ConnectionRefusedError(10061, "refused"))),
    )
    assert "no service on port 8765" in module.stop("", port=8765)
    monkeypatch.setattr(
        module, "urlopen", throwing(urllib.error.URLError(TimeoutError("timed out")))
    )
    said = module.stop("", port=8765)
    assert "may still be running" in said
    assert "no service" not in said


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        ConnectionResetError(10054, "the other end closed the connection"),
        http.client.RemoteDisconnected("Remote end closed connection"),
        # Whatever else is on the port, answering something that is no HTTP
        # answer: an HTTPException and no OSError, so it needs its own name
        # in the catch.
        http.client.BadStatusLine("not http at all"),
    ],
    ids=["timeout", "reset", "disconnected", "no-http"],
)
def test_stop_says_a_service_may_be_there_when_the_answer_breaks_off(
    error, monkeypatch
):
    """These three come out of urlopen as they are, past URLError, and used
    to fly out of stop instead of becoming a line. /shutdown answers before
    it ends its process, so a line that breaks may have been taken: this
    must not read like the free port it is not."""
    monkeypatch.setattr(module, "urlopen", throwing(error))
    said = module.stop("secret", port=8765)
    assert "may still be running" in said
    assert type(error).__name__ in said
    assert "no service" not in said
    assert "is stopping" not in said


def test_a_result_the_worker_cannot_read_ends_that_job_and_no_other(server, runner):
    """The lines after the run read `result["seconds"]` and
    `result["written"]`. A result without them used to end the only worker
    thread, and every job after it stayed queued for good (2026-09-10)."""

    def half_a_result(url, settings, **kwargs):
        if url == URL:
            return {"error": None}
        return runner(url, settings, **kwargs)

    server.service.runner = half_a_result

    first = call(server, "POST", "/jobs", {"url": URL})[1]["id"]
    job = wait_for(server, first, "error")
    assert "KeyError" in job["error"]["message"]

    # The worker is still there: the next job runs.
    second = call(server, "POST", "/jobs", {"url": SECOND_URL})[1]["id"]
    assert wait_for(server, second, "done")["title"] == "A video"


def test_a_cancel_the_worker_overtook_is_not_turned_back_into_running(service, runner):
    """cancel and the worker both touch the same job. cancel used to read
    the status outside the lock, and the worker's "running" overwrote the
    "cancelled" a moment later: the job ran although it was cancelled."""
    vid = "q_q_q_q_q_q"
    # A job the worker has pulled out of the queue but not marked yet:
    # exactly the gap cancel used to lose in.
    service.jobs[vid] = {
        "id": vid,
        "url": URL,
        "profile": "fast",
        "status": "queued",
        "step": None,
        "step_started": None,
        "queued": module.now(),
    }

    assert service.cancel(vid)["status"] == "cancelled"

    # What the worker does with what it pulled, and what it must not do.
    service.work_one(vid)
    assert service.job(vid)["status"] == "cancelled"
    assert runner.calls == 0


def test_the_worker_waits_while_cancel_is_between_its_two_steps(
    service, runner, monkeypatch
):
    """The other half: taking the job out of the queue and marking it
    cancelled happen under one lock, and the test above only calls the two
    sides one after the other. `cancel` calls `now` between its two steps,
    so a hook on it starts the worker's `begin` exactly where the gap used
    to be. The event says that thread really got as far as `begin`, and
    `began` says the job it then found was cancelled, so "running" never
    overwrote it. The 0.2 seconds are the weaker half of the proof: a
    thread that is still alive by then did not walk through the lock, which
    is what it does once the lock is gone.
    (The queue is empty here, so the removal itself is a no-op; the test
    above it covers a job that really waits in the queue.)"""
    vid = "s_s_s_s_s_s"
    service.jobs[vid] = {
        "id": vid,
        "url": URL,
        "profile": "fast",
        "status": "queued",
        "step": None,
        "step_started": None,
        "queued": module.now(),
    }
    clock = module.now
    began: list[dict | None] = []
    still_waiting: list[bool] = []
    worker: list[threading.Thread] = []
    at_begin = threading.Event()

    def take_the_job() -> None:
        at_begin.set()
        began.append(service.begin(vid))

    def let_the_worker_in() -> str:
        if not worker:
            worker.append(threading.Thread(target=take_the_job, daemon=True))
            worker[0].start()
            # Waited for, not assumed: a thread the machine had not run yet
            # would look exactly like one the lock holds.
            assert at_begin.wait(timeout=5)
            worker[0].join(0.2)
            still_waiting.append(worker[0].is_alive())
        return clock()

    monkeypatch.setattr(module, "now", let_the_worker_in)

    assert service.cancel(vid)["status"] == "cancelled"

    worker[0].join(timeout=5)
    assert still_waiting == [True]  # the lock held while cancel was inside
    assert began == [None]  # and "running" never overwrote "cancelled"
    assert runner.calls == 0


def test_restart_and_shutdown_refuse_while_a_job_is_on_unless_forced(
    service, runner, monkeypatch
):
    """An end mid-run leaves half-written outputs and takes the job list
    with it. The way past it stays open for the installer: it frees the
    port before uv can replace the exe (install.ps1)."""
    ended: list[int] = []
    monkeypatch.setattr(module.os, "_exit", lambda code: ended.append(code))
    server = Server(service, 0, relauncher=lambda *args: None)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        runner.gate.clear()
        _, job = call(server, "POST", "/jobs", {"url": URL})
        wait_for(server, job["id"], "running")

        for path in ("/restart", "/shutdown"):
            code, answer = call(server, "POST", path)
            assert code == 409, path
            assert job["id"] in answer["error"]
            # This text stands in the options page word for word, and the
            # page has no force button, so it must not ask for JSON.
            assert "force" not in answer["error"], path
        assert ended == []

        # `video-tldr stop`, the call install.ps1 makes, must still get
        # through: it forces.
        assert "is stopping" in module.stop(service.token, server.server_port)
        for _ in range(100):
            if ended:
                break
            time.sleep(0.05)
        assert ended == [0]
    finally:
        runner.gate.set()
        server.server_close()


def test_a_hand_over_that_throws_still_ends_this_process(service, monkeypatch):
    """`shutdown()` and `server_close()` run before the new process starts.
    A start that throws used to leave this one alive without its socket:
    listening to nothing, and holding the port's name in the task list."""
    ended: list[int] = []
    monkeypatch.setattr(module.os, "_exit", lambda code: ended.append(code))

    def no_python_here(*args):
        raise OSError("no interpreter to start")

    server = Server(service, 0, relauncher=no_python_here)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert call(server, "POST", "/restart")[0] == 200
        for _ in range(100):
            if ended:
                break
            time.sleep(0.05)
        assert ended == [0]
    finally:
        server.server_close()


def test_one_dialog_at_a_time_and_none_that_holds_a_request_for_good(
    server, monkeypatch
):
    """tkinter is not thread safe: a second Tk in a second request thread
    took the process with it, and a dialog nobody answers held its request
    thread without a limit."""
    opened = threading.Event()
    answered = threading.Event()

    def waiting_dialog(kind, start=""):
        opened.set()
        answered.wait(timeout=5)
        return "D:/Vaults/Notes"

    monkeypatch.setattr(module, "dialog", waiting_dialog)
    monkeypatch.setattr(module, "PICK_TIMEOUT_SECONDS", 0.2)

    code, answer = call(server, "POST", "/pick", {"kind": "folder"})
    assert code == 409
    assert "no answer" in answer["error"]
    assert opened.is_set()

    # The first dialog still stands, so the second request is turned away
    # instead of opening a Tk of its own.
    code, answer = call(server, "POST", "/pick", {"kind": "folder"})
    assert (code, "already open" in answer["error"]) == (409, True)

    answered.set()
    for _ in range(100):
        code, answer = call(server, "POST", "/pick", {"kind": "folder"})
        if code == 200:
            break
        time.sleep(0.02)
    assert (code, answer) == (200, {"path": "D:/Vaults/Notes"})
