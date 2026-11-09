/* nyc-eats — the guide page.
 *
 * Ported from nyc-restaurants docs/venues.js (the award roster page): the same
 * shape — STATE, FACETS, the URL hash as state, facet counts computed with
 * matches(row, exceptFacet), el() + textContent and never innerHTML for data,
 * every href through isHttpURL(). The comments there explain why each of those
 * rules exists; they are not repeated here. Pure logic lives in core.js.
 */
'use strict';

const { fold, isHttpURL, isOpenAt, nycNow, weightedRating, distanceMi, priceLabel, deliveryLinks,
        awardKind } = window.EATS;

const DATA_URL = 'data/restaurants.json';
const BOROUGHS_URL = 'data/boroughs.json';
const GEOSEARCH = 'https://geosearch.planninglabs.nyc/v2/search';
const FETCH_TIMEOUT_MS = 15000;
const PAGE = 100;
const FACET_LIMIT = 14;
const DEFAULT_MIN = 4.5; // ADR 0002: collect 4.2+, show 4.5+ unless asked
const DEFAULT_SORT = 'score';

const $ = (sel) => document.querySelector(sel);
const $opt = (sel) => document.querySelector(sel) || el('span');
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const link = (cls, text, href) => {
  const a = el('a', cls, text);
  a.href = href;
  a.rel = 'noreferrer noopener';
  a.target = '_blank';
  return a;
};

const STATE = {
  data: null,
  rows: [],
  byId: new Map(),
  q: '',
  sort: DEFAULT_SORT,
  minRating: DEFAULT_MIN,
  openNow: false,
  near: null,      // { lat, lng, label }
  radius: 1,       // miles; 0 = any
  filters: new Map(),
  shown: PAGE,
  view: 'list',
  pinned: null,
};
let PRIOR = 150;
let RATING_MEAN = 4.5;

/* ---------- derived fields ---------------------------------------------- */

const score = (r) => weightedRating(r.rating, r.reviews, PRIOR, RATING_MEAN);
const dist = (r) => (STATE.near ? distanceMi(STATE.near.lat, STATE.near.lng, r.lat, r.lng) : null);
function openState(r) {
  const now = nycNow();
  return isOpenAt(r.hours, now.day, now.minute);
}
const neighborhoodOf = (r) => r.neighborhood
  || (r.neighborhood_rw ? `${r.neighborhood_rw} (unverified)` : null);

/* ---------- facets ------------------------------------------------------ */

const FACETS = [
  { key: 'category', label: 'Kind of meal',
    get: (r) => [...r.categories, ...(r.restaurant_week ? ['Restaurant Week'] : [])] },
  { key: 'borough', label: 'Borough', get: (r) => (r.borough ? [r.borough] : []) },
  { key: 'neighborhood', label: 'Neighborhood', get: (r) => [neighborhoodOf(r)].filter(Boolean) },
  { key: 'cuisine', label: 'Cuisine', get: (r) => (r.cuisine ? [r.cuisine] : []) },
  { key: 'price', label: 'Price', get: (r) => [priceLabel(r.price)].filter(Boolean) },
  { key: 'award', label: 'Awards', get: (r) => [...new Set(r.awards.map(awardKind))] },
  { key: 'offers', label: 'Offers',
    get: (r) => [r.delivery === true && 'Delivery', r.takeout === true && 'Takeout',
                 r.reservable === true && 'Takes reservations'].filter(Boolean) },
];
const FACET_BY_KEY = new Map(FACETS.map((f) => [f.key, f]));

const PRESETS = [
  { label: 'Tasting menus', apply: () => setFilter('category', ['Tasting menu']) },
  { label: 'Prix fixe', apply: () => setFilter('category', ['Prix fixe', 'Restaurant Week']) },
  { label: 'Omakase', apply: () => setFilter('category', ["Omakase & chef's counter"]) },
  { label: 'Unusual proteins', apply: () => setFilter('category', ['Unusual proteins']) },
  { label: 'Michelin starred', apply: () => setFilter('award', ['Michelin ★', 'Michelin ★★', 'Michelin ★★★']) },
  { label: 'Bronx', apply: () => setFilter('borough', ['Bronx']) },
  { label: 'Delivers', apply: () => setFilter('offers', ['Delivery']) },
];

