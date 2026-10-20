(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('form'), drop = $('drop'), preview = $('preview'), go = $('go'), error = $('error');
  const resultsWrap = $('resultsWrap'), results = $('results'), timer = $('timer');
  const MAX_SIDE = 1600;

  let photo = null;      // Blob that will be uploaded
  let scenes = [...document.querySelectorAll('.scene-pick:not(.scene-both) strong')]
    .map((el) => ({ caption: el.textContent, description: '' }));

  // Scenes are written for Jack; Jane swaps the name, the same way the server does.
  const hero = () => new FormData(form).get('hero');
  const cast = (text) => (hero() === 'jane' ? text.replaceAll('Jack', 'Jane') : text);
  const castScene = (s) => ({ caption: cast(s.caption), description: cast(s.description) });

  function renderScenePicks() {
    document.querySelectorAll('.scene-pick:not(.scene-both) strong').forEach((el, i) => {
      if (scenes[i]) el.textContent = cast(scenes[i].caption);
    });
    document.querySelectorAll('.scene-desc[data-scene]').forEach((el) => {
      el.textContent = cast(scenes[+el.dataset.scene].description);
    });
  }

  fetch('/api/options').then((r) => r.json()).then((o) => {
    scenes = o.scenes;
    renderScenePicks();
    $('mockBadge').hidden = !o.mock;
  }).catch(() => {});

  // Shrink big phone photos before upload (faster on mobile data). If the browser can't
  // decode the file (e.g. HEIC in Chrome on Windows), upload it as-is: the server converts it.
  async function downscale(file) {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
      const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.9));
      return blob ? { blob, url: URL.createObjectURL(blob) } : { blob: file, url: null };
    } catch {
      return { blob: file, url: null };
    }
  }

  async function setFile(file) {
    if (!file) return;
    showError('');
    const { blob, url } = await downscale(file);
    photo = blob;
    if (url) {
      preview.src = url;
      preview.hidden = false;
      drop.classList.add('has-photo');
    } else {
      preview.hidden = true;
      drop.classList.remove('has-photo');
      drop.querySelector('.drop-title').textContent = `Selected: ${file.name}`;
    }
    go.disabled = false;
  }

  function showError(msg) {
    error.textContent = msg;
    error.hidden = !msg;
  }

  // Selfie: phones open the front camera through the file input; computers use the webcam.
  const camera = $('camera'), video = $('cameraVideo'), cameraError = $('cameraError');
  let stream = null;

  function stopCamera() {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    if (camera.open) camera.close();
  }

  $('selfieBtn').addEventListener('click', async () => {
    if (matchMedia('(pointer: coarse)').matches || !navigator.mediaDevices?.getUserMedia) {
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
      cameraError.textContent = 'We could not open your camera. Allow camera access, or choose a photo instead.';
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

  function setCaption(fig, scene) {
    const cap = fig.querySelector('figcaption');
    cap.replaceChildren(
      Object.assign(document.createElement('span'), { className: 'cap-title', textContent: scene.caption }),
      Object.assign(document.createElement('span'), { className: 'cap-desc', textContent: scene.description }),
    );
  }

  function selectedScenes() {
    const which = new FormData(form).get('which');
    return which === 'both' ? scenes : [scenes[+which - 1]];
  }

  function card(scene) {
    const fig = document.createElement('figure');
    fig.className = 'result';
    fig.innerHTML = '<div class="frame"><div class="skeleton"><div><div class="sprout">🌱</div>Drawing…</div></div></div><figcaption></figcaption><div class="actions"></div>';
    setCaption(fig, scene);
    return fig;
  }

  async function save(blob, name) {
    const file = new File([blob], name, { type: 'image/png' });
    // iPhone/iPad: the share sheet offers "Save Image" to Photos.
    if (navigator.canShare && navigator.canShare({ files: [file] }) && matchMedia('(pointer: coarse)').matches) {
      try { await navigator.share({ files: [file] }); return; } catch (e) { if (e.name === 'AbortError') return; }
    }
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  }

  function fill(fig, b64, alt, filename) {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: 'image/png' });
    const el = Object.assign(document.createElement('img'), { src: URL.createObjectURL(blob), alt });
    fig.querySelector('.frame').replaceChildren(el);
    const btn = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-ghost', textContent: 'Save image' });
    btn.addEventListener('click', () => save(blob, filename));
    fig.querySelector('.actions').replaceChildren(btn);
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!photo) return showError('Choose a photo first.');
    showError('');
    go.disabled = true;
    go.textContent = 'Drawing…';

    const cards = selectedScenes().map(castScene).map(card);
    results.replaceChildren(...cards);
    resultsWrap.hidden = false;
    $('again').hidden = true;
    resultsWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const started = Date.now();
    const tick = setInterval(() => { timer.textContent = `${Math.round((Date.now() - started) / 1000)}s · usually under a minute`; }, 1000);

    const body = new FormData(form);  // style + strength radios; file inputs are unnamed
    body.append('photo', photo, photo.name || 'photo.jpg');

    try {
      const res = await fetch('/api/generate', { method: 'POST', body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Something went wrong (${res.status}).`);
      data.images.forEach((img, i) => {
        fill(cards[i], img.image_b64, img.caption, `${hero()}-scene-${i + 1}.png`);
        setCaption(cards[i], img);  // title is exactly the scene that was sent
      });
      timer.textContent = `Done in ${Math.round((Date.now() - started) / 1000)}s`;
    } catch (err) {
      resultsWrap.hidden = true;
      showError(err.message === 'Failed to fetch' ? 'Network problem. Check your connection and try again.' : err.message);
      form.scrollIntoView({ behavior: 'smooth' });
    } finally {
      clearInterval(tick);
      $('again').hidden = false;
      go.disabled = false;
      updateButton();
    }
  });

  function updateButton() {
    go.textContent = selectedScenes().length === 2 ? 'Make my 2 scenes' : 'Make my scene';
  }
  form.addEventListener('change', (e) => {
    if (e.target.name === 'which') updateButton();
    if (e.target.name === 'hero') renderScenePicks();
  });
  updateButton();

  $('again').addEventListener('click', () => {
    photo = null;
    preview.hidden = true;
    drop.classList.remove('has-photo');
    drop.querySelector('.drop-title').textContent = 'Drop a photo here';
    resultsWrap.hidden = true;
    go.disabled = true;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
})();
