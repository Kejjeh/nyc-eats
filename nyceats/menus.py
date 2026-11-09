"""Menu crawl: read each restaurant's own website for what Google's listing cannot say.

Free (no Google calls), but it visits about a thousand small sites, so it is polite:
robots.txt is obeyed, one request at a time per site, a 10 s timeout, a 2 MB cap
per page, at most `MAX_PAGES` pages per site (the home page plus links that look
like a menu). Results go to `data/menus.json`, one record per place_id:

  status    ok | robots | http <code> | error <kind> | pdf only | no text
  pages     the URLs read
  evidence  theme -> the sentence that mentions it ("Our 10-course tasting menu ...")
  prices    dollar amounts printed next to that sentence, e.g. ["$185"]
  checked   date read (YYYY-MM-DD)

Every status is counted and printed. A site that could not be read is "not checked",
never "checked and found nothing": `build` only treats status ok as a reading.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from . import paths
from .jsonio import read_json, write_json
from .places_api import now_iso

USER_AGENT = "nyc-eats-menu-check/1.0 (+https://kejjeh.github.io/nyc-eats/)"
TIMEOUT = 10
MAX_BYTES = 2_000_000
MAX_PAGES = 4
WORKERS = 8
STALE_DAYS = 30

# What a restaurant's own site has to say for a theme to count as checked on its menu.
# Narrower than build.THEME_WORDS: a site is long, so a loose word ("counter", "game")
# would match somewhere on almost every page.
MENU_WORDS = {
    # Five courses or more: a "3-course" family meal or lunch is a prix fixe, not a tasting menu.
    "tasting-menu": r"tasting menu|chef'?s tasting|degustation|\b(?:[5-9]|[1-3]\d)[- ]courses?\b|multi-?course",
    "prix-fixe": r"prix[- ]fixe|fixed[- ]price menu|set menu",
    "omakase": r"omakase|kaiseki|kappo",
    "chefs-counter": r"chef'?s counter|chef'?s table|counter seats?|omakase counter",
}
# A sentence about a one-night holiday or event menu says nothing about what the restaurant serves
# the rest of the year ("2026 THANKSGIVING DINNER PRIX FIXE"), so it is not evidence.
ONE_OFF = re.compile(r"thanksgiving|christmas|xmas|new year|nye\b|valentine|easter|mother'?s day|"
                     r"father'?s day|hanukkah|passover|holiday|restaurant week|halloween|super bowl", re.I)
SNIPPET = 220
MENU_LINK = re.compile(r"menu|tasting|omakase|prix|dinner|food|kaiseki|course", re.I)
PRICE = re.compile(r"\$\s?(\d{2,4})(?:\.\d\d)?")


class _Page(HTMLParser):
    """Visible text and links of one HTML page. Script, style and noscript are skipped."""

    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip = 0
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._label = []
        elif tag in ("p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._label).strip()))
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._label.append(data.strip())

    def text(self) -> str:
        t = unescape(" ".join(self.parts)).replace(" ", " ")
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        return re.sub(r"\s*\n\s*", "\n", t).strip()


def parse_html(html: str) -> tuple[str, list[tuple[str, str]]]:
    p = _Page()
    p.feed(html)
    p.close()
    return p.text(), p.links


def menu_links(base_url: str, links: list[tuple[str, str]], limit: int = MAX_PAGES - 1) -> list[str]:
    """Same-site links whose URL or label looks like a menu, in page order, no repeats, no PDFs."""
    host = urlparse(base_url).netloc.lower().removeprefix("www.")
    out: list[str] = []
    for href, label in links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        u = urlparse(url)
        if u.scheme not in ("http", "https") or u.netloc.lower().removeprefix("www.") != host:
            continue
        if u.path.lower().endswith(".pdf"):
            continue
        if not (MENU_LINK.search(u.path) or MENU_LINK.search(label)):
            continue
        if url.rstrip("/") == base_url.rstrip("/") or url in out:
            continue
        out.append(url)
        if len(out) >= limit:
            break
    return out


def find_evidence(text: str) -> tuple[dict[str, str], list[str]]:
    """theme -> the sentence that mentions it; and dollar amounts in those sentences."""
    evidence: dict[str, str] = {}
    prices: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    for theme, pattern in MENU_WORDS.items():
        rx = re.compile(pattern, re.I)
        for s in sentences:
            m = rx.search(s)
            if m and not ONE_OFF.search(s):
                # A window around the match, so a long sentence keeps the words that made it evidence.
                s = s.strip()
                start = max(0, min(m.start() - 80, len(s) - SNIPPET))
                snippet = ("…" if start else "") + s[start:start + SNIPPET]
                evidence[theme] = snippet
                for m in PRICE.finditer(s):
                    amount = int(m.group(1))
                    if 25 <= amount <= 2000 and f"${amount}" not in prices:
                        prices.append(f"${amount}")
                break
    return evidence, prices


def current_evidence(menu: dict | None) -> dict[str, str]:
    """The stored evidence that still passes today's MENU_WORDS and ONE_OFF.

    A site is re-read only every STALE_DAYS, so when the rules tighten, `build` re-checks each
    stored sentence instead of trusting what an older rule accepted. (It cannot find a sentence an
    older rule missed; the next re-read does.)
    """
    if not menu or menu.get("status") != "ok":
        return {}
    # A sentence stored whole-but-cut by the first crawl (exactly SNIPPET long, from its start) may
    # have lost the matching words past the cut; only the one-off check can be repeated on it.
    def cut(s):
        return len(s) >= SNIPPET and not s.startswith("…")
    return {t: s for t, s in (menu.get("evidence") or {}).items()
            if t in MENU_WORDS and not ONE_OFF.search(s) and (cut(s) or re.search(MENU_WORDS[t], s, re.I))}


class _Fetcher:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT

    def robots(self, url: str) -> RobotFileParser:
        u = urlparse(url)
        rp = RobotFileParser()
        try:
            r = self.s.get(f"{u.scheme}://{u.netloc}/robots.txt", timeout=TIMEOUT)
            # No robots.txt (404) means everything is allowed; 401/403 means nothing is.
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.ok:
                rp.parse(r.text.splitlines())
            else:
                rp.allow_all = True
        except requests.RequestException:
            rp.allow_all = True
        return rp

    def get(self, url: str) -> tuple[str | None, str]:
        """(html, status). status is 'ok' or why there is no HTML."""
        try:
            r = self.s.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
        except requests.Timeout:
            return None, "error timeout"
        except requests.exceptions.SSLError:
            return None, "error ssl"
        except requests.ConnectionError:
            return None, "error connection"
        except requests.RequestException as e:
            return None, f"error {type(e).__name__}"
        with r:
            if not r.ok:
                return None, f"http {r.status_code}"
            ctype = r.headers.get("Content-Type", "").lower()
            if "pdf" in ctype:
                return None, "pdf only"
            if "html" not in ctype and "text" not in ctype and ctype:
                return None, f"error type {ctype.split(';')[0]}"
            body = b""
            for chunk in r.iter_content(65536):
                body += chunk
                if len(body) > MAX_BYTES:
                    break
            return decode(body, ctype), "ok"


def decode(body: bytes, content_type: str = "") -> str:
    """Page bytes -> text. The header's charset when it names one, else the page's <meta charset>,
    else UTF-8, else Windows-1252 (older sites send cp1252 bullets and quotes with no charset)."""
    m = re.search(r"charset=([\w-]+)", content_type) or \
        re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
    if m:
        name = m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)
        try:
            return body.decode(name)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


def check_site(website: str, fetcher: _Fetcher) -> dict:
    """Read one restaurant's site. Never raises for a site problem; the status says what happened."""
    rec = {"site": website, "pages": [], "evidence": {}, "prices": [], "checked": now_iso()[:10]}
    rp = fetcher.robots(website)
    if not rp.can_fetch(USER_AGENT, website):
        rec["status"] = "robots"
        return rec
    html, status = fetcher.get(website)
    if html is None:
        rec["status"] = status
        return rec
    text, links = parse_html(html)
    texts = [text]
    rec["pages"].append(website)
    for url in menu_links(website, links):
        if not rp.can_fetch(USER_AGENT, url):
            continue
        time.sleep(0.5)  # one site, one request at a time, with a pause
        h, _ = fetcher.get(url)
        if h:
            texts.append(parse_html(h)[0])
            rec["pages"].append(url)
    full = "\n".join(texts)
    if len(full) < 200:
        # A JavaScript-only site: there is nothing to read, which is not the same as "no tasting menu".
        rec["status"] = "no text"
        return rec
    rec["evidence"], rec["prices"] = find_evidence(full)
    rec["status"] = "ok"
    return rec


