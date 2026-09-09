#!/usr/bin/env python3
"""Show or bump this project's version, wherever its manifest keeps it.

Manifest search order, first match wins: Cargo.toml, pyproject.toml,
package.json, CMakeLists.txt, main.go (else the first **/version.go found),
and finally a plain VERSION file if none of those carry a version.

    bump_version.py                run's default: --patch --stage, but only
                                    before the first release tag (see below)
    bump_version.py --show
    bump_version.py --set 1.2.3
    bump_version.py --patch
    bump_version.py --patch --stage
    bump_version.py --patch --force

Until the first release tag, every commit is meant to bump the patch
number on its own. A git tag means a release has happened and the version
now moves only with a release, not with every commit -- so the plain,
no-flag form checks `git tag --list` first and does nothing once a tag
exists. --force runs the bump anyway, for the rare deliberate case.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# version = "x.y.z" at the start of a line -- Cargo's [package] table and a
# hatchling [project] table both write it exactly this way, and neither
# other file puts a bare `version = "..."` at column zero.
_TOML_VERSION = re.compile(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', re.MULTILINE)
_PACKAGE_JSON_VERSION = re.compile(r'"version"\s*:\s*"(\d+\.\d+\.\d+)"')
# project() can wrap across lines, so DOTALL over the parenthesised part.
_CMAKE_VERSION = re.compile(
    r"project\s*\([^)]*?\bVERSION\s+(\d+\.\d+\.\d+)", re.DOTALL
)
_GO_VERSION = re.compile(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', re.MULTILINE)
_VERSION_FILE = re.compile(r"^\s*(\d+\.\d+\.\d+)\s*$")


@dataclass
class Manifest:
    path: Path
    text: str
    match: "re.Match[str]"

    @property
    def version(self) -> str:
        return self.match.group(1)


def repo_root() -> Path:
    """The git worktree root, so the script works from any subdirectory."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _try(path: Path, pattern: re.Pattern) -> Manifest | None:
    if not path.is_file():
        return None
    # newline="" keeps whatever line endings the file already has; writing
    # it back must not turn a checked-in LF file into CRLF or the other way.
    text = path.read_text(encoding="utf-8", newline="")
    match = pattern.search(text)
    if match is None:
        return None
    return Manifest(path=path, text=text, match=match)


def find_manifest(root: Path) -> Manifest | None:
    for name, pattern in (
        ("Cargo.toml", _TOML_VERSION),
        ("pyproject.toml", _TOML_VERSION),
        ("package.json", _PACKAGE_JSON_VERSION),
        ("CMakeLists.txt", _CMAKE_VERSION),
        ("main.go", _GO_VERSION),
    ):
        found = _try(root / name, pattern)
        if found is not None:
            return found

    for go_file in sorted(root.glob("**/version.go")):
        found = _try(go_file, _GO_VERSION)
        if found is not None:
            return found

    return _try(root / "VERSION", _VERSION_FILE)


def write_version(manifest: Manifest, new_version: str) -> None:
    start, end = manifest.match.span(1)
    new_text = manifest.text[:start] + new_version + manifest.text[end:]
    manifest.path.write_text(new_text, encoding="utf-8", newline="")


def create_version_file(root: Path, new_version: str) -> Path:
    """The fallback manifest: used only when nothing else carries a version."""
    path = root / "VERSION"
    path.write_text(new_version + "\n", encoding="utf-8", newline="\n")
    return path


def bump_patch(version: str) -> str:
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def stage(root: Path, path: Path) -> None:
    subprocess.run(["git", "add", str(path)], cwd=root, check=True)


# Files that repeat the version and must move with it. The stores read
# src/manifest.json, npm and the release workflow read package.json; a number
# that moves in one place only ships a mislabelled build. tests/version.test.ts
# fails when the two drift.
MIRRORS = (("src/manifest.json", _PACKAGE_JSON_VERSION),)


def write_mirrors(root: Path, new_version: str, do_stage: bool) -> None:
    for name, pattern in MIRRORS:
        mirror = _try(root / name, pattern)
        if mirror is None:
            continue
        write_version(mirror, new_version)
        if do_stage:
            stage(root, mirror.path)
        print(f"{mirror.path.relative_to(root)}: {mirror.version} -> {new_version}")


def has_tags(root: Path) -> bool:
    out = subprocess.run(
        ["git", "tag", "--list"], cwd=root,
        capture_output=True, text=True, check=True,
    )
    return bool(out.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--show", action="store_true",
                         help="print the current version and exit")
    parser.add_argument("--set", metavar="X.Y.Z",
                         help="set the version to exactly this value")
    parser.add_argument("--patch", action="store_true",
                         help="bump the last version component")
    parser.add_argument("--stage", action="store_true",
                         help="git add the manifest after writing it")
    parser.add_argument("--force", action="store_true",
                         help="bump even though the repository already carries a tag")
    args = parser.parse_args(argv)

    if args.set is not None and not VERSION_RE.match(args.set):
        parser.error(f"--set wants X.Y.Z, got {args.set!r}")

    root = repo_root()
    action_given = args.show or args.set is not None or args.patch

    if not action_given:
        if has_tags(root) and not args.force:
            print("tagged repository: versions come from releases now")
            return 0
        args.patch = True
        args.stage = True

    if args.show:
        manifest = find_manifest(root)
        if manifest is None:
            print("no version manifest found", file=sys.stderr)
            return 1
        print(manifest.version)
        return 0

    if args.set is not None:
        manifest = find_manifest(root)
        path = create_version_file(root, args.set) if manifest is None else manifest.path
        if manifest is not None:
            write_version(manifest, args.set)
        if args.stage:
            stage(root, path)
        print(f"{path.relative_to(root)}: {args.set}")
        write_mirrors(root, args.set, args.stage)
        return 0

    manifest = find_manifest(root)
    if manifest is None:
        print("no version manifest found", file=sys.stderr)
        return 1
    old = manifest.version
    new = bump_patch(old)
    write_version(manifest, new)
    if args.stage:
        stage(root, manifest.path)
    print(f"{manifest.path.relative_to(root)}: {old} -> {new}")
    write_mirrors(root, new, args.stage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
