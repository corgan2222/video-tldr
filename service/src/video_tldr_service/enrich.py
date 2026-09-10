"""Step 5: how to install what the video shows.

The README of every GitHub repository the description links to, at most
LIMIT of them, read from `raw.githubusercontent.com` at `HEAD` (which
resolves the default branch without an API request), and one model request
that pulls the installation steps out. The plan limited this to software
tutorials; a repository link is the better sign that there is something to
install, whatever kind the video got, so the link decides.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import llm
from .analyze import LANGUAGES, _obj, analyze
from .config import Settings
from .fetch import fetch, work_folder

RESULT_NAME = "enrich.json"
LIMIT = 3
README_NAMES = ("README.md", "README.rst", "readme.md")
# Characters of README per repository; a longer one is cut.
SIZE_LIMIT = 60_000
TIMEOUT_SECONDS = 20

GITHUB = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
)
# First path segments that are pages of GitHub itself, not owners.
NOT_OWNERS = {
    "about",
    "apps",
    "collections",
    "events",
    "explore",
    "features",
    "join",
    "login",
    "marketplace",
    "orgs",
    "pricing",
    "security",
    "settings",
    "site",
    "sponsors",
    "topics",
    "trending",
}

INSTALL_SCHEMA = _obj(
    {
        "repositories": {
            "type": "array",
            "items": _obj(
                {
                    "repo": {"type": "string"},
                    "what": {"type": "string"},
                    "install": {"type": "array", "items": {"type": "string"}},
                }
            ),
        }
    }
)


def repositories(links: list[dict]) -> list[str]:
    """`owner/repo` of the GitHub links, the ones analyze called a
    repository first, without doubles, at most LIMIT."""
    found: list[str] = []
    for link in sorted(links, key=lambda link: link.get("role") != "repository"):
        match = GITHUB.match(link.get("url") or "")
        if not match or match[1].lower() in NOT_OWNERS:
            continue
        # A link that ends a sentence carries the period with it.
        name = f"{match[1]}/{match[2].rstrip('.').removesuffix('.git')}"
        if name not in found:
            found.append(name)
    return found[:LIMIT]


def readme(repo: str) -> tuple[str | None, str]:
    """(text, name) of the first README that answers at HEAD, or (None,
    reason). A 404 tries the next name. A dropped connection is tried
    once more: GitHub's raw host closed one per run on 2026-09-09 and
    again on 2026-09-10, and each cost a repository. Anything else gives
    up on the repository."""
    for name in README_NAMES:
        url = f"https://raw.githubusercontent.com/{repo}/HEAD/{name}"
        for attempt in range(2):
            try:
                with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
                    text = response.read().decode("utf-8", "replace")
                    if not text.strip():
                        return None, f"{name} is empty"
                    return text[:SIZE_LIMIT], name
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    return None, f"{name}: HTTP {error.code}"
                break
            except (urllib.error.URLError, OSError) as error:
                if attempt:
                    return None, f"{name}: {getattr(error, 'reason', error)}"
    return None, "no README at HEAD"


def instruction(language: str) -> str:
    # "You read the README files" made the CLI model reach for a tool and
    # run out of turns (2026-09-09); the text says the files are below.
    return (
        "Below are the README files of GitHub repositories a YouTube video "
        "links to, one README per heading, complete; nothing else needs "
        "reading or fetching. For each repository: what, one sentence in "
        f"{LANGUAGES.get(language, language)} on what the project is; "
        "install: the steps to install and first run it, in the README's "
        "order, one step per entry, each shell command verbatim as a Markdown "
        "code span, prose steps short; empty when the README gives none. "
        "repo: the owner/name from the heading."
    )


def enrich(
    url: str, settings: Settings, force: bool = False, language: str | None = None
) -> dict:
    """Write work/<id>/enrich.json and return it."""
    fetched = fetch(url, settings)
    vid = fetched["id"]
    folder = work_folder(settings, vid)
    result_path = folder / RESULT_NAME
    if result_path.exists() and not force:
        return json.loads(result_path.read_text(encoding="utf-8"))
    analysis = analyze(url, settings, language=language)
    language = language or analysis.get("language") or settings.config["language"]
    result: dict = {
        "id": vid,
        "model": llm.describe(settings),
        "cost": {},
        "skipped": [],
        "repositories": [],
    }
    readmes: dict[str, tuple[str, str]] = {}
    repos = repositories(analysis.get("links") or [])
    if not repos:
        result["skipped"].append("no GitHub repository among the links")
    for repo in repos:
        text, note = readme(repo)
        if text is None:
            result["skipped"].append(f"{repo}: {note}")
        else:
            readmes[repo] = (text, note)
    if readmes:
        data = "\n\n".join(
            f"## {repo} ({name})\n\n{text}" for repo, (text, name) in readmes.items()
        )
        answer = llm.complete(instruction(language), data, INSTALL_SCHEMA, settings)
        result["cost"] = llm.totals([dict(llm.last_cost)])
        for entry in answer.get("repositories") or []:
            repo = str(entry.get("repo", "")).strip().strip("/")
            result["repositories"].append(
                {
                    "repo": repo,
                    "url": f"https://github.com/{repo}",
                    "what": entry.get("what", ""),
                    "install": [str(s) for s in entry.get("install") or []],
                }
            )
    result_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def installations(settings: Settings, vid: str) -> list[dict]:
    """What the renderer puts under Installation; empty until enrich ran."""
    path = work_folder(settings, vid) / RESULT_NAME
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("repositories") or []
