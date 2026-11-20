// Rack Change: drag a switch (SNMP or temporary), a server, a patch panel or
// a cable organizer by its header to another unit.
//
// The device keeps its cables (and an ODF its trunks): they are tied to the
// device and its ports, not to the unit. While dragging, the units it would take are lit green
// (free, or its own) or red (another device is there, or out of the rack);
// dropping on green saves through POST <data-move-url> {"rack_unit": top U}
// (blueprints/rack_equipment.py) and redraws the editor. Esc cancels.
//
// Mouse / pen: press on the header and move. Touch screens: hold a finger on
// the device (anywhere but its ports and buttons) for a moment (LONG_PRESS_MS)
// — a short swipe still scrolls the page — then move it; the label rides
// above the finger so it stays visible.
//
// The template marks what can move (templates/rack/_switch_*.html,
// data-move-*) and which device holds each unit (render_rack.html,
// .rack-row[data-unit][data-device]). Only on the editor (editable racks),
// so only for signed-in users.
(() => {
    'use strict';

    const t = (text, values) => (window.t ? window.t(text, values) : text);
    const tm = text => (window.tm ? window.tm(text) : text);

    const ROOT_SELECTOR = '#rack-change-root';
    const START_DISTANCE = 6;       // px the pointer moves before a drag starts (a click stays a click)
    const EDGE = 60;                // px near the window edge that scroll the page while dragging
    const SCROLL_STEP = 14;
    const LONG_PRESS_MS = 400;      // touch: hold this long on a header to pick the device up
    const TOUCH_SLOP = 10;          // px a finger may wander while holding (more = it is scrolling)

    let drag = null;
    let press = null;               // touch: a finger held on a header, not picked up yet

    function headerBottom() {
        const header = document.querySelector('header');
        return header ? header.getBoundingClientRect().bottom : 0;
    }

    function setStatus(text) {
        const box = document.getElementById('connection-status');
        if (box) box.textContent = text;
    }

    // The unit row under the pointer, in the same rack as the dragged switch.
    // Cable lines (an SVG over the rack) may be on top: look through them.
    function rowAt(x, y) {
        for (const element of document.elementsFromPoint(x, y)) {
            const row = element.closest && element.closest('.rack-row[data-unit]');
            if (row && drag.shell.contains(row)) return row;
        }
        return null;
    }

    function clearMarks() {
        if (!drag) return;
        drag.shell.querySelectorAll('.rack-move-target, .rack-move-invalid').forEach(row => {
            row.classList.remove('rack-move-target', 'rack-move-invalid');
        });
    }

    // The header is on the top unit: the row under the pointer becomes the new top unit.
    function aim(x, y) {
        clearMarks();
        const row = rowAt(x, y);
        drag.top = null;
        drag.valid = false;
        if (!row) {
            drag.ghostUnit.textContent = '';
            return;
        }

        const top = Number(row.dataset.unit);
        const units = Array.from({ length: drag.height }, (_, i) => top - i);
        const rows = units.map(unit => drag.shell.querySelector(`.rack-row[data-unit="${unit}"]`));
        const free = rows.every(r => r && (!r.dataset.device || r.dataset.device === drag.key));

        rows.forEach(r => { if (r) r.classList.add(free ? 'rack-move-target' : 'rack-move-invalid'); });
        drag.top = top;
        drag.valid = free;
        const label = drag.height > 1 ? `U${top - drag.height + 1}-U${top}` : `U${top}`;
        drag.ghostUnit.textContent = free ? `→ ${label}` : `${label}: ${t('occupied')}`;
        drag.ghost.classList.toggle('is-invalid', !free);
    }

    function placeGhost(x, y) {
        if (drag.touch) {
            // Above the finger, so the finger does not hide it.
            const width = drag.ghost.offsetWidth;
            drag.ghost.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, x - width / 2))}px`;
            drag.ghost.style.top = `${Math.max(headerBottom() + 4, y - 70)}px`;
            return;
        }
        drag.ghost.style.left = `${x + 14}px`;
        drag.ghost.style.top = `${y + 14}px`;
    }

    function start() {
        drag.started = true;
        drag.device.classList.add('is-moving');
        document.body.classList.add('rack-moving');

        const ghost = document.createElement('div');
        ghost.className = 'rack-move-ghost';
        const name = document.createElement('b');
        name.textContent = drag.name;
        const unit = document.createElement('span');
        ghost.append(name, unit);
        document.body.appendChild(ghost);
        drag.ghost = ghost;
        drag.ghostUnit = unit;
        drag.scrollTimer = window.setInterval(autoScroll, 16);
    }

    // Near the top (below the sticky header) or bottom of the window the page
    // scrolls; near the left / right edge the rack scrolls sideways when it is
    // wider than the screen (phones: .rack-main scrolls on its own).
    function autoScroll() {
        if (!drag || !drag.started) return;
        let step = 0;
        if (drag.y < headerBottom() + EDGE) step = -SCROLL_STEP;
        else if (drag.y > window.innerHeight - EDGE) step = SCROLL_STEP;
        let side = 0;
        const scroller = drag.device.closest('.rack-main');
        if (scroller && scroller.scrollWidth > scroller.clientWidth + 1) {
            const box = scroller.getBoundingClientRect();
            if (drag.x < box.left + EDGE / 2) side = -SCROLL_STEP;
            else if (drag.x > box.right - EDGE / 2) side = SCROLL_STEP;
        }
        if (!step && !side) return;
        if (step) window.scrollBy(0, step);
        if (side) scroller.scrollLeft += side;
        aim(drag.x, drag.y);
    }

    function finish() {
        if (!drag) return;
        clearMarks();
        window.clearInterval(drag.scrollTimer);
        if (drag.ghost) drag.ghost.remove();
        drag.device.classList.remove('is-moving');
        document.body.classList.remove('rack-moving');
        drag = null;
    }

    // A cable organizer has no ports: no word about cables for it.
    function hasCables(device) {
        return !String(device.dataset.moveKey || '').startsWith('cable_organizer-');
    }

    async function save(device, top, name) {
        let message = '';
        try {
            const response = await fetch(device.dataset.moveUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ rack_unit: top }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
            message = hasCables(device)
                ? t('{name} moved to U{unit}; its cables stay connected.', { name, unit: top })
                : t('{name} moved to U{unit}.', { name, unit: top });
        } catch (error) {
            window.alert(t('{name} was not moved: {message}', { name, message: tm(error.message) }));
        }
        // Redraw the editor in place (as after any other change), then say what happened.
        const url = new URL(window.location.href);
        url.searchParams.delete('error');
        if (window.htmx && document.querySelector(ROOT_SELECTOR)) {
            await window.htmx.ajax('GET', url.pathname + url.search, { target: ROOT_SELECTOR, select: ROOT_SELECTOR, swap: 'outerHTML' });
            if (message) window.setTimeout(() => setStatus(message), 50);
        } else {
            window.location.reload();
        }
    }

    // The device whose header was pressed, or null (not a header, a button in it, not the editor).
    // anywhere: a finger may hold any part of the device but its ports — on a phone
    // the rack is shrunk to the screen width and the header is only a few pixels high.
    function deviceOf(target, anywhere = false) {
        const header = target && target.closest && target.closest('.rack-device-header');
        const device = anywhere
            ? target && target.closest && target.closest('[data-move-url]')
            : header && header.closest('[data-move-url]');
        const root = document.querySelector(ROOT_SELECTOR);
        if (!device || !root || !root.contains(device)) return null;
        // Buttons in the header (Remove, Ports 1 / 2, the server's ⚙️) stay buttons.
        if (target.closest('button, a, input, select, textarea, form, .rack-port, [onclick]')) return null;
        return device;
    }

    function begin(device, x, y, touch) {
        drag = {
            device,
            touch,
            shell: device.closest('[data-rack-component]') || document,
            key: device.dataset.moveKey,
            name: device.dataset.moveName || '',
            from: Number(device.dataset.moveTop),
            height: Math.max(1, Number(device.dataset.moveHeight) || 1),
            startX: x,
            startY: y,
            x,
            y,
            started: false,
        };
    }

    function drop() {
        if (!drag) return;
        const { started, valid, top, from, device, name } = drag;
        finish();
        if (!started) return;                      // a plain click on the header
        if (valid && top !== null && top !== from) save(device, top, name);
    }

    // ---------------- Mouse and pen ----------------

    document.addEventListener('pointerdown', event => {
        if (event.pointerType === 'touch' || event.button !== 0 || drag) return;
        const device = deviceOf(event.target);
        if (device) begin(device, event.clientX, event.clientY, false);
    });

    document.addEventListener('pointermove', event => {
        if (!drag || drag.touch || event.pointerType === 'touch') return;
        drag.x = event.clientX;
        drag.y = event.clientY;
        if (!drag.started) {
            if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) < START_DISTANCE) return;
            start();
        }
        event.preventDefault();
        placeGhost(drag.x, drag.y);
        aim(drag.x, drag.y);
    });

    document.addEventListener('pointerup', event => {
        if (!drag || drag.touch || event.pointerType === 'touch') return;
        drop();
    });

    document.addEventListener('pointercancel', event => {
        if (drag && !drag.touch && event.pointerType !== 'touch') finish();
    });

    // ---------------- Touch: hold, then move ----------------

    function cancelPress() {
        if (!press) return;
        window.clearTimeout(press.timer);
        press.device.classList.remove('is-pressing');
        press = null;
    }

    document.addEventListener('touchstart', event => {
        cancelPress();
        if (drag || event.touches.length !== 1) return;
        const device = deviceOf(event.target, true);
        if (!device) return;
        const touch = event.touches[0];
        device.classList.add('is-pressing');
        press = {
            device,
            x: touch.clientX,
            y: touch.clientY,
            timer: window.setTimeout(() => {
                const held = press;
                cancelPress();
                begin(held.device, held.x, held.y, true);
                start();
                placeGhost(held.x, held.y);
                aim(held.x, held.y);
                if (navigator.vibrate) navigator.vibrate(15);     // "picked up"
            }, LONG_PRESS_MS),
        };
    }, { passive: true });

    // Not passive: once a device is picked up, the finger moves it instead of scrolling the page.
    document.addEventListener('touchmove', event => {
        const touch = event.touches[0];
        if (press) {
            if (!touch || Math.hypot(touch.clientX - press.x, touch.clientY - press.y) > TOUCH_SLOP) cancelPress();   // scrolling
            return;
        }
        if (!drag || !drag.touch || !touch) return;
        event.preventDefault();
        drag.x = touch.clientX;
        drag.y = touch.clientY;
        placeGhost(drag.x, drag.y);
        aim(drag.x, drag.y);
    }, { passive: false });

    document.addEventListener('touchend', event => {
        if (press) {
            cancelPress();                         // a tap: nothing to do
            return;
        }
        if (drag && drag.touch) {
            event.preventDefault();                // no click on what was under the finger
            drop();
        }
    }, { passive: false });

    document.addEventListener('touchcancel', () => {
        cancelPress();
        if (drag && drag.touch) finish();
    });

    // A long press opens the context menu / selects text on phones: not on a header being held.
    document.addEventListener('contextmenu', event => {
        if (press || (drag && drag.touch)) event.preventDefault();
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && drag && drag.started) finish();
    });

    // The editor is redrawn by htmx: a drag in progress belongs to the old page.
    document.addEventListener('htmx:beforeSwap', () => {
        cancelPress();
        finish();
    });

    // A hint on every header that can be dragged (again after each redraw).
    function markHandles() {
        const touchScreen = window.matchMedia('(hover: none), (pointer: coarse)').matches;
        document.querySelectorAll(`${ROOT_SELECTOR} [data-move-url] > .rack-device-header`).forEach(header => {
            header.title = touchScreen
                ? t('Hold, then drag to another unit')
                : (hasCables(header.parentElement)
                    ? t('Drag to another unit; the cables stay connected')
                    : t('Drag to another unit'));
        });
    }
    document.addEventListener('DOMContentLoaded', markHandles);
    document.addEventListener('htmx:afterSettle', markHandles);
})();
