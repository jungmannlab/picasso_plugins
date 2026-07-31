#!/usr/bin/env python3
"""Verify and update the integrity hashes in ``index.json``.

Picasso refuses to install a plugin whose ``sha256`` is missing, malformed
or does not match the file it downloads, so the manifest — not the ``.py``
file — is what pins a plugin's code. This script keeps the two in sync and
checks everything else Picasso validates before it will show or install an
entry.

Usage
-----
``python tools/hash_plugins.py --check``
    Validate the manifest: every entry well-formed, every referenced file
    present, every hash correct, no unreferenced plugin files. Prints a
    per-entry report and exits non-zero on any problem. Run by CI.

``python tools/hash_plugins.py --update``
    Recompute every ``sha256`` and rewrite ``index.json`` in place, leaving
    all other fields untouched. Warns when an entry's hash changed without
    its ``version`` changing relative to ``git HEAD`` — that combination
    would hand existing users different code under the same version number.

Standard library only, on purpose: it has to run in CI and on a
maintainer's laptop without a virtualenv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

# --- The rules Picasso enforces client-side ---------------------------------
#
# Mirrors picasso/gui/plugins_loader.py. Keep the two in step: an entry that
# fails any of these is dropped or refused by the app, so it must never be
# merged here.

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# The Picasso GUIs that call load_plugins(); an entry for anything else can
# never be shown to a user.
APPS = (
    "average",
    "design",
    "filter",
    "localize",
    "nanotron",
    "render",
    "simulate",
    "spinna",
)

REQUIRED_FIELDS = (
    "id",
    "display_name",
    "app",
    "description",
    "file",
    "version",
    "sha256",
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(REPO_ROOT, "index.json")

# Directories that are not plugin sources, skipped when looking for .py files
# that nothing in the manifest references.
NON_PLUGIN_DIRS = {".git", ".github", "__pycache__", "tools", "schema"}


def is_safe_id(value) -> bool:
    """Whether ``value`` may be used as an id (and hence as a file name)."""
    return isinstance(value, str) and bool(ID_RE.match(value))


def is_safe_repo_path(value) -> bool:
    """Whether ``value`` is a relative ``.py`` path inside this repository."""
    if not isinstance(value, str) or not value.endswith(".py"):
        return False
    if value.startswith("/") or "\\" in value or ":" in value:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def sha256_file(path: str) -> str:
    """Hex SHA-256 of a file's exact bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


# --- Manifest I/O ------------------------------------------------------------


