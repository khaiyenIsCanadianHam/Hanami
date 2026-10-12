/* Local-only enhancements. Business actions remain ordinary authenticated forms. */
(() => {
  'use strict';
  document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => history.back()));
  let theme = 'light';
  try { theme = localStorage.getItem('hanami-theme') || 'light'; } catch (_) { /* Storage is optional. */ }
  document.documentElement.dataset.theme = theme;
  const toggle = document.querySelector('[data-theme-toggle]');
  toggle?.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('hanami-theme', next); } catch (_) { /* Storage is optional. */ }
    toggle.setAttribute('aria-label', `Switch to ${next === 'dark' ? 'light' : 'dark'} mode`);
  });
  const sidebarToggle = document.querySelector('[data-toggle-sidebar]');
  function sidebar(open) {
    document.body.classList.toggle('sidebar-open', open);
    sidebarToggle?.setAttribute('aria-expanded', String(open));
  }
  sidebarToggle?.addEventListener('click', () => sidebar(!document.body.classList.contains('sidebar-open')));
  document.querySelector('[data-close-sidebar]')?.addEventListener('click', () => sidebar(false));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { sidebar(false); document.querySelectorAll('details[open]').forEach(item => item.open = false); }
    if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
      const search = document.querySelector('.global-search input');
      if (search) { event.preventDefault(); search.focus(); }
    }
  });
  document.querySelectorAll('.toast-dismiss').forEach(button => button.addEventListener('click', () => button.closest('.toast').remove()));
  document.querySelectorAll('table[data-sortable] th .sort-button').forEach(button => {
    button.addEventListener('click', () => {
      const th = button.closest('th');
      const table = th.closest('table');
      const index = Array.from(th.parentNode.children).indexOf(th);
      const ascending = th.getAttribute('aria-sort') !== 'ascending';
      table.querySelectorAll('th').forEach(header => header.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
      const rows = Array.from(table.tBodies[0].rows);
      rows.sort((left, right) => {
        const a = left.cells[index].textContent.trim();
        const b = right.cells[index].textContent.trim();
        return a.localeCompare(b, undefined, {numeric: true, sensitivity: 'base'}) * (ascending ? 1 : -1);
      });
      rows.forEach(row => table.tBodies[0].appendChild(row));
    });
  });
  const recordSearch = document.querySelector('[data-filter-records]');
  const recordTable = document.querySelector('[data-records-table]');
  if (recordSearch && recordTable) {
    const filterRecords = () => {
      const query = recordSearch.value.trim().toLocaleLowerCase();
      let visible = 0;
      Array.from(recordTable.tBodies[0].rows).forEach(row => {
        row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
        if (!row.hidden) visible += 1;
      });
      const count = document.querySelector('[data-records-count]');
      if (count) count.textContent = `${visible} records`;
      const empty = document.querySelector('[data-filter-empty]');
      if (empty) empty.hidden = visible > 0;
    };
    recordSearch.addEventListener('input', filterRecords);
    filterRecords();
  }
  const dialog = document.getElementById('confirm-dialog');
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (form.dataset.confirmed === 'true') return;
    event.preventDefault();
    if (!dialog || typeof dialog.showModal !== 'function') {
      if (window.confirm(form.dataset.confirm)) { form.dataset.confirmed = 'true'; form.requestSubmit(event.submitter); }
      return;
    }
    document.getElementById('confirm-message').textContent = form.dataset.confirm;
    const submitter = event.submitter;
    dialog.returnValue = 'cancel';
    dialog.addEventListener('close', () => {
      if (dialog.returnValue === 'confirm') { form.dataset.confirmed = 'true'; form.requestSubmit(submitter); }
    }, {once: true});
    dialog.showModal();
  }));
  document.querySelectorAll('form:not([method="get"]):not([method="dialog"])').forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      const button = event.submitter;
      if (button) { window.setTimeout(() => { button.disabled = true; button.setAttribute('aria-busy', 'true'); }, 0); }
    });
  });
})();
