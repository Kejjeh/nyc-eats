"""Find the Google key without ever printing it.

Order: the GOOGLE_PLACES_KEY environment variable, then GOOGLE_API_KEY in the
gitignored `config.py` at the repo root (copy `config.example.py`). Neither is
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
    cfg_path = paths.ROOT / "config.py"
    if cfg_path.exists():
        spec = importlib.util.spec_from_file_location("nyceats_local_config", cfg_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        key = (getattr(mod, "GOOGLE_API_KEY", "") or "").strip()
        if key and key != "YOUR_API_KEY_HERE":
            return key
    raise SystemExit("No Google key: set GOOGLE_PLACES_KEY, or copy config.example.py to config.py and fill it in.")
