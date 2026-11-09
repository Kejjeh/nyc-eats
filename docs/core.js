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

  root.EATS = { fold, isHttpURL, isOpenAt, nycNow, weightedRating, distanceMi, priceLabel, deliveryLinks,
                awardKind };
})(typeof window !== 'undefined' ? window : globalThis);
