#!/usr/bin/env python3
"""Validate ``index.json`` against ``schema/index.schema.json``.

Structural counterpart to ``hash_plugins.py --check``: the schema pins the
shape of the manifest (required fields, allowed apps, hash format), while
``hash_plugins.py`` checks the things a schema cannot — that the referenced
files exist and that the hashes actually match them.

Unlike the other tools this one needs ``jsonschema``::

    pip install jsonschema
    python tools/validate_schema.py

Without it, the script says so and exits 0, so it never blocks a maintainer
working offline; CI installs the package and therefore always runs the check.
"""

from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(REPO_ROOT, "index.json")
SCHEMA_PATH = os.path.join(REPO_ROOT, "schema", "index.schema.json")


def main() -> int:
    try:
        import jsonschema
    except ImportError:
        print(
            "jsonschema is not installed, skipping the schema check "
            "(pip install jsonschema to run it)."
        )
        return 0

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    with open(INDEX_PATH, encoding="utf-8") as f:
        index = json.load(f)

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(index), key=lambda e: list(e.path))
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "<root>"
        print(f"FAIL  {location}: {error.message}")
    if errors:
        print(f"\n{len(errors)} schema violation(s) in index.json")
        return 1
    print("index.json matches schema/index.schema.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