function setFilter(key, values) {
  STATE.filters.clear();
  STATE.filters.set(key, new Set(values));
}

/* ---------- the URL is the state ----------------------------------------- */

function writeHash() {
  const p = new URLSearchParams();
  for (const [key, set] of STATE.filters) if (set.size) p.set(key, [...set].join('~'));
  if (STATE.q) p.set('q', $('#q').value.trim());
  if (STATE.sort !== DEFAULT_SORT) p.set('sort', STATE.sort);
  if (STATE.minRating !== DEFAULT_MIN) p.set('min', String(STATE.minRating));
  if (STATE.openNow) p.set('open', '1');
  if (STATE.near) {
    p.set('near', `${STATE.near.lat.toFixed(5)},${STATE.near.lng.toFixed(5)}`);
    p.set('at', STATE.near.label);
    p.set('r', String(STATE.radius));
  }
  if (STATE.view !== 'list') p.set('view', STATE.view);
  if (STATE.shown > PAGE) p.set('n', String(STATE.shown));
  const s = p.toString();
  history.replaceState(null, '', s ? `#${s}` : location.pathname + location.search);
}

function knownFacetValues(f) {
  const out = new Set();
  for (const r of STATE.rows) for (const v of f.get(r)) out.add(v);
  return out;
}

function readHash() {
  const raw = location.hash.replace(/^#/, '');
  if (!raw) return;
  const p = new URLSearchParams(raw);
  for (const f of FACETS) {
    const v = p.get(f.key);
    if (!v) continue;
    const known = knownFacetValues(f);
    const set = new Set(v.split('~').filter((x) => known.has(x)));
    if (set.size) STATE.filters.set(f.key, set);
  }
  const q = p.get('q');
  if (q) { STATE.q = fold(q.trim()); $('#q').value = q; }
  const s = p.get('sort');
  if (s && [...$('#sort').options].some((o) => o.value === s)) { STATE.sort = s; $('#sort').value = s; }
  const min = p.get('min');
  if (min && [...$('#minRating').options].some((o) => o.value === min)) {
    STATE.minRating = Number(min); $('#minRating').value = min;
  }
  if (p.get('open') === '1') STATE.openNow = true;
  const near = /^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/.exec(p.get('near') || '');
  if (near) {
    setNear(Number(near[1]), Number(near[2]), p.get('at') || 'the chosen point');
    const r = p.get('r');
    if (r && [...$('#radius').options].some((o) => o.value === r)) { STATE.radius = Number(r); $('#radius').value = r; }
  }
  if (p.get('view') === 'map') STATE.view = 'map';
  const n = Number(p.get('n'));
  if (Number.isInteger(n) && n > PAGE) STATE.shown = Math.min(n, STATE.rows.length);
}

/* ---------- filtering + sorting ----------------------------------------- */

function haystack(r) {
  if (r._hay) return r._hay;
  r._hay = fold([r.name, r.borough, neighborhoodOf(r), r.address, r.cuisine, r.summary,
                 ...(r.also_listed_as || []), ...r.awards, ...r.categories].filter(Boolean).join(' '));
  return r._hay;
}

/* The always-on controls (rating, open now, distance) are tested here too, so a
   facet's count is what clicking it would show under them. */
function matches(r, exceptKey) {
  if (r.rating == null || r.rating < STATE.minRating) return false;
  if (STATE.q && !haystack(r).includes(STATE.q)) return false;
  if (STATE.openNow && openState(r) !== true) return false;
  if (STATE.near && STATE.radius > 0) {
    const d = dist(r);
    if (d == null || d > STATE.radius) return false;
  }
  for (const [key, chosen] of STATE.filters) {
    if (key === exceptKey) continue;
    if (!FACET_BY_KEY.get(key).get(r).some((m) => chosen.has(m))) return false;
  }
  return true;
}

/* Nulls last in every direction: an unrated or unlocated place is not the worst one. */
const nullsLast = (x, y, cmp) => (x == null && y == null ? 0 : x == null ? 1 : y == null ? -1 : cmp(x, y));
const SORTS = {
  score: (a, b) => nullsLast(score(a), score(b), (x, y) => y - x) || a.name.localeCompare(b.name),
  rating: (a, b) => nullsLast(a.rating, b.rating, (x, y) => y - x) || (b.reviews || 0) - (a.reviews || 0),
  reviews: (a, b) => (b.reviews || 0) - (a.reviews || 0),
  distance: (a, b) => nullsLast(dist(a), dist(b), (x, y) => x - y) || SORTS.score(a, b),
  name: (a, b) => a.name.localeCompare(b.name),
};

/* ---------- rendering --------------------------------------------------- */

const AWARD_CLASS = (badge) => (/^Michelin|^Bib/.test(badge) ? 'michelin' : /^NYT/.test(badge) ? 'nyt' : 'beard');

function renderRow(r) {
  const row = el('article', 'venue');
  const head = el('div', 'venueHead');
  head.append(el('h2', 'venueName', r.name));
  if (r.awards.length) head.append(el('span', `pill honor ${AWARD_CLASS(r.awards[0])}`, r.awards[0]));
  for (const c of r.categories) head.append(el('span', 'pill cat', c));
  if (r.restaurant_week) head.append(el('span', 'pill cat', 'Restaurant Week'));
  const price = priceLabel(r.price);
  if (price) head.append(el('span', 'pill price', price));
  const open = openState(r);
  if (open != null) head.append(el('span', `pill ${open ? 'open' : 'shut'}`, open ? 'Open now' : 'Closed now'));
  row.append(head);

  const meta = el('p', 'venueMeta');
  meta.append(el('span', 'where', [neighborhoodOf(r), r.borough].filter(Boolean).join(', ')
                                  || r.address || 'location not established'));
  if (r.rating != null) {
    meta.append(el('span', 'rating', `${r.rating.toFixed(1)}★ (${(r.reviews || 0).toLocaleString()})`));
  }
  if (r.cuisine) meta.append(el('span', 'cuisine', r.cuisine));
  const d = dist(r);
  if (d != null) meta.append(el('span', 'dist', d < 0.1 ? 'here' : `${d.toFixed(1)} mi`));
  row.append(meta);

  const links = el('p', 'links');
  if (isHttpURL(r.website)) links.append(link('', 'Website', r.website));
  if (isHttpURL(r.maps_url)) links.append(link('', 'Google Maps', r.maps_url));
  if (r.phone) {
    const tel = el('a', '', r.phone);
    tel.href = `tel:${r.phone.replace(/[^\d+]/g, '')}`;
    links.append(tel);
  }
  /* Only where Google says the place delivers; the links are the apps' own search pages. */
  if (r.delivery === true) {
    links.append(el('span', 'deliv', 'Delivery:'));
    for (const dl of deliveryLinks(r.name)) links.append(link('deliv', dl.label, dl.url));
  }
  if (links.childNodes.length) row.append(links);

  const extra = el('details', 'more');
  extra.append(el('summary', null, 'More'));
  if (r.summary) extra.append(el('p', null, r.summary));
  if (r.hours_text && r.hours_text.length) {
    const ul = el('ul');
    for (const h of r.hours_text) ul.append(el('li', null, h));
    extra.append(ul);
  }
  if (r.awards.length) extra.append(el('p', null, `Awards: ${r.awards.join(' · ')}`));
  /* Why each category applies (ADR 0003), quoting the restaurant's own site where it was read. */
  for (const [cat, why] of Object.entries(r.category_why || {})) {
    const said = r.menu && r.menu.says && r.menu.says[cat];
    extra.append(el('p', 'why', said ? `${cat}: the restaurant's site says “${said}”`
                                     : `${cat}: ${why}${why.startsWith('price') ? ' (not checked on a menu)' : ''}`));
  }
  if (r.menu && r.menu.prices && r.menu.prices.length) {
    extra.append(el('p', null, `Menu prices on the restaurant's site: ${r.menu.prices.join(', ')}`));
  }
  if (r.menu) extra.append(el('p', 'checked', `Restaurant's own site read ${r.menu.checked}.`));
  if (r.also_listed_as) extra.append(el('p', null, `Also listed as: ${r.also_listed_as.join(', ')}`));
  if (r.address) extra.append(el('p', null, r.address));
  extra.append(el('p', 'checked', r.source === 'google'
    ? `Google details checked ${r.checked}.`
    : 'Rating from the nyc-restaurants award roster; Google details (hours, price, delivery) not fetched yet.'));
  row.append(extra);
  return row;
}

function renderFacets() {
  const box = $('#facets');
  box.textContent = '';
  for (const f of FACETS) {
    const counts = new Map();
    for (const r of STATE.rows) {
      if (!matches(r, f.key)) continue;
      for (const v of f.get(r)) counts.set(v, (counts.get(v) || 0) + 1);
    }
    for (const v of (STATE.filters.get(f.key) || [])) if (!counts.has(v)) counts.set(v, 0);
    if (counts.size < 2 && !STATE.filters.has(f.key)) continue;
    const group = el('div', 'facet');
    group.append(el('h3', null, f.label));
    const chosen = STATE.filters.get(f.key);
    const sorted = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const shown = sorted.slice(0, FACET_LIMIT);
    const shownVals = new Set(shown.map(([v]) => v));
    for (const [v, n] of sorted) if (chosen && chosen.has(v) && !shownVals.has(v)) shown.push([v, n]);
    for (const [v, n] of shown) {
      const label = el('label', 'facetOpt');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.id = `f-${f.key}-${fold(v).replace(/\W+/g, '-')}`;
      cb.checked = Boolean(chosen && chosen.has(v));
      cb.addEventListener('change', () => {
        const set = STATE.filters.get(f.key) || new Set();
        if (cb.checked) set.add(v); else set.delete(v);
        if (set.size) STATE.filters.set(f.key, set); else STATE.filters.delete(f.key);
        STATE.shown = PAGE;
        apply();
      });
      label.append(cb, el('span', 'facetName', v), el('span', 'facetN', String(n)));
      group.append(label);
    }
    const hidden = sorted.length - shown.length;
    if (hidden > 0) group.append(el('p', 'facetMore', `+${hidden} more — use the search box`));
    box.append(group);
  }
}

function renderPresets() {
  const box = $('#presets');
  box.textContent = '';
  for (const p of PRESETS) {
    const b = el('button', 'preset', p.label);
    b.type = 'button';
    b.addEventListener('click', () => { p.apply(); STATE.shown = PAGE; apply(); });
    box.append(b);
  }
}

function renderActive() {
  const box = $('#activeFilters');
  box.textContent = '';
  const chips = [];
  for (const [key, set] of STATE.filters) {
    for (const v of set) chips.push([v, () => { set.delete(v); if (!set.size) STATE.filters.delete(key); }]);
  }
  box.hidden = chips.length === 0;
  for (const [label, undo] of chips) {
    const chip = el('button', 'chip', `${label} ✕`);
    chip.type = 'button';
    chip.addEventListener('click', () => { undo(); STATE.shown = PAGE; apply(); });
    box.append(chip);
  }
  $('#filterCount').textContent = String(chips.length);
  $('#filterCount').hidden = chips.length === 0;
  $('#clearBtn').hidden = chips.length === 0;
  $('#openNow').setAttribute('aria-pressed', String(STATE.openNow));
}

/* Say which control emptied the list, not just "nothing matches". */
function emptyMessage() {
  const msg = $opt('#emptyMsg');
  const loose = STATE.rows.filter((r) => r.rating != null && r.rating >= STATE.minRating).length;
  const parts = [];
  if (STATE.near && STATE.radius > 0) parts.push(`within ${STATE.radius} mi of ${STATE.near.label}`);
  if (STATE.openNow) parts.push('open right now');
  if (STATE.q) parts.push(`matching “${$('#q').value.trim()}”`);
  if (STATE.filters.size) parts.push('with those filters');
  /* Open now can only count places whose hours are known. Say how many it could
     not judge, or an empty list reads as "everything near you is closed". */
  let unknownHours = 0;
  if (STATE.openNow) {
    STATE.openNow = false;
    unknownHours = STATE.rows.filter((r) => matches(r) && openState(r) == null).length;
    STATE.openNow = true;
  }
  msg.textContent = `No restaurant rated ${STATE.minRating}+ is ${parts.join(', ') || 'listed'}. `
    + (unknownHours ? `${unknownHours} otherwise matching have no opening hours on file yet, so Open now `
      + 'cannot include them. ' : '')
    + (STATE.minRating > 4.2 ? `Try a lower rating (${loose} are rated ${STATE.minRating}+ city-wide), ` : '')
    + (STATE.near ? 'a wider distance, ' : '') + 'or clear the filters.';
}

function apply() {
  const hits = STATE.rows.filter((r) => matches(r));
  hits.sort(SORTS[STATE.sort] || SORTS.score);
  const box = $('#rows');
  box.textContent = '';
  if (STATE.view === 'list') {
    for (const r of hits.slice(0, STATE.shown)) box.append(renderRow(r));
  } else {
    renderMap(hits);
  }
  $('#shown').textContent = String(STATE.view === 'list' ? Math.min(STATE.shown, hits.length) : hits.length);
  $('#total').textContent = String(hits.length);
  $('#empty').hidden = hits.length !== 0;
  if (!hits.length) emptyMessage();
  const more = $('#showMore');
  more.hidden = STATE.view !== 'list' || hits.length <= STATE.shown;
  more.textContent = `Show ${Math.min(PAGE, hits.length - STATE.shown)} more`;
  renderActive();
  const focused = document.activeElement && document.activeElement.id;
  renderFacets();
  if (focused) { const again = document.getElementById(focused); if (again) again.focus(); }
  writeHash();
}

/* ---------- near an address --------------------------------------------- */

function setNear(lat, lng, label) {
  STATE.near = { lat, lng, label };
  $('#nearClear').hidden = false;
  $('#nearStatus').textContent = `Near ${label}.`;
  if (STATE.sort === DEFAULT_SORT) { STATE.sort = 'distance'; $('#sort').value = 'distance'; }
}

function clearNear() {
  STATE.near = null;
  $('#near').value = '';
  $('#nearClear').hidden = true;
  $('#nearStatus').textContent = '';
  if (STATE.sort === 'distance') { STATE.sort = DEFAULT_SORT; $('#sort').value = DEFAULT_SORT; }
}

async function timedFetch(url) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, { cache: 'no-cache', signal: ctl.signal });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function geocode(text) {
  $('#nearStatus').textContent = `Looking up “${text}”…`;
  try {
    const j = await timedFetch(`${GEOSEARCH}?size=1&text=${encodeURIComponent(text)}`);
    const f = j.features && j.features[0];
    if (!f) { $('#nearStatus').textContent = `NYC GeoSearch found nothing for “${text}”.`; return; }
    const [lng, lat] = f.geometry.coordinates;
    setNear(lat, lng, (f.properties && f.properties.label) || text);
    STATE.shown = PAGE;
    apply();
  } catch (err) {
    $('#nearStatus').textContent = `Address lookup failed (${err.name === 'AbortError' ? 'no answer in 15 s' : err.message}).`;
  }
}

