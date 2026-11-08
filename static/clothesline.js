// The book "drying on a line": the pictures being drawn hang from clothespins, each filling with a wash
// of colour as it's drawn. When any picture finishes, the left-most page gets it (whichever page it is),
// blooms into colour, is unpinned onto the finished stack, the rest slide left and a fresh page is
// pinned on at the right. A picture that fails tears in two and falls away, a fresh page is pinned on,
// and its next try hangs there like any other. No art files: the string, pins and pages are drawn here.
//
//   const line = new Clothesline(el, { total: 21 });
//   line.update(images, fractionOf)   // every frame; images as /api/books/<ref> gives them
//
// Each image: {kind, page, status: waiting|drawing|done|failed, image_url, progress, label, attempt?, final?}
// (final: failed and won't be tried again)
(() => {
  'use strict';
  const reduce = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const T = (ms) => (reduce() ? 0 : ms);
  const sleep = (ms) => new Promise((r) => setTimeout(r, T(ms)));
  const keyOf = (img) => `${img.kind}-${img.page}`;
  const nameOf = (img) => (img.kind === 'hero_sheet' ? 'You' : `p. ${img.page}`);

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  const PIN = '<svg class="pin" viewBox="0 0 14 30" aria-hidden="true"><rect x="2" y="0" width="10" height="30" rx="3"/>' +
    '<rect x="6.2" y="2" width="1.6" height="26" rx=".8" class="pin-gap"/><circle cx="7" cy="12" r="2.2" class="pin-spring"/></svg>';

  class Clothesline {
    constructor(root, { total = 0 } = {}) {
      this.root = root;
      this.total = total;
      // 7 pictures are drawn at once; a wide screen shows all 7 pages, a narrower one 5, a phone 3.
      this.slots = window.innerWidth < 560 ? 3 : window.innerWidth < 1000 ? 5 : 7;
      this.status = new Map();   // key -> last status seen
      this.tries = new Map();    // key -> last try number seen
      this.queue = [];           // done / fail events, played one at a time
      this.busy = false;
      root.classList.add('clothesline');
      root.innerHTML = '';
      this.done = el('div', 'pile done-pile');
      this.doneStack = el('div', 'stack');
      this.doneCount = el('p', 'pile-count', `0 of ${total}`);
      this.done.append(this.doneStack, this.doneCount);
      const middle = el('div', 'line');
      middle.insertAdjacentHTML('beforeend', '<svg class="string" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">' +
        '<path d="M0 2 Q50 9 100 2" vector-effect="non-scaling-stroke"/></svg>');
      this.sheetsEl = el('div', 'sheets');
      middle.append(this.sheetsEl);
      root.append(this.done, middle);
      this.sheets = [];
      for (let i = 0; i < this.slots; i++) this.sheets.push(this.newSheet());
    }

    newSheet() {
      const s = { key: null, el: el('div', 'sheet blank') };
      s.el.innerHTML = PIN;
      const paper = el('div', 'paper');
      s.wash = el('div', 'wash');
      s.img = el('img');
      s.img.alt = '';
      s.num = el('span', 'num');
      paper.append(s.wash, s.img, s.num);
      s.line = el('p', 'sheet-line');
      s.el.append(paper, s.line);
      this.sheetsEl.append(s.el);
      return s;
    }

    update(images, fractionOf) {
      this.images = images;
      this.byKey = new Map(images.map((i) => [keyOf(i), i]));
      for (const img of images) {
        const k = keyOf(img), before = this.status.get(k);
        if (img.status !== before) {
          if (img.status === 'done' && before !== undefined) this.queue.push({ type: 'done', key: k });
          else if (img.status === 'done') this.addToDone(img, false);  // already finished when we started
          this.status.set(k, img.status);
        }
        // A new try means the last one failed: that page tears. (Watching the try number, not a "failed"
        // status, since the status is only "failed" for a moment between tries.)
        const tried = this.tries.get(k), now = img.attempt || 1;
        if (tried !== undefined && now > tried) this.queue.push({ type: 'fail', key: k });
        this.tries.set(k, now);
      }
      this.play();
      this.assign();
      this.trim();
      for (const s of this.sheets) this.paint(s, fractionOf);
      this.paintCount();
    }

    // Free pages on the line go to the pictures being drawn, then to the next ones waiting their turn.
    assign() {
      const onLine = new Set(this.sheets.map((s) => s.key).filter(Boolean));
      const free = (status) => this.images.filter((i) => i.status === status && !onLine.has(keyOf(i)));
      const hanging = [...free('drawing'), ...free('waiting')];
      for (const s of this.sheets) {
        if (!s.key && !s.flying && hanging.length) s.key = keyOf(hanging.shift());
      }
    }

    paint(s, fractionOf) {
      const img = s.key && this.byKey.get(s.key);
      s.el.classList.toggle('blank', !img);
      s.el.classList.toggle('waiting', !!img && img.status === 'waiting');
      if (!img) {  // nothing left to hang: the page fades back
        s.wash.style.height = '0%';
        s.num.textContent = '';
        s.line.textContent = '';
        return;
      }
      s.num.textContent = nameOf(img);
      if (img.status === 'waiting') {
        const hero = this.images.find((i) => i.kind === 'hero_sheet');
        s.line.textContent = hero && hero.status !== 'done' && img.kind !== 'hero_sheet' ? 'Waiting for your cartoon' : 'Up next';
        s.wash.style.height = '0%';
        return;
      }
      s.line.textContent = img.progress || '';
      if (img.status === 'drawing') s.wash.style.height = `${Math.min(97, fractionOf(img) * 100).toFixed(1)}%`;
      s.el.classList.toggle('retrying', (img.attempt || 1) > 1);
    }

    remaining() {  // pictures still to finish, counting ones that failed but will be tried again
      return (this.images || []).filter((i) => i.status !== 'done' && !(i.status === 'failed' && i.final)).length;
    }

    // Empty pages with nothing left to hang on them are taken down.
    trim() {
      for (const s of [...this.sheets]) {
        if (s.key || s.flying || this.sheets.length <= this.remaining()) continue;
        this.sheets = this.sheets.filter((x) => x !== s);
        if (T(1)) s.el.animate([{ opacity: 1 }, { opacity: 0, transform: 'translateY(-12px)' }], { duration: 300 })
          .finished.then(() => s.el.remove(), () => s.el.remove());
        else s.el.remove();
      }
    }

    // True when no page is mid-animation (the caller decides when the book itself is finished).
    get idle() {
      return !this.busy && !this.queue.length;
    }

    async play() {
      if (this.busy || !this.queue.length) return;
      this.busy = true;
      while (this.queue.length) {
        const ev = this.queue.shift();
        const img = this.byKey.get(ev.key);
        if (!img) continue;
        if (ev.type === 'done') await this.finish(img);
        else await this.fail(img);
      }
      this.busy = false;
      this.assign();
    }

    // The left-most page gets the finished picture, whichever page it was, then goes to the stack.
    async finish(img) {
      const k = keyOf(img);
      let s = this.sheets.find((x) => x.key === k);
      const first = this.sheets[0];
      if (s !== first) {  // swap places, so the left-most page is always the one that finishes
        const displaced = first.key;
        first.key = k;
        if (s) s.key = displaced;
        else if (displaced) { const free = this.sheets.find((x) => !x.key); if (free) free.key = displaced; }
        s = first;
      }
      s.el.classList.remove('blank', 'waiting');
      s.num.textContent = nameOf(img);
      s.line.textContent = img.progress || '';
      if (img.image_url) {
        s.img.src = `${img.image_url}${img.image_url.includes('?') ? '&' : '?'}w=360`;
        if (s.img.decode) await s.img.decode().catch(() => {});
      }
      s.flying = true;
      s.wash.style.height = '100%';
      s.el.classList.add('bloom');
      await sleep(450);
      await this.unpin(s, this.doneStack);
      this.addToDone(img, true);
    }

    // A failed picture: its page tears in two, the halves fall away, and a fresh page is pinned on.
    async fail(img) {
      const s = this.sheets.find((x) => x.key === keyOf(img));
      if (!s) return;
      s.flying = true;
      s.el.classList.add('torn');
      if (T(1)) {
        const paper = s.el.querySelector('.paper'), r = paper.getBoundingClientRect();
        const halves = ['polygon(0 0, 55% 0, 42% 30%, 58% 55%, 40% 80%, 52% 100%, 0 100%)',
          'polygon(55% 0, 100% 0, 100% 100%, 52% 100%, 40% 80%, 58% 55%, 42% 30%)'].map((clip, i) => {
          const half = paper.cloneNode(true);
          Object.assign(half.style, { position: 'fixed', left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`,
            height: `${r.height}px`, margin: 0, clipPath: clip, zIndex: 50, pointerEvents: 'none' });
          document.body.append(half);
          return half.animate([{ transform: 'none', opacity: 1 },
            { transform: `translate(${i ? 22 : -22}px, 90px) rotate(${i ? 18 : -18}deg)`, opacity: 0 }],
          { duration: 700, easing: 'cubic-bezier(.4,0,.8,.6)' }).finished.then(() => half.remove(), () => half.remove());
        });
        paper.style.visibility = 'hidden';
        await Promise.all(halves);
      }
      await this.unpin(s, null);
    }

    // Take a page off the line (flying onto the stack if there's a target), slide the rest left, and
    // pin a fresh page on at the right.
    async unpin(s, target) {
      const from = s.el.getBoundingClientRect(), to = target && target.getBoundingClientRect();
      const others = this.sheets.filter((x) => x !== s);
      const before = new Map(others.map((x) => [x, x.el.getBoundingClientRect()]));
      if (T(1) && to) {
        await s.el.animate([
          { transform: 'translate(0,0) rotate(0)' },
          { transform: `translate(0,-14px) rotate(-6deg)`, offset: 0.25 },
          { transform: `translate(${to.left + to.width / 2 - (from.left + from.width / 2)}px, ${to.top - from.top}px) rotate(-14deg) scale(.55)`, opacity: 0.9 },
        ], { duration: 520, easing: 'cubic-bezier(.5,0,.3,1)' }).finished.catch(() => {});
      }
      s.el.remove();
      this.sheets = others;
      for (const x of others) {
        const b = before.get(x), a = x.el.getBoundingClientRect();
        if (T(1) && b.left !== a.left) x.el.animate([{ transform: `translateX(${b.left - a.left}px)` }, { transform: 'none' }],
          { duration: 300, easing: 'ease-out' });
      }
      // A fresh page only while there are more pictures to come than pages left on the line, so near the
      // end the line just empties out.
      if (this.sheets.length >= this.remaining()) { await sleep(150); return; }
      const fresh = this.newSheet();
      this.sheets.push(fresh);
      if (T(1)) fresh.el.animate([{ transform: 'translateY(-40px)', opacity: 0 }, { transform: 'none', opacity: 1 }],
        { duration: 420, easing: 'cubic-bezier(.3,1.4,.5,1)' });
      await sleep(150);
    }

    paintCount() {  // the real number finished, even while their pages are still flying to the stack
      const n = (this.images || []).filter((i) => i.status === 'done').length;
      this.doneCount.textContent = `${n} of ${this.total}`;
    }

    addToDone(img, animate) {
      const card = el('div', 'stacked');
      if (img.image_url) {
        const pic = el('img');
        pic.src = `${img.image_url}${img.image_url.includes('?') ? '&' : '?'}w=240`;
        pic.alt = img.label || '';
        card.append(pic);
      }
      const n = this.doneStack.children.length;
      card.style.setProperty('--tilt', `${((n * 37) % 9) - 4}deg`);
      this.doneStack.append(card);
      while (this.doneStack.children.length > 4) this.doneStack.firstChild.remove();  // only the top few show
      this.paintCount();
      if (animate && T(1)) card.animate([{ transform: 'translateY(-10px) rotate(var(--tilt))' }, { transform: 'rotate(var(--tilt))' }], { duration: 220 });
    }

  }

  window.Clothesline = Clothesline;
})();
