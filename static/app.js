(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('form'), drop = $('drop'), preview = $('preview'), go = $('go'), error = $('error');
  const resultsWrap = $('resultsWrap'), results = $('results'), timer = $('timer');
  const MAX_SIDE = 1600;

  let photo = null;      // Blob that will be uploaded
  let scenes = [...document.querySelectorAll('.scene-pick:not(.scene-both) strong')]
    .map((el) => ({ caption: el.textContent, description: '' }));

  fetch('/api/options').then((r) => r.json()).then((o) => {
    scenes = o.scenes;
    document.querySelectorAll('.scene-desc[data-scene]').forEach((el) => {
      el.textContent = scenes[+el.dataset.scene].description;
    });
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

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!photo) return showError('Choose a photo first.');
    showError('');
    go.disabled = true;
    go.textContent = 'Drawing…';

    const cards = selectedScenes().map(card);
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
        const bytes = Uint8Array.from(atob(img.image_b64), (c) => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: 'image/png' });
        const el = Object.assign(document.createElement('img'), { src: URL.createObjectURL(blob), alt: img.caption });
        const fig = cards[i];
        fig.querySelector('.frame').replaceChildren(el);
        setCaption(fig, img);  // title is exactly the scene that was sent
        const btn = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-ghost', textContent: 'Save image' });
        btn.addEventListener('click', () => save(blob, `jack-scene-${i + 1}.png`));
        fig.querySelector('.actions').replaceChildren(btn);
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
  form.addEventListener('change', (e) => { if (e.target.name === 'which') updateButton(); });
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
