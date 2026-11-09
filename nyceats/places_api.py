"""Google Places API (New): field masks, the SKU each request bills at, response parsing, the client.

A request is billed at the highest SKU among the fields it asks for (README,
"Field -> SKU"). `sku_for` works that out from the mask itself, so the ledger
is charged for what the request will actually cost, not what the caller meant.
An unknown field raises: guessing its tier low is how a mask edit could start
spending from a tier with no free allowance left.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .ledger import Ledger

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

TIERS = ("essentials_ids", "essentials", "pro", "enterprise", "enterprise_atmosphere")
FIELD_TIER = {
    "id": "essentials_ids", "name": "essentials_ids",
    "formattedAddress": "essentials", "location": "essentials", "types": "essentials",
    "addressComponents": "essentials", "shortFormattedAddress": "essentials",
    "displayName": "pro", "businessStatus": "pro", "googleMapsUri": "pro", "primaryType": "pro",
    "primaryTypeDisplayName": "pro",
    "rating": "enterprise", "userRatingCount": "enterprise", "websiteUri": "enterprise",
    "priceLevel": "enterprise", "priceRange": "enterprise", "regularOpeningHours": "enterprise",
    "currentOpeningHours": "enterprise", "nationalPhoneNumber": "enterprise",
    "delivery": "enterprise_atmosphere", "takeout": "enterprise_atmosphere", "dineIn": "enterprise_atmosphere",
    "reservable": "enterprise_atmosphere", "servesDinner": "enterprise_atmosphere",
    "servesLunch": "enterprise_atmosphere", "outdoorSeating": "enterprise_atmosphere",
    "editorialSummary": "enterprise_atmosphere", "reviews": "enterprise_atmosphere",
}
# Text Search has no plain "Essentials" SKU: anything beyond IDs starts at Pro.
_ENDPOINT_SKUS = {
    "text_search": {"essentials_ids": "text_search_essentials_ids", "essentials": "text_search_pro",
                    "pro": "text_search_pro", "enterprise": "text_search_enterprise",
                    "enterprise_atmosphere": "text_search_enterprise_atmosphere"},
    "nearby_search": {"essentials_ids": "nearby_search_pro", "essentials": "nearby_search_pro",
                      "pro": "nearby_search_pro", "enterprise": "nearby_search_enterprise",
                      "enterprise_atmosphere": "nearby_search_enterprise_atmosphere"},
    "place_details": {"essentials_ids": "place_details_essentials", "essentials": "place_details_essentials",
                      "pro": "place_details_pro", "enterprise": "place_details_enterprise",
                      "enterprise_atmosphere": "place_details_enterprise_atmosphere"},
}

# Everything the guide shows, at the Enterprise + Atmosphere tier (delivery, reservable, dine-in).
DETAIL_FIELDS = ("id,displayName,formattedAddress,location,primaryType,types,businessStatus,googleMapsUri,"
                 "rating,userRatingCount,priceLevel,websiteUri,regularOpeningHours,nationalPhoneNumber,"
                 "delivery,takeout,dineIn,reservable,servesDinner,editorialSummary")
SEARCH_MASK = ",".join("places." + f for f in DETAIL_FIELDS.split(","))


def sku_for(endpoint: str, mask: str) -> str:
    if endpoint not in _ENDPOINT_SKUS:
        raise ValueError(f"unknown endpoint {endpoint!r}")
    tiers = []
    for raw in mask.split(","):
        field = raw.strip().removeprefix("places.")
        if field == "nextPageToken" or not field:
            continue
        top = field.split(".")[0]
        if top not in FIELD_TIER:
            raise ValueError(f"field {field!r} has no known SKU tier; add it to FIELD_TIER from Google's docs")
        tiers.append(TIERS.index(FIELD_TIER[top]))
    if not tiers:
        raise ValueError("empty field mask")
    return _ENDPOINT_SKUS[endpoint][TIERS[max(tiers)]]


PRICE_LEVELS = {"PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
                "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}


def parse_place(p: dict, fetched_at: str) -> dict:
    """One API place -> the guide's record. Every field is optional in practice (README recon)."""
    if not p.get("id"):
        raise ValueError("a place with no id cannot be stored: nothing would key it")
    hours = p.get("regularOpeningHours") or {}
    periods = []
    for per in hours.get("periods") or []:
        o, c = per.get("open") or {}, per.get("close")
        if "day" not in o:
            continue
        # A period with no close is open 24 hours from its open time (Google's convention).
        periods.append([o["day"], o.get("hour", 0), o.get("minute", 0),
                        *( [c["day"], c.get("hour", 0), c.get("minute", 0)] if c else [None, None, None])])
    loc = p.get("location") or {}
    return {
        "place_id": p["id"],
        "name": (p.get("displayName") or {}).get("text"),
        "address": p.get("formattedAddress"),
        "lat": loc.get("latitude"), "lng": loc.get("longitude"),
        "primary_type": p.get("primaryType"), "types": p.get("types") or [],
        "business_status": p.get("businessStatus"),
        "maps_url": p.get("googleMapsUri"), "website": p.get("websiteUri"),
        "phone": p.get("nationalPhoneNumber"),
        "rating": p.get("rating"), "reviews": p.get("userRatingCount"),
        "price_level": PRICE_LEVELS.get(p.get("priceLevel")),
        "hours_text": hours.get("weekdayDescriptions"),
        "hours": periods or None,
        "delivery": p.get("delivery"), "takeout": p.get("takeout"), "dine_in": p.get("dineIn"),
        "reservable": p.get("reservable"), "serves_dinner": p.get("servesDinner"),
        "summary": (p.get("editorialSummary") or {}).get("text"),
        "fetched_at": fetched_at,
    }


class PlacesError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Client:
    """Every request passes the ledger first. There is no code path to Google that skips it."""

    def __init__(self, key: str, ledger: Ledger, *, session=None, pause: float = 0.2):
        if not key:
            raise ValueError("no Google API key")
        import requests
        self._key = key
        self.ledger = ledger
        self.session = session or requests.Session()
        self.pause = pause
        self.calls = 0

    def _send(self, method: str, endpoint: str, url: str, mask: str, body: dict | None = None) -> dict:
        self.ledger.reserve(sku_for(endpoint, mask))  # raises QuotaExhausted before anything is sent
        self.calls += 1
        r = self.session.request(method, url, json=body, timeout=30,
                                 headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": mask})
        time.sleep(self.pause)
        if r.status_code != 200:
            # The body names the problem (bad field, quota); the key is in a header, never in the body.
            raise PlacesError(f"{endpoint} HTTP {r.status_code}: {r.text[:300]}", r.status_code)
        return r.json()

    def text_search(self, body: dict) -> dict:
        return self._send("POST", "text_search", TEXT_SEARCH_URL, SEARCH_MASK + ",nextPageToken", body)

    def nearby_search(self, body: dict) -> dict:
        return self._send("POST", "nearby_search", NEARBY_URL, SEARCH_MASK, body)

    def details(self, place_id: str) -> dict:
        return self._send("GET", "place_details", DETAILS_URL.format(place_id=place_id), DETAIL_FIELDS)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
