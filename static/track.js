// What visitors look at and click, for the admin's Funnel tab (app/tracking.py). Loaded on every page with
// the nav. No cookies: a random visitor ID in this browser, never what anyone typed, never page text (the
// flip book has the child's name in it). Browsers that ask not to be tracked send nothing.
//
//   track('book_requested', { story: 'jack' })   // a step; app/tracking.py lists the names it accepts
//   <button data-track="download">               // a click's name; otherwise its id or link path
//   <button data-repeat>                         // clicked over and over on purpose: not tracked
(() => {
  'use strict';
  const off = navigator.globalPrivacyControl === true || navigator.doNotTrack === '1' || window.doNotTrack === '1';
  const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, '0')).join('');
  function kept(storage, key) {
    try {
      let id = storage.getItem(key);
      if (!id) { id = newId(); storage.setItem(key, id); }
      return id;
    } catch { return newId(); }  // private windows can refuse storage: still counts, just not joined up
  }
  const visitor = off ? '' : kept(localStorage, 'jack.visitor');
  // A visit ends after 30 minutes with nothing happening (the usual rule), so coming back later, in this tab or
  // another, is a new visit; moving between pages or tabs within that is the same one.
  const VISIT_GAP = 30 * 60 * 1000;
  const fallback = newId();  // private windows can refuse storage
  function visit() {
    const now = Date.now();
    try {
      const v = JSON.parse(localStorage.getItem('jack.visit') || 'null');
      const id = v && now - v.last < VISIT_GAP ? v.id : newId();
      localStorage.setItem('jack.visit', JSON.stringify({ id, last: now }));
      return id;
    } catch { return fallback; }
  }

  function track(name, props) {
    if (off) return;
    const body = JSON.stringify({ name, props, visitor, session: visit(), path: location.pathname });
    try {
      if (navigator.sendBeacon && navigator.sendBeacon('/api/e', new Blob([body], { type: 'text/plain' }))) return;
    } catch { /* fall through */ }
    fetch('/api/e', { method: 'POST', body, keepalive: true }).catch(() => {});
  }
  window.track = track;

  // A click's name: data-track, else the element's id, else a link's path. Never its text.
  function nameOf(el) {
    if (el.dataset.track) return el.dataset.track;
    if (el.id) return el.id;
    const href = el.getAttribute('href');
    if (href) return href.split(/[?#]/)[0] || href;
    return el.tagName.toLowerCase();
  }

  let recent = [];
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-repeat]')) return;  // turning pages: quick clicks there are normal, not frustration
    const el = e.target.closest('a, button, [data-track], input[type="radio"], summary');
    const now = Date.now();
    // Three clicks in a second in the same spot: something isn't doing what the visitor expected.
    recent = recent.filter((c) => now - c.t < 1000 && Math.hypot(c.x - e.clientX, c.y - e.clientY) < 40);
    recent.push({ t: now, x: e.clientX, y: e.clientY });
    if (recent.length === 3) track('rage_click', { target: el ? nameOf(el) : e.target.tagName.toLowerCase() });
    if (el && el.type !== 'radio') track('click', { target: nameOf(el) });
  }, { capture: true });

  // A refresh isn't a new view (and never a new person: the visitor ID stays the same).
  const nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
  const reloaded = nav ? nav.type === 'reload' : performance.navigation && performance.navigation.type === 1;
  if (!reloaded) track('page_view');
})();
