const editor = document.querySelector('[data-fields-editor]');
if (editor) {
  const rows = editor.querySelector('tbody');
  const template = document.querySelector('#new-field');
  document.querySelector('[data-add-field]').addEventListener('click', () => {
    if (rows.children.length >= 30) return;
    rows.append(template.content.cloneNode(true));
    rows.lastElementChild.querySelector('[name=label]').focus();
  });
  rows.addEventListener('click', event => {
    if (event.target.matches('[data-remove-field]')) event.target.closest('tr').remove();
  });
}
