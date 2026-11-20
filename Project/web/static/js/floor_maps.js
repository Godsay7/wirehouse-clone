// Floor Maps editor (templates/floor_maps.html).
//
// The map is an SVG in grid cells: rooms are polygons, workplaces are small
// squares coloured by PC role. View mode shows details on hover; Edit mode
// draws rooms (drag for a rectangle, or click corners and press Enter),
// places workplaces and moves/edits everything. Every change is saved at
// once through /floor-maps/api/...
(() => {
    'use strict';

    // Interface language (static/js/i18n.js); plain text if it is not loaded.
    const t = (text, values) => (window.t ? window.t(text, values) : text);
    const tn = (one, many, n, values) => (window.tn ? window.tn(one, many, n, values) : (n === 1 ? one : many).replace('{n}', n));
    const tm = text => (window.tm ? window.tm(text) : text);

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const ROOM_STEP = 0.5;
    const WORKPLACE_STEP = 0.25;
    const WORKPLACE_SIZE = 3;
    const LABEL_LINE_CHARS = 8;      // PC names wrap at _ - / . so neighbours do not overlap
    const LABEL_LINE_HEIGHT = 1.0;
    const CLOSE_DISTANCE = 0.75;
    const DRAG_THRESHOLD = 0.3;
    const NUDGE_STEP = 0.5;          // arrow key; Shift + arrow moves 4 cells
    const NUDGE_STEP_LARGE = 4;
    const NUDGE_SAVE_DELAY_MS = 400;
    const MODE_KEY = 'floorMaps.mode';
    const ZOOM_KEY = 'floorMaps.zoom.';   // + map id
    const ZOOM_MIN = 0.25;
    const ZOOM_MAX = 6;
    const ZOOM_STEP = 1.25;               // buttons and +/- keys

    // Distinct colours for PC roles; workplaces without a role are grey.
    const ROLE_COLORS = [
        '#4f80ff', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6',
        '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#64748b',
    ];
    const NO_ROLE_COLOR = '#cbd5e1';

    // What stands at a place. PCs are coloured by role; phones and Wi-Fi
    // points are smaller, have their own colour and a label to the right.
    const DEVICES = {
        pc: { label: t('PC'), nameLabel: t('PC name'), size: WORKPLACE_SIZE },
        phone: { label: t('Phone'), plural: t('Phones'), nameLabel: t('Number / name'), size: 2, color: '#475569' },
        wifi: { label: t('Wi-Fi AP'), plural: t('Wi-Fi APs'), nameLabel: t('AP name'), size: 2, color: '#0891b2' },
    };
    // Tools that draw an outline, and what they draw: a room (walls) or a
    // work area (see-through, dashed border).
    const DRAW_TOOLS = { room: 'room', area: 'area' };
    const ROOM_LABELS = { room: t('Room'), area: t('Work area') };
    // Tools that put something on the map, and what they put.
    const PLACE_TOOLS = { workplace: 'pc', phone: 'phone', wifi: 'wifi' };

    const state = {
        map: null,
        rooms: [],
        workplaces: [],
        roles: [],
        mode: 'view',
        tool: 'select',
        selected: null,       // { kind: 'room' | 'workplace', id }
        panel: 'item',        // 'item' | 'settings'
        draft: null,          // room being drawn: { points: [[x, y], ...] }
        pointer: null,        // active pointer gesture
        hover: null,          // [x, y] under the pointer while drawing
        search: '',
        refreshPending: false,
        undo: null,           // last deleted item, restored by Undo / Ctrl+Z
        nudge: null,          // arrow-key moves waiting to be saved
        zoom: 1,              // 1 = map as wide as the canvas
    };

    let svg, canvas, viewport, panel, tooltip, statusBox, searchCount;

    // ------------------------------------------------------------
    // Small helpers
    // ------------------------------------------------------------

    function el(tag, attrs = {}, text) {
        const node = document.createElement(tag);
        Object.entries(attrs).forEach(([key, value]) => {
            if (value === undefined || value === null || value === false) return;
            if (key === 'className') node.className = value;
            else node.setAttribute(key, value === true ? '' : value);
        });
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function svgEl(tag, attrs = {}, text) {
        const node = document.createElementNS(SVG_NS, tag);
        Object.entries(attrs).forEach(([key, value]) => {
            if (value !== undefined && value !== null) node.setAttribute(key, value);
        });
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function snap(value, step, limit) {
        return Math.min(Math.max(Math.round(value / step) * step, 0), limit);
    }

    function snapPoint(point, step) {
        return [snap(point[0], step, state.map.width), snap(point[1], step, state.map.height)];
    }

    function distance(a, b) {
        return Math.hypot(a[0] - b[0], a[1] - b[1]);
    }

    function pointInPolygon(x, y, points) {
        let inside = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
            const [xi, yi] = points[i];
            const [xj, yj] = points[j];
            if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
        }
        return inside;
    }

    function polygonCenter(points) {
        // Area-weighted centroid; falls back to the average for degenerate shapes.
        let area = 0, cx = 0, cy = 0;
        points.forEach((p, i) => {
            const q = points[(i + 1) % points.length];
            const cross = p[0] * q[1] - q[0] * p[1];
            area += cross;
            cx += (p[0] + q[0]) * cross;
            cy += (p[1] + q[1]) * cross;
        });
        if (Math.abs(area) < 1e-9) {
            const n = points.length;
            return [points.reduce((s, p) => s + p[0], 0) / n, points.reduce((s, p) => s + p[1], 0) / n];
        }
        return [cx / (3 * area), cy / (3 * area)];
    }

    // Room names go into the top-left corner, like labels on a floor plan,
    // so they do not cover the desks; the centre is the fallback.
    function roomLabelPoint(points) {
        const corner = points.reduce((best, p) => (p[1] < best[1] || (p[1] === best[1] && p[0] < best[0]) ? p : best));
        const label = [corner[0] + 0.6, corner[1] + 0.6];
        if (pointInPolygon(label[0], label[1], points)) return label;
        const [cx, cy] = polygonCenter(points);
        return [cx, cy];
    }

    // Split a PC name into short lines at _ - / . or spaces, never cutting it:
    // "ASB3_Avid-Playout" -> ["ASB3_", "Avid-", "Playout"].
    function wrapLabel(text, max = LABEL_LINE_CHARS) {
        const parts = text.trim().match(/[^_\-/.\s]+[_\-/.\s]*|[_\-/.\s]+/g) || [];
        const lines = [];
        let line = '';
        parts.forEach(part => {
            if (line && (line + part).trimEnd().length > max) {
                lines.push(line.trimEnd());
                line = '';
            }
            line += part;
        });
        if (line.trim()) lines.push(line.trimEnd());
        return lines;
    }

    function roleColor(role) {
        if (!role) return NO_ROLE_COLOR;
        const index = state.roles.findIndex(r => r.toLowerCase() === role.toLowerCase());
        return ROLE_COLORS[(index < 0 ? state.roles.length : index) % ROLE_COLORS.length];
    }

    function deviceOf(workplace) {
        return DEVICES[workplace.device_type] || DEVICES.pc;
    }

    function isPc(workplace) {
        return !workplace.device_type || workplace.device_type === 'pc';
    }

    function placeColor(workplace) {
        return isPc(workplace) ? roleColor(workplace.role) : deviceOf(workplace).color;
    }

    function isArea(room) {
        return room.room_type === 'area';
    }

    function roomLabel(room) {
        return ROOM_LABELS[room.room_type] || ROOM_LABELS.room;
    }

    function roomOf(workplace) {
        return state.rooms.find(room => !isArea(room) && pointInPolygon(workplace.x, workplace.y, room.points)) || null;
    }

    function areaOf(workplace) {
        return state.rooms.find(room => isArea(room) && pointInPolygon(workplace.x, workplace.y, room.points)) || null;
    }

    // Rooms and work areas are counted apart: an area is a zone inside a room.
    function outlineCounts() {
        const areas = state.rooms.filter(isArea).length;
        const rooms = state.rooms.length - areas;
        return [tn('{n} room', '{n} rooms', rooms), areas ? tn('{n} work area', '{n} work areas', areas) : ''].filter(Boolean).join(' · ');
    }

    // "Room" / "Work area in Studio 1": what an outline is, for its details and tooltip.
    function outlineKind(room) {
        if (!isArea(room)) return t('Room');
        const [cx, cy] = polygonCenter(room.points);
        const parent = state.rooms.find(other => !isArea(other) && pointInPolygon(cx, cy, other.points));
        return parent && parent.name ? t('Work area in {name}', { name: parent.name }) : t('Work area');
    }

    // What moves together with an outline: workplaces inside it and, for a
    // room, the work areas inside it.
    function contentsOf(room) {
        const workplaces = state.workplaces.filter(w => pointInPolygon(w.x, w.y, room.points));
        const areas = isArea(room) ? [] : state.rooms.filter(other => {
            if (other === room || !isArea(other)) return false;
            const [cx, cy] = polygonCenter(other.points);
            return pointInPolygon(cx, cy, room.points);
        });
        return { workplaces, areas };
    }

    function findItem(kind, id) {
        const list = kind === 'room' ? state.rooms : state.workplaces;
        return list.find(item => item.id === id) || null;
    }

    function selectedItem() {
        return state.selected ? findItem(state.selected.kind, state.selected.id) : null;
    }

    function matchesSearch(workplace) {
        if (!state.search) return true;
        const needle = state.search.toLowerCase();
        return [workplace.pc_name, workplace.ip, workplace.dante_ip, workplace.role, workplace.note, workplace.socket, workplace.dante_socket, isPc(workplace) ? '' : deviceOf(workplace).label]
            .some(value => String(value || '').toLowerCase().includes(needle));
    }

    function svgPoint(event) {
        const point = svg.createSVGPoint();
        point.x = event.clientX;
        point.y = event.clientY;
        const local = point.matrixTransform(svg.getScreenCTM().inverse());
        return [local.x, local.y];
    }

    let statusTimer = null;

    function setStatus(text, kind = 'info', action = null) {
        statusBox.replaceChildren();
        if (text) statusBox.append(el('span', {}, text));
        if (action) {
            const button = el('button', { type: 'button', className: 'fm-status-action' }, action.label);
            button.addEventListener('click', action.run);
            statusBox.append(button);
        }
        statusBox.dataset.kind = kind;
        statusBox.classList.toggle('is-visible', Boolean(text));
        statusBox.classList.toggle('has-action', Boolean(action));
        clearTimeout(statusTimer);
        if (text && kind !== 'error') statusTimer = setTimeout(() => setStatus(''), action ? 8000 : 2500);
    }

    async function api(method, url, body) {
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        let data = {};
        try { data = await response.json(); } catch (_error) { /* not JSON */ }
        if (!response.ok || !data.ok) throw new Error(tm(data.error) || `HTTP ${response.status}`);
        return data;
    }

    function readMode() {
        // Edit mode only for a signed-in user (js/auth.js).
        if (!(window.WirehouseAuth && window.WirehouseAuth.canEdit())) return 'view';
        try { return localStorage.getItem(MODE_KEY) === 'edit' ? 'edit' : 'view'; } catch (_e) { return 'view'; }
    }

    function saveMode(mode) {
        try { localStorage.setItem(MODE_KEY, mode); } catch (_e) { /* private window */ }
    }

    // ------------------------------------------------------------
    // Drawing
    // ------------------------------------------------------------

    function render() {
        const { width, height } = state.map;
        svg.setAttribute('viewBox', `-0.5 -0.5 ${width + 1} ${height + 1}`);
        svg.classList.toggle('is-editing', state.mode === 'edit');
        svg.dataset.tool = state.mode === 'edit' ? state.tool : 'view';
        svg.replaceChildren();

        const defs = svgEl('defs');
        const minor = svgEl('pattern', { id: 'fm-grid-minor', width: 1, height: 1, patternUnits: 'userSpaceOnUse' });
        minor.append(svgEl('path', { d: 'M 1 0 L 0 0 0 1', class: 'fm-grid-line' }));
        const major = svgEl('pattern', { id: 'fm-grid-major', width: 5, height: 5, patternUnits: 'userSpaceOnUse' });
        major.append(svgEl('rect', { width: 5, height: 5, fill: 'url(#fm-grid-minor)' }));
        major.append(svgEl('path', { d: 'M 5 0 L 0 0 0 5', class: 'fm-grid-line-major' }));
        defs.append(minor, major);
        svg.append(defs);

        svg.append(svgEl('rect', { x: 0, y: 0, width, height, class: 'fm-floor' }));
        svg.append(svgEl('rect', { x: 0, y: 0, width, height, class: 'fm-grid', fill: 'url(#fm-grid-major)' }));

        // Areas above rooms, so an area inside a room can be clicked.
        const roomsLayer = svgEl('g', { class: 'fm-rooms' });
        state.rooms.filter(room => !isArea(room)).forEach(room => roomsLayer.append(renderRoom(room)));
        state.rooms.filter(isArea).forEach(room => roomsLayer.append(renderRoom(room)));
        svg.append(roomsLayer);
        fitRoomNames(roomsLayer);

        const placesLayer = svgEl('g', { class: 'fm-workplaces' });
        state.workplaces.forEach(workplace => placesLayer.append(renderWorkplace(workplace)));
        svg.append(placesLayer);

        const selected = selectedItem();
        if (state.mode === 'edit' && state.selected && state.selected.kind === 'room' && selected) {
            svg.append(renderVertexHandles(selected));
        }

        renderDraft();
        renderSearchCount();

        const tabCount = document.querySelector('.fm-tab.is-active .fm-tab-count');
        if (tabCount) tabCount.textContent = String(state.workplaces.filter(isPc).length);
    }

    function renderRoom(room) {
        const isSelected = state.selected && state.selected.kind === 'room' && state.selected.id === room.id;
        const group = svgEl('g', {
            class: `fm-room${isArea(room) ? ' fm-area' : ''}${isSelected ? ' is-selected' : ''}`,
            'data-kind': 'room',
            'data-id': room.id,
        });
        group.append(svgEl('polygon', { points: room.points.map(p => p.join(',')).join(' '), class: 'fm-room-shape' }));

        if (room.name) {
            const [x, y] = roomLabelPoint(room.points);
            group.append(svgEl('text', { x, y, class: 'fm-room-name' }, room.name));
        }

        // Wide invisible lines on the sides: drag one to move that wall.
        if (state.mode === 'edit' && state.tool === 'select') {
            room.points.forEach((a, index) => {
                const b = room.points[(index + 1) % room.points.length];
                const direction = a[1] === b[1] ? 'horizontal' : (a[0] === b[0] ? 'vertical' : 'diagonal');
                group.append(svgEl('line', {
                    x1: a[0], y1: a[1], x2: b[0], y2: b[1],
                    class: `fm-edge fm-edge-${direction}`,
                    'data-kind': 'edge', 'data-id': room.id, 'data-index': index,
                }));
            });
        }
        return group;
    }

    // Shrink a room name that is wider than its room (e.g. "SOUNDBOX1" in a
    // narrow booth). Text can only be measured once it is in the document.
    function fitRoomNames(layer) {
        layer.querySelectorAll('.fm-room').forEach(group => {
            const text = group.querySelector('.fm-room-name');
            const shape = group.querySelector('.fm-room-shape');
            if (!text || !shape) return;

            const box = shape.getBBox();
            const available = box.x + box.width - Number(text.getAttribute('x')) - 0.5;
            const length = text.getComputedTextLength();
            if (length > available && available > 0) {
                const size = parseFloat(getComputedStyle(text).fontSize) || 1.4;
                text.style.fontSize = `${Math.max(size * available / length, 0.6)}px`;
            }
        });
    }

    function deviceGlyph(type, scale) {
        const glyph = svgEl('g', { transform: `scale(${scale})`, class: 'fm-glyph' });
        if (type === 'phone') {
            // Handset.
            glyph.append(svgEl('path', {
                d: 'M -0.42 -0.5 Q -0.6 -0.48 -0.55 -0.25 Q -0.35 0.35 0.25 0.55 Q 0.48 0.6 0.5 0.42 L 0.5 0.25 Q 0.48 0.15 0.35 0.14 L 0.18 0.18 Q 0.1 0.2 0.04 0.13 Q -0.1 0 -0.15 -0.06 Q -0.2 -0.12 -0.18 -0.2 L -0.14 -0.36 Q -0.14 -0.48 -0.25 -0.5 Z',
                class: 'fm-workplace-glyph',
            }));
        } else if (type === 'wifi') {
            // Signal arcs above a dot.
            glyph.append(svgEl('path', { d: 'M -0.55 -0.12 A 0.78 0.78 0 0 1 0.55 -0.12 M -0.36 0.08 A 0.5 0.5 0 0 1 0.36 0.08 M -0.17 0.27 A 0.24 0.24 0 0 1 0.17 0.27', class: 'fm-workplace-glyph-stand fm-glyph-wifi' }));
            glyph.append(svgEl('circle', { cx: 0, cy: 0.45, r: 0.1, class: 'fm-workplace-glyph' }));
        } else {
            // Monitor so a desk reads as a PC at a glance.
            glyph.append(svgEl('rect', { x: -0.55, y: -0.5, width: 1.1, height: 0.75, rx: 0.08, class: 'fm-workplace-glyph' }));
            glyph.append(svgEl('path', { d: 'M -0.3 0.55 H 0.3 M 0 0.25 V 0.55', class: 'fm-workplace-glyph-stand' }));
        }
        return glyph;
    }

    function renderWorkplace(workplace) {
        const device = deviceOf(workplace);
        const size = device.size;
        const half = size / 2;
        const isSelected = state.selected && state.selected.kind === 'workplace' && state.selected.id === workplace.id;
        const dimmed = state.search && !matchesSearch(workplace);
        const found = state.search && !dimmed;

        const group = svgEl('g', {
            class: `fm-workplace${isSelected ? ' is-selected' : ''}${dimmed ? ' is-dimmed' : ''}${found ? ' is-found' : ''}`,
            'data-kind': 'workplace',
            'data-id': workplace.id,
            transform: `translate(${workplace.x} ${workplace.y})`,
        });
        group.append(svgEl('rect', {
            x: -half, y: -half, width: size, height: size, rx: isPc(workplace) ? 0.5 : half,
            class: 'fm-workplace-shape', fill: placeColor(workplace),
        }));
        group.append(deviceGlyph(workplace.device_type, size / 2));

        if (!isPc(workplace)) {
            // Phone number / AP name to the right, like on the paper plan.
            if (workplace.pc_name) {
                group.append(svgEl('text', { x: half + 0.3, y: 0, class: 'fm-workplace-label fm-device-label' }, workplace.pc_name));
            }
        } else if (workplace.pc_name) {
            const label = svgEl('text', { x: 0, y: half + 1.0, class: 'fm-workplace-label' });
            wrapLabel(workplace.pc_name).forEach((line, index) => {
                label.append(svgEl('tspan', { x: 0, dy: index ? LABEL_LINE_HEIGHT : 0 }, line));
            });
            group.append(label);
        }
        return group;
    }

    function renderVertexHandles(room) {
        const group = svgEl('g', { class: 'fm-handles' });
        room.points.forEach((point, index) => {
            group.append(svgEl('circle', {
                cx: point[0], cy: point[1], r: 0.45, class: 'fm-handle',
                'data-kind': 'vertex', 'data-index': index,
            }));
        });
        return group;
    }

    function renderDraft() {
        const old = svg.querySelector('.fm-draft');
        if (old) old.remove();

        const pointer = state.pointer;
        let points = null;

        if (pointer && pointer.type === 'rect' && pointer.moved) {
            const [x1, y1] = pointer.start;
            const [x2, y2] = pointer.current;
            points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
        } else if (state.draft) {
            points = state.draft.points.slice();
            if (state.hover) points.push(state.hover);
        }

        if (!points || !points.length) return;

        const group = svgEl('g', { class: 'fm-draft' });
        group.append(svgEl(points.length > 2 ? 'polygon' : 'polyline', {
            points: points.map(p => p.join(',')).join(' '), class: 'fm-draft-shape',
        }));
        if (state.draft) {
            state.draft.points.forEach((point, index) => {
                group.append(svgEl('circle', {
                    cx: point[0], cy: point[1], r: index === 0 ? 0.5 : 0.3,
                    class: index === 0 ? 'fm-draft-start' : 'fm-draft-point',
                }));
            });
        }
        svg.append(group);
    }

    function renderSearchCount() {
        if (!searchCount) return;
        searchCount.textContent = state.search
            ? `${state.workplaces.filter(matchesSearch).length} / ${state.workplaces.length}`
            : '';
    }

    // ------------------------------------------------------------
    // Side panel
    // ------------------------------------------------------------

    function renderPanel() {
        panel.replaceChildren();

        if (state.mode === 'edit' && state.panel === 'settings') {
            panel.append(renderSettings());
            return;
        }

        const item = selectedItem();

        if (item && state.selected.kind === 'workplace') {
            panel.append(state.mode === 'edit' ? renderWorkplaceForm(item) : renderWorkplaceDetails(item));
        } else if (item && state.selected.kind === 'room') {
            panel.append(state.mode === 'edit' ? renderRoomForm(item) : renderRoomDetails(item));
        } else {
            panel.append(renderHints());
        }

        panel.append(renderLegend());
    }

    function section(title) {
        const box = el('section', { className: 'fm-panel-section' });
        if (title) box.append(el('h2', { className: 'fm-panel-title' }, title));
        return box;
    }

    function renderHints() {
        const box = section(state.mode === 'edit' ? t('Editing') : state.map.name);
        const hints = state.mode === 'edit' ? {
            select: [t('Click a room, area or workplace to edit it.'), t('Drag with the mouse or use the arrow keys to move (Shift + arrow: 4 cells); a room moves with its areas and workplaces.'), t('Drag a side of a room or area to make it bigger or smaller; drag the round corners of a selected one to reshape it.'), t('Delete removes the selected item; Ctrl+Z brings it back.')],
            room: [t('Drag to draw a rectangular room.'), t('Or click corner by corner; click the first corner or press Enter to finish.'), t('Esc cancels.')],
            area: [t('A work area is a see-through zone with a dashed border, e.g. a desk group inside a room.'), t('Drag to draw a rectangle, or click corner by corner and press Enter.'), t('Esc cancels.')],
            workplace: [t('Click on an empty spot to place a workplace, then fill in role, PC name and IP.'), t('Drag an existing workplace to move it; arrow keys move the selected one.'), t('Delete removes the selected workplace; Ctrl+Z brings it back.')],
            phone: [t('Click on an empty spot to place a phone, then enter its number.'), t('Drag or use the arrow keys to move it; Delete removes it.')],
            wifi: [t('Click on an empty spot to place a Wi-Fi access point; name and IP are optional.'), t('Drag or use the arrow keys to move it; Delete removes it.')],
        }[state.tool] : [
            `${tn('{n} workplace', '{n} workplaces', state.workplaces.filter(isPc).length)} · ${outlineCounts()}.`,
            t('Hover a workplace to see its role, PC name and IP.'),
            t('Zoom: Ctrl + mouse wheel, + / − keys or the buttons above; drag the map to move around.'),
            t('Switch to Edit to change the map.'),
        ];
        const list = el('ul', { className: 'fm-hints' });
        hints.forEach(text => list.append(el('li', {}, text)));
        box.append(list);
        return box;
    }

    function renderLegend() {
        const counts = new Map();
        state.workplaces.filter(isPc).forEach(workplace => {
            const role = workplace.role || '';
            counts.set(role, (counts.get(role) || 0) + 1);
        });

        const box = section(t('PC roles'));
        const devices = renderDeviceLegend();
        if (!counts.size) {
            box.append(el('p', { className: 'fm-muted' }, t('No workplaces on this map yet.')));
            if (devices) box.append(devices);
            return box;
        }

        const list = el('ul', { className: 'fm-legend' });
        [...counts.entries()]
            .sort((a, b) => (a[0] || '￿').localeCompare(b[0] || '￿'))
            .forEach(([role, count]) => {
                const item = el('li');
                const button = el('button', { type: 'button', className: 'fm-legend-item', title: role ? t('Find "{role}"', { role }) : '' });
                const swatch = el('span', { className: 'fm-swatch' });
                swatch.style.background = roleColor(role);
                button.append(swatch, el('span', { className: 'fm-legend-name' }, role || t('No role')), el('span', { className: 'fm-legend-count' }, String(count)));
                if (role) button.addEventListener('click', () => setSearch(state.search === role ? '' : role));
                else button.disabled = true;
                item.append(button);
                list.append(item);
            });
        box.append(list);
        if (devices) box.append(devices);
        return box;
    }

    function renderDeviceLegend() {
        const types = ['phone', 'wifi']
            .map(type => [type, state.workplaces.filter(w => w.device_type === type).length])
            .filter(([, count]) => count);
        if (!types.length) return null;

        const list = el('ul', { className: 'fm-legend fm-legend-devices' });
        types.forEach(([type, count]) => {
            const device = DEVICES[type];
            const button = el('button', { type: 'button', className: 'fm-legend-item', title: t('Find {what}', { what: device.label }) });
            const swatch = el('span', { className: 'fm-swatch fm-swatch-round' });
            swatch.style.background = device.color;
            button.append(swatch, el('span', { className: 'fm-legend-name' }, device.plural), el('span', { className: 'fm-legend-count' }, String(count)));
            button.addEventListener('click', () => setSearch(state.search === device.label ? '' : device.label));
            const item = el('li');
            item.append(button);
            list.append(item);
        });
        return list;
    }

    function detailRow(list, label, value, className) {
        if (!value) return;
        list.append(el('dt', {}, label), el('dd', { className }, value));
    }

    // Where the PC is plugged in now: IP -> MAC (ARP) -> switch port, from
    // the last collector run (see domain.ports.locate_ips).
    // dante: the second network card (Dante audio network) of the PC.
    // part: 'all'; 'main' = the switch port(s) and the MAC; 'extra' = the
    // rest (port description, devices on the port, DNS, how it was found).
    function networkRows(list, workplace, withLinks, dante = false, part = 'all') {
        const main = part !== 'extra';
        const extra = part !== 'main';
        const network = dante ? workplace.dante_network : workplace.network;
        const ip = dante ? workplace.dante_ip : workplace.ip;
        const switchLabel = dante ? t('Dante switch') : t('Switch');
        // Without an IP the port can still be known from the documented MAC.
        if (!network || (!ip && !network.by)) return;

        if (!network.found) {
            if (main) detailRow(list, switchLabel, t('Not seen in ARP'), 'fm-network-missing');
            return;
        }

        if (!network.ports.length && main) {
            detailRow(list, switchLabel, t('MAC known, switch port not found'), 'fm-network-missing');
        }

        network.ports.forEach(port => {
            if (!main) {
                const descLabel = dante ? `${t('Port desc.')} Dante` : t('Port desc.');
                detailRow(list, network.ports.length > 1 ? `${descLabel} ${port.port_name}` : descLabel, port.description);
                if (port.mac_count > 1) {
                    detailRow(list, '', t('{n} devices on this port (Wi-Fi AP or small switch?)', { n: port.mac_count }), 'fm-muted-value');
                }
                return;
            }
            const value = el('dd', { className: 'fm-network-port' });
            const text = `${port.switch} · ${port.port_name}`;
            if (withLinks) {
                const link = el('a', { href: `/switch/${port.switch_id}?search=${encodeURIComponent(port.port_name)}` }, text);
                value.append(link);
            } else {
                value.append(el('span', {}, text));
            }
            if (port.link) {
                value.append(el('span', { className: `fm-link fm-link-${port.link.toLowerCase() === 'up' ? 'up' : 'down'}` }, port.link));
            }
            list.append(el('dt', {}, switchLabel), value);
            if (extra) {
                detailRow(list, t('Port desc.'), port.description);
                if (port.mac_count > 1) {
                    detailRow(list, '', t('{n} devices on this port (Wi-Fi AP or small switch?)', { n: port.mac_count }), 'fm-muted-value');
                }
            }
        });

        if (main) detailRow(list, dante ? t('Dante MAC') : 'MAC', network.mac, 'fm-mono');
        if (extra) {
            detailRow(list, 'DNS', network.hostname);
            if (network.by) detailRow(list, '', t('Found by the documented MAC (no IP set)'), 'fm-muted-value');
        }
    }

    // Wall socket -> patch port -> switch port as documented in the racks,
    // and whether the PC is really there now (bll/services/floor_maps.py).
    // dante: the socket of the Dante card (its own path and check).
    function socketRows(list, workplace, withLinks, dante = false) {
        const cabling = dante ? workplace.dante_cabling : workplace.cabling;
        const socketLabel = dante ? t('Dante socket') : t('Socket');
        if (!cabling) {
            if (!dante && workplace.suggested_socket) {
                detailRow(list, t('Socket'), t('{socket}? (suggested)', { socket: workplace.suggested_socket }), 'fm-muted-value');
            }
            return;
        }
        if (!cabling.found) {
            detailRow(list, socketLabel, t('{socket} — not found on any patch panel', { socket: cabling.socket }), 'fm-network-missing');
            return;
        }
        detailRow(list, socketLabel, `${cabling.socket} → ${cabling.patch} (${cabling.where})${cabling.ambiguous ? ' · ' + t('several panels have it') : ''}`);
        if (!cabling.switch) {
            detailRow(list, dante ? t('Dante cable') : t('Cable'), t('Patch port is not cabled to a switch'), 'fm-network-missing');
            return;
        }
        const value = el('dd', { className: 'fm-network-port' });
        const text = `${cabling.switch.switch} · ${cabling.switch.port_name}`;
        if (withLinks) {
            value.append(el('a', { href: `/switch/${cabling.switch.switch_id}?search=${encodeURIComponent(cabling.switch.port_name)}` }, text));
        } else {
            value.append(el('span', {}, text));
        }
        list.append(el('dt', {}, dante ? t('Dante cabled to') : t('Cabled to')), value);
        if (cabling.matches_network === false) {
            detailRow(list, '', dante
                ? t('The Dante card is seen on another switch port now — moved, or the documentation is out of date')
                : t('The PC is seen on another switch port now — moved, or the documentation is out of date'), 'fm-network-missing');
        } else if (cabling.matches_network === true) {
            detailRow(list, '', dante ? t('The Dante card is on this port now ✓') : t('The PC is on this port now ✓'), 'fm-socket-ok');
        }
    }

    function renderWorkplaceDetails(workplace) {
        const device = deviceOf(workplace);
        const box = section(workplace.pc_name || (isPc(workplace) ? t('Workplace') : device.label));
        const list = el('dl', { className: 'fm-details' });
        if (!isPc(workplace)) detailRow(list, t('Type'), device.label);
        detailRow(list, t('PC role'), workplace.role);
        detailRow(list, device.nameLabel, workplace.pc_name);
        detailRow(list, t('IP address'), workplace.ip, 'fm-mono');
        socketRows(list, workplace, true);
        networkRows(list, workplace, true);
        detailRow(list, t('Dante IP'), workplace.dante_ip, 'fm-mono');
        networkRows(list, workplace, true, true);
        if (workplace.dante_ip) socketRows(list, workplace, true, true);
        const room = roomOf(workplace);
        detailRow(list, t('Room'), room && room.name);
        const area = areaOf(workplace);
        detailRow(list, t('Work area'), area && area.name);
        detailRow(list, t('Note'), workplace.note, 'fm-note');
        if (!list.children.length) list.append(el('dd', { className: 'fm-muted' }, t('No details yet.')));
        box.append(list);
        return box;
    }

    function renderRoomDetails(room) {
        const box = section(room.name || roomLabel(room));
        const inside = state.workplaces.filter(w => isPc(w) && pointInPolygon(w.x, w.y, room.points));
        box.append(el('p', { className: 'fm-muted' }, `${outlineKind(room)} · ${tn('{n} workplace', '{n} workplaces', inside.length)}`));
        return box;
    }

    function field(label, input, hint) {
        const wrapper = el('label', { className: 'fm-field' });
        wrapper.append(el('span', { className: 'fm-field-label' }, label), input);
        const error = el('span', { className: 'fm-field-error', hidden: true });
        wrapper.append(error);
        if (hint) wrapper.append(el('span', { className: 'fm-field-hint' }, hint));
        input.fmError = error;
        return wrapper;
    }

    function bindSave(input, save) {
        let saved = input.value;
        input.addEventListener('change', async () => {
            if (input.value === saved) return;
            input.fmError.hidden = true;
            input.removeAttribute('aria-invalid');
            try {
                await save(input.value);
                saved = input.value;
                setStatus(t('Saved'));
            } catch (error) {
                input.fmError.textContent = error.message;
                input.fmError.hidden = false;
                input.setAttribute('aria-invalid', 'true');
            }
        });
        input.addEventListener('keydown', event => {
            if (event.key === 'Enter' && input.tagName !== 'TEXTAREA') input.blur();
        });
    }

    function renderWorkplaceForm(workplace) {
        const device = deviceOf(workplace);
        const box = section(isPc(workplace) ? t('Workplace') : device.label);

        // Type: PC / phone / Wi-Fi; the form changes with it.
        const type = el('select');
        Object.entries(DEVICES).forEach(([value, info]) => type.append(el('option', { value }, info.label)));
        type.value = workplace.device_type || 'pc';
        box.append(field(t('Type'), type));
        type.addEventListener('change', async () => {
            try {
                await api('PATCH', `/floor-maps/api/workplaces/${workplace.id}`, { device_type: type.value });
                await reload({ panelToo: true });
                setStatus(t('Saved'));
            } catch (error) {
                setStatus(error.message, 'error');
            }
        });

        const datalist = el('datalist', { id: 'fm-roles' });
        state.roles.forEach(role => datalist.append(el('option', { value: role })));

        const inputs = {
            role: el('input', { type: 'text', list: 'fm-roles', maxlength: 80, autocomplete: 'off' }),
            pc_name: el('input', { type: 'text', maxlength: 80, autocomplete: 'off', spellcheck: 'false' }),
            ip: el('input', { type: 'text', maxlength: 45, autocomplete: 'off', spellcheck: 'false', inputmode: 'decimal', className: 'fm-mono', placeholder: '10.13.40.15' }),
            note: el('textarea', { rows: 3, maxlength: 500 }),
            socket: el('input', { type: 'text', maxlength: 40, autocomplete: 'off', spellcheck: 'false', placeholder: '2-19' }),
            dante_ip: el('input', { type: 'text', maxlength: 45, autocomplete: 'off', spellcheck: 'false', inputmode: 'decimal', className: 'fm-mono', placeholder: '10.13.33.31' }),
            dante_socket: el('input', { type: 'text', maxlength: 40, autocomplete: 'off', spellcheck: 'false', placeholder: '2-20' }),
        };
        Object.entries(inputs).forEach(([key, input]) => { input.value = workplace[key] || ''; });

        if (isPc(workplace)) box.append(datalist, field(t('PC role'), inputs.role));
        else delete inputs.role;
        box.append(
            field(device.nameLabel, inputs.pc_name),
            field(t('IP address'), inputs.ip),
        );
        if (isPc(workplace)) box.append(field(t('Dante IP'), inputs.dante_ip, t('Second network card in the Dante audio network, if any')));
        else delete inputs.dante_ip;
        box.append(field(t('Wall socket'), inputs.socket, t('As written on the socket and on its patch-panel port, e.g. 2-19')));
        if (isPc(workplace)) box.append(field(t('Dante socket'), inputs.dante_socket, t('The wall socket of the Dante card, if it has its own')));
        else delete inputs.dante_socket;
        box.append(field(t('Note'), inputs.note));
        if (!workplace.socket && workplace.suggested_socket) {
            const use = el('button', { type: 'button', className: 'fm-suggest' }, t('Use suggested socket {socket}', { socket: workplace.suggested_socket }));
            use.addEventListener('click', async () => {
                try {
                    await api('PATCH', `/floor-maps/api/workplaces/${workplace.id}`, { socket: workplace.suggested_socket });
                    await reload({ panelToo: true });
                    setStatus(t('Saved'));
                } catch (error) {
                    setStatus(error.message, 'error');
                }
            });
            inputs.socket.closest('.fm-field').after(use);
        }

        Object.entries(inputs).forEach(([key, input]) => {
            bindSave(input, async value => {
                await api('PATCH', `/floor-maps/api/workplaces/${workplace.id}`, { [key]: value });
                await reload();
            });
        });

        const room = roomOf(workplace);
        if (room && room.name) box.append(el('p', { className: 'fm-muted' }, t('Room: {name}', { name: room.name })));

        const network = el('dl', { className: 'fm-details fm-network' });
        socketRows(network, workplace, true);
        networkRows(network, workplace, true);
        networkRows(network, workplace, true, true);
        if (workplace.dante_ip) socketRows(network, workplace, true, true);
        if (network.children.length) box.append(network);

        box.append(deleteButton(isPc(workplace) ? t('Delete workplace') : t('Delete {what}', { what: device.label }), () => deleteSelected()));
        requestAnimationFrame(() => {
            if (state.focusNew) { (inputs.role || inputs.pc_name).focus(); state.focusNew = false; }
        });
        return box;
    }

    function renderRoomForm(room) {
        const box = section(roomLabel(room));

        const type = el('select');
        Object.entries(ROOM_LABELS).forEach(([value, label]) => type.append(el('option', { value }, value === 'area' ? t('Work area (dashed)') : label)));
        type.value = room.room_type || 'room';
        box.append(field(t('Type'), type));
        type.addEventListener('change', async () => {
            try {
                await api('PATCH', `/floor-maps/api/rooms/${room.id}`, { room_type: type.value });
                await reload({ panelToo: true });
                setStatus(t('Saved'));
            } catch (error) {
                setStatus(error.message, 'error');
            }
        });

        const name = el('input', { type: 'text', maxlength: 80, autocomplete: 'off' });
        name.value = room.name || '';
        box.append(field(isArea(room) ? t('Work area name') : t('Room name'), name));
        bindSave(name, async value => {
            await api('PATCH', `/floor-maps/api/rooms/${room.id}`, { name: value });
            await reload();
        });

        const inside = state.workplaces.filter(w => isPc(w) && pointInPolygon(w.x, w.y, room.points));
        box.append(el('p', { className: 'fm-muted' }, t('{corners} corners · {n} workplaces inside', { corners: room.points.length, n: inside.length })));
        box.append(deleteButton(isArea(room) ? t('Delete work area') : t('Delete room'), () => deleteSelected()));
        requestAnimationFrame(() => {
            if (state.focusNew) { name.focus(); state.focusNew = false; }
        });
        return box;
    }

    function deleteButton(text, onClick) {
        const button = el('button', { type: 'button', className: 'fm-danger' }, text);
        button.addEventListener('click', onClick);
        return button;
    }

    function renderSettings() {
        const box = section(t('Map settings'));
        const name = el('input', { type: 'text', maxlength: 80 });
        name.value = state.map.name;
        const width = el('input', { type: 'number', min: 10, max: 400, step: 1 });
        width.value = state.map.width;
        const height = el('input', { type: 'number', min: 10, max: 400, step: 1 });
        height.value = state.map.height;

        const form = el('form', { className: 'fm-settings' });
        form.append(
            field(t('Name'), name),
            field(t('Width, cells'), width),
            field(t('Height, cells'), height, t('One cell ≈ half a desk. A map can only shrink if everything still fits.')),
        );
        const error = el('p', { className: 'fm-field-error', hidden: true });
        const actions = el('div', { className: 'fm-actions' });
        const save = el('button', { type: 'submit', className: 'button' }, t('Save'));
        const close = el('button', { type: 'button', className: 'button secondary' }, t('Close'));
        actions.append(save, close);
        form.append(error, actions);

        form.addEventListener('submit', async event => {
            event.preventDefault();
            error.hidden = true;
            try {
                await api('PATCH', `/floor-maps/api/maps/${state.map.id}`, {
                    name: name.value, width: width.value, height: height.value,
                });
                if (name.value.trim() !== state.map.name) {
                    window.location.reload();
                    return;
                }
                state.panel = 'item';
                await reload();
                setStatus(t('Map saved'));
            } catch (err) {
                error.textContent = err.message;
                error.hidden = false;
            }
        });
        close.addEventListener('click', () => { state.panel = 'item'; renderPanel(); syncToolbar(); });

        box.append(form);

        const suggested = state.workplaces.filter(w => !w.socket && w.suggested_socket).length;
        if (suggested) {
            const fill = el('button', { type: 'button', className: 'fm-suggest' }, tn('Fill {n} wall socket from the cable journal', 'Fill {n} wall sockets from the cable journal', suggested));
            fill.title = t('Workplaces without a socket get the one found by their PC name or switch port');
            fill.addEventListener('click', async () => {
                try {
                    const data = await api('POST', `/floor-maps/api/maps/${state.map.id}/fill-sockets`);
                    await reload({ panelToo: true });
                    setStatus(tn('{n} socket set', '{n} sockets set', data.filled));
                } catch (err) {
                    setStatus(err.message, 'error');
                }
            });
            box.append(fill);
        }

        box.append(deleteButton(t('Delete this map'), async () => {
            const total = state.rooms.length + state.workplaces.length;
            const message = total
                ? t('Delete map "{name}" with {outlines} and {places}? This cannot be undone.', { name: state.map.name, outlines: outlineCounts(), places: tn('{n} workplace', '{n} workplaces', state.workplaces.length) })
                : t('Delete map "{name}"?', { name: state.map.name });
            if (!confirm(message)) return;
            try {
                const data = await api('DELETE', `/floor-maps/api/maps/${state.map.id}`);
                window.location.href = data.url;
            } catch (err) {
                setStatus(err.message, 'error');
            }
        }));
        return box;
    }

    // ------------------------------------------------------------
    // Toolbar and modes
    // ------------------------------------------------------------

    function syncToolbar() {
        document.querySelectorAll('[data-fm-mode]').forEach(button => {
            const active = button.dataset.fmMode === state.mode;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', String(active));
        });
        document.querySelectorAll('[data-fm-edit-only]').forEach(node => { node.hidden = state.mode !== 'edit'; });
        document.querySelectorAll('[data-fm-tool]').forEach(button => {
            const active = button.dataset.fmTool === state.tool;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', String(active));
        });
        const settings = document.querySelector('[data-fm-settings]');
        if (settings) settings.classList.toggle('is-active', state.panel === 'settings');
    }

    function setMode(mode) {
        state.mode = mode;
        state.draft = null;
        state.pointer = null;
        state.panel = 'item';
        saveMode(mode);
        syncToolbar();
        render();
        renderPanel();
    }

    function setTool(tool) {
        state.tool = tool;
        state.draft = null;
        state.hover = null;
        if (tool !== 'select') state.selected = null;
        state.panel = 'item';
        syncToolbar();
        render();
        renderPanel();
    }

    function select(kind, id) {
        state.selected = kind ? { kind, id } : null;
        state.panel = 'item';
        syncToolbar();
        render();
        renderPanel();
    }

    function setSearch(value) {
        state.search = value.trim();
        const input = document.querySelector('[data-fm-search]');
        if (input && input.value !== value) input.value = value;
        render();
    }

    // ------------------------------------------------------------
    // Data
    // ------------------------------------------------------------

    function applyData(data) {
        state.map = data.map;
        state.rooms = data.rooms;
        state.workplaces = data.workplaces;
        state.roles = data.roles;
        if (state.selected && !selectedItem()) state.selected = null;
    }

    async function reload({ panelToo = false } = {}) {
        const data = await api('GET', `/floor-maps/api/maps/${state.map.id}`);
        applyData(data);
        render();
        if (panelToo) renderPanel();
        else refreshPanelLight();
    }

    // After a field is saved: refresh legend/hints without rebuilding the
    // form the user is typing in.
    function refreshPanelLight() {
        const legend = panel.querySelector('.fm-legend');
        if (legend) legend.closest('.fm-panel-section').replaceWith(renderLegend());
        else if (!panel.querySelector('input, textarea')) renderPanel();
    }

    async function deleteSelected() {
        const item = selectedItem();
        if (!item) return;

        const kind = state.selected.kind;
        const name = kind === 'room' ? item.name : item.pc_name;
        const what = kind === 'room' ? roomLabel(item) : (isPc(item) ? t('Workplace') : deviceOf(item).label);
        const label = name ? t('{what} "{name}" deleted', { what, name }) : t('{what} deleted', { what });

        await flushNudge();

        try {
            await api('DELETE', `/floor-maps/api/${kind === 'room' ? 'rooms' : 'workplaces'}/${item.id}`);
            state.selected = null;
            state.undo = { kind, item: JSON.parse(JSON.stringify(item)) };
            await reload({ panelToo: true });
            setStatus(label, 'info', { label: t('Undo'), run: undoDelete });
        } catch (error) {
            setStatus(error.message, 'error');
        }
    }

    // Put the last deleted room/workplace back (it gets a new id).
    async function undoDelete() {
        const undo = state.undo;
        if (!undo) return;
        state.undo = null;

        const { kind, item } = undo;
        try {
            const data = kind === 'room'
                ? await api('POST', `/floor-maps/api/maps/${state.map.id}/rooms`, { name: item.name, points: item.points, room_type: item.room_type })
                : await api('POST', `/floor-maps/api/maps/${state.map.id}/workplaces`, {
                    x: item.x, y: item.y, device_type: item.device_type, role: item.role, pc_name: item.pc_name, ip: item.ip, note: item.note, socket: item.socket, dante_ip: item.dante_ip, dante_socket: item.dante_socket,
                });
            state.selected = { kind, id: data.id };
            await reload({ panelToo: true });
            setStatus(t('Restored'));
        } catch (error) {
            setStatus(error.message, 'error');
        }
    }

    // ------------------------------------------------------------
    // Arrow keys: move the selected workplace (or room with its workplaces)
    // ------------------------------------------------------------

    function nudge(dx, dy) {
        const item = selectedItem();
        if (!item) return;

        const pending = state.nudge || (state.nudge = { rooms: new Map(), workplaces: new Map(), timer: null });

        if (state.selected.kind === 'workplace') {
            [item.x, item.y] = snapPoint([item.x + dx, item.y + dy], WORKPLACE_STEP);
            pending.workplaces.set(item.id, item);
        } else {
            const xs = item.points.map(p => p[0]);
            const ys = item.points.map(p => p[1]);
            const sx = Math.min(Math.max(dx, -Math.min(...xs)), state.map.width - Math.max(...xs));
            const sy = Math.min(Math.max(dy, -Math.min(...ys)), state.map.height - Math.max(...ys));
            if (!sx && !sy) return;
            const contents = contentsOf(item);
            contents.workplaces.forEach(w => {
                w.x = Math.min(Math.max(w.x + sx, 0), state.map.width);
                w.y = Math.min(Math.max(w.y + sy, 0), state.map.height);
                pending.workplaces.set(w.id, w);
            });
            contents.areas.forEach(area => {
                area.points = area.points.map(p => snapPoint([p[0] + sx, p[1] + sy], ROOM_STEP));
                pending.rooms.set(area.id, area);
            });
            item.points = item.points.map(([x, y]) => [x + sx, y + sy]);
            pending.rooms.set(item.id, item);
        }

        hideTooltip();
        render();
        clearTimeout(pending.timer);
        pending.timer = setTimeout(flushNudge, NUDGE_SAVE_DELAY_MS);
    }

    async function flushNudge() {
        const pending = state.nudge;
        if (!pending) return;
        state.nudge = null;
        clearTimeout(pending.timer);

        try {
            await api('POST', `/floor-maps/api/maps/${state.map.id}/move`, {
                rooms: [...pending.rooms.values()].map(room => ({ id: room.id, points: room.points })),
                workplaces: [...pending.workplaces.values()].map(w => ({ id: w.id, x: w.x, y: w.y })),
            });
            setStatus(t('Saved'));
        } catch (error) {
            setStatus(error.message, 'error');
            await reload({ panelToo: true });
        }
    }

    async function createRoom(points, roomType = 'room') {
        try {
            const data = await api('POST', `/floor-maps/api/maps/${state.map.id}/rooms`, { name: '', points, room_type: roomType });
            state.draft = null;
            state.hover = null;
            state.selected = { kind: 'room', id: data.id };
            state.focusNew = true;
            state.tool = 'select';
            syncToolbar();
            await reload({ panelToo: true });
            setStatus(t('Room added — give it a name'));
        } catch (error) {
            setStatus(error.message, 'error');
        }
    }

    async function createWorkplace(point, deviceType = 'pc') {
        try {
            const data = await api('POST', `/floor-maps/api/maps/${state.map.id}/workplaces`, { x: point[0], y: point[1], device_type: deviceType });
            state.selected = { kind: 'workplace', id: data.id };
            state.focusNew = true;
            await reload({ panelToo: true });
            setStatus(t('{what} added', { what: deviceType === 'pc' ? t('Workplace') : DEVICES[deviceType].label }));
        } catch (error) {
            setStatus(error.message, 'error');
        }
    }

    async function saveMove(rooms, workplaces) {
        await flushNudge();
        try {
            await api('POST', `/floor-maps/api/maps/${state.map.id}/move`, { rooms, workplaces });
            setStatus(t('Saved'));
        } catch (error) {
            setStatus(error.message, 'error');
        }
        await reload({ panelToo: true });
    }

    // ------------------------------------------------------------
    // Pointer interaction
    // ------------------------------------------------------------

    // ------------------------------------------------------------
    // Zoom and panning
    // ------------------------------------------------------------

    function readZoom() {
        try {
            const value = Number(localStorage.getItem(ZOOM_KEY + state.map.id));
            return Number.isFinite(value) && value > 0 ? value : 1;
        } catch (_e) {
            return 1;
        }
    }

    // Change zoom keeping the map point under (clientX, clientY) in place;
    // without a point, the centre of the visible part stays in place.
    function setZoom(zoom, clientX, clientY) {
        zoom = Math.min(Math.max(zoom, ZOOM_MIN), ZOOM_MAX);
        const box = viewport.getBoundingClientRect();
        const anchorX = clientX === undefined ? box.left + box.width / 2 : clientX;
        const anchorY = clientY === undefined ? box.top + box.height / 2 : clientY;
        const before = svgPoint({ clientX: anchorX, clientY: anchorY });

        state.zoom = zoom;
        applyZoom();

        const point = svg.createSVGPoint();
        [point.x, point.y] = before;
        const after = point.matrixTransform(svg.getScreenCTM());
        viewport.scrollLeft += after.x - anchorX;
        viewport.scrollTop += after.y - anchorY;

        try { localStorage.setItem(ZOOM_KEY + state.map.id, String(zoom)); } catch (_e) { /* private window */ }
    }

    function applyZoom() {
        svg.style.width = `${state.zoom * 100}%`;
        const level = document.querySelector('.fm-zoom-level');
        if (level) level.textContent = `${Math.round(state.zoom * 100)}%`;
    }

    // Largest zoom (up to 100%) at which the whole map is visible.
    function fitZoom() {
        const { width, height } = state.map;
        const fullHeight = viewport.clientWidth * (height + 1) / (width + 1);
        return Math.min(1, viewport.clientHeight / fullHeight);
    }

    function onWheel(event) {
        // Ctrl + wheel, or a pinch on a touchpad (sent as Ctrl + wheel).
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        setZoom(state.zoom * Math.exp(-event.deltaY * 0.0025), event.clientX, event.clientY);
    }

    function finishDraft() {
        if (state.draft && state.draft.points.length >= 3) createRoom(state.draft.points, DRAW_TOOLS[state.tool]);
    }

    function cancelDraft() {
        state.draft = null;
        state.hover = null;
        renderDraft();
    }

    function onPointerDown(event) {
        if (event.button !== 0) return;
        hideTooltip();
        // Save the field being edited before the panel is rebuilt.
        if (panel.contains(document.activeElement)) document.activeElement.blur();
        const point = svgPoint(event);
        const target = event.target.closest('[data-kind]');

        if (state.mode !== 'edit') {
            // Drag moves the view; a click selects what is under the pointer.
            startPan(event, target);
            return;
        }

        if (PLACE_TOOLS[state.tool] && !(target && target.dataset.kind === 'workplace')) {
            createWorkplace(snapPoint(point, WORKPLACE_STEP), PLACE_TOOLS[state.tool]);
            return;
        }

        if (DRAW_TOOLS[state.tool]) {
            const snapped = snapPoint(point, ROOM_STEP);
            if (state.draft) {
                if (state.draft.points.length >= 3 && distance(snapped, state.draft.points[0]) <= CLOSE_DISTANCE) {
                    finishDraft();
                } else {
                    const last = state.draft.points[state.draft.points.length - 1];
                    if (!last || distance(last, snapped) > 0) state.draft.points.push(snapped);
                    renderDraft();
                }
                return;
            }
            state.pointer = { type: 'rect', start: snapped, current: snapped, moved: false };
            svg.setPointerCapture(event.pointerId);
            return;
        }

        // Select tool (placing tools also drag existing workplaces)
        if (!target) {
            startPan(event, null);
            return;
        }

        const kind = target.dataset.kind;

        if (kind === 'vertex') {
            const room = selectedItem();
            state.pointer = { type: 'vertex', room, index: Number(target.dataset.index), start: point, moved: false };
        } else if (kind === 'edge') {
            const room = findItem('room', Number(target.dataset.id));
            if (!state.selected || state.selected.kind !== 'room' || state.selected.id !== room.id) select('room', room.id);
            state.pointer = {
                type: 'edge', room, index: Number(target.dataset.index),
                origin: room.points.map(p => p.slice()), start: point, moved: false,
            };
        } else if (kind === 'workplace') {
            const workplace = findItem('workplace', Number(target.dataset.id));
            if (!state.selected || state.selected.kind !== 'workplace' || state.selected.id !== workplace.id) select('workplace', workplace.id);
            state.pointer = { type: 'workplace', item: workplace, origin: [workplace.x, workplace.y], start: point, moved: false };
        } else if (kind === 'room') {
            const room = findItem('room', Number(target.dataset.id));
            if (!state.selected || state.selected.kind !== 'room' || state.selected.id !== room.id) select('room', room.id);
            const contents = contentsOf(room);
            state.pointer = {
                type: 'room', item: room, origin: room.points.map(p => p.slice()),
                carried: contents.workplaces.map(w => ({ item: w, origin: [w.x, w.y] })),
                carriedAreas: contents.areas.map(area => ({ item: area, origin: area.points.map(p => p.slice()) })),
                start: point, moved: false,
            };
        }

        if (state.pointer) svg.setPointerCapture(event.pointerId);
    }

    // Move side ``index`` of an outline (corners index and index + 1) across
    // itself by the pointer shift; straight walls stay straight.
    function moveEdge(origin, index, dx, dy) {
        const n = origin.length;
        const a = origin[index];
        const b = origin[(index + 1) % n];
        let shift;

        if (a[1] === b[1]) {
            shift = [0, Math.round(dy / ROOM_STEP) * ROOM_STEP];
        } else if (a[0] === b[0]) {
            shift = [Math.round(dx / ROOM_STEP) * ROOM_STEP, 0];
        } else {
            const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
            const normal = [-(b[1] - a[1]) / length, (b[0] - a[0]) / length];
            const along = Math.round((dx * normal[0] + dy * normal[1]) / ROOM_STEP) * ROOM_STEP;
            shift = [normal[0] * along, normal[1] * along];
        }

        return origin.map((point, i) => (i === index || i === (index + 1) % n)
            ? snapPoint([point[0] + shift[0], point[1] + shift[1]], ROOM_STEP)
            : point.slice());
    }

    function onPointerMove(event) {
        const point = svgPoint(event);
        const pointer = state.pointer;

        if (!pointer) {
            if (state.mode === 'edit' && DRAW_TOOLS[state.tool] && state.draft) {
                state.hover = snapPoint(point, ROOM_STEP);
                renderDraft();
            }
            updateTooltip(event);
            return;
        }

        if (pointer.type === 'pan') {
            const dx = event.clientX - pointer.start[0];
            const dy = event.clientY - pointer.start[1];
            if (!pointer.moved && Math.hypot(dx, dy) < 4) return;
            pointer.moved = true;
            svg.classList.add('is-panning');
            viewport.scrollLeft = pointer.scroll[0] - dx;
            viewport.scrollTop = pointer.scroll[1] - dy;
            return;
        }

        if (pointer.type === 'rect') {
            pointer.current = snapPoint(point, ROOM_STEP);
            pointer.moved = pointer.moved || distance(pointer.start, pointer.current) >= 1;
            renderDraft();
            return;
        }

        const dx = point[0] - pointer.start[0];
        const dy = point[1] - pointer.start[1];
        if (!pointer.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
        pointer.moved = true;

        if (pointer.type === 'workplace') {
            [pointer.item.x, pointer.item.y] = snapPoint([pointer.origin[0] + dx, pointer.origin[1] + dy], WORKPLACE_STEP);
        } else if (pointer.type === 'vertex') {
            pointer.room.points[pointer.index] = snapPoint(point, ROOM_STEP);
        } else if (pointer.type === 'edge') {
            pointer.room.points = moveEdge(pointer.origin, pointer.index, dx, dy);
        } else if (pointer.type === 'room') {
            // Keep the whole room on the map: clamp the shift, not each corner.
            const xs = pointer.origin.map(p => p[0]);
            const ys = pointer.origin.map(p => p[1]);
            const sx = Math.min(Math.max(Math.round(dx / ROOM_STEP) * ROOM_STEP, -Math.min(...xs)), state.map.width - Math.max(...xs));
            const sy = Math.min(Math.max(Math.round(dy / ROOM_STEP) * ROOM_STEP, -Math.min(...ys)), state.map.height - Math.max(...ys));
            pointer.item.points = pointer.origin.map(([x, y]) => [x + sx, y + sy]);
            pointer.carried.forEach(({ item, origin }) => {
                item.x = Math.min(Math.max(origin[0] + sx, 0), state.map.width);
                item.y = Math.min(Math.max(origin[1] + sy, 0), state.map.height);
            });
            pointer.carriedAreas.forEach(({ item, origin }) => {
                item.points = origin.map(p => snapPoint([p[0] + sx, p[1] + sy], ROOM_STEP));
            });
        }
        render();
    }

    function startPan(event, target) {
        state.pointer = {
            type: 'pan', target, moved: false,
            start: [event.clientX, event.clientY],
            scroll: [viewport.scrollLeft, viewport.scrollTop],
        };
        svg.setPointerCapture(event.pointerId);
    }

    function onPointerUp(event) {
        const pointer = state.pointer;
        if (!pointer) return;
        state.pointer = null;
        if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);

        if (pointer.type === 'pan') {
            svg.classList.remove('is-panning');
            if (pointer.moved) return;
            const target = pointer.target;
            if (target && target.dataset.kind === 'workplace') select('workplace', Number(target.dataset.id));
            else if (target && target.dataset.kind === 'room') select('room', Number(target.dataset.id));
            else select(null);
            return;
        }

        if (pointer.type === 'rect') {
            if (pointer.moved) {
                const [x1, y1] = pointer.start;
                const [x2, y2] = pointer.current;
                if (x1 !== x2 && y1 !== y2) {
                    createRoom([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], DRAW_TOOLS[state.tool]);
                    return;
                }
                renderDraft();
                return;
            }
            // A click without dragging starts a polygon.
            state.draft = { points: [pointer.start] };
            renderDraft();
            renderPanel();
            return;
        }

        if (!pointer.moved) return;

        if (pointer.type === 'workplace') {
            saveMove([], [{ id: pointer.item.id, x: pointer.item.x, y: pointer.item.y }]);
        } else if (pointer.type === 'vertex' || pointer.type === 'edge') {
            saveMove([{ id: pointer.room.id, points: pointer.room.points }], []);
        } else if (pointer.type === 'room') {
            saveMove(
                [pointer.item, ...pointer.carriedAreas.map(({ item }) => item)].map(room => ({ id: room.id, points: room.points })),
                pointer.carried.map(({ item }) => ({ id: item.id, x: item.x, y: item.y })),
            );
        }
    }

    // ------------------------------------------------------------
    // Tooltip
    // ------------------------------------------------------------

    function hideTooltip() {
        tooltip.hidden = true;
    }

    function updateTooltip(event) {
        const target = event.target.closest && event.target.closest('[data-kind="workplace"], [data-kind="room"]');
        if (!target || (state.mode === 'edit' && state.tool !== 'select')) {
            hideTooltip();
            return;
        }

        const item = findItem(target.dataset.kind, Number(target.dataset.id));
        if (!item) {
            hideTooltip();
            return;
        }

        tooltip.replaceChildren();
        if (target.dataset.kind === 'workplace') {
            const device = deviceOf(item);
            const swatch = el('span', { className: `fm-swatch${isPc(item) ? '' : ' fm-swatch-round'}` });
            swatch.style.background = placeColor(item);
            const head = el('div', { className: 'fm-tooltip-head' });
            head.append(swatch, el('span', {}, isPc(item) ? (item.role || t('No role')) : device.label));
            tooltip.append(head);
            const list = el('dl', { className: 'fm-details' });
            // First the name and the network: IP, switch, MAC, then the same
            // for Dante (only with a Dante IP); everything else after them.
            // A little space above the IP and the Dante IP: each starts its group.
            const spaced = (label, value) => {
                const before = list.children.length;
                detailRow(list, label, value, 'fm-mono');
                Array.from(list.children).slice(before).forEach(cell => cell.classList.add('fm-row-spaced'));
            };
            detailRow(list, device.nameLabel, item.pc_name);
            spaced('IP', item.ip);
            networkRows(list, item, false, false, 'main');
            if (item.dante_ip) {
                spaced(t('Dante IP'), item.dante_ip);
                networkRows(list, item, false, true, 'main');
            }
            // A little space below the (Dante) MAC: the rest follows.
            const rest = list.children.length;
            networkRows(list, item, false, false, 'extra');
            if (item.dante_ip) networkRows(list, item, false, true, 'extra');
            socketRows(list, item, false);
            if (item.dante_ip) socketRows(list, item, false, true);
            if (rest > 2 && list.children[rest]) {
                list.children[rest].classList.add('fm-row-spaced');
                if (list.children[rest + 1]) list.children[rest + 1].classList.add('fm-row-spaced');
            }
            const room = roomOf(item);
            detailRow(list, t('Room'), room && room.name);
            const area = areaOf(item);
            detailRow(list, t('Work area'), area && area.name);
            detailRow(list, t('Note'), item.note, 'fm-note');
            if (!list.children.length) list.append(el('dd', { className: 'fm-muted' }, t('No details yet')));
            tooltip.append(list);
        } else {
            const inside = state.workplaces.filter(w => isPc(w) && pointInPolygon(w.x, w.y, item.points)).length;
            tooltip.append(el('div', { className: 'fm-tooltip-head' }, item.name || roomLabel(item)));
            tooltip.append(el('div', { className: 'fm-muted' }, `${outlineKind(item)} · ${tn('{n} workplace', '{n} workplaces', inside)}`));
        }

        tooltip.hidden = false;
        const box = canvas.getBoundingClientRect();
        const tip = tooltip.getBoundingClientRect();
        let left = event.clientX - box.left + 14;
        let top = event.clientY - box.top + 14;
        if (left + tip.width > box.width - 4) left = event.clientX - box.left - tip.width - 14;
        if (top + tip.height > box.height - 4) top = event.clientY - box.top - tip.height - 14;
        tooltip.style.left = `${Math.max(4, left)}px`;
        tooltip.style.top = `${Math.max(4, top)}px`;
    }

    // ------------------------------------------------------------
    // Keyboard
    // ------------------------------------------------------------

    const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

    function onKeyDown(event) {
        const typing = event.target.closest && event.target.closest('input, textarea, select');
        if (typing) return;

        if ((event.ctrlKey || event.metaKey) && !event.altKey && (event.key === 'z' || event.key === 'Z') && state.mode === 'edit' && state.undo) {
            event.preventDefault();
            undoDelete();
            return;
        }

        if (event.ctrlKey || event.metaKey || event.altKey) return;

        if (event.key === '+' || event.key === '=') {
            setZoom(state.zoom * ZOOM_STEP);
            return;
        }
        if (event.key === '-' || event.key === '_') {
            setZoom(state.zoom / ZOOM_STEP);
            return;
        }
        if (event.key === '0') {
            setZoom(1);
            return;
        }

        if (state.mode === 'edit' && ARROWS[event.key] && state.selected && !state.draft && !state.pointer) {
            event.preventDefault();
            const step = event.shiftKey ? NUDGE_STEP_LARGE : NUDGE_STEP;
            const [dx, dy] = ARROWS[event.key];
            nudge(dx * step, dy * step);
            return;
        }

        if (event.key === 'Escape') {
            if (state.draft) cancelDraft();
            else if (state.selected) select(null);
            return;
        }

        if (state.mode !== 'edit') return;

        if (event.key === 'Enter' && state.draft) {
            event.preventDefault();
            finishDraft();
        } else if ((event.key === 'Delete' || event.key === 'Backspace') && state.selected) {
            event.preventDefault();
            deleteSelected();
        } else if (event.key === 'v' || event.key === 'V') {
            setTool('select');
        } else if (event.key === 'r' || event.key === 'R') {
            setTool('room');
        } else if (event.key === 'w' || event.key === 'W') {
            setTool('workplace');
        } else if (event.key === 'a' || event.key === 'A') {
            setTool('area');
        } else if (event.key === 'p' || event.key === 'P') {
            setTool('phone');
        } else if (event.key === 'f' || event.key === 'F') {
            setTool('wifi');
        }
    }

    // ------------------------------------------------------------
    // Start
    // ------------------------------------------------------------

    // Map tabs: drag one to another place; the order is saved for everyone
    // and the first tab is the one /floor-maps opens.
    function setupTabOrder() {
        const nav = document.querySelector('.fm-tabs');
        if (!nav || !(window.WirehouseAuth && window.WirehouseAuth.canEdit())) return;

        const tabs = () => [...nav.querySelectorAll('.fm-tab[data-map-id]')];
        const order = () => tabs().map(tab => tab.dataset.mapId);
        let saved = order();
        let dragged = null;

        tabs().forEach(tab => {
            tab.addEventListener('dragstart', event => {
                dragged = tab;
                tab.classList.add('is-dragging');
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', tab.dataset.mapId);
            });

            tab.addEventListener('dragend', async event => {
                tab.classList.remove('is-dragging');
                dragged = null;

                if (event.dataTransfer.dropEffect === 'none') {
                    // Dropped outside the tabs: put everything back.
                    const byId = new Map(tabs().map(t => [t.dataset.mapId, t]));
                    const newMap = nav.querySelector('[data-fm-new-map]');
                    saved.forEach(id => nav.insertBefore(byId.get(id), newMap));
                    return;
                }

                const current = order();
                if (current.join() === saved.join()) return;
                try {
                    await api('POST', '/floor-maps/api/maps/order', { map_ids: current.map(Number) });
                    saved = current;
                    if (statusBox) setStatus(t('Map order saved'));
                } catch (error) {
                    alert(error.message);
                    window.location.reload();
                }
            });
        });

        nav.addEventListener('dragover', event => {
            if (!dragged) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            const target = event.target.closest('.fm-tab[data-map-id]');
            if (!target || target === dragged) return;
            const box = target.getBoundingClientRect();
            const after = event.clientX > box.left + box.width / 2;
            nav.insertBefore(dragged, after ? target.nextSibling : target);
        });

        nav.addEventListener('drop', event => {
            if (dragged) event.preventDefault();
        });
    }

    async function createMap() {
        const name = prompt(t('Name of the new map:'));
        if (name === null || !name.trim()) return;
        try {
            const data = await api('POST', '/floor-maps/api/maps', { name });
            window.location.href = data.url;
        } catch (error) {
            alert(error.message);
        }
    }

    function init() {
        document.querySelectorAll('[data-fm-new-map]').forEach(button => button.addEventListener('click', createMap));
        setupTabOrder();

        const dataNode = document.getElementById('floor-map-data');
        if (!dataNode) return;

        svg = document.querySelector('[data-fm-svg]');
        canvas = document.querySelector('[data-fm-canvas]');
        viewport = document.querySelector('[data-fm-viewport]');
        panel = document.querySelector('[data-fm-panel]');
        tooltip = document.querySelector('[data-fm-tooltip]');
        statusBox = document.querySelector('[data-fm-status]');
        searchCount = document.querySelector('[data-fm-search-count]');

        applyData(JSON.parse(dataNode.textContent));
        state.mode = readMode();
        // Opened from the dashboard search: highlight what was found.
        const initialSearch = new URLSearchParams(window.location.search).get('search');
        if (initialSearch) state.search = initialSearch.trim();

        document.querySelectorAll('[data-fm-mode]').forEach(button => {
            button.addEventListener('click', () => setMode(button.dataset.fmMode));
        });
        document.querySelectorAll('[data-fm-tool]').forEach(button => {
            button.addEventListener('click', () => setTool(button.dataset.fmTool));
        });
        const settings = document.querySelector('[data-fm-settings]');
        if (settings) {
            settings.addEventListener('click', () => {
                state.panel = state.panel === 'settings' ? 'item' : 'settings';
                syncToolbar();
                renderPanel();
            });
        }

        const search = document.querySelector('[data-fm-search]');
        if (search) {
            if (state.search) search.value = state.search;
            search.addEventListener('input', () => setSearch(search.value));
        }

        viewport.addEventListener('wheel', onWheel, { passive: false });
        document.querySelectorAll('[data-fm-zoom]').forEach(button => {
            button.addEventListener('click', () => {
                const action = button.dataset.fmZoom;
                if (action === 'in') setZoom(state.zoom * ZOOM_STEP);
                else if (action === 'out') setZoom(state.zoom / ZOOM_STEP);
                else if (action === 'fit') setZoom(fitZoom());
                else setZoom(1);
            });
        });

        svg.addEventListener('pointerdown', onPointerDown);
        svg.addEventListener('pointermove', onPointerMove);
        svg.addEventListener('pointerup', onPointerUp);
        svg.addEventListener('pointercancel', onPointerUp);
        svg.addEventListener('pointerleave', hideTooltip);
        svg.addEventListener('dblclick', event => {
            if (state.mode === 'edit' && DRAW_TOOLS[state.tool] && state.draft) {
                event.preventDefault();
                finishDraft();
            }
        });
        document.addEventListener('keydown', onKeyDown);

        // Someone else changed a map, or the collector found PCs on new ports:
        // reload, unless the user is busy here.
        const refresh = () => {
            const busy = state.pointer || state.draft || state.nudge || panel.contains(document.activeElement);
            if (busy) state.refreshPending = true;
            else reload({ panelToo: true }).catch(() => {});
        };
        document.body.addEventListener('maps-changed', refresh);
        document.body.addEventListener('inventory-changed', refresh);
        panel.addEventListener('focusout', () => {
            setTimeout(() => {
                if (state.refreshPending && !panel.contains(document.activeElement) && !state.pointer && !state.draft) {
                    state.refreshPending = false;
                    reload({ panelToo: true }).catch(() => {});
                }
            }, 0);
        });

        syncToolbar();
        render();
        renderPanel();
        state.zoom = readZoom();
        applyZoom();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
