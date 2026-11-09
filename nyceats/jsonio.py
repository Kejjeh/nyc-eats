"""Read and write the committed JSON files the same way everywhere.

Writes go to a temp file first and are then renamed over the target, so a crash
mid-write (or a Ctrl-C during a live discovery run) never leaves a half-written
ledger. A truncated ledger would read as "no calls made" and lift the cap.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        if default is None:
            raise FileNotFoundError(f"{path} does not exist")
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data, *, compact_rows: bool = False) -> None:
    """Write `data` atomically. `compact_rows` puts each list/dict member on one line.

    One row per line keeps a 24,000-row file reviewable in a diff without paying
    for pretty-printing every field.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact_rows and isinstance(data, list):
        body = "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in data) + "\n]\n"
    elif compact_rows and isinstance(data, dict):
        body = "{\n" + ",\n".join(
            f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)}"
            for k, v in sorted(data.items())) + "\n}\n"
    else:
        body = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
