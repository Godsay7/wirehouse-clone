// Live updates without full page reloads.
//
// Every page carries the data versions it was rendered with
// (<body data-inventory-version data-rack-version data-maps-version>).
// This script polls /api/version and, when a counter grows, fires
// "inventory-changed", "rack-changed" or "maps-changed" on <body>.
// Page regions subscribe with htmx, e.g.
//
//   <div id="x" hx-get="..." hx-trigger="inventory-changed from:body"
//        hx-select="#x" hx-swap="outerHTML">
//
// so only those regions are re-rendered. Swapped content may contain a
// [data-versions] marker, which moves the baseline forward (this avoids a
// second refresh right after our own changes).
(() => {
    'use strict';

    const POLL_INTERVAL_MS = 20000;
    const KEYS = ['inventory', 'rack', 'maps'];
    const versions = {};

    function readVersions(element) {
        if (!element) return;
        KEYS.forEach(key => {
            const value = Number(element.dataset[`${key}Version`]);
            if (Number.isFinite(value)) {
                versions[key] = Math.max(versions[key] || 0, value);
            }
        });
    }

    async function poll() {
        if (document.hidden) return;

        let data;
        try {
            const response = await fetch('/api/version', { cache: 'no-store' });
            if (!response.ok) return;
            data = await response.json();
        } catch (_error) {
            return; // Server restarting or network hiccup: try again later.
        }

        KEYS.forEach(key => {
            const value = Number(data[key]);
            if (!Number.isFinite(value) || value <= (versions[key] || 0)) return;

            versions[key] = value;
            htmx.trigger(document.body, `${key}-changed`, { version: value });
        });
    }

    // --------------------------------------------------------
    // Search forms: [data-live-search] forms submit through htmx while the
    // user types; [data-search-clear] links empty the field instead of
    // reloading the page.
    // --------------------------------------------------------

    function syncClearLinks(form) {
        const input = form.querySelector('input[name="search"]');
        form.querySelectorAll('[data-search-clear][data-hide-when-empty]').forEach(link => {
            link.style.display = input && input.value.trim() ? '' : 'none';
        });
    }

    document.addEventListener('input', event => {
        const form = event.target.closest && event.target.closest('form[data-live-search]');
        if (form) syncClearLinks(form);
    });

    document.addEventListener('click', event => {
        const link = event.target.closest && event.target.closest('[data-search-clear]');
        if (!link) return;

        const form = link.closest('form[data-live-search]');
        const input = form && form.querySelector('input[name="search"]');
        if (!input) return;

        event.preventDefault();
        input.value = '';
        syncClearLinks(form);
        htmx.trigger(form, 'submit');
        input.focus();
    });

    document.addEventListener('DOMContentLoaded', () => {
        readVersions(document.body);
        document.querySelectorAll('form[data-live-search]').forEach(syncClearLinks);
        setInterval(poll, POLL_INTERVAL_MS);
    });

    document.addEventListener('htmx:afterSettle', () => {
        document.querySelectorAll('[data-versions]').forEach(readVersions);
        document.querySelectorAll('form[data-live-search]').forEach(syncClearLinks);
    });

    // Catch up immediately when the tab becomes visible again.
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) poll();
    });
})();
