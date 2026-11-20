// Home page: search suggestions while typing and example searches.
(() => {
    'use strict';

    const t = (text, values) => (window.t ? window.t(text, values) : text);

    const DELAY = 200;          // ms after the last key press
    const MIN_LENGTH = 2;

    function setupSuggestions(form) {
        const input = form.querySelector('input[name="search"]');
        const list = form.querySelector('.home-suggest');
        const url = form.dataset.suggestUrl;
        if (!input || !list || !url) return;

        let timer = null;
        let controller = null;
        let items = [];
        let active = -1;

        function close() {
            list.hidden = true;
            list.replaceChildren();
            input.setAttribute('aria-expanded', 'false');
            items = [];
            active = -1;
        }

        function highlight(index) {
            const options = list.querySelectorAll('[role="option"]');
            options.forEach((option, i) => option.classList.toggle('is-active', i === index));
            active = index;
            if (options[index]) options[index].scrollIntoView({ block: 'nearest' });
        }

        function render(data) {
            list.replaceChildren();
            items = data.items || [];
            active = -1;
            if (!items.length) {
                const empty = document.createElement('div');
                empty.className = 'home-suggest-empty';
                empty.textContent = t('Nothing quick found — press Enter to search everywhere');
                list.append(empty);
            }
            items.forEach((item, index) => {
                const option = document.createElement('a');
                option.className = 'home-suggest-item';
                option.href = item.href;
                option.setAttribute('role', 'option');
                option.addEventListener('mouseenter', () => highlight(index));

                const kind = document.createElement('span');
                kind.className = 'home-suggest-kind';
                kind.textContent = item.kind;
                const label = document.createElement('span');
                label.className = 'home-suggest-label';
                label.textContent = item.label;
                option.append(kind, label);
                if (item.detail) {
                    const detail = document.createElement('span');
                    detail.className = 'home-suggest-detail';
                    detail.textContent = item.detail;
                    option.append(detail);
                }
                list.append(option);
            });
            if (data.all) {
                const all = document.createElement('a');
                all.className = 'home-suggest-all';
                all.href = data.all;
                all.textContent = t('All results for “{q}” →', { q: data.query });
                list.append(all);
            }
            list.hidden = false;
            input.setAttribute('aria-expanded', 'true');
        }

        async function load() {
            const query = input.value.trim();
            if (query.length < MIN_LENGTH) {
                close();
                return;
            }
            if (controller) controller.abort();
            controller = new AbortController();
            try {
                const response = await fetch(`${url}?q=${encodeURIComponent(query)}`, {
                    headers: { Accept: 'application/json' },
                    signal: controller.signal,
                });
                if (!response.ok) return;
                const data = await response.json();
                if (input.value.trim() === query) render(data);
            } catch (error) {
                if (error.name !== 'AbortError') close();
            }
        }

        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(load, DELAY);
        });

        input.addEventListener('keydown', event => {
            if (list.hidden) return;
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                highlight(Math.min(active + 1, items.length - 1));
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                highlight(Math.max(active - 1, -1));
            } else if (event.key === 'Enter' && active >= 0 && items[active]) {
                event.preventDefault();
                window.location.href = items[active].href;
            } else if (event.key === 'Escape') {
                close();
            }
        });

        document.addEventListener('click', event => {
            if (!form.contains(event.target)) close();
        });
        input.addEventListener('focus', () => {
            if (input.value.trim().length >= MIN_LENGTH && list.hidden) load();
        });

        return { input, load };
    }

    function init() {
        const form = document.querySelector('.home-search');
        const search = form ? setupSuggestions(form) : null;

        // Example chips fill the box and show the suggestions.
        document.querySelectorAll('.home-examples [data-example]').forEach(button => {
            button.addEventListener('click', () => {
                if (!search) return;
                search.input.value = button.dataset.example;
                search.input.focus();
                search.load();
            });
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
