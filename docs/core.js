/* nyc-eats — the page's pure logic, with no DOM in it.
 *
 * Kept apart from app.js so tests/test_site_core.py can run every function here
 * under plain `node`, the way the nyc-restaurants and omakase dashboards test
 * theirs. Loaded by index.html before app.js; exposes one global, EATS.
 */
'use strict';

(function (root) {
  /** Fold diacritics + case so "Café" and "cafe" compare equal (copied from nyc-restaurants). */
  const fold = (s) =>
    (s == null ? '' : String(s))
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[‘’ʼ′]/g, "'")
      .replace(/[–—‒−]/g, '-')
      .replace(/[“”]/g, '"')
      .toLowerCase();

  /* No base URL on purpose: with one, a bare "www.x.com" resolves relative to this
     page and passes as http (nyc-restaurants venues.js explains the bug it caused). */
  const isHttpURL = (u) => {
    if (!u) return false;
    try { return /^https?:$/.test(new URL(u).protocol); } catch { return false; }
  };

  const WEEK = 7 * 1440;

  /* Is a place open at (day, minute-of-day)? `hours` is Google's periods as
     [openDay, openH, openM, closeDay, closeH, closeM], day 0 = Sunday.
     Returns null when the hours are unknown: unknown is not "closed". */
  function isOpenAt(hours, day, minute) {
    if (!Array.isArray(hours) || !hours.length) return null;
    const t = day * 1440 + minute;
    for (const p of hours) {
      if (p[3] == null) return true; // a period with no close is open around the clock
      const o = p[0] * 1440 + p[1] * 60 + p[2];
      let c = p[3] * 1440 + p[4] * 60 + p[5];
      if (c <= o) c += WEEK; // runs past Saturday midnight into Sunday
      if ((t >= o && t < c) || (t + WEEK >= o && t + WEEK < c)) return true;
    }
    return false;
  }

  /* Day and minute in New York, whatever time zone the phone is in. */
  const DAYS = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  function nycNow(date) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(date || new Date());
    const get = (t) => parts.find((p) => p.type === t).value;
    return { day: DAYS[get('weekday')], minute: Number(get('hour')) * 60 + Number(get('minute')) };
  }

  /* The guide's score: the rating shrunk toward the mean by `prior` reviews of doubt
     (m = 150, nyc-restaurants' GOOGLE_PRIOR). Null when there is no rating. */
  function weightedRating(rating, reviews, prior, mean) {
    if (rating == null) return null;
    const n = reviews || 0;
    return (rating * n + mean * prior) / (n + prior);
  }

  /* Miles between two points (haversine). */
  function distanceMi(lat1, lng1, lat2, lng2) {
    if ([lat1, lng1, lat2, lng2].some((v) => v == null)) return null;
    const R = 3958.8, rad = Math.PI / 180;
    const dLat = (lat2 - lat1) * rad, dLng = (lng2 - lng1) * rad;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  const priceLabel = (level) => (level == null ? null : level === 0 ? 'Free' : '$'.repeat(level));

  /* Search links only. The guide never scrapes a delivery platform (README decision);
     these open the app's own search for the name. */
  function deliveryLinks(name) {
    const q = encodeURIComponent(name || '');
    return [
      { label: 'Uber Eats', url: `https://www.ubereats.com/search?q=${q}` },
      { label: 'DoorDash', url: `https://www.doordash.com/search/store/${q}/` },
      { label: 'Seamless', url: `https://www.seamless.com/search?queryText=${q}` },
    ];
  }

  /* "Michelin ★ 2025" -> "Michelin ★": the award without its year, for grouping. */
  const awardKind = (badge) => String(badge).replace(/\s+\d{4}$/, '');

  /* ---------- Ask: a plain-English question -> the page's own filters ----------
     "Italian, $$, open past 10, near Union Square" becomes cuisine Italian, price $$, open at
     10 PM, near "union square". Everything runs on the page, free. Words it cannot place are
     returned in `ignored` and shown, never silently turned into a text search that empties the list. */

  const ASK_PHRASES = [
    // [pattern, facet key, values]   values may be a function of the vocab
    [/\btasting menus?\b|\bdegustation\b|\bmulti-?course\b/, 'category', ['Tasting menu']],
    [/\bprix[- ]?fixe\b|\bset menu\b/, 'category', ['Prix fixe']],
    [/\bomakase\b|\bchef'?s counter\b|\bkaiseki\b/, 'category', ["Omakase & chef's counter"]],
    [/\bfine dining\b|\bfancy\b|\bspecial occasion\b/, 'category', ['Fine dining']],
    [/\bunusual (?:proteins?|meats?)\b|\bwagyu\b|\bgoat\b|\brabbit\b|\bvenison\b|\bwild game\b|\buni\b|\boctopus\b|\beel\b/,
      'category', ['Unusual proteins']],
    [/\brestaurant week\b/, 'category', ['Restaurant Week']],
    [/\bmichelin[- ]starred\b|\bmichelin stars?\b|\bstarred\b/, 'award', ['Michelin ★', 'Michelin ★★', 'Michelin ★★★']],
    [/\bbib gourmand\b|\bbib\b/, 'award', ['Bib Gourmand']],
    [/\bmichelin\b/, 'award', (v) => v.awards.filter((a) => /^Michelin/.test(a))],
    [/\bjames beard\b|\bbeard\b/, 'award', (v) => v.awards.filter((a) => /^James Beard/.test(a))],
    [/\bnyt\b|\bnew york times\b/, 'award', (v) => v.awards.filter((a) => /^NYT/.test(a))],
    [/\bdeliver(?:y|s|ing)?\b/, 'offers', ['Delivery']],
    [/\btake ?out\b|\bto go\b|\bpick ?up\b/, 'offers', ['Takeout']],
    [/\breservations?\b|\breservable\b|\bbook(?:able)?\b/, 'offers', ['Takes reservations']],
    [/\bcheap\b|\binexpensive\b|\bbudget\b|\baffordable\b/, 'price', ['$', '$$']],
    [/\bexpensive\b|\bsplurge\b|\bpricey\b|\bhigh[- ]end\b/, 'price', ['$$$', '$$$$']],
  ];
  const ASK_STOP = new Set(('a an the and or with for in on at to of me my us we i find show give want need '
    + 'some any place places spot spots restaurant restaurants food dinner lunch brunch eat eating good great '
    + 'best top nice really very that is are serves serving which where what who something somewhere '
    + 'tonight today please like').split(' '));
  const RATINGS = [4.2, 4.3, 4.4, 4.5, 4.6, 4.7];

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  /* Clock words -> minute of the day. "10" alone means 10 PM (a dinner guide); 1-4 mean after midnight. */
  function clock(h, m, ampm) {
    let hour = Number(h) % 12;
    const min = Number(m || 0);
    if (ampm === 'pm' || (!ampm && hour >= 5)) hour += 12;
    if (ampm === 'am' && Number(h) === 12) hour = 0;
    return hour * 60 + min;
  }

  function parseAsk(text, vocab) {
    const out = { filters: {}, minRating: null, openNow: false, openAt: null, near: null,
                  understood: [], ignored: [] };
    let s = ' ' + fold(text).replace(/[“”"]/g, ' ') + ' ';
    const take = (re, fn) => {
      s = s.replace(re, (...m) => { fn(...m); return ' '; });
    };
    const add = (key, values) => {
      const vals = (typeof values === 'function' ? values(vocab) : values).filter(Boolean);
      if (!vals.length) return;
      out.filters[key] = [...new Set([...(out.filters[key] || []), ...vals])];
    };

    take(/\b(?:near|close to|around|by)\s+(.+?)(?=,|;|\s+(?:open|that|with|rated|under|for|and|serving|which|tonight|today)\b|\s*$)/,
      (_, place) => { out.near = place.trim(); });
    take(/\bopen now\b|\bopen right now\b|\bstill open\b/, () => { out.openNow = true; });
    take(/\b(?:open )?(?:past|after|until|till|at)\s+(\d{1,2})(?::(\d\d))?\s*(am|pm)?\b|\bopen\s+(\d{1,2})(?::(\d\d))?\s*(am|pm)\b/,
      (_, h, m, ap, h2, m2, ap2) => { out.openAt = clock(h || h2, m || m2, ap || ap2); });
    take(/\b(?:open )?late(?: night)?\b|\blate-night\b/, () => { if (out.openAt == null) out.openAt = 23 * 60; });
    take(/\b(?:rated\s+)?(4\.\d)\s*\+?(?:\s*(?:stars?|rating|or (?:better|higher|more)|and up))?/, (_, r) => {
      const n = Number(r);
      out.minRating = RATINGS.reduce((best, x) => (x <= n + 1e-9 ? x : best), RATINGS[0]);
    });
    take(/(^|\s)(\${1,4})(?=\s|,|$)/, (_, sp, d) => add('price', [d]));
    for (const [re, key, values] of ASK_PHRASES) take(new RegExp(re.source, 'g'), () => add(key, values));

    /* Places and cuisines from the data itself, longest name first so "Upper East Side"
       wins over "East". Neighborhood names like "Midtown-Midtown South" also answer to each part. */
    const names = [];
    for (const b of vocab.boroughs || []) names.push([fold(b), 'borough', b]);
    for (const n of vocab.neighborhoods || []) {
      names.push([fold(n), 'neighborhood', n]);
      for (const part of String(n).split(/-(?=\S)/)) if (part.length >= 5 && part !== n) names.push([fold(part), 'neighborhood', n]);
    }
    for (const c of vocab.cuisines || []) {
      names.push([fold(c), 'cuisine', c]);
      names.push([fold(c) + 's', 'cuisine', c]); // "steakhouses", "tapas" stays as is
    }
    names.sort((a, b) => b[0].length - a[0].length);
    for (const [name, key, value] of names) {
      const re = new RegExp(`(^|[\\s,])${escapeRe(name)}(?=[\\s,]|$)`, 'g');
      if (re.test(s)) { s = s.replace(re, ' '); add(key, [value]); }
    }

    out.ignored = s.split(/[\s,;.!?]+/).filter((w) => w && !ASK_STOP.has(w));
    for (const v of Object.values(out.filters)) out.understood.push(...v);
    return out;
  }

  root.EATS = { fold, isHttpURL, isOpenAt, nycNow, weightedRating, distanceMi, priceLabel, deliveryLinks,
                awardKind, parseAsk, clock };
})(typeof window !== 'undefined' ? window : globalThis);
