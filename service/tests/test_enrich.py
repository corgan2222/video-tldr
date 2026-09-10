import io
import json
import urllib.error
import urllib.request

from corganshelper_service import enrich as enrich_module
from corganshelper_service import llm
from corganshelper_service.config import Settings
from corganshelper_service.enrich import (
    INSTALL_SCHEMA,
    enrich,
    installations,
    readme,
    repositories,
)
from corganshelper_service.fetch import work_folder

VID = "jFHu6wx_TMQ"


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def serving(pages: dict):
    """A stand-in for urlopen: `pages` maps a URL to bytes, else 404."""

    def urlopen(url, timeout=None):
        if url in pages:
            return Answer(pages[url])
        raise urllib.error.HTTPError(url, 404, "nope", {}, None)

    return urlopen


def test_repositories_come_from_github_links_repository_role_first():
    links = [
        {"url": "https://github.com/sponsors/x", "role": "sponsor"},
        {"url": "https://www.github.com/a/b.git", "role": "other"},
        {"url": "https://github.com/c/d/tree/main/docs", "role": "repository"},
        {"url": "https://github.com/a/b", "role": "other"},
        {"url": "https://huggingface.co/e/f", "role": "other"},
        {"url": "https://github.com/g/h.", "role": "other"},
        {"url": "https://github.com/i/j", "role": "other"},
    ]
    assert repositories(links) == ["c/d", "a/b", "g/h"]


def test_readme_tries_the_next_name_on_404_and_gives_up_otherwise(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        serving(
            {
                "https://raw.githubusercontent.com/a/b/HEAD/README.rst": b"rst",
                "https://raw.githubusercontent.com/e/f/HEAD/README.md": b" \n",
            }
        ),
    )
    assert readme("a/b") == ("rst", "README.rst")
    assert readme("c/d") == (None, "no README at HEAD")
    assert readme("e/f") == (None, "README.md is empty")

    # One dropped connection is tried again, a second one ends it.
    calls = []

    def resetting_once(url, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.URLError("connection reset")
        return Answer(b"second time lucky")

    monkeypatch.setattr(urllib.request, "urlopen", resetting_once)
    assert readme("a/b") == ("second time lucky", "README.md")
    assert len(calls) == 2

    def resetting(url, timeout=None):
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", resetting)
    text, note = readme("a/b")
    assert text is None and "connection reset" in note


def test_enrich_reads_the_readmes_and_stores_the_steps(tmp_path, monkeypatch):
    settings = Settings(home=tmp_path)
    folder = work_folder(settings, VID)
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(json.dumps({"id": VID}), encoding="utf-8")
    (folder / "analysis.json").write_text(
        json.dumps(
            {
                "id": VID,
                "language": "de",
                "kind": "review",
                "links": [
                    {
                        "url": "https://github.com/openai/human-eval",
                        "role": "repository",
                    },
                    {
                        "url": "https://github.com/lukesdevlab/youtube",
                        "role": "repository",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        serving(
            {
                "https://raw.githubusercontent.com/openai/human-eval/HEAD/README.md": (
                    b"# HumanEval\n\n    pip install -e human-eval\n"
                )
            }
        ),
    )
    requests = []

    def fake_complete(instruction, data, schema, settings, images=None, max_turns=1):
        requests.append((instruction, data, schema))
        llm.last_cost.update(input=5, output=1, usd=0.0)
        return {
            "repositories": [
                {
                    "repo": "openai/human-eval",
                    "what": "Der Benchmark.",
                    "install": ["`pip install -e human-eval`"],
                }
            ]
        }

    monkeypatch.setattr(llm, "complete", fake_complete)

    result = enrich(f"https://youtu.be/{VID}", settings)

    instruction, data, schema = requests[0]
    assert schema is INSTALL_SCHEMA
    assert "## openai/human-eval (README.md)" in data and "pip install" in data
    assert "German" in instruction
    assert result["repositories"][0]["url"] == "https://github.com/openai/human-eval"
    assert result["skipped"] == ["lukesdevlab/youtube: no README at HEAD"]
    assert result["cost"] == {"requests": 1, "input": 5, "output": 1, "usd": 0.0}
    assert installations(settings, VID) == result["repositories"]
    assert json.loads((folder / "enrich.json").read_text(encoding="utf-8")) == result


def test_without_a_repository_no_request_is_made(tmp_path, monkeypatch):
    settings = Settings(home=tmp_path)
    folder = work_folder(settings, VID)
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(json.dumps({"id": VID}), encoding="utf-8")
    (folder / "analysis.json").write_text(
        json.dumps({"id": VID, "language": "de", "links": []}), encoding="utf-8"
    )
    monkeypatch.setattr(llm, "complete", lambda *a, **k: 1 / 0)
    result = enrich(f"https://youtu.be/{VID}", settings)
    assert result["repositories"] == []
    assert result["skipped"] == ["no GitHub repository among the links"]
    assert enrich_module.installations(settings, VID) == []
