import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from corganshelper_service import serve as module
from corganshelper_service.config import Settings, store
from corganshelper_service.serve import Server, Service

URL = "https://youtu.be/x_x_x_x_x_x"


class Runner:
    """Stands in for run: waits at the gate, then answers like run does."""

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.calls = 0
        self.fail = None
        self.seen: list[tuple] = []

    def __call__(self, url, settings, progress=None, force=False, **kwargs):
        self.calls += 1
        self.seen.append((settings.config["stt"], settings.config["model"], force))
        if progress:
            progress("fetch")
            progress("fetch", "0.1s, A video, 1 caption tracks")
        self.gate.wait(timeout=5)
        if self.fail:
            raise self.fail
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
            "written": {"summary": "C:/w/summary.md", "obsidian": "C:/v/n.md"},
            "error": None,
        }


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def service(tmp_path, runner):
    # With a token set, so the tests below see the check; without one the
    # service answers everyone on 127.0.0.1 (test below).
    store(tmp_path, {"token": "secret"})
    return Service(tmp_path, runner=runner)


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


def test_open_starts_the_note_in_obsidian_first(server, runner, monkeypatch):
    started = []
    monkeypatch.setattr(module, "start", started.append)
    code, job = call(server, "POST", "/jobs", {"url": URL})
    wait_for(server, job["id"], "done")

    code, answer = call(server, "POST", f"/jobs/{job['id']}/open")

    assert code == 200
    assert answer["opened"] == "obsidian://open?path=C%3A/v/n.md"
    assert started == [answer["opened"]]


def test_a_bad_url_and_an_unknown_job_are_errors_with_a_reason(server):
    code, answer = call(server, "POST", "/jobs", {"url": "https://example.org"})
    assert code == 400
    assert "not a YouTube video URL" in answer["error"]
    assert call(server, "POST", "/jobs", {})[0] == 400
    assert call(server, "GET", "/jobs/nope")[0] == 404
    assert call(server, "GET", "/nothing")[0] == 404


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
    code, answer = call(server, "PUT", "/config", {"obsidian_folder": 5})
    assert code == 400
    assert "every setting is a string" in answer["error"]


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


def test_stats_come_from_the_runs_in_the_work_folder(server, tmp_path):
    code, answer = call(server, "GET", "/stats")
    assert (code, answer["runs"]) == (200, 0)

    folder = tmp_path / "work" / "v"
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
