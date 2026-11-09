"""The Quota ledger: every billable Google call, counted per SKU per month, with a hard cap.

ADR 0002: the guide spends nothing. Each Places SKU has its own monthly free
allowance (1,000 for the Enterprise tiers, more for Pro and Essentials). The
code caps every capped SKU at 950 a month, so a miscount of up to 50 still
lands inside the free tier.

A call is counted BEFORE it is sent. A call that is counted and then fails
costs one unit of headroom; a call that is sent and then not counted (crash,
network error, Ctrl-C) could push a real month past the free tier. Only the
first mistake is affordable.

The month is Google's billing month, which runs on Pacific time. Counting in
Eastern or UTC would put the first hours of each month in the wrong bucket.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import paths
from .jsonio import read_json, write_json

CAP = 950
BILLING_TZ = ZoneInfo("America/Los_Angeles")

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


class Ledger:
    def __init__(self, path: Path = paths.LEDGER, *, cap: int = CAP):
        self.path = Path(path)
        self.cap = cap
        self.data = read_json(self.path, default={"months": {}})
        if "months" not in self.data:
            raise ValueError(f"{self.path} is not a quota ledger (no 'months' key); refusing to guess")

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
        used = self.used(sku, month)
        if sku not in UNCAPPED and used + n > self.cap:
            raise QuotaExhausted(
                f"{sku}: {used} of {self.cap} calls already used in {month}; "
                f"{n} more would pass the cap. Nothing was sent.")
        self.data["months"].setdefault(month, {})[sku] = used + n
        write_json(self.path, self.data)

    @staticmethod
    def _check(sku: str) -> None:
        if sku not in KNOWN_SKUS:
            raise ValueError(f"unknown SKU {sku!r}; add it to ledger.KNOWN_SKUS with its free cap first")
