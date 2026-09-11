#!/usr/bin/env python3
"""Pack `dist/` once per store, each with the manifest that store reads.

    python scripts/package.py            packs all three into packages/
    python scripts/package.py firefox    packs one

One source tree serves every browser; only the manifest differs, and only
in two places. Firefox reads `background.scripts` and needs the
`browser_specific_settings.gecko` block for its add-on id. Chrome reads
`background.service_worker` and calls both of the others an unrecognised
key. Shipping the union to both, which is what a single zip does, means
every store review starts with a warning about the half that store
ignores.

Edge is Chromium: same package, own name, because Partner Center wants a
file of its own and the name is what tells two uploads apart.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT = ROOT / "packages"

# What each store's manifest must not carry. The keys are paths into the
# manifest, dotted; everything else is the same file.
DROP: dict[str, tuple[str, ...]] = {
    "firefox": ("background.service_worker",),
    "chrome": ("background.scripts", "browser_specific_settings"),
    "edge": ("background.scripts", "browser_specific_settings"),
}


def without(manifest: dict, dotted: str) -> None:
    """Delete one dotted path, and the parent if that empties it."""
    head, _, tail = dotted.partition(".")
    if not tail:
        manifest.pop(head, None)
        return
    child = manifest.get(head)
    if isinstance(child, dict):
        without(child, tail)
        if not child:
            manifest.pop(head, None)


def manifest_for(target: str) -> dict:
    manifest = json.loads((DIST / "manifest.json").read_text(encoding="utf-8"))
    for dotted in DROP[target]:
        without(manifest, dotted)
    return manifest


def pack(target: str) -> Path:
    manifest = manifest_for(target)
    OUT.mkdir(exist_ok=True)
    out = OUT / f"video-tldr-{manifest['version']}-{target}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(DIST.rglob("*")):
            if path.is_dir():
                continue
            name = path.relative_to(DIST).as_posix()
            if name == "manifest.json":
                # Written from memory, so the file on disk stays the one
                # `web-ext run` loads during development.
                zf.writestr(name, json.dumps(manifest, indent=2) + "\n")
            else:
                zf.write(path, name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", choices=list(DROP))
    args = ap.parse_args()
    if not (DIST / "manifest.json").exists():
        print("no dist/manifest.json -- run npm run build first", file=sys.stderr)
        return 1
    for target in args.targets or DROP:
        out = pack(target)
        print(f"{out.relative_to(ROOT).as_posix()}  {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
