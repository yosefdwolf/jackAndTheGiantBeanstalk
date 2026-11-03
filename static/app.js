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
  const form = $('form'), drop = $('drop'), preview = $('preview'), go = $('go'), error = $('error');
  const MAX_SIDE = 1600;
  const PDF_NAME = 'JackAndTheBeanstalk.pdf';
  const PASSWORD_KEY = 'beanstalk-password';
  const BOOK_KEY = 'beanstalk-book';
  const POLL_MS = 1500;

  let photo = null;      // Blob that will be uploaded
  let password = '';
  let hero = 'Jack';

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
  const meReady = fetch('/api/me', { cache: 'no-store' }).then((r) => r.json()).then((m) => { me = m; paintAccount(); })
    .catch(() => {});

  function paintAccount() {
    const a = $('account');
    if (!me || !me.signed_in) { a.hidden = true; return; }
    const left = me.unlimited ? 'unlimited books' : me.left === 1 ? '1 book left today' : `${me.left} books left today`;
    a.replaceChildren(`Hi ${me.name || me.email}! `, Object.assign(document.createElement('span'), { className: 'left', textContent: left }),
      ...(me.admin ? [' · ', Object.assign(document.createElement('a'), { href: '/admin', textContent: 'admin' })] : []),
      ' · ', Object.assign(document.createElement('a'), { href: '/auth/logout', textContent: 'sign out' }));
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
      form.hidden = false;
      form.classList.add('reveal');
    };
    if (animate) { gate.classList.add('opening'); setTimeout(show, 520); } else show();
  }

  function lockAgain(message) {
    store.drop(PASSWORD_KEY);
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
  }

  function showError(msg) {
    error.textContent = msg;
    error.hidden = !msg;
  }

  function updateReady() {
    const hasName = form.name.value.trim().length > 0;
    go.disabled = !(photo && hasName);
    $('goNote').textContent = !photo && !hasName ? 'Add a photo and a name to begin'
      : !photo ? 'Now pop in a photo' : !hasName ? 'Now write their name' : 'Ready when you are!';
  }
  form.name.addEventListener('input', updateReady);
  form.addEventListener('change', (e) => { if (e.target.name === 'gender') hero = e.target.value === 'girl' ? 'Jane' : 'Jack'; });

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

  // --- planting the beans: send the book to be drawn ------------------------------------------------

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!photo) return showError('Pop in a photo of the child first.');
    if (!form.name.value.trim()) return showError('Write the child’s name first.');
    showError('');
    go.disabled = true;
    go.textContent = 'Planting…';
    hero = new FormData(form).get('gender') === 'girl' ? 'Jane' : 'Jack';

    const body = new FormData(form);
    body.append('photo', photo, 'photo.jpg');
    try {
      const res = await fetch('/api/books', { method: 'POST', body, headers: { 'X-App-Password': password } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = errorDetail(data, res);
        if (d.reason === 'wrong_password') return lockAgain(`The magic word changed. Please type it again. (reference ${d.ref})`);
        if (d.reason === 'not_signed_in') { me = null; return askToSignIn(`Please sign in again. (reference ${d.ref})`); }
        showError(`${d.message}${d.ref ? ` (reference ${d.ref})` : ''}`);
        return error.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      if (me && me.left != null) { me.left = Math.max(0, me.left - 1); paintAccount(); }
      watch(data.id);
    } catch {
      showError('We couldn’t reach the book. Check your connection and try again.');
    } finally {
      go.textContent = 'Plant the magic beans';
      updateReady();
    }
  });

  // --- growing the book: one progress bar per picture -------------------------------------------------

  // What each picture is "doing", by how far along it is. Showing the work holds attention and
  // makes the wait feel worthwhile (Buell & Norton's labour illusion).
  const STAGES = {
    hero_sheet: ['Studying the photo', 'Sketching the face', 'Finding the likeness', 'Adding colour', 'Final sparkle'],
    page: ['Setting the scene', 'Sketching {hero} and friends', 'Inking the lines', 'Painting the colours', 'Final sparkle'],
  };

  // How full a bar is, from how long the picture has been drawing (t) and how long that kind of
  // picture usually takes (eta). Speeding up toward the end feels fastest and stalling near the end
  // feels worst (Harrison et al., "Rethinking the progress bar"), so: gently accelerate to 88% at the
  // usual time, keep creeping toward 97% without ever stopping, then sweep to 100% when it arrives.
  function estimate(t, eta) {
    const r = Math.max(0, t) / eta;
    if (r <= 1) return 0.04 + 0.84 * Math.pow(r, 1.35);
    return 0.97 - 0.09 * Math.exp(-(r - 1) * 1.6);
  }

  function stageText(img, fraction, overdue) {
    if (overdue) return img.kind === 'page' ? 'Last little details…' : 'Taking a little longer than usual';
    const list = STAGES[img.kind] || STAGES.page;
    return list[Math.min(list.length - 1, Math.floor(fraction * list.length))].replace('{hero}', hero);
  }

  let book = null, clockOffset = 0, frame = 0, pollTimer = 0, watching = null;
  const rows = new Map();  // "kind-page" -> {el, shown}

  const key = (img) => `${img.kind}-${img.page}`;
  const seconds = (ms) => `${Math.max(0, Math.round(ms / 1000))}s`;
  const serverNow = () => Date.now() + clockOffset;

  function makeRow(img) {
    const li = document.createElement('li');
    li.className = `plate waiting${img.kind === 'hero_sheet' ? ' hero' : ''}`;
    li.innerHTML = '<div class="thumb"><img alt=""></div><div class="plate-body"><p class="plate-name"></p>' +
      '<p class="plate-text"></p><p class="plate-stage"><span class="what"></span><span class="time"></span></p>' +
      '<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"><i></i></div></div>';
    li.querySelector('.plate-name').textContent = img.label;
    li.querySelector('.plate-text').textContent = img.text || 'Drawn first, so the child looks the same on every page.';
    $('plates').append(li);
    return { el: li, shown: 0 };
  }

  function paintRow(img) {
    const row = rows.get(key(img));
    const el = row.el, bar = el.querySelector('.bar i'), what = el.querySelector('.what'), time = el.querySelector('.time');
    el.className = `plate ${img.status}${img.kind === 'hero_sheet' ? ' hero' : ''}`;
    let fraction = 0;
    if (img.status === 'waiting') {
      const heroImg = book.images.find((i) => i.kind === 'hero_sheet');
      what.textContent = img.kind === 'page' && heroImg && heroImg.status !== 'done' ? 'Waiting for the cartoon' : 'Up next';
      time.textContent = '';
    } else if (img.status === 'drawing') {
      const t = serverNow() - Date.parse(img.started_at);
      fraction = estimate(t / 1000, img.eta_seconds);
      what.textContent = stageText(img, fraction, t / 1000 > img.eta_seconds * 1.3);
      time.textContent = `${seconds(t)} · usually ${Math.round(img.eta_seconds)}s`;
    } else if (img.status === 'done') {
      fraction = 1;
      what.textContent = 'Done!';
      time.textContent = img.started_at && img.finished_at ? seconds(Date.parse(img.finished_at) - Date.parse(img.started_at)) : '';
      const pic = el.querySelector('.thumb img');
      if (!pic.getAttribute('src') && img.image_url) {
        pic.onload = () => pic.classList.add('shown');
        pic.src = `${img.image_url}?w=360`;
        pic.alt = img.label;
      }
    } else if (img.status === 'failed') {
      fraction = Math.max(row.shown, 0.1);
      what.textContent = img.error || 'This picture couldn’t be drawn.';
      time.textContent = '';
    }
    // Never move a bar backwards; when a picture arrives, sweep the rest of the way.
    fraction = Math.max(row.shown, fraction);
    bar.style.transition = img.status === 'done' && row.shown < 1 ? 'width .45s ease-out' : 'none';
    bar.style.width = `${(fraction * 100).toFixed(2)}%`;
    el.querySelector('.bar').setAttribute('aria-valuenow', String(Math.round(fraction * 100)));
    row.shown = fraction;
    return fraction;
  }

  function paintAll() {
    if (!book) return;
    const fractions = book.images.map(paintRow);
    const done = book.images.filter((i) => i.status === 'done').length;
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
      if (res.status === 404) return finish({ id: watching, status: 'failed', error: 'We couldn’t find that book.' });
      const data = await res.json();
      clockOffset = Date.parse(data.server_time) - Date.now();
      book = data;
      for (const img of data.images) if (!rows.has(key(img))) rows.set(key(img), makeRow(img));
      cancelAnimationFrame(frame);
      paintAll();
      if (['done', 'failed', 'refused'].includes(data.status)) return finish(data);
    } catch {
      // A blip in the connection: the book keeps growing on the server, so just ask again.
    }
    pollTimer = setTimeout(poll, POLL_MS);
  }

  function watch(id) {
    watching = id;
    store.set(BOOK_KEY, id);
    if (location.hash !== `#book=${id}`) history.replaceState(null, '', `#book=${id}`);
    rows.clear();
    $('plates').replaceChildren();
    $('ref').textContent = id;
    $('readerRef').textContent = id;
    $('bookError').hidden = true;
    $('printingTitle').textContent = 'Growing your book';
    gate.hidden = true;
    form.hidden = true;
    $('signin').hidden = true;
    $('reader').hidden = true;
    $('review').hidden = true;
    $('printing').hidden = false;
    $('printing').scrollIntoView({ behavior: 'smooth', block: 'start' });
    clearTimeout(pollTimer);
    poll();
  }

  function finish(data) {
    cancelAnimationFrame(frame);
    clearTimeout(pollTimer);
    store.drop(BOOK_KEY);
    if (data.status === 'done' && data.book) {
      openReader(data);
      showReview(data.id);
    } else {
      $('printingTitle').textContent = 'Oh no, the beans didn’t grow';
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
          watch(data.id);
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
    $('printingTitle').textContent = 'Binding your book…';
    await preload(bookEl);
    $('printing').hidden = true;
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

  function turn(step) {
    const next = Math.max(0, Math.min(leaves.length - 1, current + step));
    if (next === current) return;
    const leaf = leaves[step > 0 ? current : next];
    turningLeaf = leaf;
    leaf.classList.add('turning');
    current = next;
    showPage();
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
  async function showReview(id) {
    $('review').hidden = false;
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
        // One review per person: answering here replaces what they said about an earlier book.
        $('reviewAlready').textContent = review.book_id === id ? ''
          : `You already answered for an earlier book (reference ${review.book_id}). It’s one review per person, so sending these replaces those answers.`;
        $('reviewAlready').hidden = review.book_id === id;
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
      $('reviewError').hidden = true;
      $('reviewThanks').hidden = false;
      $('reviewAlready').hidden = true;
      $('reviewBtn').textContent = 'Update my answers';
    } catch (err) {
      $('reviewError').textContent = err.message.startsWith('Failed') ? 'We couldn’t reach the book. Try again in a moment.' : err.message;
      $('reviewError').hidden = false;
    } finally {
      updateReviewReady();
    }
  });

  function startOver() {
    clearTimeout(pollTimer);
    cancelAnimationFrame(frame);
    history.replaceState(null, '', location.pathname);
    store.drop(BOOK_KEY);
    $('printing').hidden = true;
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
    tryPassword(savedPassword, false).then((ok) => { if (ok !== true) store.drop(PASSWORD_KEY); }).catch(() => {});
  } else {
    pwField.focus({ preventScroll: true });
  }
  if (fromHash || savedBook) watch(fromHash || savedBook);
})();
