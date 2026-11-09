"""The City spine: every restaurant the health department inspected in the last 18 months.

Free, no key (README, "NYC health inspections"). The guide uses it for three
things Google is not allowed to supply (ADR 0001): the neighborhood (DOHMH's
own `nta` code, so no point-in-polygon on Google coordinates), the borough of
each ZIP code, and the restaurant density that lays out the nearby-search grid.

One row per `camis`, the department's stable restaurant ID.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

import math

from . import paths
from .jsonio import read_json, write_json
from .names import building_number, name_similarity, phone_digits

DOHMH_URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
NTA_URL = "https://data.cityofnewyork.us/resource/swpk-hqdp.json"
BOROUGHS = ("Bronx", "Manhattan", "Brooklyn", "Queens")
WINDOW_DAYS = 548  # 18 months
_FIELDS = "camis,dba,boro,building,street,zipcode,phone,cuisine_description,latitude,longitude,nta"


def fetch_rows(session, today: date | None = None) -> list[dict]:
    """One grouped query: one row per distinct (camis, its fields), latest inspection date on each."""
    since = (today or date.today()) - timedelta(days=WINDOW_DAYS)
    boros = ",".join(f"'{b}'" for b in BOROUGHS)
    r = session.get(DOHMH_URL, timeout=120, params={
        "$select": _FIELDS + ",max(inspection_date) as last_inspected",
        "$where": f"inspection_date > '{since.isoformat()}T00:00:00' AND boro in({boros})",
        "$group": _FIELDS, "$limit": 100000,
    })
    r.raise_for_status()
    rows = r.json()
    if len(rows) >= 100000:
        raise RuntimeError("DOHMH returned the row limit exactly; the spine would be silently truncated")
    return rows


def parse_rows(rows: list[dict]) -> list[dict]:
    """Raw DOHMH rows -> one record per camis, the most recently inspected version winning."""
    best: dict[str, dict] = {}
    for r in rows:
        camis = r.get("camis")
        if not camis or r.get("boro") not in BOROUGHS:
            continue
        lat, lng = _coord(r.get("latitude")), _coord(r.get("longitude"))
        rec = {
            "camis": camis, "name": (r.get("dba") or "").strip(), "borough": r["boro"],
            "building": (r.get("building") or "").strip(), "street": (r.get("street") or "").strip(),
            "zip": (r.get("zipcode") or "").strip() or None, "phone": phone_digits(r.get("phone")),
            "cuisine": r.get("cuisine_description"), "nta": r.get("nta") or None,
            "lat": round(lat, 5) if lat else None, "lng": round(lng, 5) if lng else None,
            "last_inspected": (r.get("last_inspected") or "")[:10] or None,
        }
        old = best.get(camis)
        if old is None or (rec["last_inspected"] or "") > (old["last_inspected"] or ""):
            best[camis] = rec
    return sorted(best.values(), key=lambda x: x["camis"])


def _coord(v) -> float | None:
    """DOHMH writes a missing coordinate as 0, which is a point in the Atlantic. Treat it as missing."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f else None


GRADES = ("A", "B", "C")


def fetch_grades(session, today: date | None = None) -> dict[str, dict]:
    """camis -> {"grade", "grade_date"}: the letter on its most recent graded inspection.

    Only A, B and C are letters a restaurant posts. N (not yet graded), P/Z (grade pending) are
    not grades and are left out, so an ungraded place shows no grade rather than a wrong one.
    """
    since = (today or date.today()) - timedelta(days=WINDOW_DAYS)
    letters = ",".join(f"'{g}'" for g in GRADES)
    r = session.get(DOHMH_URL, timeout=120, params={
        "$select": "camis,grade,max(grade_date) as last_graded",
        "$where": f"grade_date > '{since.isoformat()}T00:00:00' AND grade in({letters})",
        "$group": "camis,grade", "$limit": 100000})
    r.raise_for_status()
    rows = r.json()
    if len(rows) >= 100000:
        raise RuntimeError("DOHMH grades hit the row limit exactly; grades would be silently truncated")
    return latest_grades(rows)


