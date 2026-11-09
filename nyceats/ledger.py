"""The Quota ledger: every billable Google call, counted per SKU per month, with a hard cap.

ADR 0002: the guide spends nothing. Each Places SKU has its own monthly free
allowance (1,000 for the Enterprise tiers, more for Pro and Essentials). The
code caps every capped SKU at 950 a month, so a miscount of up to 50 still
lands inside the free tier.

A call is counted BEFORE it is sent. A call that is counted and then fails
costs one unit of headroom; a call that is sent and then not counted (crash,
network error, Ctrl-C) could push a real month past the free tier. Only the
first mistake is affordable.

Three more ways the count could go DOWN, each closed here (review of
2026-11-09):
- Two runs at once, each holding its own copy and overwriting the other's
  count. Every reservation re-reads the file under a lock file.
- The committed file rolled back by `git restore`/`stash`/`checkout`, or a
  fresh clone. A second copy lives outside the repo (`~/.nyceats/`), and the
  count used is the higher of the two, per SKU per month.
- A missing file read as "no calls". The committed ledger must exist unless
  the caller explicitly allows a new one.

The month is Google's billing month, which runs on Pacific time. Counting in
Eastern or UTC would put the first hours of each month in the wrong bucket.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import paths
from .jsonio import read_json, write_json

CAP = 950
BILLING_TZ = ZoneInfo("America/Los_Angeles")
LOCK_WAIT_S = 30

# SKUs with no charge at all. Counted (so the record is complete) but never capped.
UNCAPPED = {"text_search_essentials_ids"}

KNOWN_SKUS = UNCAPPED | {
    "text_search_pro", "text_search_enterprise", "text_search_enterprise_atmosphere",
    "nearby_search_pro", "nearby_search_enterprise", "nearby_search_enterprise_atmosphere",
    "place_details_essentials", "place_details_pro", "place_details_enterprise",
    "place_details_enterprise_atmosphere",
}


class QuotaExhausted(RuntimeError):
    """Raised instead of making a call that would pass the monthly cap."""


def billing_month(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("billing_month needs an aware datetime; a naive one has no billing month")
    return now.astimezone(BILLING_TZ).strftime("%Y-%m")


def _read(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"months": {}}
    data = read_json(path)
    if "months" not in data:
        raise ValueError(f"{path} is not a quota ledger (no 'months' key); refusing to guess")
    return data


class Ledger:
    def __init__(self, path: Path | None = None, *, cap: int = CAP, mirror: Path | None = None,
                 allow_new: bool = False):
        self.path = Path(path) if path is not None else paths.LEDGER
        self.mirror = Path(mirror) if mirror is not None else None
        self.cap = cap
        if not self.path.exists() and not allow_new:
            raise FileNotFoundError(
                f"{self.path} is missing. It is committed; restore it from git rather than starting "
                "from zero, which would forget this month's calls.")
        self._load()

    def _load(self) -> None:
        """The committed file, with every count raised to the mirror's where the mirror is higher."""
        self.data = _read(self.path)
        for month, skus in _read(self.mirror)["months"].items():
            mine = self.data["months"].setdefault(month, {})
            for sku, n in skus.items():
                mine[sku] = max(int(mine.get(sku, 0)), int(n))

    def used(self, sku: str, month: str | None = None) -> int:
        month = month or billing_month()
        return int(self.data["months"].get(month, {}).get(sku, 0))

    def remaining(self, sku: str, month: str | None = None) -> int | None:
        """Calls left this month, or None for an uncapped SKU."""
        self._check(sku)
        if sku in UNCAPPED:
            return None
        return max(0, self.cap - self.used(sku, month))

    def reserve(self, sku: str, n: int = 1, *, now: datetime | None = None) -> None:
        """Count n calls now, and save, or raise QuotaExhausted without counting anything."""
        self._check(sku)
        if n < 1:
            raise ValueError("reserve at least one call")
        month = billing_month(now)
        with _FileLock(self.path.with_suffix(".lock")):
            self._load()  # another process may have reserved since we last looked
            used = self.used(sku, month)
            if sku not in UNCAPPED and used + n > self.cap:
                raise QuotaExhausted(
                    f"{sku}: {used} of {self.cap} calls already used in {month}; "
                    f"{n} more would pass the cap. Nothing was sent.")
            self.data["months"].setdefault(month, {})[sku] = used + n
            if self.mirror is not None:
                # The mirror first: if the repo copy then fails to write, the higher count survives.
                write_json(self.mirror, {"months": self.data["months"],
                                         "notes": f"Mirror of {self.path}; never lower a count."})
            write_json(self.path, self.data)

    @staticmethod
    def _check(sku: str) -> None:
        if sku not in KNOWN_SKUS:
            raise ValueError(f"unknown SKU {sku!r}; add it to ledger.KNOWN_SKUS with its free cap first")


class _FileLock:
    """A lock file created exclusively. A stale one (a killed run) is reported, never broken silently."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"{self.path} has been held for {LOCK_WAIT_S}s. If no other nyceats run is going, "
                        "a killed run left it behind: delete it and run again.") from None
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
