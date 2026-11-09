"""Name, phone and address normalising, shared by every match in the package.

`name_similarity` is copied from Kejjeh/omakase `scripts/shared/places.py`, with
its threshold, because it was tuned there on known wrong matches: "Omakase by
Teisui" vs "Omakase By Tento" scores 0.76 and must not pass. Copied, not imported:
the README says the repos share code by copying until a shared package exists.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

SIMILARITY_THRESHOLD = 0.80


def normalize(s: str | None) -> str:
    """Casefold, strip accents and punctuation. 'Hōseki' -> 'hoseki'."""
    folded = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def name_similarity(ours: str | None, theirs: str | None) -> float:
    """0..1. Containment scores 1.0: a longer official name is still a match."""
    a, b = normalize(ours), normalize(theirs)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def phone_digits(s: str | None) -> str | None:
    """'(212) 228-7900' and '2122287900' -> '2122287900'. None when not a 10-digit US number."""
    d = re.sub(r"\D", "", s or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else None


_ZIP = re.compile(r"\bNY,? (\d{5})\b")


def zip_from_address(address: str | None) -> str | None:
    """The ZIP in a Google address ('NY 10003, USA') or a roster address ('Manhattan, NY, 10002')."""
    m = _ZIP.search(address or "")
    return m.group(1) if m else None


def building_number(address: str | None) -> str | None:
    """The house number at the start of an address: '37-04 74th St' -> '3704', '106 E 19th' -> '106'."""
    m = re.match(r"\s*(\d+(?:-\d+)?)\b", address or "")
    return m.group(1).replace("-", "") if m else None
