// The admin site. Everything is built with textContent, never innerHTML, since rows hold user input.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const API = '/admin/api';

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null) n.append(kid instanceof Node ? kid : String(kid));
    return n;
  }

  async function api(path, opts) {
    const res = await fetch(API + path, { cache: 'no-store', ...opts,
      headers: { 'Content-Type': 'application/json', ...(opts && opts.headers) } });
    if (res.status === 401) { location.href = '/auth/login?next=' + encodeURIComponent(location.pathname); throw new Error('signed out'); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data.detail && data.detail.message) || `HTTP ${res.status}`);
    return data;
  }

  const fmt = {
    when(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      const today = new Date().toDateString() === d.toDateString();
      return today ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    },
    secs(s) { return s == null ? '' : s >= 90 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s.toFixed ? s.toFixed(1) : s}s`; },
    cost(c) { return c ? `$${c.toFixed(c < 1 ? 3 : 2)}` : '$0'; },
  };
  const pill = (status) => el('span', { class: `pill s-${status}`, text: status });

  // --- tabs (remembered in the address, so a link opens the same view) ---------------------------
  const tabs = document.querySelectorAll('[data-tab]');
  function showTab(name) {
    tabs.forEach((t) => t.setAttribute('aria-selected', String(t.dataset.tab === name)));
    document.querySelectorAll('.tab').forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
    ({ books: loadBooks, days: loadDays, errors: loadErrors, settings: loadSettings })[name]();
  }
  tabs.forEach((t) => t.addEventListener('click', () => { setHash({ tab: t.dataset.tab, book: '' }); }));

  function readHash() { return Object.fromEntries(new URLSearchParams(location.hash.slice(1))); }
  function setHash(changes) {
    const h = { ...readHash(), ...changes };
    for (const k of Object.keys(h)) if (h[k] === '' || h[k] == null) delete h[k];
    location.hash = new URLSearchParams(h).toString();
  }

  // --- books -------------------------------------------------------------------------------------
  const bookFilters = $('bookFilters');
  let filterOptionsFilled = false;

  function bookQuery() {
    const f = new FormData(bookFilters);
    const p = new URLSearchParams();
    for (const [k, v] of f.entries()) if (v && k !== 'slow' && k !== 'failed') p.set(k, v);
    if (bookFilters.slow.checked) p.set('slow', 'true');
    if (bookFilters.failed.checked) p.set('failed', 'true');
    return p.toString();
  }

  function fillOptions(select, values) {
    const keep = select.value;
    select.replaceChildren(el('option', { value: '', text: 'any' }), ...values.map((v) => el('option', { text: v })));
    select.value = values.includes(keep) ? keep : '';
  }

  async function loadBooks() {
    let data;
    try { data = await api('/books?' + bookQuery()); } catch (e) { $('bookSummary').textContent = e.message; return; }
    if (!filterOptionsFilled || document.activeElement.tagName !== 'SELECT') {
      fillOptions(bookFilters.reason, data.filters.reasons);
      fillOptions(bookFilters.provider, data.filters.providers);
      filterOptionsFilled = true;
    }
    const s = data.summary;
    $('bookSummary').replaceChildren(
      el('b', { text: `${data.total} books` }), ' · ',
      ...Object.entries(s.by_status).flatMap(([k, v]) => [pill(k), ` ${v}  `]),
      ' · spent ', el('b', { text: fmt.cost(s.cost) }));
    const body = $('bookTable').tBodies[0];
    body.replaceChildren(...(data.items.length ? data.items.map(bookRow)
      : [el('tr', { class: 'empty' }, el('td', { colspan: 11, text: 'No books match these filters.' }))]));
  }

  function bookRow(b) {
    return el('tr', { onclick: () => setHash({ book: b.id }) },
      el('td', { class: 'when', text: fmt.when(b.created_at) }),
      el('td', { class: 'mono', text: b.id }),
      el('td', {}, pill(b.status)),
      el('td', { text: b.email || '—' }),
      el('td', { text: b.child_name }),
      el('td', { class: 'mono', text: [b.provider, b.model, b.quality].filter(Boolean).join(' · ') }),
      el('td', { class: 'num', text: b.images_total ? `${b.images_done}/${b.images_total}${b.images_failed ? ` (${b.images_failed} failed)` : ''}` : '—' }),
      el('td', { class: 'num', text: b.status === 'refused' ? '' : fmt.secs(b.seconds) }),
      el('td', { class: 'num' + (b.slowest > 60 ? ' slow' : ''), text: fmt.secs(b.slowest) }),
      el('td', { class: 'num', text: fmt.cost(b.cost) }),
      el('td', { class: 'msg', text: b.reason || '' }));
  }

  let typing;
  bookFilters.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(loadBooks, 250); });
  bookFilters.addEventListener('submit', (e) => { e.preventDefault(); loadBooks(); });

  // --- one book ----------------------------------------------------------------------------------
  const drawer = $('drawer');
  let openStatus = null;  // the open book is only refreshed while it's still being drawn
  $('drawerClose').addEventListener('click', () => setHash({ book: '' }));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !drawer.hidden) setHash({ book: '' }); });

  async function openBook(ref) {
    drawer.hidden = false;
    $('drawerTitle').textContent = `Book ${ref}`;
    let d;
    try { d = await api(`/books/${encodeURIComponent(ref)}`); }
    catch (e) { $('drawerBody').replaceChildren(el('p', { class: 'alert', text: e.message })); return; }
    const b = d.book;
    openStatus = b.status;
    $('drawerTitle').replaceChildren(`Book `, el('span', { class: 'mono', text: b.id }), ' ', pill(b.status));
    const facts = [
      ['Made', new Date(b.created_at).toLocaleString()], ['Who', b.email || 'not signed in'],
      ['Child', `${b.child_name || '—'} (${b.gender === 'girl' ? 'Jane' : 'Jack'})`],
      ['Drawn by', [b.provider, b.model, b.quality].filter(Boolean).join(' · ')],
      ['Total time', fmt.secs(b.seconds)], ['Cost', fmt.cost(b.cost)],
      ['Prompt version', b.prompt_version], ['Story · style', `${b.story} · ${b.style}`],
      ...(b.details || []).map(([k, v]) => [k, v]),
    ];
    const parts = [
      el('dl', { class: 'facts' }, facts.map(([k, v]) => el('div', {}, el('dt', { text: k }), el('dd', { text: v || '—' })))),
      (b.reason || b.message) && el('p', { class: 'alert', text: [b.reason, b.message].filter(Boolean).join(': ') }),
      el('h3', { text: 'Pictures' }),
      el('div', { class: 'pictures' },
        d.photo_url && el('div', { class: 'pic square' }, el('img', { src: d.photo_url, alt: 'Uploaded photo', loading: 'lazy' }),
          el('div', { class: 'pic-body' }, el('b', { text: 'Uploaded photo' }),
            d.upload && el('span', { class: 'soft', text: `${d.upload.mime} · ${d.upload.width}×${d.upload.height}` }),
            d.upload && d.upload.face_description && el('details', {}, el('summary', { text: 'face description' }),
              el('pre', { text: d.upload.face_description })))),
        d.images.map(imageCard)),
      el('h3', { text: `Timeline (${d.events.length} events)` }),
      timeline(d.events),
    ];
    $('drawerBody').replaceChildren(...parts.filter(Boolean));
  }

  function imageCard(i) {
    const label = i.kind === 'hero_sheet' ? 'Cartoon (hero sheet)' : `Page ${i.page}`;
    const tokens = i.tokens ? Object.entries(i.tokens).map(([k, v]) => `${k} ${v}`).join(' · ') : '';
    return el('div', { class: 'pic' + (i.kind === 'hero_sheet' ? ' square' : '') },
      i.image_url ? el('a', { href: i.image_url, target: '_blank' }, el('img', { src: i.image_url + '?w=600', alt: label, loading: 'lazy' }))
        : el('div', { class: 'ph', text: i.status }),
      el('div', { class: 'pic-body' },
        el('div', { class: 'line' }, el('b', { text: label }), pill(i.status)),
        el('div', { class: 'line soft' }, el('span', { class: i.seconds > 60 ? 'slow' : '', text: fmt.secs(i.seconds) }),
          el('span', { text: fmt.cost(i.cost) })),
        i.refs && el('div', { class: 'kv', text: 'refs: ' + i.refs.join(', ') }),
        tokens && el('div', { class: 'kv', text: tokens }),
        i.provider_request_id && el('div', { class: 'kv', text: 'request ' + i.provider_request_id }),
        (i.error_code || i.error_message) && el('div', { class: 'alert', text: [i.error_code, i.error_message].filter(Boolean).join(': ') }),
        i.prompt && el('details', {}, el('summary', { text: 'prompt' }), el('pre', { text: i.prompt }))));
  }

  function timeline(events) {
    if (!events.length) return el('p', { class: 'soft', text: 'No events.' });
    return el('div', { class: 'table-wrap' }, el('table', { class: 'grid timeline' },
      el('thead', {}, el('tr', {}, ['+time', 'step', 'event', 'took', 'details'].map((h) => el('th', { text: h })))),
      el('tbody', {}, events.map((e) => el('tr', { class: `lvl-${e.level} ev-${e.event}${e.stuck ? ' stuck' : ''}` },
        el('td', { class: 't', text: `+${(e.offset || 0).toFixed(1)}s` }),
        el('td', { text: e.step }),
        el('td', {}, pill(e.stuck ? 'never finished' : e.event)),
        el('td', { class: 'num' + (e.duration_ms > 60000 ? ' slow' : ''), text: e.duration_ms == null ? '' : fmt.secs(e.duration_ms / 1000) }),
        el('td', { class: 'kv' }, Object.entries(e.fields || {}).flatMap(([k, v]) => [el('b', { text: k }), `=${typeof v === 'object' ? JSON.stringify(v) : v}  `])))))));
  }

  // --- days --------------------------------------------------------------------------------------
  async function loadDays() {
    const rows = await api('/days?n=30');
    $('dayTable').tBodies[0].replaceChildren(...(rows.length ? rows.map((d) => el('tr', {
      onclick: () => { bookFilters.since.value = d.day; bookFilters.until.value = d.day; setHash({ tab: 'books' }); } },
      el('td', { text: d.day }), el('td', { class: 'num', text: d.books }), el('td', { class: 'num', text: d.done }),
      el('td', { class: 'num', text: d.failed }), el('td', { class: 'num', text: d.refused }),
      el('td', { class: 'num', text: d.people }), el('td', { class: 'num', text: fmt.cost(d.cost) }),
      el('td', { class: 'soft', text: 'see books →' })))
      : [el('tr', { class: 'empty' }, el('td', { colspan: 8, text: 'No books in the last 30 days.' }))]));
  }

  // --- errors ------------------------------------------------------------------------------------
  const errorFilters = $('errorFilters');
  async function loadErrors() {
    const p = new URLSearchParams([...new FormData(errorFilters)].filter(([, v]) => v));
    const data = await api('/errors?' + p);
    if (document.activeElement !== errorFilters.type) fillOptions(errorFilters.type, data.types);
    $('errorTable').tBodies[0].replaceChildren(...(data.items.length ? data.items.map((r) => {
      const row = el('tr', {},
        el('td', { class: 'when', text: fmt.when(r.at) }), el('td', { class: 'mono', text: r.id }),
        el('td', { class: 'mono', text: r.path }), el('td', { class: 'num', text: r.status ?? '' }),
        el('td', {}, el('span', { class: 'pill s-failed', text: r.type || '?' })),
        el('td', { class: 'msg' }, r.message || '',
          (r.traceback || r.browser) && el('details', {}, el('summary', { text: 'more' }),
            el('pre', { text: [r.browser && `Browser: ${r.browser}`, r.traceback].filter(Boolean).join('\n\n') }))));
      return row;
    }) : [el('tr', { class: 'empty' }, el('td', { colspan: 6, text: 'No errors.' }))]));
  }
  errorFilters.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(loadErrors, 250); });
  errorFilters.addEventListener('submit', (e) => { e.preventDefault(); loadErrors(); });

  // --- settings ----------------------------------------------------------------------------------
  const modelForm = $('modelForm');
  const PROVIDER_NOTES = {
    openai: ['OpenAI', 'What everyone gets. Costs about 3¢ a picture.'],
    agnes: ['Agnes', 'Free right now. May train on what it’s sent, so only your own test photos.'],
    mock: ['Mock', 'Placeholder pictures, no cost. For trying the site.'],
  };
  let settings;

  function fillModelSelects(provider, model, quality) {
    const c = settings.choices[provider];
    modelForm.model.replaceChildren(...c.models.map((m) => el('option', { text: m })));
    modelForm.model.value = c.models.includes(model) ? model : c.models[0];
    modelForm.quality.replaceChildren(...c.qualities.map((q) => el('option', { value: q, text: q || '—' })));
    modelForm.quality.value = c.qualities.includes(quality) ? quality : c.default_quality;
    const warn = settings.forced_mock ? 'MOCK=1 is set on this server, so every book is a mock book whatever you pick here.'
      : !settings.available[provider] ? `No ${provider === 'agnes' ? 'AGNES_API_KEY' : 'OPENAI_API_KEY'} on this server, so these books will fail.` : '';
    $('modelWarn').textContent = warn;
    $('modelWarn').hidden = !warn;
  }

  async function loadSettings() {
    settings = await api('/settings');
    $('providerChoice').replaceChildren(el('legend', { class: 'soft', text: 'Provider' }),
      ...Object.keys(settings.choices).map((p) => el('label', { class: 'choice' + (settings.available[p] ? '' : ' off') },
        el('input', { type: 'radio', name: 'provider', value: p, checked: p === settings.provider,
          onchange: () => fillModelSelects(p) }),
        el('span', {}, el('b', { text: PROVIDER_NOTES[p][0] }), el('small', { text: PROVIDER_NOTES[p][1] })))));
    fillModelSelects(settings.provider, settings.model, settings.quality);
    loadUnlimited();
  }

  modelForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { provider: modelForm.provider.value, model: modelForm.model.value, quality: modelForm.quality.value || null };
    try {
      settings = await api('/settings', { method: 'PUT', body: JSON.stringify(body) });
      $('modelSaved').textContent = `Saved. Your next book uses ${settings.provider} · ${settings.model}.`;
    } catch (err) { $('modelSaved').textContent = err.message; }
    $('modelSaved').hidden = false;
    setTimeout(() => { $('modelSaved').hidden = true; }, 4000);
  });

  const unlimitedForm = $('unlimitedForm');
  function paintEmails(data) {
    $('emails').replaceChildren(
      ...data.admins.map((a) => el('li', {}, el('span', { text: a }), el('span', { class: 'pill', text: 'admin' }))),
      ...data.emails.map((r) => el('li', {}, el('span', { text: r.email }),
        el('button', { class: 'btn plain small', type: 'button', text: 'Remove',
          onclick: async () => paintEmails(await api(`/unlimited/${encodeURIComponent(r.email)}`, { method: 'DELETE' })) }))));
  }
  async function loadUnlimited() { paintEmails(await api('/unlimited')); }
  unlimitedForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    paintEmails(await api('/unlimited', { method: 'POST', body: JSON.stringify({ email: unlimitedForm.email.value }) }));
    unlimitedForm.reset();
  });

  // --- routing and live refresh ------------------------------------------------------------------
  function route() {
    const h = readHash();
    showTab(h.tab || 'books');
    if (h.book) openBook(h.book); else drawer.hidden = true;
  }
  window.addEventListener('hashchange', route);
  route();

  setInterval(() => {
    if (document.hidden || !$('live').checked) return;
    const h = readHash();
    if ((h.tab || 'books') === 'books') loadBooks();
    if (h.book && ['queued', 'running', 'interrupted'].includes(openStatus)) openBook(h.book);
  }, 5000);
})();
