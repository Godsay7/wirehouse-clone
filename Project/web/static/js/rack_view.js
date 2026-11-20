// Rack View board: room switch, drag & drop rack slots, rack detail popup, cable drawing.
//
// The board lives in #rack-view-root. It is refreshed in place (htmx) when
// rack or inventory data changes, after "Reset rack order" and when another
// room is selected. init() runs on page load and after every swap; listeners
// on window/document are registered only once.
(() => {

    // Interface language (static/js/i18n.js); plain text if it is not loaded.
    const t = (text, values) => (window.t ? window.t(text, values) : text);
    const tn = (one, many, n, values) => (window.tn ? window.tn(one, many, n, values) : (n === 1 ? one : many).replace('{n}', n));
    const tm = text => (window.tm ? window.tm(text) : text);
    const ROOT_ID = 'rack-view-root';
    const ROOT_SELECTOR = `#${ROOT_ID}`;

    // Functions of the currently initialised board (used by global listeners).
    let current = null;

    // Zoom of an opened (expanded) rack; the same for every rack, remembered
    // in the browser. 1 = natural size.
    const DETAIL_ZOOM_KEY = 'switch-inventory-rack-detail-zoom';
    const DETAIL_ZOOM_MIN = 0.25;
    const DETAIL_ZOOM_MAX = 3;
    const DETAIL_ZOOM_STEP = 1.25;
    let detailZoom = 1;
    // "Port menu" on (touch screens): tapping a port in an opened rack shows
    // its details and cable path, since phones have no hover or right click.
    let portMenuMode = false;
    try {
        const saved = Number(localStorage.getItem(DETAIL_ZOOM_KEY));
        if (Number.isFinite(saved) && saved > 0) detailZoom = saved;
    } catch (_error) { }

    function refreshBoard(url) {
        return htmx.ajax('GET', url || (window.location.pathname + window.location.search), {
            target: ROOT_SELECTOR,
            select: ROOT_SELECTOR,
            swap: 'outerHTML',
        });
    }

    function init() {
    if (!document.getElementById(ROOT_ID)) return;

    const roomSelector = document.getElementById('rack-view-room-selector');
    const board = document.querySelector('[data-rack-board]');
    const resetLayoutButton = document.getElementById('rack-view-reset-layout');
    const toggleEmptyButton = document.getElementById('rack-view-toggle-empty');
    const detailBackdrop = document.getElementById('rack-detail-backdrop');

    function refreshSlotClasses() {
        if (!board) return;
        board.querySelectorAll('[data-rack-slot]').forEach(slot => {
            const occupied = Boolean(slot.querySelector('[data-rack-card]'));
            slot.classList.toggle('is-occupied', occupied);
            slot.classList.toggle('is-empty', !occupied);
        });
    }

    function updateBoardDensity() {
        if (!board) return;

        const defaultColumns = Math.max(1, Number(board.dataset.slotColumns || 6));
        const slots = Array.from(board.querySelectorAll('[data-rack-slot]'));
        const emptyHidden = board.classList.contains('hide-empty-slots');

        // Always clear the compact-mode placement first. The persistent slot
        // index remains untouched; these styles only control visual placement.
        slots.forEach(slot => {
            slot.classList.remove('compact-visible-empty');
            slot.style.removeProperty('grid-row');
            slot.style.removeProperty('grid-column');
        });

        // Custom board: only some positions exist. Keep each rack in its row
        // (position // columns) and pack the row from the left; rows with no
        // positions disappear. Narrow screens just flow the slots.
        if (board.dataset.layout === 'custom') {
            if (window.innerWidth <= 1199) {
                board.style.setProperty('--rack-active-columns', window.innerWidth <= 720 ? '2' : '3');
                return;
            }
            const rows = new Map();
            slots.forEach(slot => {
                const rowIndex = Math.floor(Number(slot.dataset.slotIndex || 0) / defaultColumns);
                if (!rows.has(rowIndex)) rows.set(rowIndex, []);
                rows.get(rowIndex).push(slot);
            });
            const rowList = Array.from(rows.keys()).sort((a, b) => a - b);
            const columns = Math.max(1, ...Array.from(rows.values()).map(rowSlots => rowSlots.length));
            board.style.setProperty('--rack-active-columns', String(columns));
            rowList.forEach((rowIndex, visualRow) => {
                rows.get(rowIndex)
                    .sort((a, b) => Number(a.dataset.slotIndex) - Number(b.dataset.slotIndex))
                    .forEach((slot, columnIndex) => {
                        slot.style.gridRow = String(visualRow + 1);
                        slot.style.gridColumn = String(columnIndex + 1);
                    });
            });
            return;
        }

        if (!emptyHidden) {
            const responsiveColumns = window.innerWidth <= 720
                ? 2
                : (window.innerWidth <= 1199 ? 3 : defaultColumns);
            board.style.setProperty('--rack-active-columns', String(responsiveColumns));
            return;
        }

        // Compact each original 6-slot row independently. Racks never jump
        // from row 2 into row 1 just because empty positions are hidden.
        const rows = new Map();
        slots.forEach(slot => {
            const slotIndex = Number(slot.dataset.slotIndex || 0);
            const rowIndex = Math.floor(slotIndex / defaultColumns);
            if (!rows.has(rowIndex)) rows.set(rowIndex, []);
            rows.get(rowIndex).push(slot);
        });

        const occupiedRowIndexes = Array.from(rows.entries())
            .filter(([, rowSlots]) => rowSlots.some(slot => slot.querySelector('[data-rack-card]')))
            .map(([rowIndex]) => rowIndex);

        const lastOccupiedRow = occupiedRowIndexes.length
            ? Math.max(...occupiedRowIndexes)
            : 0;

        let maxRackCountInRow = 1;
        for (let rowIndex = 0; rowIndex <= lastOccupiedRow; rowIndex += 1) {
            const rowSlots = rows.get(rowIndex) || [];
            const rackCount = rowSlots.filter(slot => slot.querySelector('[data-rack-card]')).length;
            maxRackCountInRow = Math.max(maxRackCountInRow, rackCount);
        }

        board.style.setProperty('--rack-active-columns', String(maxRackCountInRow));

        for (let rowIndex = 0; rowIndex <= lastOccupiedRow; rowIndex += 1) {
            const rowSlots = rows.get(rowIndex) || [];
            const occupiedSlots = rowSlots.filter(slot => slot.querySelector('[data-rack-card]'));
            const emptySlots = rowSlots.filter(slot => !slot.querySelector('[data-rack-card]'));
            const fillersNeeded = Math.max(0, maxRackCountInRow - occupiedSlots.length);
            const visibleFillers = emptySlots.slice(0, fillersNeeded);
            const visibleSlots = [...occupiedSlots, ...visibleFillers];

            visibleSlots.forEach((slot, columnIndex) => {
                slot.style.gridRow = String(rowIndex + 1);
                slot.style.gridColumn = String(columnIndex + 1);
                if (!slot.querySelector('[data-rack-card]')) {
                    slot.classList.add('compact-visible-empty');
                }
            });
        }
    }

    function setEmptySlotsHidden(hidden, persist = true) {
        if (!board) return;

        board.classList.toggle('hide-empty-slots', Boolean(hidden));
        if (toggleEmptyButton) {
            toggleEmptyButton.textContent = hidden ? t('Show empty slots') : t('Hide empty slots');
            toggleEmptyButton.setAttribute('aria-pressed', hidden ? 'true' : 'false');
        }

        updateBoardDensity();

        if (persist) {
            try {
                localStorage.setItem(
                    `switch-inventory-rack-hide-empty-${board.dataset.roomId || 0}`,
                    hidden ? '1' : '0'
                );
            } catch (_error) { }
        }

        requestAnimationFrame(() => {
            redrawVisibleRacks();
            setTimeout(redrawVisibleRacks, 100);
        });
    }

    function openRackDetail(card) {
        if (!card || card.classList.contains('is-expanded')) return;

        const opened = document.querySelector('[data-rack-card].is-expanded');
        if (opened && opened !== card) closeRackDetail(opened);

        card.classList.add('is-expanded');
        document.body.classList.add('rack-view-detail-open');
        if (detailBackdrop) detailBackdrop.setAttribute('aria-hidden', 'false');

        requestAnimationFrame(() => {
            // Detail view must keep the rack at its natural geometry so the
            // body has real scrollable overflow. The board view is zoomed to
            // fit cards, but the expanded view intentionally is not.
            // Nothing of the board drawing may stay: the stretched rows, the
            // card's minimum height (the tallest rack of the board) and the
            // cable layer sized for the stretched rack would make the opened
            // window scroll far below the rack (fitExpandedRack clears them).
            fitExpandedRack(card);
            const panel = card.querySelector('[data-rack-side-panel]:not([hidden])');
            const body = card.querySelector('.rack-dashboard-card-body');
            updateZoomLabel(card);

            if (body) {
                body.scrollTop = 0;
                body.scrollLeft = 0;
            }

            requestAnimationFrame(() => {
                if (panel) drawConnections(panel);
            });
            setTimeout(() => {
                if (panel) drawConnections(panel);
            }, 100);
        });
    }

    // ------------------------------------------------------------
    // Zoom of the opened rack
    // ------------------------------------------------------------

    // The expanded view's CSS forces its zoom (zoom: var(--rack-detail-zoom)),
    // so the value goes into that variable as well as the inline style.
    function setDetailZoom(scaleNode, zoom) {
        scaleNode.style.zoom = String(zoom);
        scaleNode.style.setProperty('--rack-detail-zoom', String(zoom));
        scaleNode.dataset.rackZoom = String(zoom);
    }

    function updateZoomLabel(card) {
        const label = card && card.querySelector('.rack-detail-zoom-level');
        if (label) label.textContent = `${Math.round(detailZoom * 100)}%`;
    }

    // action: 'in' | 'out' | 'reset' | 'fit' | a number (new zoom).
    // The point at (clientX, clientY), or the middle of the view, stays put.
    function zoomDetail(action, clientX, clientY) {
        const card = document.querySelector('[data-rack-card].is-expanded');
        if (!card) return;

        const panel = card.querySelector('[data-rack-side-panel]:not([hidden])');
        const scaleNode = panel && panel.querySelector('.rack-preview-scale');
        const body = card.querySelector('.rack-dashboard-card-body');
        if (!scaleNode || !body) return;

        const oldZoom = Number(scaleNode.dataset.rackZoom) || 1;
        let zoom = detailZoom;
        if (action === 'in') zoom = detailZoom * DETAIL_ZOOM_STEP;
        else if (action === 'out') zoom = detailZoom / DETAIL_ZOOM_STEP;
        else if (action === 'reset') zoom = 1;
        else if (action === 'fit') {
            const shell = scaleNode.querySelector('.rack-visual-shell');
            const naturalWidth = (shell ? shell.offsetWidth : scaleNode.scrollWidth) || 1;
            const padding = element => {
                const style = element ? getComputedStyle(element) : null;
                return style ? parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) : 0;
            };
            const available = body.clientWidth - padding(body) - padding(panel.querySelector('.rack-preview-stage'));
            // A little margin so rounding never leaves a horizontal scrollbar.
            zoom = (available - 4) / naturalWidth;
        } else if (typeof action === 'number') zoom = action;

        zoom = Math.min(DETAIL_ZOOM_MAX, Math.max(DETAIL_ZOOM_MIN, zoom));
        detailZoom = zoom;
        try { localStorage.setItem(DETAIL_ZOOM_KEY, String(zoom)); } catch (_error) { }

        const box = body.getBoundingClientRect();
        const anchorX = (clientX === undefined ? box.left + body.clientWidth / 2 : clientX) - box.left;
        const anchorY = (clientY === undefined ? box.top + body.clientHeight / 2 : clientY) - box.top;
        const contentX = (body.scrollLeft + anchorX) / oldZoom;
        const contentY = (body.scrollTop + anchorY) / oldZoom;

        setDetailZoom(scaleNode, zoom);
        body.scrollLeft = contentX * zoom - anchorX;
        body.scrollTop = contentY * zoom - anchorY;
        updateZoomLabel(card);

        requestAnimationFrame(() => drawConnections(panel));
    }

    function closeRackDetail(card = null) {
        card = card || document.querySelector('[data-rack-card].is-expanded');
        if (!card) return;

        card.classList.remove('is-expanded');
        document.body.classList.remove('rack-view-detail-open');
        if (detailBackdrop) detailBackdrop.setAttribute('aria-hidden', 'true');

        requestAnimationFrame(() => {
            redrawVisibleRacks();
            setTimeout(redrawVisibleRacks, 100);
        });
    }

    const DEFAULT_RACK_UNIT_HEIGHT = 58;

    function resetRackRowStretch(card) {
        if (!card) return;

        resetSideStretch(card);
    }

    // node: a card (both sides) or one side panel.
    function resetSideStretch(node) {
        node.querySelectorAll('.rack-row').forEach(row => {
            row.style.removeProperty('--rack-view-row-height');
        });

        node.querySelectorAll(
            '.c4900m-rack-device, .switch-placeholder-device, .server-device'
        ).forEach(device => {
            device.style.removeProperty('--rack-view-device-height');
        });
    }

    const TALL_DEVICES = '.c4900m-rack-device, .switch-placeholder-device, .server-device';

    // Row heights (CSS px) on the rows, and on every multi-U device the exact
    // sum of the rows it spans (they are absolutely positioned), so it fills
    // its units without moving its labels / ports out of place.
    function applyRowHeights(side, rowHeights) {
        side.rows.forEach((row, rowIndex) => {
            row.style.setProperty('--rack-view-row-height', `${rowHeights[rowIndex].toFixed(3)}px`);
        });
        side.devices.forEach(({ device, rowIndex, units }) => {
            const spanHeight = rowHeights
                .slice(rowIndex, rowIndex + units)
                .reduce((sum, value) => sum + value, 0);
            if (spanHeight > 0) device.style.setProperty('--rack-view-device-height', `${spanHeight.toFixed(3)}px`);
        });
    }

    function sideParts(card, panel) {
        const stage = panel.querySelector('.rack-preview-stage');
        const scaleNode = panel.querySelector('.rack-preview-scale');
        const frame = panel.querySelector('.rack-frame');
        if (!stage || !scaleNode || !frame) return null;
        const rows = Array.from(panel.querySelectorAll('.rack-row'));
        const devices = [];
        rows.forEach((row, rowIndex) => {
            row.querySelectorAll(TALL_DEVICES).forEach(device => devices.push({ device, rowIndex, units: 1 }));
        });
        return { card, panel, stage, scaleNode, frame, rows, devices, zoom: 1, heights: [] };
    }

    // The opened rack keeps its natural geometry and the detail zoom, so its
    // body has real scrollable overflow.
    function fitExpandedRack(card) {
        resetRackRowStretch(card);
        const body = card.querySelector('.rack-dashboard-card-body');
        if (body) body.style.removeProperty('min-height');
        const scaleNode = card.querySelector('[data-rack-side-panel]:not([hidden]) .rack-preview-scale');
        if (!scaleNode) return;
        const cableLayer = scaleNode.querySelector('.rack-connections-svg');
        if (cableLayer) {
            cableLayer.setAttribute('width', '0');
            cableLayer.setAttribute('height', '0');
        }
        setDetailZoom(scaleNode, detailZoom);
    }

    // Every rack of the board is zoomed to its card width and gets the height
    // of the tallest rack, each measured on its taller side (natural rows,
    // plus what the rows under tall devices grow by): all racks share one
    // scale, and turning a rack to its other side changes nothing for the
    // others. The shown side then fills its card: rows under tall devices
    // grow first, the rest is shared by every row.
    //
    // Done in phases — change every rack, then measure every rack, … — so the
    // browser lays the board out a few times per redraw, not once per rack and
    // measurement (that made a large room take about half a second).
    function redrawVisibleRacks() {
        const cards = Array.from(document.querySelectorAll('[data-rack-card]'));
        cards.filter(card => card.classList.contains('is-expanded')).forEach(fitExpandedRack);
        const board = cards.filter(card => !card.classList.contains('is-expanded'));
        const bodies = board.map(card => card.querySelector('.rack-dashboard-card-body')).filter(Boolean);

        // 1. Natural geometry, zoom 1, and both sides shown for measuring.
        const shown = new Map();
        const sides = [];
        board.forEach(card => {
            resetRackRowStretch(card);
            card.querySelectorAll('[data-rack-side-panel]').forEach(panel => {
                shown.set(panel, !panel.hidden);
                panel.hidden = false;
                const side = sideParts(card, panel);
                if (!side) return;
                side.scaleNode.style.zoom = '1';
                // The cable layer keeps the size of its last drawing; it would
                // make the rack measure too wide. drawConnections() sizes it again.
                const cableLayer = side.scaleNode.querySelector('.rack-connections-svg');
                if (cableLayer) {
                    cableLayer.setAttribute('width', '0');
                    cableLayer.setAttribute('height', '0');
                }
                sides.push(side);
            });
        });
        bodies.forEach(body => body.style.removeProperty('min-height'));

        // 2. Zoom that fits each card's width.
        sides.forEach(side => {
            // A narrower rack (data-rack-width) gets the zoom of a normal one: it
            // stays narrower on the board instead of being enlarged to the card.
            // Only its frame is narrower (the cable margins around it are not).
            const shell = side.scaleNode.querySelector('[data-rack-width]');
            const share = shell ? Math.max(0.2, Math.min(1, Number(shell.dataset.rackWidth) / 100)) : 1;
            let naturalWidth = Math.max(1, side.scaleNode.scrollWidth, side.scaleNode.getBoundingClientRect().width);
            if (share < 1) naturalWidth += side.frame.getBoundingClientRect().width * (1 / share - 1);
            const availableWidth = Math.max(1, side.stage.clientWidth - 2);
            side.zoom = Math.min(1, Math.max(0.12, availableWidth / naturalWidth));
            side.devices.forEach(item => {
                const units = parseInt(getComputedStyle(item.device).getPropertyValue('--rack-device-units'), 10);
                item.units = Number.isFinite(units) && units > 0 ? units : 1;
            });
        });
        // A narrower rack sits in a narrower position: its own fit would shrink
        // it. It takes the zoom of the normal racks instead (all share one scale).
        const normal = sides.filter(side => !side.scaleNode.querySelector('[data-rack-width]')).map(side => side.zoom);
        if (normal.length) {
            const common = Math.min(...normal);
            sides.forEach(side => {
                if (side.scaleNode.querySelector('[data-rack-width]')) side.zoom = common;
            });
        }
        sides.forEach(side => {
            side.scaleNode.style.zoom = String(side.zoom);
            side.scaleNode.dataset.rackZoom = String(side.zoom);
        });

        // 3. Natural height of every U (a populated U may be taller than an
        //    empty one: its ports need room).
        sides.forEach(side => {
            side.heights = side.rows.map(row => Math.max(
                DEFAULT_RACK_UNIT_HEIGHT,
                row.getBoundingClientRect().height / side.zoom
            ));
        });
        sides.forEach(side => applyRowHeights(side, side.heights));

        // 4. A multi-U device grows with its content (a 4900M with two
        //    modules needs more than 2 x 58px): its rows get the missing height.
        sides.forEach(side => {
            side.needs = side.devices.map(item => item.device.getBoundingClientRect().height / side.zoom);
        });
        sides.forEach(side => {
            side.devices.forEach((item, index) => {
                const spanned = side.heights.slice(item.rowIndex, item.rowIndex + item.units);
                const missing = side.needs[index] - spanned.reduce((sum, value) => sum + value, 0);
                if (missing <= 0.5) return;
                spanned.forEach((height, offset) => {
                    side.heights[item.rowIndex + offset] = height + missing / spanned.length;
                });
            });
            applyRowHeights(side, side.heights);
        });

        // 5. The height each side needs; the card body's padding on top of it.
        const needed = new Map();
        sides.forEach(side => {
            needed.set(side.card, Math.max(needed.get(side.card) || 0, side.scaleNode.getBoundingClientRect().height));
        });
        const chrome = new Map(board.map(card => {
            const body = card.querySelector('.rack-dashboard-card-body');
            if (!body) return [card, 0];
            const style = getComputedStyle(body);
            return [card, ['paddingTop', 'paddingBottom', 'borderTopWidth', 'borderBottomWidth']
                .reduce((sum, key) => sum + (parseFloat(style[key]) || 0), 0)];
        }));

        // 6. Back to the side each rack shows; every card as tall as the tallest.
        sides.forEach(side => {
            if (shown.get(side.panel)) return;
            side.panel.hidden = true;
            resetSideStretch(side.panel);
        });
        const visible = sides.filter(side => shown.get(side.panel));
        const tallest = Math.ceil(Math.max(0, ...board.map(card => (needed.get(card) || 0) + (chrome.get(card) || 0))));
        if (tallest > 0) bodies.forEach(body => { body.style.minHeight = `${tallest}px`; });

        // 7. The shown side fills its card: what is left is shared by every row.
        const fill = () => {
            const room = visible.map(side => Math.max(0, side.stage.clientHeight - side.frame.getBoundingClientRect().height));
            visible.forEach((side, index) => {
                if (room[index] < 0.5 || !side.rows.length) return;
                const extra = room[index] / side.zoom / side.rows.length;
                applyRowHeights(side, side.heights.map(height => height + extra));
            });
        };
        fill();

        // A rack that still comes out taller sets the height for all.
        const tallestShown = Math.max(0, ...bodies.map(body => body.getBoundingClientRect().height));
        if (tallest > 0 && tallestShown > tallest + 0.5) {
            bodies.forEach(body => { body.style.minHeight = `${Math.ceil(tallestShown)}px`; });
            visible.forEach(side => applyRowHeights(side, side.heights));
            fill();
        }

        // 8. Cables after the ports have moved.
        requestAnimationFrame(() => {
            cards.forEach(card => {
                const panel = card.querySelector('[data-rack-side-panel]:not([hidden])');
                if (panel) drawConnections(panel);
            });
        });

        // The board is shown once it has its final geometry (css/rack/rack-view.css):
        // the racks do not jump from their natural size to the zoomed one.
        const boardNode = document.querySelector('[data-rack-board]');
        if (boardNode) boardNode.classList.add('is-laid-out');
    }

    function afterRackMove() {
        refreshSlotClasses();
        updateBoardDensity();
        saveRackSlots();

        requestAnimationFrame(() => {
            redrawVisibleRacks();
            setTimeout(redrawVisibleRacks, 100);
        });
    }

    function setupRackDragAndDrop() {
        // Only a signed-in user may move racks (js/auth.js).
        if (!board || typeof Sortable === 'undefined' || !(window.WirehouseAuth && window.WirehouseAuth.canEdit())) return;

        board.querySelectorAll('[data-rack-slot]').forEach(slot => {
            Sortable.create(slot, {
                group: 'rack-dashboard-slots',
                draggable: '[data-rack-card]',
                handle: '[data-rack-drag-handle]',
                animation: 140,
                ghostClass: 'is-dragging',
                emptyInsertThreshold: 80,
                onChoose: () => {
                    document.body.classList.add('rack-dashboard-drag-active');
                },
                onUnchoose: () => {
                    document.body.classList.remove('rack-dashboard-drag-active');
                    board.querySelectorAll('[data-rack-slot]').forEach(item => {
                        item.classList.remove('is-drop-target');
                    });
                },
                onMove: event => {
                    if (event.to && event.to.matches('[data-rack-slot]')) {
                        board.querySelectorAll('[data-rack-slot]').forEach(item => {
                            item.classList.toggle('is-drop-target', item === event.to);
                        });
                    }
                    return true;
                },
                onAdd: event => {
                    const sourceSlot = event.from;
                    const targetSlot = event.to;
                    const movedCard = event.item;

                    // One position can hold exactly one rack. If the destination
                    // already had a rack, swap it back into the source position.
                    const displacedCard = Array.from(
                        targetSlot.querySelectorAll(':scope > [data-rack-card]')
                    ).find(card => card !== movedCard);

                    if (displacedCard && sourceSlot) {
                        sourceSlot.appendChild(displacedCard);
                    }

                    afterRackMove();
                },
            });
        });

        refreshSlotClasses();
    }

    if (roomSelector) {
        roomSelector.addEventListener('change', event => {
            const url = `/rack?room_id=${encodeURIComponent(event.target.value)}`;
            refreshBoard(url).then(() => window.history.pushState({}, '', url));
        });
    }

    function sideLabel(side) {
        return String(side || '').toLowerCase() === 'rear' ? t('Rear') : t('Front');
    }

    function formatLocation(roomName, rackName, side) {
        return [roomName, rackName, sideLabel(side)].filter(Boolean).join(' / ');
    }

    function parseConnections(panel) {
        const node = panel.querySelector('script[data-rack-connections]');
        if (!node) return [];
        try {
            return JSON.parse(node.textContent || '[]');
        } catch (_error) {
            return [];
        }
    }

    function remoteDescription(connection, localElementId) {
        if (localElementId === connection.endpoint_a_element_id) {
            return `${tm(connection.endpoint_b_label)} — ${tm(connection.endpoint_b_location)}`;
        }

        return `${tm(connection.endpoint_a_label)} — ${tm(connection.endpoint_a_location)}`;
    }

    function portMenuElement() {
        let menu = document.getElementById('rv-port-menu');
        if (!menu) {
            menu = document.createElement('div');
            menu.id = 'rv-port-menu';
            menu.hidden = true;
            document.body.appendChild(menu);
            document.addEventListener('click', event => {
                if (!menu.contains(event.target)) menu.hidden = true;
            });
            document.addEventListener('keydown', event => {
                if (event.key === 'Escape') menu.hidden = true;
            });
        }
        return menu;
    }

    // Details of one port (what the desktop shows as a hover tooltip) and,
    // for fibre, a button for its full cable path.
    function openPortMenu(element, connection) {
        const menu = portMenuElement();
        menu.replaceChildren();

        const lines = String(element.title || '').split('\n')
            .map(line => line.trim())
            .filter(line => line && line !== t('Right-click: show cable path'));
        const head = document.createElement('div');
        head.className = 'rv-port-menu-title';
        head.textContent = element.dataset.endpointLabel || lines.shift() || element.id;
        if (element.dataset.endpointLabel && lines[0] && element.dataset.endpointLabel.startsWith(lines[0])) lines.shift();
        menu.appendChild(head);

        lines.forEach(line => {
            const row = document.createElement('div');
            row.className = 'rv-port-menu-line';
            row.textContent = line;
            menu.appendChild(row);
        });
        if (!connection) {
            const row = document.createElement('div');
            row.className = 'rv-port-menu-line rv-port-menu-muted';
            row.textContent = t('Not connected');
            menu.appendChild(row);
        }

        if (window.CablePath && window.CablePath.canTrace(element)) {
            const pathButton = document.createElement('button');
            pathButton.type = 'button';
            pathButton.className = 'rv-port-menu-action';
            pathButton.textContent = t('Show Cable Path');
            pathButton.addEventListener('click', () => {
                menu.hidden = true;
                window.CablePath.open(element);
            });
            menu.appendChild(pathButton);
        }

        menu.hidden = false;
        const rect = element.getBoundingClientRect();
        const box = menu.getBoundingClientRect();
        const left = Math.min(Math.max(8, rect.left), window.innerWidth - box.width - 8);
        let top = rect.bottom + 6;
        if (top + box.height > window.innerHeight - 8) top = Math.max(8, rect.top - box.height - 6);
        menu.style.left = `${left}px`;
        menu.style.top = `${top}px`;
    }

    function syncPortMenuButtons() {
        document.querySelectorAll('[data-rv-port-menu]').forEach(button => {
            button.classList.toggle('active', portMenuMode);
            button.setAttribute('aria-pressed', String(portMenuMode));
        });
        document.body.classList.toggle('rv-port-menu-mode', portMenuMode);
    }

    function decorateRack(panel) {
        if (panel.dataset.decorated === '1') return;

        const shell = panel.querySelector('[data-rack-component]');
        if (!shell) return;

        const connections = parseConnections(panel);
        const connectionByElement = new Map();

        connections.forEach(connection => {
            connectionByElement.set(connection.endpoint_a_element_id, connection);
            connectionByElement.set(connection.endpoint_b_element_id, connection);

            [connection.endpoint_a_element_id, connection.endpoint_b_element_id].forEach(elementId => {
                const element = shell.querySelector(`#${elementId}`);
                if (!element) return;

                element.classList.add('connected', `connected-${connection.cable_type || 'ethernet'}`);
                element.dataset.connectionId = String(connection.id);

                if (!element.dataset.connectionTooltipAdded) {
                    element.title = `${element.title}\n${t('Connected to:')} ${remoteDescription(connection, elementId)}`;
                    element.dataset.connectionTooltipAdded = '1';
                }
            });
        });

        shell.querySelectorAll('.rack-port').forEach(element => {
            if (window.CablePath && window.CablePath.canTrace(element)) {
                element.title = `${element.title}\n${t('Right-click: show cable path')}`;
                element.addEventListener('contextmenu', event => {
                    event.preventDefault();
                    event.stopPropagation();
                    window.CablePath.open(element);
                });
            }

            element.addEventListener('click', event => {
                const card = element.closest('[data-rack-card]');
                if (!card || !card.classList.contains('is-expanded')) return;
                if (!portMenuMode) {
                    // Ports are connected in Rack Change: a visitor is asked to sign in first.
                    if (window.WirehouseAuth && !window.WirehouseAuth.canEdit()) {
                        window.WirehouseAuth.showLoginNotice(t('Sign in to connect ports and change racks'));
                    }
                    return;
                }
                event.stopPropagation();
                openPortMenu(element, connectionByElement.get(element.id));
            });

            const connection = connectionByElement.get(element.id);
            if (!connection) return;

            element.addEventListener('mouseenter', () => window.RackCables.highlight(shell, connection, true));
            element.addEventListener('mouseleave', () => window.RackCables.highlight(shell, connection, false));
        });

        panel.dataset.decorated = '1';
    }


    // Cable lines: static/js/rack_cables.js
    function drawConnections(panel) {
        const shell = panel.querySelector('[data-rack-component]');
        if (!shell || panel.hidden) return;
        window.RackCables.draw(shell, parseConnections(panel));
    }

    // One delayed redraw at a time: several requests within the delay
    // (a side switched twice, several cards set up) draw the board once.
    let redrawTimer = null;
    function scheduleRedraw(delay = 100) {
        clearTimeout(redrawTimer);
        redrawTimer = setTimeout(redrawVisibleRacks, delay);
    }

    // redraw = false: only show the side (the caller redraws the whole board once).
    function activateSide(card, side, redraw = true) {
        side = side === 'rear' ? 'rear' : 'front';

        card.querySelectorAll('[data-rack-side-button]').forEach(button => {
            const active = button.dataset.rackSideButton === side;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        card.querySelectorAll('[data-rack-side-panel]').forEach(panel => {
            panel.hidden = panel.dataset.rackSidePanel !== side;
        });

        const panel = card.querySelector(`[data-rack-side-panel="${side}"]`);
        if (!panel) return;

        const meta = card.querySelector('[data-rack-meta]');
        if (meta) {
            meta.textContent = `${card.dataset.rackUnits}U · ${sideLabel(side)} · ${tn('{n} connection', '{n} connections', parseConnections(panel).length)}`;
        }

        try {
            localStorage.setItem(`switch-inventory-rack-dashboard-side-${card.dataset.rackId}`, side);
        } catch (_error) { }

        decorateRack(panel);
        if (!redraw) return;
        // Right away, so the newly shown side is never seen unstretched.
        redrawVisibleRacks();
        scheduleRedraw();
    }

    function currentRackSlots() {
        if (!board) return [];

        return Array.from(board.querySelectorAll('[data-rack-slot]')).map(slot => {
            const card = slot.querySelector('[data-rack-card]');
            if (!card) return null;

            const rackId = Number(card.dataset.rackId);
            return Number.isFinite(rackId) ? rackId : null;
        });
    }

    async function saveRackSlots() {
        if (!board) return;
        try {
            const response = await fetch('/rack/layout/order', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    server_room_id: Number(board.dataset.roomId || 0),
                    slots: currentRackSlots(),
                    slot_positions: Array.from(board.querySelectorAll('[data-rack-slot]'))
                        .map(slot => Number(slot.dataset.slotIndex)),
                }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (error) {
            console.error(t('Unable to save Rack View slot layout:'), error);
        }
    }

    // Remove all empty positions / add one / remove one, then redraw the board.
    async function layoutAction(path, body) {
        if (!board) return;
        try {
            const response = await fetch(path, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ server_room_id: Number(board.dataset.roomId || 0), ...body }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
            await refreshBoard();
        } catch (error) {
            alert(error.message);
        }
    }

    const removeEmptyButton = document.getElementById('rack-view-remove-empty');
    if (removeEmptyButton) {
        removeEmptyButton.addEventListener('click', () => layoutAction('/rack/layout/remove-empty', {}));
    }

    const addSlotButton = document.getElementById('rack-view-add-slot');
    if (addSlotButton) {
        addSlotButton.addEventListener('click', () => layoutAction('/rack/layout/add-slot', {}));
    }

    if (board) {
        board.querySelectorAll('[data-remove-slot]').forEach(button => {
            button.addEventListener('click', event => {
                event.stopPropagation();
                const slot = button.closest('[data-rack-slot]');
                if (slot && slot.querySelector('[data-rack-card]')) return;
                layoutAction('/rack/layout/remove-slot', { position: Number(button.dataset.removeSlot) });
            });
        });
    }

    if (toggleEmptyButton && board) {
        let initialHidden = false;
        try {
            initialHidden = localStorage.getItem(
                `switch-inventory-rack-hide-empty-${board.dataset.roomId || 0}`
            ) === '1';
        } catch (_error) { }

        setEmptySlotsHidden(initialHidden, false);

        toggleEmptyButton.addEventListener('click', () => {
            setEmptySlotsHidden(!board.classList.contains('hide-empty-slots'));
        });
    } else {
        updateBoardDensity();
    }

    if (resetLayoutButton) {
        resetLayoutButton.addEventListener('click', async () => {
            if (!board) return;
            resetLayoutButton.disabled = true;

            try {
                const response = await fetch('/rack/layout/reset', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        server_room_id: Number(board.dataset.roomId || 0),
                    }),
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                refreshBoard();
            } catch (error) {
                console.error(t('Unable to reset Rack View order:'), error);
                resetLayoutButton.disabled = false;
            }
        });
    }

    setupRackDragAndDrop();
    syncPortMenuButtons();

    document.querySelectorAll('[data-rack-card]').forEach(card => {
        let initialSide = 'front';
        try {
            if (localStorage.getItem(`switch-inventory-rack-dashboard-side-${card.dataset.rackId}`) === 'rear') {
                initialSide = 'rear';
            }
        } catch (_error) { }

        card.querySelectorAll('[data-rack-side-button]').forEach(button => {
            button.addEventListener('click', event => {
                event.stopPropagation();
                activateSide(card, button.dataset.rackSideButton);
            });
        });

        const openArea = card.querySelector('[data-rack-open-detail]');
        if (openArea) {
            openArea.addEventListener('click', event => {
                if (event.target.closest('button, a, input, select, textarea, form')) return;
                openRackDetail(card);
            });
        }

        card.querySelectorAll('[data-rv-port-menu]').forEach(button => {
            button.addEventListener('click', event => {
                event.preventDefault();
                event.stopPropagation();
                portMenuMode = !portMenuMode;
                syncPortMenuButtons();
            });
        });

        // Only the buttons: the zoomed rack itself carries data-rack-zoom too
        // (its current zoom, see setDetailZoom).
        card.querySelectorAll('button[data-rack-zoom]').forEach(button => {
            button.addEventListener('click', event => {
                event.preventDefault();
                event.stopPropagation();
                zoomDetail(button.dataset.rackZoom);
            });
        });

        const detailBody = card.querySelector('.rack-dashboard-card-body');
        if (detailBody) {
            // Ctrl + wheel (or a touchpad pinch) zooms the opened rack around the pointer.
            detailBody.addEventListener('wheel', event => {
                if (!card.classList.contains('is-expanded') || !(event.ctrlKey || event.metaKey)) return;
                event.preventDefault();
                zoomDetail(detailZoom * Math.exp(-event.deltaY * 0.0025), event.clientX, event.clientY);
            }, { passive: false });
        }

        const closeButton = card.querySelector('[data-rack-close-detail]');
        if (closeButton) {
            closeButton.addEventListener('click', event => {
                event.preventDefault();
                event.stopPropagation();
                closeRackDetail(card);
            });
        }

        activateSide(card, initialSide, false);
    });

    // Every card has its side: draw the board once (not once per card).
    redrawVisibleRacks();
    scheduleRedraw();

    if (detailBackdrop) {
        detailBackdrop.addEventListener('click', () => closeRackDetail());
    }

    // Open one rack, its side and a port: /rack?room_id=..&open=<rack id>&side=rear&focus=<port id>
    // (links from the history, Check and search for visitors, see blueprints/rack_view.py).
    function openRackAt(rackId, side, focus) {
        const card = document.querySelector(`[data-rack-card][data-rack-id="${CSS.escape(String(rackId))}"]`);
        if (!card) return;
        side = side === 'rear' ? 'rear' : 'front';
        activateSide(card, side);
        openRackDetail(card);
        if (!focus) return;
        setTimeout(() => {
            const panel = card.querySelector(`[data-rack-side-panel="${side}"]`);
            const element = panel && panel.querySelector(`#${CSS.escape(focus)}`);
            if (!element) return;
            element.scrollIntoView({ block: 'center', inline: 'center' });
            element.classList.add('search-focus');
            setTimeout(() => element.classList.remove('search-focus'), 6000);
        }, 400);
    }

    current = { closeRackDetail, updateBoardDensity, redrawVisibleRacks, zoomDetail, openRackAt };
    }

    // ------------------------------------------------------------
    // Global listeners (registered once)
    // ------------------------------------------------------------

    document.addEventListener('keydown', event => {
        // Escape closes only the top window: the cable path dialog first.
        const cablePathOpen = document.querySelector('.cable-path-backdrop:not([hidden])');
        if (event.key === 'Escape' && current && !cablePathOpen) current.closeRackDetail();

        // + / − / 0 zoom the opened rack.
        if (!current || !document.querySelector('[data-rack-card].is-expanded')) return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.target.closest && event.target.closest('input, textarea, select')) return;
        if (event.key === '+' || event.key === '=') current.zoomDetail('in');
        else if (event.key === '-' || event.key === '_') current.zoomDetail('out');
        else if (event.key === '0') current.zoomDetail('reset');
    });

    let resizeTimer = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (!current) return;
            current.updateBoardDensity();
            current.redrawVisibleRacks();
        }, 80);
    });

    document.addEventListener('htmx:afterSettle', () => {
        if (!document.getElementById(ROOT_ID)) return;
        // The detail backdrop class lives on <body>, outside the swapped root.
        document.body.classList.remove('rack-view-detail-open', 'rack-dashboard-drag-active');
        init();
    });

    // New data: refresh the board unless the user is dragging a rack or
    // looking at one rack in detail (it refreshes after they close it).
    let refreshPending = false;

    function refreshIfIdle() {
        if (!document.getElementById(ROOT_ID)) return;

        const busy = document.body.classList.contains('rack-dashboard-drag-active')
            || document.querySelector('[data-rack-card].is-expanded');

        if (busy) {
            refreshPending = true;
            return;
        }

        refreshPending = false;
        refreshBoard();
    }

    document.addEventListener('rack-changed', refreshIfIdle);
    document.addEventListener('inventory-changed', refreshIfIdle);

    // Apply a postponed refresh once the detail view closes / drag ends.
    document.addEventListener('click', () => {
        if (refreshPending) setTimeout(refreshIfIdle, 300);
    });

    window.addEventListener('popstate', () => {
        if (document.getElementById(ROOT_ID)) refreshBoard();
    });

    document.addEventListener('DOMContentLoaded', init);

    // ?open=<rack id>: open that rack once, on page load (after init above).
    document.addEventListener('DOMContentLoaded', () => {
        const params = new URLSearchParams(window.location.search);
        const rackId = params.get('open');
        if (rackId && current) current.openRackAt(rackId, params.get('side'), params.get('focus'));
    });
})();
