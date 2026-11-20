// Table rows with data-href open that page when clicked anywhere on the row.
// The row also holds a real <a> (keyboard, middle click, "open in new tab");
// Ctrl / Cmd / Shift click on the row opens a new tab like a link would.
(() => {
    'use strict';

    document.addEventListener('click', event => {
        const row = event.target.closest('tr[data-href]');
        if (!row || event.button !== 0) return;
        if (event.target.closest('a, button, input, select, textarea, label')) return;
        if (window.getSelection && String(window.getSelection()).length) return;   // selecting text

        const url = row.dataset.href;
        if (event.ctrlKey || event.metaKey || event.shiftKey) {
            window.open(url, '_blank', 'noopener');
        } else {
            window.location.href = url;
        }
    });
})();
