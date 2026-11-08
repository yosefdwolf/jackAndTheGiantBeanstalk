// If anything on this page breaks, say so on screen (with a reference) and save it on the server,
// so "I clicked and nothing happened" can be traced.
function reportPageError(message) {
  const box = document.getElementById('error');
  const show = (ref) => {
    if (box) {
      box.textContent = 'Oops, something on this page broke. Please reload it and try again.' + (ref ? ` (reference ${ref})` : '');
      box.hidden = false;
    }
  };
  try {
    fetch('/api/client-error', { method: 'POST', keepalive: true,
      body: JSON.stringify({ message: String(message).slice(0, 500), page: location.pathname }) })
      .then((r) => r.json()).then((d) => show(d.ref)).catch(() => show());
  } catch { show(); }
}
window.addEventListener('error', (e) => reportPageError(e.message));
window.addEventListener('unhandledrejection', (e) => reportPageError(e.reason));

(() => {
  const $ = (id) => document.getElementById(id);
  const track = window.track || (() => {});  // static/track.js; a blocker may have stopped it loading
  const reduceMotion = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const form = $('form'), drop = $('drop'), preview = $('preview'), go = $('go'), error = $('error');
  const MAX_SIDE = 1600;
  const COPY = JSON.parse($('storyCopy').textContent);  // this story's own words, from its story file
  const PDF_NAME = COPY.pdf_name;
  const PASSWORD_KEY = 'beanstalk-password';
  const BOOK_KEY = 'beanstalk-book';
  const POLL_MS = 1500;

  let photo = null;      // Blob that will be uploaded
  let password = '';
  let hero = '';  // the reader's own name, as the story says it

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
    drop(k) { try { localStorage.removeItem(k); } catch {} },
  };

  function errorDetail(data, res) {
    const d = data && typeof data.detail === 'object' ? data.detail : { message: (data && data.detail) || `Something went wrong (${res.status}).` };
    d.ref = d.ref || res.headers.get('X-Request-Id');
    return d;
  }

  fetch('/api/options').then((r) => r.json()).then((o) => { $('mockBadge').hidden = !o.mock; }).catch(() => {});


  // --- the magic word comes first ---------------------------------------------------------------------

  const gate = $('gate'), pwField = $('password'), pwError = $('passwordError');

  function showPasswordError(msg) {
    pwError.textContent = msg;
    pwError.hidden = false;
    pwField.setAttribute('aria-invalid', 'true');
    pwField.value = '';
    pwField.focus();
  }
  pwField.addEventListener('input', () => { pwError.hidden = true; pwField.removeAttribute('aria-invalid'); });

  // --- then Google sign-in --------------------------------------------------------------------------

  let me = null;  // who's signed in (from /api/me)
  const meReady = fetch('/api/me', { cache: 'no-store' }).then((r) => r.json()).then((m) => { me = m; paintAccount(); updateReady(); })
    .catch(() => {});

  const money = (c) => `$${(c / 100).toFixed(2)}`;

  function paintAccount() {
    const a = $('account');
    if (!me || !me.signed_in) { a.hidden = true; return; }
    const left = me.unlimited ? 'free books' : `${money(me.balance_cents)} in your wallet`;
    a.replaceChildren(`Hi ${me.name || me.email}! `,
      Object.assign(document.createElement('a'), { className: 'left', href: '/wallet', textContent: left }));
    a.hidden = false;
  }

  function askToSignIn(message) {
    form.hidden = true;
    gate.hidden = true;
    $('signin').hidden = false;
    $('signin').classList.add('reveal');
    $('signinError').textContent = message || '';
    $('signinError').hidden = !message;
  }

  function openBook(animate) {
    store.set(PASSWORD_KEY, password);
    const show = async () => {
      await meReady;
      gate.hidden = true;
      if (!me || !me.signed_in) return askToSignIn();
      $('signin').hidden = true;
      if (!$('reader').hidden || !$('printing').hidden || !$('bookLoading').hidden) return;  // a book is already open
      form.hidden = false;
      form.classList.add('reveal');
    };
    if (animate) { gate.classList.add('opening'); setTimeout(show, 520); } else show();
  }

  function lockAgain(message) {
    store.drop(PASSWORD_KEY);
    document.documentElement.classList.remove('known-word');
    password = '';
    form.hidden = true;
    $('signin').hidden = true;
    $('printing').hidden = true;
    gate.hidden = false;
    gate.classList.remove('opening');
    showPasswordError(message);
    gate.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function tryPassword(candidate, animate) {
    const res = await fetch('/api/unlock', { method: 'POST', headers: { 'X-App-Password': candidate } });
    if (res.ok) { password = candidate; openBook(animate); return true; }
    const d = errorDetail(await res.json().catch(() => ({})), res);
    return d;
  }

  $('gateForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!pwField.value) return showPasswordError('Type the magic word first.');
    $('unlockBtn').disabled = true;
    try {
      const result = await tryPassword(pwField.value, true);
      if (result !== true) showPasswordError(`That’s not the magic word. (reference ${result.ref})`);
    } catch {
      showPasswordError('We couldn’t reach the book. Check your connection and try again.');
    } finally {
      $('unlockBtn').disabled = false;
    }
  });

  // --- the photograph -------------------------------------------------------------------------------

  // Shrink big phone photos before upload (faster on mobile data).
  async function downscale(file) {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
      const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.9));
      if (blob) return blob;
    } catch {}
    return null;
  }

  // Browsers that can't read the photo (e.g. an iPhone HEIC in Chrome) get it converted by the server.
  async function convertOnServer(file) {
    const body = new FormData();
    body.append('photo', file, file.name || 'photo');
    const res = await fetch('/api/photo-preview', { method: 'POST', body });
    if (!res.ok) throw errorDetail(await res.json().catch(() => ({})), res);
    return res.blob();
  }

  async function setFile(file) {
    if (!file) return;
    showError('');
    $('polaroidCaption').textContent = 'developing…';
    let blob = await downscale(file);
    if (!blob) {
      try { blob = await convertOnServer(file); }
      catch (d) {
        $('polaroidCaption').textContent = 'tap or drop a photo';
        return showError(`${d.message || 'We couldn’t open that photo.'}${d.ref ? ` (reference ${d.ref})` : ''}`);
      }
    }
    photo = blob;
    preview.src = URL.createObjectURL(blob);
    preview.hidden = false;
    drop.classList.add('has-photo');
    $('polaroidCaption').textContent = 'what a star!';
    updateReady();
    track('photo_added');
  }

  function showError(msg) {
    error.textContent = msg;
    error.hidden = !msg;
  }

  let toldNoMoney = false;
  function updateReady() {
    const hasName = form.name.value.trim().length > 0;
    if (me && me.left === 0) {  // not enough in the wallet for a book
      if (!toldNoMoney) { toldNoMoney = true; track('no_money'); }
      go.disabled = true;
      $('goNote').replaceChildren(`A book costs ${money(me.price_cents)}. `,
        Object.assign(document.createElement('a'), { href: '/wallet', textContent: 'Add money to your wallet' }));
      return;
    }
    go.disabled = !(photo && hasName);
    $('goNote').textContent = !photo && !hasName ? 'Add a photo and a name to begin'
      : !photo ? 'Now pop in a photo' : !hasName ? 'Now write your name' : 'Ready when you are!';
  }
  form.name.addEventListener('input', updateReady);

  // Selfie: phones open the front camera through the file input; computers use the webcam.
  const camera = $('camera'), video = $('cameraVideo'), cameraError = $('cameraError');
  let stream = null;

  function stopCamera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    if (camera.open) camera.close();
  }

  $('selfieBtn').addEventListener('click', async () => {
    if (matchMedia('(pointer: coarse)').matches || !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      $('cameraInput').click();
      return;
    }
    cameraError.hidden = true;
    $('cameraShoot').disabled = true;
    camera.showModal();
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 } } });
      video.srcObject = stream;
      $('cameraShoot').disabled = false;
    } catch {
      cameraError.textContent = 'We couldn’t open your camera. Allow camera access, or choose a photo instead.';
      cameraError.hidden = false;
    }
  });

  $('cameraShoot').addEventListener('click', () => {
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    canvas.toBlob((blob) => { if (blob) setFile(new File([blob], 'selfie.jpg', { type: 'image/jpeg' })); }, 'image/jpeg', 0.92);
    stopCamera();
  });
  $('cameraCancel').addEventListener('click', stopCamera);
  camera.addEventListener('close', stopCamera);

  for (const input of [$('fileInput'), $('cameraInput')]) {
    input.addEventListener('change', () => { setFile(input.files[0]); input.value = ''; });
  }
  drop.addEventListener('click', () => $('fileInput').click());
  drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('fileInput').click(); } });
  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => setFile(e.dataTransfer.files[0]));

  // --- send the book to be drawn ------------------------------------------------------------------

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!photo) return showError('Pop in a photo of yourself first.');
    if (!form.name.value.trim()) return showError('Write your name first.');
    showError('');
    go.disabled = true;
    go.textContent = COPY.going;
    hero = form.name.value.trim();  // their own name, as in the story

    const body = new FormData(form);
    body.append('photo', photo, 'photo.jpg');
    body.append('story', document.body.dataset.story || '');
    track('book_requested', { story: document.body.dataset.story });
    try {
      const res = await fetch('/api/books', { method: 'POST', body, headers: { 'X-App-Password': password } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = errorDetail(data, res);
        track('book_refused', { reason: d.reason });
        if (d.reason === 'wrong_password') return lockAgain(`The magic word changed. Please type it again. (reference ${d.ref})`);
        if (d.reason === 'not_signed_in') { me = null; return askToSignIn(`Please sign in again. (reference ${d.ref})`); }
        showError(`${d.message}${d.ref ? ` (reference ${d.ref})` : ''}`);
        return error.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      if (me && me.left != null) {
        me.left = Math.max(0, me.left - 1);
        me.balance_cents -= me.price_cents;
        paintAccount();
      }
      watch(data.id, true);
    } catch {
      showError('We couldn’t reach the book. Check your connection and try again.');
    } finally {
      go.textContent = COPY.go;
      updateReady();
    }
  });

  // --- growing the book: the pages drying on a line (static/clothesline.js) --------------------------

  // How far along a picture is, from how long it has been drawing (t) and how long that kind of
  // picture usually takes (eta). Speeding up toward the end feels fastest and stalling near the end
  // feels worst (Harrison et al., "Rethinking the progress bar"), so: gently accelerate to 88% at the
  // usual time, keep creeping toward 97% without ever stopping, then sweep to 100% when it arrives.
  function estimate(t, eta) {
    const r = Math.max(0, t) / eta;
    if (r <= 1) return 0.04 + 0.84 * Math.pow(r, 1.35);
    return 0.97 - 0.09 * Math.exp(-(r - 1) * 1.6);
  }

  let book = null, clockOffset = 0, frame = 0, pollTimer = 0, watching = null, line = null;
  const shown = new Map();  // "kind-page-try" -> how full it has been shown (it never goes backwards)

  const seconds = (ms) => `${Math.max(0, Math.round(ms / 1000))}s`;
  const serverNow = () => Date.now() + clockOffset;

  function fractionOf(img) {
    if (img.status === 'done') return 1;
    if (img.status !== 'drawing' || !img.started_at) return 0;
    const k = `${img.kind}-${img.page}-${img.attempt}`;
    const f = Math.max(shown.get(k) || 0, estimate((serverNow() - Date.parse(img.started_at)) / 1000, img.eta_seconds));
    shown.set(k, f);
    return f;
  }

  // The whole book: the stage it's in (cartoon, pages, binding) and the newest story line being drawn.
  function paintOverall(fractions) {
    const total = fractions.reduce((a, b) => a + b, 0) / Math.max(1, fractions.length);
    $('overallBar').style.width = `${(total * 100).toFixed(1)}%`;
    $('overallBar').parentElement.setAttribute('aria-valuenow', String(Math.round(total * 100)));
    const heroImg = book.images.find((i) => i.kind === 'hero_sheet');
    const pages = book.images.filter((i) => i.kind === 'page');
    const pagesDone = pages.filter((i) => i.status === 'done').length;
    const drawing = book.images.filter((i) => i.status === 'drawing')
      .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))[0];
    let name;
    if (book.status === 'failed') name = 'Stopped';
    else if (heroImg && heroImg.status !== 'done') name = COPY.hero_progress || 'Drawing your cartoon';
    else if (pagesDone < pages.length) name = `Painting the pages · ${pagesDone} of ${pages.length}`;
    else name = COPY.binding;
    $('stageName').textContent = name;
    $('stageLine').textContent = drawing && drawing.progress ? drawing.progress : '';
  }

  function paintAll() {
    if (!book) return;
    const fractions = book.images.map(fractionOf);
    const done = book.images.filter((i) => i.status === 'done').length;
    paintOverall(fractions);
    if (!line) line = new Clothesline($('line'), { total: book.images.length });
    line.update(book.images, fractionOf);
    $('tally').textContent = `${done} of ${book.images.length}`;
    const starts = book.images.map((i) => i.started_at).filter(Boolean).map(Date.parse);
    if (starts.length) {
      const ends = book.images.map((i) => i.finished_at).filter(Boolean).map(Date.parse);
      const end = book.status === 'done' || book.status === 'failed' ? Math.max(...ends) : serverNow();
      $('elapsed').textContent = seconds(end - Math.min(...starts));
    }
    if (['running', 'queued', 'interrupted'].includes(book.status)) frame = requestAnimationFrame(paintAll);
  }

  async function poll() {
    try {
      const res = await fetch(`/api/books/${watching}`, { cache: 'no-store' });
      // Not this person's book (or no such book): forget it, clear it from the address, back to the form.
      if (res.status === 404) return startOver();
      const data = await res.json();
      clockOffset = Date.parse(data.server_time) - Date.now();
      book = data;
      if (data.hero) hero = data.hero;  // their own name, also for books opened from the bookshelf page
      cancelAnimationFrame(frame);
      paintAll();
      if (data.status !== 'done') showProgress();
      if (['done', 'failed', 'refused'].includes(data.status)) return finish(data);
    } catch {
      // A blip in the connection: the book keeps growing on the server, so just ask again.
    }
    pollTimer = setTimeout(poll, POLL_MS);
  }

  // A book just started shows its progress bars. One opened again (from the bookshelf or a reload)
  // shows a gray outline of the book instead, and only switches to the bars if it's still being drawn.
  function showProgress() {
    $('bookLoading').hidden = true;
    $('printing').hidden = false;
  }

  // While the book is drawn, the title changes every few seconds to a little job from the story file
  // ("Watering the magic beans…", "Polishing the golden eggs…"), never the same one twice in a row.
  const MUSE_MS = 3200;
  let museTimer = null, lastMuse = '';
  function muse() {
    const words = COPY.musing.filter((w) => w !== lastMuse);
    if (!words.length) return;
    lastMuse = words[Math.floor(Math.random() * words.length)];
    const title = $('printingTitle');
    title.textContent = `${lastMuse}…`;
    if (!reduceMotion()) title.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }],
      { duration: 350, easing: 'ease-out' });
  }
  function startMusing() {
    stopMusing();
    if (!COPY.musing || !COPY.musing.length) return;
    muse();
    museTimer = setInterval(muse, MUSE_MS);
  }
  function stopMusing() { clearInterval(museTimer); museTimer = null; }

  let watchingFresh = false;
  function watch(id, fresh = false) {
    watching = id;
    watchingFresh = fresh;
    store.set(BOOK_KEY, id);
    if (location.hash !== `#book=${id}`) history.replaceState(null, '', `#book=${id}`);
    line = null;  // a fresh line for this book, made on the first paint
    shown.clear();
    $('ref').textContent = id;
    $('readerRef').textContent = id;
    $('bookError').hidden = true;
    $('printingTitle').textContent = COPY.growing;
    startMusing();
    gate.hidden = true;
    form.hidden = true;
    $('signin').hidden = true;
    $('reader').hidden = true;
    $('review').hidden = true;
    $('printing').hidden = !fresh;
    $('bookLoading').hidden = fresh;
    (fresh ? $('printing') : $('bookLoading')).scrollIntoView({ behavior: 'smooth', block: 'start' });
    clearTimeout(pollTimer);
    poll();
  }

  function finish(data) {
    stopMusing();
    cancelAnimationFrame(frame);
    clearTimeout(pollTimer);
    store.drop(BOOK_KEY);
    // A failed book gives the day's book back; a finished one uses it. Ask the server which.
    fetch('/api/me', { cache: 'no-store' }).then((r) => r.json()).then((m) => { me = m; paintAccount(); updateReady(); })
      .catch(() => {});
    if (data.status === 'done' && data.book) {
      track('book_ready', { fresh: watchingFresh ? '1' : '0', ref: data.id });
      openReader(data);
      showReview(data.id);
    } else {
      track('book_failed', { ref: data.id });
      $('printingTitle').textContent = COPY.failed;
      $('bookError').textContent = `${data.error || 'This book couldn’t be finished.'} (reference ${data.id})`;
      $('bookError').hidden = false;
      // Redraw only the missing pictures (the finished ones are kept), or start a fresh book.
      const again = document.createElement('p');
      again.className = 'try-again';
      const retryBtn = Object.assign(document.createElement('button'), { className: 'btn bean', type: 'button',
        textContent: 'Try the missing pictures again' });
      const freshBtn = Object.assign(document.createElement('button'), { className: 'btn plain', type: 'button',
        textContent: 'Start a new book' });
      retryBtn.addEventListener('click', async () => {
        retryBtn.disabled = true;
        try {
          const res = await fetch(`/api/books/${data.id}/retry`, { method: 'POST', headers: { 'X-App-Password': password } });
          if (!res.ok) throw errorDetail(await res.json().catch(() => ({})), res);
          again.remove();
          watch(data.id, true);
        } catch (d) {
          retryBtn.disabled = false;
          $('bookError').textContent = `${d.message || 'That didn’t work.'}${d.ref ? ` (reference ${d.ref})` : ''}`;
        }
      });
      freshBtn.addEventListener('click', startOver);
      again.append(retryBtn, freshBtn);
      $('printing').append(again);
    }
  }

  // --- the flip book --------------------------------------------------------------------------------

  let leaves = [], current = 0;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function pageFace(spec, info) {
    const face = el('div', 'face front');
    if (spec.kind === 'cover') {
      face.classList.add('cover-page');
      const img = el('img'); img.src = `${info.cover_url}?w=700`; img.alt = `${info.child_name} as ${info.hero}`;
      const words = el('div');
      words.append(el('h3', null, info.title), el('p', null, `starring ${info.child_name}`));
      face.append(img, words);
    } else if (spec.kind === 'illustrated') {
      face.classList.add('story-page', `zone-${spec.text_zone}`);
      const img = el('img'); img.src = `${spec.image_url}?w=1400`; img.alt = spec.text;
      face.append(img, el('p', 'story-text', spec.text));
    } else if (spec.kind === 'about_me') {
      face.classList.add('about-page');
      const img = el('img'); img.src = `${info.cover_url}?w=600`; img.alt = info.child_name;
      const words = el('div');
      words.append(el('h3', null, 'About Me'), el('p', 'child', info.child_name));
      const dl = el('dl');
      for (const [label, value] of info.details) dl.append(el('dt', null, label), el('dd', null, value));
      words.append(dl);
      face.append(img, words);
    } else {
      face.classList.add('end-page');
      face.append(el('h3', null, 'The End'));
    }
    return face;
  }

  // Load every picture before the book opens, so a turning page always has the next one ready under it.
  function preload(bookEl) {
    return Promise.all([...bookEl.querySelectorAll('img')].map((img) =>
      img.decode ? img.decode().catch(() => {}) : new Promise((r) => { img.onload = img.onerror = r; })));
  }

  async function openReader(data) {
    const info = data.book;
    const specs = [{ kind: 'cover' }, ...info.pages, { kind: 'end' }];
    const bookEl = $('flipbook');
    bookEl.replaceChildren();
    leaves = specs.map((spec, i) => {
      const leaf = el('div', 'leaf');
      leaf.style.zIndex = String(specs.length - i);
      leaf.append(pageFace(spec, info), el('div', 'face back'));
      bookEl.append(leaf);
      return leaf;
    });
    current = 0;
    readToEnd = false;
    $('printingTitle').textContent = COPY.binding;
    await preload(bookEl);
    $('printing').hidden = true;
    $('bookLoading').hidden = true;
    Object.assign($('download'), { href: data.pdf_url, download: PDF_NAME });
    $('reader').hidden = false;
    $('reader').classList.add('reveal');
    showPage();
    $('reader').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Stacking: unturned pages from front to back, turned pages underneath. A page that's mid-turn stays
  // on top of everything until it has finished turning, so it never vanishes behind the next one.
  let turningLeaf = null;
  function stack() {
    leaves.forEach((leaf, i) => {
      leaf.style.zIndex = leaf === turningLeaf ? String(leaves.length * 3)
        : String(i < current ? i + 1 : leaves.length * 2 - i);
    });
  }

  function showPage() {
    leaves.forEach((leaf, i) => leaf.classList.toggle('turned', i < current));
    stack();
    $('prevPage').disabled = current === 0;
    $('nextPage').disabled = current >= leaves.length - 1;
    $('pageCount').textContent = current === 0 ? 'Cover' : current === leaves.length - 1 ? 'The End' : `Page ${current} of ${leaves.length - 2}`;
  }

  let readToEnd = false;
  function turn(step) {
    const next = Math.max(0, Math.min(leaves.length - 1, current + step));
    if (next === current) return;
    const leaf = leaves[step > 0 ? current : next];
    turningLeaf = leaf;
    leaf.classList.add('turning');
    current = next;
    showPage();
    if (current === leaves.length - 1 && !readToEnd) { readToEnd = true; track('reached_end', { ref: watching }); }
    clearTimeout(leaf._done);
    leaf._done = setTimeout(() => {
      leaf.classList.remove('turning');
      if (turningLeaf === leaf) turningLeaf = null;
      stack();
    }, 900);
  }

  $('prevPage').addEventListener('click', () => turn(-1));
  $('nextPage').addEventListener('click', () => turn(1));
  $('flipbook').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight') { e.preventDefault(); turn(1); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); turn(-1); }
  });
  let swiped = false;
  $('flipbook').addEventListener('click', (e) => {
    if (swiped) { swiped = false; return; }  // the swipe already turned the page
    const box = e.currentTarget.getBoundingClientRect();
    turn(e.clientX - box.left > box.width / 2 ? 1 : -1);
  });
  let swipeX = null;
  $('flipbook').addEventListener('pointerdown', (e) => { swipeX = e.clientX; });
  $('flipbook').addEventListener('pointerup', (e) => {
    if (swipeX != null && Math.abs(e.clientX - swipeX) > 40) { swiped = true; turn(e.clientX < swipeX ? 1 : -1); }
    swipeX = null;
  });

  // --- what did you think? (each person rates their own book) ---------------------------------------

  // A crowd study links here as /?pid=PARTICIPANT_ID. Kept across the Google sign-in, and saved with
  // the review so each answer can be matched to a payment.
  const PID_KEY = 'jack-participant';
  const pidFromLink = new URLSearchParams(location.search).get('pid');
  if (pidFromLink && /^[\w-]{1,64}$/.test(pidFromLink)) store.set(PID_KEY, pidFromLink);

  const reviewForm = $('reviewForm');
  const SCORES = ['looks_like_me', 'story_rings_true', 'looks_professional'];

  // Every question is required: the button only wakes up once all four are answered.
  function reviewMissing() {
    const f = new FormData(reviewForm);
    return SCORES.filter((k) => !f.get(k)).length + (String(f.get('not_good') || '').trim() ? 0 : 1);
  }
  function updateReviewReady() {
    const missing = reviewMissing();
    $('reviewBtn').disabled = missing > 0;
    $('reviewNote').textContent = missing === 0 ? '' : missing === 1 ? 'One more to answer' : `Answer all four to send (${4 - missing} of 4 done)`;
    $('reviewNote').hidden = missing === 0;
  }
  reviewForm.addEventListener('input', updateReviewReady);
  reviewForm.addEventListener('change', updateReviewReady);
  function setReviewOpen(open) {
    $('reviewToggle').setAttribute('aria-expanded', String(open));
    $('reviewBody').hidden = !open;
  }
  $('reviewToggle').addEventListener('click', () => {
    if ($('reviewBody').hidden) track('review_opened');
    setReviewOpen($('reviewBody').hidden);
  });

  async function showReview(id) {
    $('review').hidden = false;
    setReviewOpen(false);  // starts closed, under the book; opening it shows the questions
    $('reviewPdf').href = `/api/books/${id}/pdf?inline=1`;
    $('reviewThanks').hidden = true;
    $('reviewError').hidden = true;
    $('reviewAlready').hidden = true;
    reviewForm.reset();
    try {
      const res = await fetch(`/api/books/${id}/review`, { cache: 'no-store' });
      if (!res.ok) { $('review').hidden = true; return; }  // not this person's book
      const { review } = await res.json();
      if (review) {
        for (const k of ['looks_like_me', 'story_rings_true', 'looks_professional']) {
          const input = reviewForm.querySelector(`input[name="${k}"][value="${review[k]}"]`);
          if (input) input.checked = true;
        }
        reviewForm.not_good.value = review.not_good;
        $('reviewBtn').textContent = 'Update my answers';
        // One review per person, so sending again replaces it.
        $('reviewAlready').textContent = (review.book_id === id ? 'You’ve already left a review. '
          : `You already left a review for an earlier book (reference ${review.book_id}). `)
          + 'Open this to change it: sending again replaces your earlier answers.';
        $('reviewAlready').hidden = false;
      } else {
        $('reviewBtn').textContent = 'Send my answers';
      }
    } catch { /* the review card is a bonus; the book still works without it */ }
    updateReviewReady();
  }

  reviewForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(reviewForm);
    const body = {};
    for (const k of ['looks_like_me', 'story_rings_true', 'looks_professional']) {
      if (!f.get(k)) {
        $('reviewError').textContent = 'Pick a number for each question first.';
        $('reviewError').hidden = false;
        return reviewForm.querySelector(`input[name="${k}"]`).closest('fieldset').scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      body[k] = Number(f.get(k));
    }
    body.not_good = String(f.get('not_good') || '').trim();
    if (!body.not_good) {
      $('reviewError').textContent = 'Tell us what isn’t good too, even if it’s small.';
      $('reviewError').hidden = false;
      return reviewForm.not_good.focus();
    }
    if (store.get(PID_KEY)) body.participant_id = store.get(PID_KEY);
    $('reviewBtn').disabled = true;
    try {
      const res = await fetch(`/api/books/${watching}/review`, { method: 'PUT', body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' } });
      if (!res.ok) {
        const d = errorDetail(await res.json().catch(() => ({})), res);
        throw new Error(`${d.message || 'That didn’t save.'}${d.ref ? ` (reference ${d.ref})` : ''}`);
      }
      track('review_sent', { ref: watching });
      $('reviewError').hidden = true;
      $('reviewThanks').hidden = false;
      $('reviewAlready').textContent = 'You’ve already left a review. Sending again replaces your earlier answers.';
      $('reviewAlready').hidden = false;
      $('reviewBtn').textContent = 'Update my answers';
    } catch (err) {
      $('reviewError').textContent = err.message.startsWith('Failed') ? 'We couldn’t reach the book. Try again in a moment.' : err.message;
      $('reviewError').hidden = false;
    } finally {
      updateReviewReady();
    }
  });

  function startOver() {
    stopMusing();
    clearTimeout(pollTimer);
    cancelAnimationFrame(frame);
    history.replaceState(null, '', location.pathname);
    store.drop(BOOK_KEY);
    $('printing').hidden = true;
    $('bookLoading').hidden = true;
    $('reader').hidden = true;
    $('review').hidden = true;
    for (const extra of $('printing').querySelectorAll('p:not(.ref):not(.tally):not(.error)')) extra.remove();
    form.hidden = !password || !(me && me.signed_in);
    $('signin').hidden = !password || !!(me && me.signed_in);
    gate.hidden = !!password;
    photo = null;
    preview.hidden = true;
    drop.classList.remove('has-photo');
    $('polaroidCaption').textContent = 'tap or drop a photo';
    updateReady();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  $('again').addEventListener('click', startOver);

  // --- on load ----------------------------------------------------------------------------------------

  updateReady();
  const fromHash = (location.hash.match(/^#book=([a-f0-9]{8})$/) || [])[1];
  const savedBook = store.get(BOOK_KEY);
  const savedPassword = store.get(PASSWORD_KEY);
  if (savedPassword) {
    // Already know the magic word on this device: check it quietly and skip the gate.
    gate.hidden = true;
    const showGate = () => { document.documentElement.classList.remove('known-word'); gate.hidden = false; };
    tryPassword(savedPassword, false).then((ok) => { if (ok !== true) { store.drop(PASSWORD_KEY); showGate(); } })
      .catch(showGate);
  } else {
    pwField.focus({ preventScroll: true });
  }
  if (fromHash || savedBook) watch(fromHash || savedBook);
})();
