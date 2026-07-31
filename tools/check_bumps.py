#!/usr/bin/env python3
"""Fail when a plugin's code changes without the manifest changing with it.

The registry's integrity guarantee is that a plugin's bytes cannot change
without a reviewed change to ``index.json``: Picasso pins each plugin by the
``sha256`` published there, and only offers an update when ``version``
increases. A pull request that edits a ``.py`` file but leaves either field
alone breaks that guarantee — silently, and in the direction that matters
(existing users keep running the old code, or receive new code under an
unchanged version).

This compares the working tree against a base ref and reports any such
mismatch.

Usage
-----
``python tools/check_bumps.py --base origin/main``

Exits 0 when every changed plugin file has both a new hash and a new version
in the manifest, 1 otherwise. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return out.stdout.decode("utf-8")


def changed_files(base: str) -> list:
    """Repo-relative paths that differ between ``base`` and the working tree."""
    diff = git("diff", "--name-only", f"{base}...HEAD")
    names = [line.strip() for line in diff.splitlines() if line.strip()]
    # Include anything not yet committed, so the check is useful locally too.
    for extra in ("diff --name-only HEAD", "ls-files --others --exclude-standard"):
        out = git(*extra.split())
        names.extend(line.strip() for line in out.splitlines() if line.strip())
    return sorted(set(names))


def entries_by_file(index: dict) -> dict:
    result = {}
    for entry in index.get("plugins", []):
        if isinstance(entry, dict) and isinstance(entry.get("file"), str):
            result[entry["file"]] = entry
    return result


def load_base_index(base: str) -> dict:
    try:
        return json.loads(git("show", f"{base}:index.json"))
    except (subprocess.CalledProcessError, ValueError):
        return {"plugins": []}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="ref to compare against (default: origin/main)",
    )
    args = parser.parse_args(argv)

    with open(os.path.join(REPO_ROOT, "index.json"), encoding="utf-8") as f:
        head_index = json.load(f)
    base_index = load_base_index(args.base)

    head_entries = entries_by_file(head_index)
    base_entries = entries_by_file(base_index)

    problems = []
    for path in changed_files(args.base):
        if not path.endswith(".py") or path.startswith("tools/"):
            continue
        entry = head_entries.get(path)
        if entry is None:
            # Not in the manifest: hash_plugins.py --check reports it as
            # unreachable; nothing to compare here.
            continue
        previous = base_entries.get(path)
        if previous is None:
            print(f"ok    {path}: new plugin entry")
            continue
        found = []
        if previous.get("sha256") == entry.get("sha256"):
            found.append(
                f"{path} changed but its 'sha256' in index.json did not. "
                "Run: python tools/hash_plugins.py --update"
            )
        if previous.get("version") == entry.get("version"):
            found.append(
                f"{path} changed but its 'version' in index.json is still "
                f"{entry.get('version')!r}. Users already on that version "
                "would never be offered the update."
            )
        problems.extend(found)
        if not found:
            print(
                f"ok    {path}: {previous.get('version')} -> "
                f"{entry.get('version')}, hash updated"
            )

    if problems:
        print()
        for problem in problems:
            print(f"FAIL  {problem}")
        return 1
    print("\nNo plugin file changed without a matching manifest update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