def load_index(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_index(data: dict, path: str) -> None:
    """Write the manifest back, keeping it diffable: two-space indent, key
    order preserved, trailing newline."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def with_hash(entry: dict, digest: str) -> dict:
    """Return ``entry`` with ``sha256`` set, placed just after ``file``."""
    out = {}
    for key, value in entry.items():
        if key == "sha256":
            continue
        out[key] = value
        if key == "file":
            out["sha256"] = digest
    if "sha256" not in out:
        out["sha256"] = digest
    return out


# --- Checking ----------------------------------------------------------------


def referenced_files(plugins: list) -> set:
    return {
        e["file"]
        for e in plugins
        if isinstance(e, dict) and isinstance(e.get("file"), str)
    }


def find_plugin_files() -> list:
    """All ``.py`` files in the repo that look like plugin sources."""
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in NON_PLUGIN_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            found.append(os.path.relpath(full, REPO_ROOT).replace(os.sep, "/"))
    return sorted(found)


def check(path: str) -> int:
    """Validate the manifest. Returns the number of problems found."""
    problems = []
    warnings = []

    try:
        data = load_index(path)
    except (OSError, ValueError) as exc:
        print(f"FAIL  cannot read {path}: {exc}")
        return 1

    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        print("FAIL  index.json must be an object with a 'plugins' array")
        return 1

    plugins = data["plugins"]
    seen_ids = {}
    seen_files = {}

    for position, entry in enumerate(plugins):
        label = f"entry #{position}"
        if not isinstance(entry, dict):
            problems.append(f"{label}: not an object")
            continue
        label = f"{entry.get('id', label)!r}"
        entry_problems = []

        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                entry_problems.append(f"missing or empty '{field}'")

        pid = entry.get("id")
        if isinstance(pid, str) and not is_safe_id(pid):
            entry_problems.append(
                f"id {pid!r} is rejected by Picasso "
                "(allowed: letters, digits, '_' and '-', not leading '-')"
            )
        if isinstance(pid, str) and pid in seen_ids:
            entry_problems.append(f"duplicate id (also entry #{seen_ids[pid]})")
        elif isinstance(pid, str):
            seen_ids[pid] = position

        app = entry.get("app")
        if isinstance(app, str) and app not in APPS:
            entry_problems.append(
                f"unknown app {app!r}; expected one of {', '.join(APPS)}"
            )

        rel = entry.get("file")
        full = None
        if isinstance(rel, str):
            if not is_safe_repo_path(rel):
                entry_problems.append(
                    f"file {rel!r} is rejected by Picasso (must be a relative "
                    "'.py' path inside this repo, no '..')"
                )
            else:
                if rel in seen_files:
                    entry_problems.append(
                        f"file also used by entry #{seen_files[rel]}"
                    )
                seen_files[rel] = position
                full = os.path.join(REPO_ROOT, rel)
                if not os.path.isfile(full):
                    entry_problems.append(f"file {rel!r} does not exist")
                    full = None

        digest = entry.get("sha256")
        if isinstance(digest, str) and not SHA256_RE.match(digest):
            entry_problems.append(
                f"sha256 {digest!r} is not 64 lowercase hex characters"
            )
        elif full is not None and isinstance(digest, str):
            actual = sha256_file(full)
            if actual != digest:
                entry_problems.append(
                    "sha256 does not match the file\n"
                    f"        manifest {digest}\n"
                    f"        actual   {actual}\n"
                    "        run: python tools/hash_plugins.py --update"
                )

        version = entry.get("version")
        if isinstance(version, str) and not re.search(r"\d", version):
            entry_problems.append(
                f"version {version!r} contains no digits; Picasso compares "
                "versions numerically and cannot order it"
            )

        minimum = entry.get("min_picasso_version")
        if minimum is not None and (
            not isinstance(minimum, str) or not re.search(r"\d", minimum)
        ):
            entry_problems.append(
                f"min_picasso_version {minimum!r} is not a version string"
            )

        if entry_problems:
            print(f"FAIL  {label}")
            for problem in entry_problems:
                print(f"      - {problem}")
            problems.extend(entry_problems)
        else:
            print(f"ok    {label}  {rel}  v{entry.get('version')}")

    unreferenced = set(find_plugin_files()) - referenced_files(plugins)
    for rel in sorted(unreferenced):
        warnings.append(
            f"{rel} is not referenced by any manifest entry, so no user can "
            "install it"
        )

    print()
    for warning in warnings:
        print(f"WARN  {warning}")
    if problems:
        print(f"\n{len(problems)} problem(s) found in {os.path.basename(path)}")
    else:
        print(f"{len(plugins)} entrie(s) verified, no problems found")
    return len(problems)


# --- Updating ----------------------------------------------------------------


def previous_index() -> dict | None:
    """``index.json`` as of ``git HEAD``, or ``None`` if unavailable.

    Used only to warn about content changing without a version bump; a repo
    without git (or a first commit) simply skips that check.
    """
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:index.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
        return json.loads(out.stdout.decode("utf-8"))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def update(path: str) -> int:
    """Recompute every hash and rewrite the manifest. Returns problem count."""
    data = load_index(path)
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        print("FAIL  index.json must be an object with a 'plugins' array")
        return 1

    before = previous_index()
    old_by_id = {}
    if isinstance(before, dict):
        for entry in before.get("plugins", []):
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                old_by_id[entry["id"]] = entry

    problems = 0
    changed = 0
    new_plugins = []
    for entry in data["plugins"]:
        if not isinstance(entry, dict):
            print("FAIL  skipping an entry that is not an object")
            problems += 1
            continue
        pid = entry.get("id", "<no id>")
        rel = entry.get("file")
        if not is_safe_repo_path(rel):
            print(f"FAIL  {pid!r}: file {rel!r} is not a valid plugin path")
            problems += 1
            new_plugins.append(entry)
            continue
        full = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(full):
            print(f"FAIL  {pid!r}: file {rel!r} does not exist")
            problems += 1
            new_plugins.append(entry)
            continue

        digest = sha256_file(full)
        old = entry.get("sha256")
        if old != digest:
            changed += 1
            print(f"hash  {pid!r}: {old or '(none)'} -> {digest}")
        new_plugins.append(with_hash(entry, digest))

        previous = old_by_id.get(pid)
        if previous is not None:
            # An entry that had no hash before is being migrated, not
            # changed, so there is nothing to compare and nothing to warn
            # about.
            was_hashed = SHA256_RE.match(str(previous.get("sha256") or ""))
            content_changed = was_hashed and previous["sha256"] != digest
            version_same = previous.get("version") == entry.get("version")
            if content_changed and version_same:
                print(
                    f"WARN  {pid!r}: the file changed but 'version' is still "
                    f"{entry.get('version')!r}. Existing users would receive "
                    "different code under the same version and would not be "
                    "offered an update. Bump the version."
                )

    data["plugins"] = new_plugins
    dump_index(data, path)
    if changed:
        print(f"\n{changed} hash(es) updated in {os.path.basename(path)}")
    else:
        print(f"\nAll hashes already correct in {os.path.basename(path)}")
    return problems


# --- Entry point -------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate the manifest (default)",
    )
    mode.add_argument(
        "--update",
        action="store_true",
        help="recompute and rewrite every sha256",
    )
    parser.add_argument(
        "--index",
        default=INDEX_PATH,
        help="path to index.json (default: the one next to this repo's root)",
    )
    args = parser.parse_args(argv)

    if args.update:
        return 1 if update(args.index) else 0
    return 1 if check(args.index) else 0


if __name__ == "__main__":
    sys.exit(main())
