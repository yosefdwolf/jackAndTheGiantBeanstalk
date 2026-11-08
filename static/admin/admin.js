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
    ({ books: loadBooks, activity: loadActivity, funnel: loadFunnel, characters: loadCharacters, reviews: loadReviews, refunds: loadRefunds, days: loadDays, errors: loadErrors, settings: loadSettings })[name]();
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
      ['Child', `${b.child_name || '—'} (${b.gender})`],
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
      d.reviews.length && el('h3', { text: 'Their review' }),
      ...d.reviews.map((r) => el('dl', { class: 'facts' },
        [['Looks like me', r.looks_like_me], ['Rings true', r.story_rings_true], ['Professional', r.looks_professional],
          ['What isn’t good', r.not_good || '—']].map(([k, v]) => el('div', {}, el('dt', { text: k }), el('dd', { text: v }))))),
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

  // --- reviews -----------------------------------------------------------------------------------
  const SITE = location.hostname.startsWith('admin.') ? `${location.protocol}//${location.hostname.slice(6)}` : location.origin;

  async function loadReviews() {
    const d = await api('/reviews');
    $('reviewCount').textContent = `${d.count} review${d.count === 1 ? '' : 's'}`;
    const qr = `${API}/qr.svg?url=${encodeURIComponent(SITE + '/')}`;
    $('qrImg').src = qr;
    $('qrDownload').href = qr;
    $('qrUrl').textContent = SITE.replace(/^https?:\/\//, '');
    $('studyUrl').textContent = `${SITE.replace(/^https?:\/\//, '')}/?pid={participant ID}`;
    $('reviewQuestions').replaceChildren(...d.questions.map((q) => {
      const most = Math.max(1, ...q.counts);
      return el('div', { class: 'panel question' },
        el('h3', { text: q.label }),
        el('p', { class: 'avg' }, q.average == null ? '—' : q.average.toFixed(1), el('small', { text: ' / 5 average' })),
        el('div', { class: 'bars' }, q.counts.map((n, i) => el('div', {},
          el('span', { text: i + 1 }), el('i', { style: `width:${(n / most) * 100}%` }), el('span', { text: n })))));
    }));
    const score = (n) => el('td', { class: 'num' }, el('span', { class: 'score' + (n <= 2 ? ' low' : ''), text: n }));
    $('reviewTable').tBodies[0].replaceChildren(...(d.items.length ? d.items.map((r) => el('tr', {
      onclick: () => setHash({ tab: 'books', book: r.book_id }) },
      el('td', { class: 'when', text: fmt.when(r.at) }),
      el('td', {}, el('img', { class: 'thumb', src: r.cover_url + '?w=120', alt: '', loading: 'lazy' }),
        el('span', { class: 'mono', text: r.book_id })),
      r.source === 'ai'  // an AI persona review: say which persona, not the book owner's email
        ? el('td', {}, el('span', { class: 'pill', text: 'AI' }), ' ', (r.respondent || '').replace(/^ai:\d+-/, '').replace(/-/g, ' '))
        : el('td', {}, r.email || '—', r.participant_id && el('div', { class: 'kv', text: `participant ${r.participant_id}` })),
      score(r.looks_like_me), score(r.story_rings_true), score(r.looks_professional),
      commentCell(r.not_good || '')))
      : [el('tr', { class: 'empty' }, el('td', { colspan: 7, text: 'No reviews yet. Share the QR code!' }))]));
  }

  // A review comment starts as 3 lines ending in "…"; clicking it opens the rest (and doesn't open the book).
  function commentCell(text) {
    const body = el('div', { class: 'clamp', text });
    const toggle = el('button', { class: 'more', type: 'button', text: 'more', hidden: true });
    const cell = el('td', { class: 'msg comment' }, body, toggle);
    const flip = (e) => {
      e.stopPropagation();
      if (toggle.hidden) return;  // short comment: nothing more to show
      const open = body.classList.toggle('open');
      toggle.textContent = open ? 'less' : 'more';
    };
    cell.addEventListener('click', flip);
    requestAnimationFrame(() => { toggle.hidden = body.scrollHeight <= body.clientHeight + 1; });
    return cell;
  }

  // --- refunds -----------------------------------------------------------------------------------
  const refundFilters = $('refundFilters');
  const dollars = (c) => `$${(c / 100).toFixed(2)}`;

  async function loadRefunds() {
    const d = await api(`/refunds?status=${encodeURIComponent(refundFilters.status.value)}`);
    $('refundTable').tBodies[0].replaceChildren(...(d.items.length ? d.items.map((r) => el('tr', {},
      el('td', { class: 'when', text: fmt.when(r.at) }),
      el('td', { text: r.email }),
      el('td', {}, el('a', { class: 'mono', href: `#tab=books&book=${r.book_id}`, text: r.book_id })),
      el('td', { class: 'num', text: dollars(r.cents) }),
      el('td', { class: 'num', text: dollars(r.balance_cents) }),
      commentCell(r.reason),
      el('td', {}, pill(r.status), r.admin_note && el('div', { class: 'kv', text: r.admin_note })),
      el('td', { class: 'decide' }, r.status === 'pending' ? decideControls(r) : null)))
      : [el('tr', { class: 'empty' }, el('td', { colspan: 8, text: 'No refund requests here.' }))]));
    refreshBadge();
  }

  function decideControls(r) {
    const note = el('input', { type: 'text', placeholder: 'note they’ll see (optional)', maxlength: 500 });
    const problem = el('p', { class: 'warn', hidden: true });
    const decide = async (approve, button) => {
      button.disabled = true;
      try {
        await api(`/refunds/${r.id}`, { method: 'POST', body: JSON.stringify({ approve, note: note.value }) });
        loadRefunds();
      } catch (e) {
        problem.textContent = e.message;
        problem.hidden = false;
        button.disabled = false;
      }
    };
    return el('div', {}, note, el('div', { class: 'row' },
      el('button', { class: 'btn small', type: 'button', text: 'Approve', onclick: (e) => decide(true, e.target) }),
      el('button', { class: 'btn plain small', type: 'button', text: 'Deny', onclick: (e) => decide(false, e.target) })), problem);
  }

  async function refreshBadge() {
    const d = await api('/refunds?status=pending').catch(() => null);
    const n = d ? d.items.length : 0;
    $('refundBadge').textContent = n;
    $('refundBadge').hidden = n === 0;
  }
  refundFilters.addEventListener('change', loadRefunds);
  refreshBadge();

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

  // --- activity ----------------------------------------------------------------------------------
  const activityFilters = $('activityFilters');
  const usd = (c) => `$${((Number(c) || 0) / 100).toFixed(2)}`;
  // Each logged step/event in words. Anything not listed shows as "<step> <event>".
  const SAYS = {
    'wallet paid': (f) => [`Added ${usd(f.cents)} to their wallet`, 'in'],
    'wallet checkout opened': (f) => [`Opened the card page for ${usd(f.cents)}`],
    'wallet checkout failed': (f) => [`Couldn’t open the card page: ${f.error || ''}`],
    'wallet check failed': (f) => [`Couldn’t check a payment with Stripe: ${f.error || ''}`],
    'wallet charged': (f) => [`Paid ${usd(f.cents)} for a book`, 'out'],
    'wallet refunded to card': (f) => [`Got ${usd(f.cents)} back on their card${f.problem ? ` (${f.problem})` : ''}`, 'out'],
    'wallet book refund asked': () => ['Asked for a book refund'],
    'wallet book refund approved': () => ['Book refund approved', 'in'],
    'wallet book refund denied': () => ['Book refund denied'],
    'sign-in done': (f) => [f.admin === 'True' ? 'Signed in (admin)' : 'Signed in'],
    'sign-in dev': () => ['Signed in (local test)'],
    'sign-in refused': (f) => [`Sign-in failed: ${f.reason || ''}`],
    'unlock refused': () => ['Typed the wrong magic word'],
    'request received': () => ['Asked for a book'],
    'request refused': (f) => [`Book refused: ${f.reason || ''}`],
    'book start': () => ['Drawing started'],
    'book done': (f) => [`Book finished${f.seconds ? ` in ${fmt.secs(Number(f.seconds))}` : ''}`],
    'book failed': (f) => [`Book failed${f.error ? `: ${f.error}` : ''}`],
    'book retry': () => ['Asked to redraw the missing pictures'],
    'book interrupted': () => ['Server restarted mid-book; resuming'],
    'review saved': (f) => [`Left a review (${f.scores || ''})`],
    'email sent': (f) => [`Email sent: ${f.subject || ''}`],
    'email failed': (f) => [`Email failed: ${f.subject || ''}`],
    'email not set up': (f) => [`Email not sent (not set up): ${f.subject || ''}`],
    'page script error': () => ['The page hit a script error'],
  };
  async function loadActivity() {
    const p = new URLSearchParams([...new FormData(activityFilters)].filter(([, v]) => v));
    const d = await api('/activity?' + p);
    const m = d.money, period = activityFilters.days.selectedOptions[0].text;
    $('moneyTotals').replaceChildren(...[
      ['Added', m.added], ['Spent on books', m.spent], ['Back to cards', m.refunded_to_cards],
      ['Book refunds', m.books_refunded], ['In wallets now', m.in_wallets, true],
    ].map(([label, c, now]) => el('div', { class: 'stat' }, el('b', { text: usd(c) }),
      el('span', { text: now ? label : `${label}, last ${period}` }))));
    $('activityTable').tBodies[0].replaceChildren(...(d.items.length ? d.items.map((a) => {
      const say = SAYS[`${a.step} ${a.event}`];
      const [text, flow] = say ? say(a.fields) : [`${a.step} ${a.event}`];
      return el('tr', { class: a.level !== 'INFO' ? 'problem' : null },
        el('td', { class: 'when', text: fmt.when(a.at) }), el('td', { text: a.email || 'signed out' }),
        el('td', {}, flow && el('span', { class: `flow ${flow}`, text: flow === 'in' ? '+' : '−' }), text),
        el('td', {}, a.book_id && el('a', { class: 'mono', href: `#tab=books&book=${a.book_id}`, text: a.book_id })));
    }) : [el('tr', { class: 'empty' }, el('td', { colspan: 4, text: 'Nothing yet.' }))]));
  }
  activityFilters.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(loadActivity, 250); });
  activityFilters.addEventListener('submit', (e) => { e.preventDefault(); loadActivity(); });

  // --- funnel ------------------------------------------------------------------------------------
  const funnelFilters = $('funnelFilters');
  // Clicks are named by data-track, an id, or a link's path (static/track.js); these read better.
  const CLICK_NAMES = {
    go: 'Generate (make my book)', download: 'Download the PDF', again: 'Make another book', selfieBtn: 'Take a selfie',
    drop: 'Photo frame', reviewToggle: 'Open the review', reviewBtn: 'Send the review', reviewPdf: 'Review: open the PDF',
    prevPage: 'Flip book: back', nextPage: 'Flip book: next', customBtn: 'Add a custom amount', cardBtn: 'Refund to card',
    bookBtn: 'Ask about a book', navSign: 'Sign in / out', navWallet: 'Nav: Wallet', navAdmin: 'Nav: Admin',
    '/': 'Library', '/bookshelf': 'Bookshelf', '/wallet': 'Wallet', '/privacy': 'Privacy', '/auth/login': 'Sign in',
    '/auth/logout': 'Sign out',
  };
  const clickName = (t) => CLICK_NAMES[t] || (t.startsWith('top_up_') ? `Add ${usd(t.slice(7))}`
    : t.startsWith('/stories/') ? `Story: ${t.slice(9)}` : t);
  const pct = (x) => (x == null ? '' : `${Math.round(x * 100)}%`);
  function paintFunnel(list, steps) {
    const top = steps[0] && steps[0].visitors;
    const drops = steps.slice(1).map((s) => (s.of_previous == null ? 1 : s.of_previous));
    const worst = drops.length && Math.min(...drops) < 1 ? drops.indexOf(Math.min(...drops)) + 1 : -1;
    list.replaceChildren(...steps.map((s, i) => el('li', { class: i === worst ? 'worst' : null },
      el('div', { class: 'bar', style: `--w:${top ? Math.max(2, (s.visitors / top) * 100) : 0}%` }),
      el('span', { class: 'label', text: s.step }),
      el('b', { text: s.visitors }),
      el('span', { class: 'soft', text: !i ? 'people' : s.of_previous == null ? `nobody reached “${s.after}”`
        : s.after === steps[i - 1].step ? `${pct(s.of_previous)} of the step before` : `${pct(s.of_previous)} of “${s.after}”` }))));
  }
  async function loadFunnel() {
    const d = await api(`/funnel?days=${funnelFilters.days.value}&admins=${funnelFilters.admins.checked}`);
    $('keepDays').textContent = d.keep_days;
    const ft = d.minutes_to_first_book, dr = d.drawing_seconds, sb = d.second_book;
    $('funnelStats').replaceChildren(...[
      [d.visitors, `different people (${d.new_visitors} new)`], [d.signed_in, 'of them signed in'],
      [d.sessions, 'visits'],
      [ft.median == null ? '—' : `${ft.median} min`, `typical time to a first book (${ft.count})`],
      [dr.p50 == null ? '—' : fmt.secs(dr.p50), `typical drawing time, slowest 5%: ${dr.p95 == null ? '—' : fmt.secs(dr.p95)}`],
      [sb.makers ? pct(sb.again / sb.makers) : '—', `made a second book (${sb.again} of ${sb.makers}, all time)`],
    ].map(([big, label]) => el('div', { class: 'stat' }, el('b', { text: big }), el('span', { text: label }))));
    $('peopleDays').tBodies[0].replaceChildren(...(d.days.length ? d.days.map((x) => el('tr', {},
      el('td', { text: x.day }), el('td', { class: 'num', text: x.people }), el('td', { class: 'num', text: x.new }),
      el('td', { class: 'num', text: x.signed_in }), el('td', { class: 'num', text: x.visits })))
      : [el('tr', { class: 'empty' }, el('td', { colspan: 5, text: 'Nobody yet.' }))]));
    paintFunnel($('bookFunnel'), d.book_funnel);
    paintFunnel($('walletFunnel'), d.wallet_funnel);
    const none = (text) => el('li', { class: 'soft', text });
    $('blocked').replaceChildren(...(d.blocked.length ? d.blocked.map((b) => el('li', {}, el('b', { text: b.times }), ` ${b.what}`))
      : [none('Nothing yet.')]));
    $('rageRows').replaceChildren(...(d.rage_clicks.length ? d.rage_clicks.map((r) => el('li', {}, el('b', { text: r.times }),
      ` ${clickName(r.target)} on `, el('span', { class: 'mono', text: r.path }))) : [none('None. Good.')]));
    const rows = (items, cells) => (items.length ? items.map((x) => el('tr', {}, ...cells(x)))
      : [el('tr', { class: 'empty' }, el('td', { colspan: 3, text: 'Nothing yet.' }))]);
    $('clickRows').replaceChildren(...rows(d.clicks, (c) => [el('td', { text: clickName(c.target) }),
      el('td', { class: 'num', text: c.clicks }), el('td', { class: 'num', text: c.visitors })]));
    $('latestEvents').tBodies[0].replaceChildren(...(d.latest.length ? d.latest.map((x) => el('tr', {},
      el('td', { class: 'when', text: fmt.when(x.at) }),
      el('td', {}, el('span', { class: 'mono', text: x.person }), x.signed_in ? ' (signed in)' : ''),
      el('td', { text: x.name === 'click' ? `Clicked ${clickName(x.detail || '?')}` : x.name === 'page_view' ? 'Opened the page'
        : `${x.name.replace(/_/g, ' ')}${x.detail ? `: ${x.detail}` : ''}` }),
      el('td', { class: 'mono', text: x.path })))
      : [el('tr', { class: 'empty' }, el('td', { colspan: 4, text: 'Nothing yet.' }))]));
    $('pageRows').replaceChildren(...rows(d.pages, (p) => [el('td', { class: 'mono', text: p.path }),
      el('td', { class: 'num', text: p.views }), el('td', { class: 'num', text: p.visitors })]));
  }
  funnelFilters.addEventListener('input', loadFunnel);

  // --- characters ----------------------------------------------------------------------------------
  const WHY = {
    pinned: 'pinned in the story file', 'pinned but missing': 'pinned picture not found: using the description',
    repo: 'a picture kept in the repo', 'matches the description': 'drawn from the current description',
    'not drawn yet': 'not drawn yet: the first book draws it', 'description changed': 'description changed: the next book draws a new version',
  };
  function whyText(c) {
    const source = (c.versions.find((v) => v.name === c.in_use) || {}).source;
    if (c.why === 'matches the description' && source === 'uploaded') return 'uploaded here, in use';
    if (c.why === 'matches the description' && source === 'imported') return 'imported from the repo, in use';
    return WHY[c.why] || c.why;
  }
  function copyPin(name, button) {
    const text = `picture: ${name}`;
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
      () => { button.textContent = 'copied!'; setTimeout(() => { button.textContent = name; }, 1200); },
      () => window.prompt('Copy this into the story file:', text));
  }
  // Click a character's picture to upload a new one: saved as a new version (the old ones stay) and used from now on.
  function replaceButton(st, c) {
    const input = el('input', { type: 'file', accept: 'image/*', hidden: true });
    const note = el('span', { class: 'replace-note', text: c.in_use_url ? 'Click to replace' : 'Click to upload one' });
    const button = el('button', { class: 'cast-main replace', type: 'button', title: `Upload a new picture of ${c.name}`,
      onclick: () => input.click() },
    c.in_use_url ? el('img', { src: c.in_use_url, alt: c.name, loading: 'lazy' }) : el('span', { text: 'No picture yet' }),
    note);
    input.addEventListener('change', async () => {
      const file = input.files[0];
      if (!file) return;
      note.textContent = 'Uploading…';
      button.disabled = true;
      const body = new FormData();
      body.append('photo', file);
      try {
        const res = await fetch(`${API}/characters/${encodeURIComponent(st.key)}/${encodeURIComponent(c.key)}/picture`,
          { method: 'POST', body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error((data.detail && data.detail.message) || `HTTP ${res.status}`);
        if (data.note) window.alert(data.note);
        await loadCharacters();
      } catch (e) {
        note.textContent = e.message;
        button.disabled = false;
      }
    });
    const draw = el('button', { class: 'btn plain small draw', type: 'button',
      text: c.in_use_url ? 'Draw a new version' : 'Draw it now', onclick: async () => {
        if (!window.confirm(`Draw ${c.name} from the story file’s description? It costs about 4¢ and takes about a minute.`)) return;
        draw.disabled = true;
        draw.textContent = 'Drawing… (about a minute)';
        try {
          const res = await fetch(`${API}/characters/${encodeURIComponent(st.key)}/${encodeURIComponent(c.key)}/draw`,
            { method: 'POST' });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error((data.detail && data.detail.message) || `HTTP ${res.status}`);
          if (data.note) window.alert(data.note);
          await loadCharacters();
        } catch (e) {
          draw.textContent = `Didn’t work: ${e.message}`;
          draw.disabled = false;
        }
      } });
    return el('div', { class: 'cast-picture' }, button, input, draw);
  }

  async function loadCharacters() {
    const stories = await api('/characters');
    $('characterStories').replaceChildren(...stories.map((st) => el('section', { class: 'cast-story' },
      el('h2', { class: 'section-title', text: st.title }),
      el('div', { class: 'cast-grid' }, ...st.characters.map((c) => el('article', { class: 'panel cast-card' },
        replaceButton(st, c),
        el('h3', { text: c.name }),
        el('p', { class: `why ${c.why.replace(/ /g, '-')}`, text: `${c.in_use ? `${c.in_use}: ` : ''}${whyText(c)}` }),
        el('details', {}, el('summary', { text: 'description' }), el('p', { class: 'soft', text: c.description })),
        c.versions.length ? el('div', { class: 'versions' }, ...c.versions.map((v) => el('figure', {
          class: v.name === c.in_use ? 'current' : null },
          el('img', { src: `${v.url}?w=160`, alt: v.name, loading: 'lazy' }),
          el('figcaption', {}, el('button', { class: 'btn plain small', type: 'button', title: 'Copy picture: ' + v.name,
            text: v.name, onclick: (e) => copyPin(v.name, e.currentTarget) }),
            el('span', { class: 'soft', text: `${v.source}${v.cost ? ` · ${fmt.cost(v.cost)}` : ''}` })))))
          : null))))));
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
    if (h.tab === 'activity') loadActivity();
    if (h.tab === 'funnel') loadFunnel();
    if (h.book && ['queued', 'running', 'interrupted'].includes(openStatus)) openBook(h.book);
  }, 5000);
})();
