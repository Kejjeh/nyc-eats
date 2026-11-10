"""Menu crawl: read each restaurant's own website for what Google's listing cannot say.

Free (no Google calls), but it visits about a thousand small sites, so it is polite:
robots.txt is obeyed, one request at a time per site, a 10 s timeout, a 2 MB cap
per page (8 MB for a PDF), at most `MAX_PAGES` pages per site (the home page plus
links that look like a menu) and `MAX_PDFS` PDF menus linked from those pages.
Many restaurants publish the menu only as a PDF, so a site read without its PDFs
can look silent when it is not (issue #4 item 5). Results go to `data/menus.json`,
one record per place_id:

  status    ok | robots | http <code> | error <kind> | no text
  pages     the URLs read
  evidence  theme -> the sentence that mentions it ("Our 10-course tasting menu ...")
  prices    dollar amounts printed next to that sentence, e.g. ["$185"]
  checked   date read (YYYY-MM-DD)
  reader    READER when read; an older (or missing) number was read by a crawl that skipped PDFs
  pdf_timeouts  menu PDFs that took over PDF_SECONDS to read (only when there were any)

Every status is counted and printed. A site that could not be read is "not checked",
never "checked and found nothing": `build` only treats status ok as a reading.
"""
from __future__ import annotations

import io
import logging
import multiprocessing
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
MAX_PDFS = 2
MAX_PDF_BYTES = 8_000_000
MAX_PDF_PAGES = 12
# pypdf has no time limit, and a crawl thread cannot be stopped, so each PDF is read in its own
# process that is stopped after this many seconds (review of PR #14): one pathological PDF must
# not hang the unattended monthly run.
PDF_SECONDS = 30
WORKERS = 8
STALE_DAYS = 30
# 2: PDF menus are read. `menus --upgrade` re-reads every site an older reader read.
READER = 2

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
# Sites and PDFs often print "Chef’s" with a curly apostrophe; MENU_WORDS spell it straight.
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})
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


# Only MAX_PDFS are read, so the dinner and tasting menus go first and the wine list, brunch or
# private-events PDFs last (review of PR #14): a skipped tasting-menu PDF would read as "silent".
PDF_FIRST = re.compile(r"tasting|dinner|prix|omakase|kaiseki|course|chef|seasonal", re.I)
PDF_LAST = re.compile(r"wine|drink|cocktail|beverage|\bbar\b|brunch|lunch|dessert|kid|happy|catering|"
                      r"event|private|party|press|gift", re.I)


def pdf_candidates(base_url: str, links: list[tuple[str, str]]) -> list[tuple[int, str]]:
    """(rank, url) for PDF links whose URL or label looks like a menu, in page order, no repeats.

    Rank 0 names dinner or a tasting menu, 2 names drinks, brunch or events, 1 is anything else.
    Unlike `menu_links`, any host is allowed: restaurant sites built on Squarespace, Wix or
    BentoBox keep their PDFs on the builder's file host (static1.squarespace.com), and a menu
    PDF linked from the restaurant's own page is the restaurant's own menu.
    """
    out: list[tuple[int, str]] = []
    for href, label in links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.path.lower().endswith(".pdf"):
            continue
        if not (MENU_LINK.search(u.path) or MENU_LINK.search(label)) or url in (v for _, v in out):
            continue
        words = f"{u.path} {label}"
        out.append((0 if PDF_FIRST.search(words) else 2 if PDF_LAST.search(words) else 1, url))
    return out


def pdf_links(base_url: str, links: list[tuple[str, str]], limit: int = MAX_PDFS) -> list[str]:
    """The `limit` best menu PDFs on one page: dinner and tasting menus first, then page order."""
    return [url for _, url in sorted(pdf_candidates(base_url, links), key=lambda c: c[0])][:limit]


def pdf_text(body: bytes, timeout: float = PDF_SECONDS, extract=None) -> str | None:
    """The PDF's text; "" for a PDF that cannot be read; None when reading took over `timeout` s.

    Runs `extract` (default `_extract`) in a spawned process, so it can be stopped. Spawn, not fork:
    the crawl runs in threads, and forking a threaded process can deadlock. `extract` must be a
    module-level function (it is pickled to the child). Never raises.
    """
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_pdf_child, args=(extract or _extract, body, send), daemon=True)
    child.start()
    send.close()
    try:
        text = receive.recv() if receive.poll(timeout) else None
    except (EOFError, OSError):  # the child died without answering
        text = ""
    finally:
        if child.is_alive():
            child.terminate()
        child.join(5)
        receive.close()
    return text


def _pdf_child(extract, body, send) -> None:
    try:
        text = extract(body)
        send.send(text if isinstance(text, str) else "")
    except Exception:  # noqa: BLE001 - anything the parser raises means "unreadable"
        send.send("")
    finally:
        send.close()


def _extract(body: bytes) -> str:
    """The text of the first MAX_PDF_PAGES pages, or "" for a PDF that cannot be read.

    A broken or scanned PDF is one site's problem, and the crawl's "no text" status already says a
    site had nothing to read.
    """
    try:
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed-but-readable PDFs are common
        reader = PdfReader(io.BytesIO(body))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES]).strip()
    except Exception:  # noqa: BLE001 - pypdf raises many kinds on a bad file; all mean "unreadable"
        return ""