def due(places: dict, menus: dict, today: str, everything: bool = False,
        scope: set | None = None) -> list[tuple[str, str]]:
    """(place_id, website) pairs to read now: never read, read for another URL, or older than STALE_DAYS.

    `scope` limits the crawl to places in the published guide: most places discovery finds are
    rated below 4.2 or are not restaurants, and their sites are not worth a visit.
    """
    from datetime import date
    t = date.fromisoformat(today)
    out = []
    for pid, g in sorted(places.items()):
        if scope is not None and pid not in scope:
            continue
        site = g.get("website")
        if not site:
            continue
        old = menus.get(pid)
        if everything or not old or old.get("site") != site:
            out.append((pid, site))
            continue
        age = (t - date.fromisoformat(old["checked"])).days
        if age >= STALE_DAYS:
            out.append((pid, site))
    return out


def crawl(limit: int | None = None, everything: bool = False, fetcher: _Fetcher | None = None,
          workers: int = WORKERS) -> dict:
    places = read_json(paths.PLACES, default={})
    menus = read_json(paths.MENUS, default={})
    site = read_json(paths.SITE_DATA, default={"restaurants": None})
    scope = {r["id"] for r in site["restaurants"]} if site["restaurants"] is not None else None
    todo = due(places, menus, now_iso()[:10], everything, scope)[: limit or None]
    fetcher = fetcher or _Fetcher()
    statuses: Counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (pid, _), rec in zip(todo, pool.map(lambda t: check_site(t[1], fetcher), todo)):
            menus[pid] = rec
            statuses[rec["status"].split(" ")[0] if rec["status"].startswith("error") else rec["status"]] += 1
    # Places that left places.json leave the menu file too.
    menus = {pid: m for pid, m in menus.items() if pid in places}
    write_json(paths.MENUS, menus, compact_rows=True)
    themes = Counter(t for m in menus.values() if m.get("status") == "ok" for t in m.get("evidence", {}))
    return {"read_now": len(todo), "status": dict(statuses), "menus_on_file": len(menus),
            "ok_on_file": sum(1 for m in menus.values() if m.get("status") == "ok"),
            "evidence_by_theme": dict(themes)}
