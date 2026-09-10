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
    # through the settings page or the command line.
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
        assert f"a job may not set {key}" in answer["error"]


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
    # Port 0 is never listening; the message names the port it tried.
    assert "no service on port 1" in module.stop("", port=1)