/* ---------- map (hand-drawn SVG shoreline; no tiles, no third party) ----- */

const svgEl = (tag, attrs) => {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  return n;
};
let MAP = null;
let MAP_LOADING = false;

function buildMap(geo) {
  const shapes = geo.boroughs.filter((b) => b.name !== 'Staten Island');
  const pts = shapes.flatMap((b) => b.rings.flat());
  const lngs = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
  const lng0 = Math.min(...lngs), lng1 = Math.max(...lngs), lat0 = Math.min(...lats), lat1 = Math.max(...lats);
  const K = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180);
  const W = 700, scale = W / ((lng1 - lng0) * K), H = Math.round((lat1 - lat0) * scale), PAD = 8;
  const project = (lat, lng) => [PAD + (lng - lng0) * K * scale, PAD + (lat1 - lat) * scale];
  const svg = svgEl('svg', { viewBox: `0 0 ${W + 2 * PAD} ${H + 2 * PAD}`, role: 'img',
    'aria-label': 'Dot map of the current selection. The list view has the same restaurants with full details.' });
  const land = svgEl('g', { class: 'mapLand' });
  for (const b of shapes) {
    for (const ring of b.rings) {
      land.append(svgEl('path', {
        d: 'M' + ring.map(([x, y]) => project(y, x).map((n) => n.toFixed(1)).join(' ')).join('L') + 'Z' }));
    }
  }
  svg.append(land);
  const dots = svgEl('g', { class: 'mapDots' });
  svg.append(dots);
  return { svg, dots, project };
}

