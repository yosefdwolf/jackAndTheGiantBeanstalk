(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('form'), drop = $('drop'), preview = $('preview'), go = $('go'), error = $('error');
  const resultsWrap = $('resultsWrap'), timer = $('timer');
  const MAX_SIDE = 1600;
  const PDF_NAME = 'JackAndTheBeanstalk.pdf';
  const PASSWORD_KEY = 'beanstalk-password';

  let photo = null;      // Blob that will be uploaded
  let pdfUrl = null;

  fetch('/api/options').then((r) => r.json()).then((o) => {
    $('mockBadge').hidden = !o.mock;
  }).catch(() => {});

  // Remember the password on this device only, as a convenience. Never required to work.
  try { form.password.value = localStorage.getItem(PASSWORD_KEY) || ''; } catch {}

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

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!photo) return showError('Choose a photo first.');
    if (!form.name.value.trim()) return showError("Please enter the child's name.");
    if (!form.password.value) return showError('Enter the password to make a book.');
    showError('');
    go.disabled = true;
    go.textContent = 'Making your book…';

    $('bookReady').hidden = true;
    $('bookWorking').hidden = false;
    resultsWrap.hidden = false;
    $('again').hidden = true;
    resultsWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const started = Date.now();
    const tick = setInterval(() => { timer.textContent = `${Math.round((Date.now() - started) / 1000)}s · usually about a minute`; }, 1000);

    const body = new FormData(form);
    body.delete('password');  // sent as a header instead
    body.append('photo', photo, photo.name || 'photo.jpg');

    try {
      const res = await fetch('/api/book', { method: 'POST', body, headers: { 'X-App-Password': form.password.value } });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Something went wrong (${res.status}).`);
      }
      try { localStorage.setItem(PASSWORD_KEY, form.password.value); } catch {}
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
      pdfUrl = URL.createObjectURL(await res.blob());
      Object.assign($('download'), { href: pdfUrl, download: PDF_NAME });
      $('openPdf').href = pdfUrl;
      $('bookWorking').hidden = true;
      $('bookReady').hidden = false;
      timer.textContent = `Done in ${Math.round((Date.now() - started) / 1000)}s`;
    } catch (err) {
      resultsWrap.hidden = true;
      showError(err.message === 'Failed to fetch' ? 'Network problem. Check your connection and try again.' : err.message);
      form.scrollIntoView({ behavior: 'smooth' });
    } finally {
      clearInterval(tick);
      $('again').hidden = false;
      go.disabled = false;
      go.textContent = 'Make my book';
    }
  });

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
