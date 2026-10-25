// Storage stays UTC; presentation follows the browser's timezone.
function localizeTimes(root) {
  root.querySelectorAll('time[data-local-time]').forEach((element) => {
    const instant = new Date(element.dateTime);
    if (Number.isNaN(instant.getTime())) return;
    element.title = instant.toISOString();
    element.textContent = new Intl.DateTimeFormat(undefined, {
      day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
    }).format(instant);
  });
}
localizeTimes(document);
document.addEventListener('htmx:afterSwap', () => localizeTimes(document));