function renderMap(hits) {
  if (!MAP) return;
  MAP.dots.textContent = '';
  let placed = 0;
  for (const r of [...hits].reverse()) {
    if (r.lat == null || r.lng == null) continue;
    placed += 1;
    const [x, y] = MAP.project(r.lat, r.lng);
    const dot = svgEl('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: 2.8, class: `dot ${r.source}`,
                                  'data-id': r.id });
    const t = svgEl('title');
    t.textContent = `${r.name} — ${r.rating.toFixed(1)}★`;
    dot.append(t);
    MAP.dots.append(dot);
  }
  if (STATE.near) {
    const [x, y] = MAP.project(STATE.near.lat, STATE.near.lng);
    MAP.dots.append(svgEl('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: 5, class: 'here' }));
  }
  if (STATE.pinned && !hits.some((r) => r.id === STATE.pinned)) {
    STATE.pinned = null;
    $opt('#mapDetail').textContent = '';
  }
  const off = hits.length - placed;
  $('#mapGaps').textContent = !hits.length ? '' : off
    ? `${placed.toLocaleString()} of the ${hits.length.toLocaleString()} shown are on the map; ${off} have no location.`
    : `All ${placed.toLocaleString()} shown are on the map. Tap a dot for its details.`;
}

function setView(view) {
  STATE.view = view;
  $('#viewList').setAttribute('aria-pressed', String(view === 'list'));
  $('#viewMap').setAttribute('aria-pressed', String(view === 'map'));
  $('#rows').hidden = view !== 'list';
  $('#mapView').hidden = view === 'list';
  if (view === 'list' || MAP) { apply(); return; }
  if (MAP_LOADING) return;
  MAP_LOADING = true;
  $('#mapGaps').textContent = 'Loading the map…';
  timedFetch(BOROUGHS_URL).then((geo) => {
    MAP = buildMap(geo);
    $('#mapWrap').append(MAP.svg);
    apply();
  }).catch((err) => {
    $('#mapGaps').textContent = `Could not load the map outlines (${err.message}). The list view has everything.`;
  }).finally(() => { MAP_LOADING = false; });
}

/* ---------- boot -------------------------------------------------------- */

function renderCoverage() {
  const m = STATE.data.meta;
  const box = $opt('#coverage');
  box.hidden = false;
  box.textContent = '';
  const p = el('p');
  p.append(el('strong', null, `${m.restaurants.toLocaleString()} restaurants rated ${m.min_rating}+`));
  p.append(document.createTextNode(
    ` across ${Object.entries(m.by_borough).map(([b, n]) => `${b} ${n}`).join(', ')}. `
    + `${m.with_google_details.toLocaleString()} have full Google details (hours, price, delivery); `
    + 'the rest come from the award roster and fill in as the monthly free Google allowance reaches them.'));
  box.append(p);
}

function wire() {
  const q = $('#q');
  q.addEventListener('input', () => { STATE.q = fold(q.value.trim()); STATE.shown = PAGE; apply(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) {
      e.preventDefault();
      q.focus();
    }
  });
  $('#sort').addEventListener('change', (e) => { STATE.sort = e.target.value; apply(); });
  $('#minRating').addEventListener('change', (e) => { STATE.minRating = Number(e.target.value); STATE.shown = PAGE; apply(); });
  $('#openNow').addEventListener('click', () => { STATE.openNow = !STATE.openNow; STATE.shown = PAGE; apply(); });
  $('#radius').addEventListener('change', (e) => { STATE.radius = Number(e.target.value); STATE.shown = PAGE; apply(); });
  $('#nearForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const text = $('#near').value.trim();
    if (text) geocode(text);
  });
  $('#hereBtn').addEventListener('click', () => {
    if (!navigator.geolocation) { $('#nearStatus').textContent = 'This browser cannot share its location.'; return; }
    $('#nearStatus').textContent = 'Finding you…';
    navigator.geolocation.getCurrentPosition(
      (pos) => { setNear(pos.coords.latitude, pos.coords.longitude, 'your location'); STATE.shown = PAGE; apply(); },
      (err) => { $('#nearStatus').textContent = `Location unavailable (${err.message}).`; },
      { timeout: FETCH_TIMEOUT_MS, maximumAge: 300000 });
  });
  $('#nearClear').addEventListener('click', () => { clearNear(); apply(); });
  $('#filterBtn').addEventListener('click', () => {
    const panel = $('#panel');
    panel.hidden = !panel.hidden;
    $('#filterBtn').setAttribute('aria-expanded', String(!panel.hidden));
  });
  $('#showMore').addEventListener('click', () => { STATE.shown += PAGE; apply(); });
  $('#viewList').addEventListener('click', () => setView('list'));
  $('#viewMap').addEventListener('click', () => setView('map'));
  $('#mapWrap').addEventListener('click', (e) => {
    const hit = e.target.closest ? e.target.closest('.dot') : null;
    const r = hit && STATE.byId.get(hit.getAttribute('data-id'));
    if (!r) return;
    STATE.pinned = r.id;
    const box = $('#mapDetail');
    box.textContent = '';
    box.append(renderRow(r));
  });
  for (const id of ['#clearBtn', '#clearBtn2']) {
    $(id).addEventListener('click', () => {
      STATE.filters.clear();
      STATE.q = '';
      $('#q').value = '';
      STATE.openNow = false;
      STATE.shown = PAGE;
      apply();
    });
  }
  addEventListener('hashchange', () => {
    STATE.filters.clear();
    STATE.q = ''; $('#q').value = '';
    STATE.sort = DEFAULT_SORT; $('#sort').value = DEFAULT_SORT;
    STATE.minRating = DEFAULT_MIN; $('#minRating').value = String(DEFAULT_MIN);
    STATE.openNow = false;
    clearNear();
    STATE.radius = 1; $('#radius').value = '1';
    STATE.shown = PAGE;
    STATE.view = 'list';
    readHash();
    setView(STATE.view);
  });
  const toTop = $('#toTop');
  toTop.addEventListener('click', () => window.scrollTo({ top: 0 }));
  window.addEventListener('scroll', () => { toTop.hidden = window.scrollY < 800; }, { passive: true });
  let saved = null;
  try { saved = localStorage.getItem('eats-theme'); } catch { /* private mode */ }
  if (saved) document.documentElement.dataset.theme = saved;
  $('#themeToggle').addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('eats-theme', next); } catch { /* private mode */ }
  });
}