def latest_grades(rows: list[dict]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for r in rows:
        camis, g, d = r.get("camis"), r.get("grade"), (r.get("last_graded") or "")[:10]
        if not camis or g not in GRADES or not d:
            continue
        if camis not in best or d > best[camis]["grade_date"]:
            best[camis] = {"grade": g, "grade_date": d}
    return best


def fetch_nta_names(session) -> dict[str, str]:
    r = session.get(NTA_URL, timeout=60, params={"$select": "nta_code,nta_name", "$where": "year='2010'",
                                                "$limit": 1000})
    r.raise_for_status()
    return {row["nta_code"]: row["nta_name"] for row in r.json() if row.get("nta_code")}


def refresh(session=None) -> dict:
    """Fetch both city datasets and write them. Free; no Google involved."""
    import requests
    session = session or requests.Session()
    spine = parse_rows(fetch_rows(session))
    grades = fetch_grades(session)
    for s in spine:
        s.update(grades.get(s["camis"], {"grade": None, "grade_date": None}))
    names = fetch_nta_names(session)
    missing = sorted({s["nta"] for s in spine if s["nta"]} - set(names))
    if missing:
        raise RuntimeError(f"NTA codes with no name: {missing}. The NTA table changed; check NTA_URL.")
    old = read_json(paths.SPINE, default=[])
    if old and len(spine) < 0.8 * len(old):
        raise RuntimeError(f"spine shrank from {len(old)} to {len(spine)} rows; refusing to overwrite. "
                           "An upstream outage looks like a city that lost a fifth of its restaurants.")
    write_json(paths.SPINE, spine, compact_rows=True)
    write_json(paths.NTA_NAMES, names, compact_rows=True)
    return {"restaurants": len(spine), "by_borough": dict(Counter(s["borough"] for s in spine)),
            "no_nta": sum(1 for s in spine if not s["nta"]), "nta_names": len(names),
            "graded": dict(Counter(s["grade"] for s in spine if s["grade"]))}


def load() -> list[dict]:
    return read_json(paths.SPINE)


def zip_boroughs(spine: list[dict]) -> dict[str, str]:
    """ZIP -> the borough most of its inspected restaurants are in.

    A few ZIPs straddle a line (11385 Ridgewood/Bushwick); the majority wins and
    the ZIP's minority sits in the neighbouring borough. A ZIP absent from the
    spine is outside the four boroughs (New Jersey, Nassau, Westchester), and the
    guide drops it.
    """
    votes: dict[str, Counter] = defaultdict(Counter)
    for s in spine:
        if s["zip"]:
            votes[s["zip"]][s["borough"]] += 1
    return {z: c.most_common(1)[0][0] for z, c in votes.items()}


class SpineIndex:
    """Find the DOHMH record for a Google place: phone first, then name within the ZIP."""

    TILE = 0.002      # degrees, about 170-220 m: the lookup grid for nta_near
    NEAR_M = 120.0    # inspected restaurants this close count as the same block

    def __init__(self, spine: list[dict]):
        self.by_phone: dict[str, list[dict]] = defaultdict(list)
        self.by_zip: dict[str, list[dict]] = defaultdict(list)
        self.by_tile: dict[tuple, list[dict]] = defaultdict(list)
        for s in spine:
            if s["lat"] and s["lng"] and s["nta"]:
                self.by_tile[(int(s["lat"] / self.TILE), int(s["lng"] / self.TILE))].append(s)
            if s["phone"]:
                self.by_phone[s["phone"]].append(s)
            if s["zip"]:
                self.by_zip[s["zip"]].append(s)

    def match(self, name: str | None, phone: str | None, zip_code: str | None,
              address: str | None) -> tuple[dict | None, str]:
        """(record, how) or (None, why not). A miss is reported, never guessed."""
        bldg = building_number(address)
        digits = phone_digits(phone)
        # A shared phone is strong evidence, but a hotel or food hall switchboard serves several rooms,
        # so the name still has to be close, or the building has to agree.
        # Branches of one group can share a phone line, so the record in this ZIP/building goes first.
        same_phone = sorted(self.by_phone.get(digits or "", []),
                            key=lambda s: (s["zip"] != zip_code, s["building"].replace("-", "") != bldg))
        for s in same_phone:
            if name_similarity(name, s["name"]) >= 0.5 or (bldg and s["building"].replace("-", "") == bldg
                                                            and s["zip"] == zip_code):
                return s, "phone"
        cands = [s for s in self.by_zip.get(zip_code or "", [])
                 if name_similarity(name, s["name"]) >= 0.80]
        same_bldg = [s for s in cands if bldg and s["building"].replace("-", "") == bldg]
        if len(same_bldg) == 1:
            return same_bldg[0], "name+building"
        if len(cands) == 1 and not bldg:
            return cands[0], "name in zip"
        if not cands:
            return None, "no DOHMH record with a similar name in this ZIP"
        return None, f"{len(cands)} DOHMH records with similar names in this ZIP; none at this building"

    def nta_at(self, zip_code: str | None, address: str | None) -> str | None:
        """The neighborhood of an address, from the other inspected restaurants at the same building number.

        A neighborhood belongs to the address, not to the restaurant, so a name
        mismatch ("STK Midtown" vs "STK STEAKHOUSE") need not cost the row its
        neighborhood. The building number is compared without the street, so two
        streets can share it within one ZIP ("230 9th Ave" and "230 Fifth Ave",
        both 10001); the code is used only when every such record agrees.
        """
        bldg = building_number(address)
        if not bldg or not zip_code:
            return None
        codes = {s["nta"] for s in self.by_zip.get(zip_code, []) if s["building"].replace("-", "") == bldg}
        return codes.pop() if len(codes) == 1 and None not in codes else None


def _metres(lat1, lng1, lat2, lng2) -> float:
    dy = (lat2 - lat1) * 111_320.0
    dx = (lng2 - lng1) * 111_320.0 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def _nta_near(self, lat: float | None, lng: float | None) -> str | None:
    """The neighborhood shared by every inspected restaurant within NEAR_M of a point.

    For a place whose name, phone and building all miss the spine: its neighbours on the block
    know the neighborhood. Used only when they all agree (on a boundary street they may not),
    and only with at least two of them, so one stray record cannot place a restaurant.
    """
    if lat is None or lng is None:
        return None
    ti, tj = int(lat / self.TILE), int(lng / self.TILE)
    codes = [s["nta"] for di in (-1, 0, 1) for dj in (-1, 0, 1) for s in self.by_tile.get((ti + di, tj + dj), [])
             if _metres(lat, lng, s["lat"], s["lng"]) <= self.NEAR_M]
    return codes[0] if len(codes) >= 2 and len(set(codes)) == 1 else None


SpineIndex.nta_near = _nta_near