def find_evidence(text: str) -> tuple[dict[str, str], list[str]]:
    """theme -> the sentence that mentions it; and dollar amounts in those sentences."""
    evidence: dict[str, str] = {}
    prices: list[str] = []
    text = text.translate(APOSTROPHES)
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
            if t in MENU_WORDS and not ONE_OFF.search(s)
            and (cut(s) or re.search(MENU_WORDS[t], s.translate(APOSTROPHES), re.I))}


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
        """(content, status). status 'ok': content is HTML; 'pdf': content is the PDF's text;
        anything else says why there is no content."""
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
            is_pdf = "pdf" in ctype or urlparse(url).path.lower().endswith(".pdf")
            if not is_pdf and "html" not in ctype and "text" not in ctype and ctype:
                return None, f"error type {ctype.split(';')[0]}"
            cap = MAX_PDF_BYTES if is_pdf else MAX_BYTES
            buf = bytearray()
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) > cap:
                    break
            body = bytes(buf)
            if is_pdf:
                # A PDF cut at the cap has no trailer and reads as "", which is "no text", not a guess.
                text = pdf_text(body)
                return (None, "pdf timeout") if text is None else (text, "pdf")
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


def _read(fetcher: _Fetcher, url: str) -> tuple[str | None, list, str]:
    """(text, links, status) of one page or PDF."""
    content, status = fetcher.get(url)
    if content is None:
        return None, [], status
    if status == "pdf":
        return content, [], "ok"
    text, links = parse_html(content)
    return text, links, "ok"


def check_site(website: str, fetcher: _Fetcher) -> dict:
    """Read one restaurant's site. Never raises for a site problem; the status says what happened.

    The home page, then up to MAX_PAGES - 1 menu pages it links, then up to MAX_PDFS menu PDFs
    linked from any of those (the usual shape is home -> /menu -> dinner.pdf).
    """
    rec = {"site": website, "pages": [], "evidence": {}, "prices": [], "checked": now_iso()[:10],
           "reader": READER}
    rp = fetcher.robots(website)
    if not rp.can_fetch(USER_AGENT, website):
        rec["status"] = "robots"
        return rec
    text, links, status = _read(fetcher, website)
    if text is None:
        rec["status"] = status
        return rec
    texts, all_links = [text], [(website, links)]
    rec["pages"].append(website)
    for url in menu_links(website, links):
        if not rp.can_fetch(USER_AGENT, url):
            continue
        time.sleep(0.5)  # one site, one request at a time, with a pause
        t, page_links, _ = _read(fetcher, url)
        if t:
            texts.append(t)
            all_links.append((url, page_links))
            rec["pages"].append(url)
    candidates: list[tuple[int, str]] = []
    for base, page_links in all_links:
        candidates += [c for c in pdf_candidates(base, page_links)
                       if c[1] not in rec["pages"] and c[1] not in (u for _, u in candidates)]
    pdfs = [url for _, url in sorted(candidates, key=lambda c: c[0])]  # stable: home page first per rank
    host = urlparse(website).netloc.lower().removeprefix("www.")
    for url in pdfs[:MAX_PDFS]:
        same_site = urlparse(url).netloc.lower().removeprefix("www.") == host
        if not (rp if same_site else fetcher.robots(url)).can_fetch(USER_AGENT, url):
            continue
        time.sleep(0.5)
        t, _, status = _read(fetcher, url)
        if t:
            texts.append(t)
            rec["pages"].append(url)
        elif status == "pdf timeout":
            # Recorded, so a site whose menu PDF could not be read in time is visible in the data
            # instead of quietly reading as a site that names no tasting menu.
            rec.setdefault("pdf_timeouts", []).append(url)
    full = "\n".join(texts)
    if len(full) < 200:
        # A JavaScript-only site: there is nothing to read, which is not the same as "no tasting menu".
        rec["status"] = "no text"
        return rec
    rec["evidence"], rec["prices"] = find_evidence(full)
    rec["status"] = "ok"
    return rec


def due(places: dict, menus: dict, today: str, everything: bool = False,
        scope: set | None = None, upgrade: bool = False) -> list[tuple[str, str]]:
    """(place_id, website) pairs to read now: never read, read for another URL, or older than STALE_DAYS.

    `upgrade` also re-reads every site an older READER read (before PDFs were read).

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
        if everything or not old or old.get("site") != site or (upgrade and old.get("reader", 1) < READER):
            out.append((pid, site))
            continue
        age = (t - date.fromisoformat(old["checked"])).days
        if age >= STALE_DAYS:
            out.append((pid, site))
    return out


def crawl(limit: int | None = None, everything: bool = False, fetcher: _Fetcher | None = None,
          workers: int = WORKERS, upgrade: bool = False) -> dict:
    places = read_json(paths.PLACES, default={})
    menus = read_json(paths.MENUS, default={})
    site = read_json(paths.SITE_DATA, default={"restaurants": None})
    scope = {r["id"] for r in site["restaurants"]} if site["restaurants"] is not None else None
    todo = due(places, menus, now_iso()[:10], everything, scope, upgrade)[: limit or None]
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
            "pdfs_read_now": sum(1 for pid, _ in todo for u in menus.get(pid, {}).get("pages", [])
                                 if urlparse(u).path.lower().endswith(".pdf")),
            "pdf_timeouts_now": sum(len(menus.get(pid, {}).get("pdf_timeouts", [])) for pid, _ in todo),
            "ok_on_file": sum(1 for m in menus.values() if m.get("status") == "ok"),
            "evidence_by_theme": dict(themes)}