async function boot() {
  $('#rows').append(el('p', 'empty', 'Loading the guide…'));
  let payload;
  try {
    payload = await timedFetch(DATA_URL);
  } catch (err) {
    $('#rows').textContent = '';
    $('#rows').append(el('p', 'empty', `Could not load the guide (${err.name === 'AbortError'
      ? 'no answer within fifteen seconds' : err.message}). The data file is docs/data/restaurants.json.`));
    return;
  }
  STATE.data = payload;
  STATE.rows = payload.restaurants;
  for (const r of STATE.rows) STATE.byId.set(r.id, r);
  if (payload.meta.prior) PRIOR = payload.meta.prior;
  if (payload.meta.rating_mean != null) RATING_MEAN = payload.meta.rating_mean;
  $opt('#rosterCount').textContent = `${payload.meta.restaurants.toLocaleString()} restaurants`;
  $opt('#footProvenance').textContent = `Built ${payload.meta.generated_at.slice(0, 10)} from Google Places, `
    + 'the nyc-restaurants award roster (Michelin, James Beard, NYT, Restaurant Week) and NYC health-inspection '
    + 'records. Source: github.com/Kejjeh/nyc-eats.';
  renderCoverage();
  renderPresets();
  wire();
  readHash();
  if (STATE.view === 'map') setView('map'); else apply();
}

boot();
