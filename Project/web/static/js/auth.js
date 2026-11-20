// Sign-in in the browser (the server side is web/auth.py).
//
// Without signing in the site is read-only: <body data-auth="0">. Then
//   * buttons that only change data are not there: the templates leave them
//     out ({% if can_edit %}: Rack Change in the menu, Undo, Add / Delete in
//     Rack Change) or they are marked [data-requires-login] and hidden by
//     css/common/auth.css (Edit on maps, ✎, fix buttons on Check, …);
//   * should one still be clicked, and for any POST form, the action is
//     stopped and a notice "Sign in to make changes" with Sign in appears;
//   * a click on a port of an opened rack in Rack View shows the notice too;
//   * page scripts ask WirehouseAuth.ensure() before a change (port clicks
//     in Rack Change) and WirehouseAuth.canEdit() to switch off dragging;
//   * an answer 401 with X-Login-Required (e.g. the session ended in another
//     tab) shows the same notice.
(() => {
    'use strict';

    const t = (text, values) => (window.t ? window.t(text, values) : text);
    const NOTICE_MS = 8000;
    const OPEN_FORMS = ['/login', '/logout'];
    let notice = null;
    let hideTimer = null;

    function canEdit() {
        return Boolean(document.body) && document.body.dataset.auth === '1';
    }

    function loginUrl() {
        const next = window.location.pathname + window.location.search;
        return `/login?next=${encodeURIComponent(next)}`;
    }

    function hideNotice() {
        if (notice) notice.hidden = true;
    }

    function showLoginNotice(message) {
        if (!notice) {
            notice = document.createElement('div');
            notice.className = 'auth-notice';
            notice.setAttribute('role', 'alert');

            const text = document.createElement('span');
            text.className = 'auth-notice-text';

            const link = document.createElement('a');
            link.className = 'button auth-notice-login';
            link.textContent = t('Sign in');

            const close = document.createElement('button');
            close.type = 'button';
            close.className = 'auth-notice-close';
            close.setAttribute('aria-label', t('Close'));
            close.textContent = '×';
            close.addEventListener('click', hideNotice);

            notice.append(text, link, close);
            document.body.appendChild(notice);
        }
        notice.querySelector('.auth-notice-text').textContent = message || t('Sign in to make changes');
        notice.querySelector('.auth-notice-login').href = loginUrl();
        notice.hidden = false;
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hideNotice, NOTICE_MS);
    }

    // true when signed in; otherwise shows the notice and returns false.
    function ensure() {
        if (canEdit()) return true;
        showLoginNotice();
        return false;
    }

    window.WirehouseAuth = { canEdit, ensure, showLoginNotice };

    function stop(event) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
    }

    // Capture phase on window: runs before the page's own handlers (and htmx).
    window.addEventListener('click', event => {
        if (canEdit() || !event.target.closest) return;
        if (!event.target.closest('[data-requires-login]')) return;
        stop(event);
        showLoginNotice();
    }, true);

    window.addEventListener('submit', event => {
        if (canEdit()) return;
        const form = event.target;
        if (!form || (form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
        const action = new URL(form.action || window.location.href, window.location.href).pathname;
        if (OPEN_FORMS.includes(action)) return;
        stop(event);
        showLoginNotice();
    }, true);

    function loggedOut() {
        if (document.body) document.body.dataset.auth = '0';
        showLoginNotice(t('You are not signed in (any more). Sign in to make changes.'));
    }

    // Requests from page scripts.
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        if (response.status === 401 && response.headers.get('X-Login-Required')) loggedOut();
        return response;
    };

    // Requests from htmx (Rack Change forms).
    document.addEventListener('htmx:responseError', event => {
        const xhr = event.detail && event.detail.xhr;
        if (xhr && xhr.status === 401 && xhr.getResponseHeader('X-Login-Required')) loggedOut();
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') hideNotice();
    });
})();
