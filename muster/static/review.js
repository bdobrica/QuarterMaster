/* Review writes only to local save routes. It never calls an AI provider. */
const rows = [...document.querySelectorAll('tr[data-open-url]')];
for (const row of rows) row.addEventListener('keydown', event => {
  if (event.target.matches('input,select,textarea,button,a')) return;
  if (!['ArrowUp', 'ArrowDown', 'Enter'].includes(event.key)) return;
  event.preventDefault();
  if (event.key === 'Enter') location.href = row.dataset.openUrl;
  else rows[Math.max(0, Math.min(rows.length - 1, rows.indexOf(row) + (event.key === 'ArrowDown' ? 1 : -1)))].focus();
});

const form = document.querySelector('#review-form');
if (form) {
  const feedback = document.querySelector('#save-state');
  const badge = document.querySelector('#review-state');
  const revision = form.elements.namedItem('revision');
  const key = form.dataset.reviewKey;
  const controls = [...form.querySelectorAll('[name^="value:"],[data-unknown],[name=notes],[name=exclusion_reason]')];
  const byName = new Map(controls.map(control => [control.name, control]));
  const recovery = document.querySelector('#draft-recovery');
  const conflictNotice = document.querySelector('#review-conflict');
  let version = 0, savedVersion = 0, timer, conflicted = false, leaving = false;
  let pending = Promise.resolve(true), recovered = null, recoveryPending = false;
  const labels = {needs_review: 'Needs review', reviewed: 'Reviewed', excluded: 'Excluded'};
  const entries = () => controls.map(control => ({name: control.name, value: control.value, checked: control.type === 'checkbox' ? control.checked : null}));
  const initial = JSON.stringify(entries());
  function show(text, error = false) {
    feedback.textContent = text;
    feedback.classList.toggle('error', error);
  }
  function journal() {
    try { localStorage.setItem(key, JSON.stringify({revision: Number(revision.value), entries: entries()})); }
    catch { show('Browser draft backup unavailable. Keep this page open until Saved appears.', true); }
  }
  function clearJournal(force = false) {
    try {
      const stored = JSON.parse(localStorage.getItem(key));
      // Finishing one tab's save must not erase another tab's different pending draft.
      if (force || !stored || JSON.stringify(stored.entries) === JSON.stringify(entries())) localStorage.removeItem(key);
    } catch {}
  }
  function syncUnknowns() {
    for (const control of controls.filter(control => control.dataset.unknown)) {
      byName.get('value:' + control.dataset.unknown).disabled = control.checked;
    }
  }
  function changed() {
    version++;
    syncUnknowns();
    journal();
    show('Unsaved changes');
    clearTimeout(timer);
    timer = setTimeout(() => run('autosave'), 650);
  }
  form.addEventListener('input', changed);
  form.addEventListener('change', event => {
    if (event.target.type === 'checkbox' || event.target.tagName === 'SELECT') changed();
  });

  async function write(action) {
    if (recoveryPending) { show('Choose Restore local draft or Use saved version first.', true); return false; }
    if (conflicted) { show('Reload to compare saved changes. Your local draft is kept.', true); return false; }
    if (action === 'autosave' && version === savedVersion) return true;
    while (true) {
      const stamp = version;
      const body = new URLSearchParams(new FormData(form));
      body.set('action', action);
      show('Saving…');
      let response, result;
      try {
        response = await fetch(form.getAttribute('action'), {method: 'POST', headers: {'Accept': 'application/json'}, body});
        result = await response.json().catch(() => ({message: response.status === 403 ? 'This form expired. Reload to recover your draft.' : 'Could not save. Your draft is kept in this browser.'}));
      } catch {
        journal();
        show('Not saved — connection interrupted. Your browser draft is kept; retry Save.', true);
        return false;
      }
      if (!response.ok) {
        journal();
        show(result.message || 'Could not save. Check your fields.', true);
        if (response.status === 409 || response.status === 403) {
          conflicted = true;
          conflictNotice.hidden = false;
        }
        if (result.field) byName.get('value:' + result.field)?.setAttribute('aria-invalid', 'true');
        return false;
      }
      revision.value = result.revision;
      savedVersion = stamp;
      badge.textContent = labels[result.status];
      badge.className = 'review-badge state-' + result.status;
      for (const control of controls) control.removeAttribute('aria-invalid');
      if (stamp !== version) { journal(); continue; }
      clearJournal();
      show('Saved');
      if (['previous', 'next', 'review_next', 'exclude', 'include'].includes(action)) {
        leaving = true;
        location.href = result.redirect;
      }
      return true;
    }
  }
  function run(action) {
    clearTimeout(timer);
    const job = pending.then(() => write(action), () => write(action));
    pending = job.catch(() => { journal(); show('Could not save. Your local draft is kept.', true); return false; });
    return pending;
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    run(event.submitter?.value || 'save');
  });
  document.addEventListener('click', async event => {
    const link = event.target.closest('a');
    if (!link || event.defaultPrevented || link.target === '_blank' || link.hasAttribute('download') || link.hash || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const target = new URL(link.href, location.href);
    if (target.origin !== location.origin) return;
    event.preventDefault();
    if (await run('save')) { leaving = true; location.href = target.href; }
  });
  document.querySelector('[data-reload-review]').addEventListener('click', () => { leaving = true; location.reload(); });

  try { recovered = JSON.parse(localStorage.getItem(key)); } catch {}
  function restore() {
    for (const entry of recovered.entries || []) {
      const control = byName.get(entry.name);
      if (!control) continue;
      control.value = entry.value;
      if (control.type === 'checkbox') control.checked = entry.checked === true;
    }
    recovery.hidden = true;
    recoveryPending = false;
    for (const control of controls) control.disabled = false;
    syncUnknowns();
    changed();
    show('Recovered browser draft — saving…');
  }
  if (recovered && Array.isArray(recovered.entries)) {
    if (JSON.stringify(recovered.entries) === initial) clearJournal();
    else if (recovered.revision === Number(revision.value)) restore();
    else {
      recoveryPending = true;
      recovery.hidden = false;
      for (const control of controls) control.disabled = true;
    }
  }
  document.querySelector('[data-restore-draft]').addEventListener('click', restore);
  document.querySelector('[data-discard-draft]').addEventListener('click', () => {
    clearJournal(true); recovery.hidden = true; recoveryPending = false;
    for (const control of controls) control.disabled = false;
    syncUnknowns();
  });
  window.addEventListener('online', () => { if (!conflicted && version !== savedVersion) run('autosave'); });
  window.addEventListener('beforeunload', event => {
    if (!leaving && version !== savedVersion) { journal(); event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pagehide', () => {
    if (version === savedVersion || conflicted) return;
    journal();
    const body = new URLSearchParams(new FormData(form));
    body.set('action', 'autosave');
    if (new TextEncoder().encode(body.toString()).length < 60000) {
      fetch(form.getAttribute('action'), {method: 'POST', headers: {'Accept': 'application/json'}, body, keepalive: true}).catch(() => {});
    }
  });

  const photos = [...document.querySelectorAll('[data-gallery-image]')];
  const main = document.querySelector('#gallery-main');
  const full = document.querySelector('#gallery-full');
  const caption = document.querySelector('#gallery-caption');
  let photoIndex = 0;
  function showPhoto(src, alt) {
    main.src = full.href = src;
    main.alt = alt || 'Retained source image';
    photoIndex = photos.findIndex(photo => new URL(photo.dataset.src, location.href).href === new URL(src, location.href).href);
    caption.textContent = photoIndex >= 0 ? `${photoIndex + 1} / ${photos.length}` : 'Screenshot';
    for (let index = 0; index < photos.length; index++) photos[index].classList.toggle('active', index === photoIndex);
  }
  function stepPhoto(step) {
    const index = photoIndex < 0 ? (step > 0 ? 0 : photos.length - 1) : (photoIndex + step + photos.length) % photos.length;
    showPhoto(photos[index].dataset.src, photos[index].dataset.alt);
  }
  for (const photo of photos) photo.addEventListener('click', () => showPhoto(photo.dataset.src, photo.dataset.alt));
  for (const button of document.querySelectorAll('[data-photo-step]')) button.addEventListener('click', () => stepPhoto(Number(button.dataset.photoStep)));
  for (const link of document.querySelectorAll('[data-show-image]')) link.addEventListener('click', event => {
    event.preventDefault(); showPhoto(link.href); document.querySelector('.review-source').scrollTop = 0;
  });
  for (const link of document.querySelectorAll('[data-open-sheet]')) link.addEventListener('click', event => {
    event.preventDefault();
    const details = document.querySelector('#spreadsheet-details details');
    if (details) { details.open = true; details.scrollIntoView({block: 'nearest'}); }
  });
  showPhoto(photos[0].dataset.src, photos[0].dataset.alt);
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && ['s', 'Enter'].includes(event.key)) {
      event.preventDefault();
      form.requestSubmit(form.querySelector(`[name=action][value=${event.key === 'Enter' ? 'review_next' : 'save'}]`));
    } else if (event.altKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      if (['ArrowUp', 'ArrowDown'].includes(event.key)) stepPhoto(event.key === 'ArrowDown' ? 1 : -1);
      else {
        const button = form.querySelector(`[name=action][value=${event.key === 'ArrowLeft' ? 'previous' : 'next'}]`);
        if (!button.disabled) form.requestSubmit(button);
      }
    } else if (event.key === 'Enter' && event.target.tagName === 'INPUT') {
      event.preventDefault(); form.requestSubmit(form.querySelector('[name=action][value=save]'));
    }
  });
}
