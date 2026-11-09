"""Find the Google key without ever printing it.

Order: the GOOGLE_PLACES_KEY environment variable, then GOOGLE_API_KEY in the
gitignored `config.py` at the repo root (copy `config.example.py`), then GOOGLE_API_KEY in the
omakase checkout's gitignored `scripts/config.py` (`paths.OMAKASE_CONFIG`), the key the first
live runs used. That file is only read, never written. Neither is
ever committed; `.gitignore` covers `config.py`, and CI has no key at all.
"""
from __future__ import annotations

import importlib.util
import os

from . import paths


def google_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_KEY", "").strip()
    if key:
        return key
    for i, cfg_path in enumerate((paths.ROOT / "config.py", paths.OMAKASE_CONFIG)):
        if not cfg_path.exists():
            continue
        spec = importlib.util.spec_from_file_location(f"nyceats_key_config_{i}", cfg_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        key = (getattr(mod, "GOOGLE_API_KEY", "") or "").strip()
        if key and key != "YOUR_API_KEY_HERE":
            return key
    raise SystemExit("No Google key: set GOOGLE_PLACES_KEY, or copy config.example.py to config.py and fill it in.")
