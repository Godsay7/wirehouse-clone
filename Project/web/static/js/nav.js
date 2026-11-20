// Main menu: the Switches / Racks lists open on hover (CSS); the titles
// themselves are not clickable. Only on touch screens (no hover) a tap on the
// title opens / closes its list.
(() => {
    'use strict';

    const canHover = window.matchMedia('(hover: hover)');

    function closeAll(except) {
        document.querySelectorAll('[data-nav-group].open').forEach(group => {
            if (group === except) return;
            group.classList.remove('open');
            const toggle = group.querySelector('[data-nav-toggle]');
            if (toggle) toggle.setAttribute('aria-expanded', 'false');
        });
    }

    document.addEventListener('click', event => {
        const toggle = event.target.closest('[data-nav-toggle]');
        if (!toggle) {
            if (!event.target.closest('[data-nav-group]')) closeAll(null);
            return;
        }
        if (canHover.matches) {
            event.preventDefault();
            return;
        }
        const group = toggle.closest('[data-nav-group]');
        const open = !group.classList.contains('open');
        closeAll(group);
        group.classList.toggle('open', open);
        toggle.setAttribute('aria-expanded', String(open));
        // :focus-within keeps a list open; let a second tap really close it.
        if (!open) toggle.blur();
    });

    // With a mouse a click must not focus the title: :focus-within would
    // keep its list open after the pointer leaves, like a pressed toggle.
    // The keyboard (Tab) still focuses it and opens the list.
    document.addEventListener('mousedown', event => {
        if (canHover.matches && event.target.closest('[data-nav-toggle]')) event.preventDefault();
    });

    // Phones: the whole menu folds behind the ☰ button in the header.
    function setMenuOpen(open) {
        const header = document.querySelector('header');
        const burger = document.querySelector('[data-nav-burger]');
        if (!header || !burger) return;
        header.classList.toggle('nav-open', open);
        burger.setAttribute('aria-expanded', String(open));
    }

    document.addEventListener('click', event => {
        if (event.target.closest('[data-nav-burger]')) {
            setMenuOpen(!document.querySelector('header').classList.contains('nav-open'));
        } else if (event.target.closest('.main-nav a')) {
            setMenuOpen(false);
        }
    });

    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        closeAll(null);
        setMenuOpen(false);
    });

    // The header sticks to the top of the window (css/common/base.css). Its
    // height (one row on a wide screen, two on a phone) goes to
    // --header-height, so sticky panels and #anchor jumps stay below it.
    function measureHeader() {
        const header = document.querySelector('header');
        if (header) document.documentElement.style.setProperty('--header-height', `${header.offsetHeight}px`);
    }

    document.addEventListener('DOMContentLoaded', () => {
        measureHeader();
        const header = document.querySelector('header');
        if (header && window.ResizeObserver) new ResizeObserver(measureHeader).observe(header);
    });
})();
