// Poll saved progress only. Keep open source details and scroll position intact.
async function updateProgress() {
  try {
    const response = await fetch(window.location.href, {cache: 'no-store'});
    if (!response.ok) throw new Error('Progress unavailable');
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    let focusedUpdate = false;
    page.querySelectorAll('[data-live]').forEach(updated => {
      const current = document.querySelector(`[data-live="${updated.dataset.live}"]`);
      if (current && current.contains(document.activeElement)) focusedUpdate = true;
      if (current && !current.contains(document.activeElement)) {
        if (current.innerHTML !== updated.innerHTML) current.replaceChildren(...updated.childNodes);
        if (updated.dataset.running) current.dataset.running = updated.dataset.running;
      }
    });
    if (focusedUpdate || page.querySelector('[data-running="yes"]')) setTimeout(updateProgress, 5000);
  } catch (_) {
    setTimeout(updateProgress, 10000);
  }
}
setTimeout(updateProgress, 5000);
