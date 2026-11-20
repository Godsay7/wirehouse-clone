// Cable lines of a rack, shared by Rack View and Rack Change.
//
//   RackCables.draw(shell, connections)       draw every cable of the rack
//   RackCables.highlight(shell, connection, on) light up a cable and its ports
//
// A click on a cable line keeps it lit, as if the mouse were over it, until
// a click anywhere else or Esc. Every line has a wider invisible twin
// (.connection-hit) on top, so a thin line is easy to hit.
//
// A cable leaves its port up or down, runs sideways to a vertical lane in the
// strip between the rack frame and the edge of the component, and comes back
// to the other port. Lanes are given out so that cables whose vertical runs
// overlap do not share one while there is room: short cables stay next to the
// frame, long ones go outside them, so lines cross as little as possible.
// Line styles: css/rack/rack-devices.css and rack.css (.connection-path).
(() => {
    'use strict';

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const GAP = 6;             // the first lane is this far from the frame
    const MAX_STEP = 4;        // distance between lanes when there is room
    const MIN_STEP = 2;        // closer lines merge into one band; beyond that lanes are shared
    const LEVELS = 3;          // heights of the short run out of a port
    const LEVEL_STEP = 6;
    const FIRST_LEVEL = 7;

    function findPort(shell, elementId) {
        return elementId ? shell.querySelector(`#${CSS.escape(elementId)}`) : null;
    }

    // Ports in the top row of a switch (or of a panel with odd ports on top)
    // leave upwards, all others downwards.
    function direction(element) {
        return element.closest('.rack-switch-port-row-top') || element.classList.contains('patch-port-top') ? -1 : 1;
    }

    function overlap(runs, cable) {
        return runs.reduce((sum, [top, bottom]) =>
            sum + Math.max(0, Math.min(bottom, cable.bottom + 2) - Math.max(top, cable.top - 2)), 0);
    }

    // Lane per cable: interval colouring of the vertical runs, shortest first
    // (they stay next to the frame). With more cables than lanes fit, a cable
    // takes the lane where it overlaps the least.
    function assignLanes(cables, maxLanes) {
        const lanes = [];                       // lanes[i] = list of [top, bottom]
        [...cables].sort((a, b) => (a.bottom - a.top) - (b.bottom - b.top)).forEach(cable => {
            let lane = lanes.findIndex(runs => overlap(runs, cable) === 0);
            if (lane < 0 && lanes.length < maxLanes) {
                lane = lanes.length;
                lanes.push([]);
            } else if (lane < 0) {
                const costs = lanes.map(runs => overlap(runs, cable));
                lane = costs.indexOf(Math.min(...costs));
            }
            lanes[lane].push([cable.top, cable.bottom]);
            cable.lane = lane;
        });
        return lanes.length;
    }

    // Side per cable: long cables choose first, each takes the side where
    // fewer cables already run at its height (relative to the room there);
    // the far side costs extra, the more the further the cable is from the
    // middle, so a cable crosses the rack only when that really thins out the
    // lines (and cables near the middle cross first).
    const FAR_SIDE_COST = 2;
    const FAR_SIDE_DISTANCE_COST = 16;

    function chooseSides(cables, width, fitLeft, fitRight) {
        const placed = { true: [], false: [] };
        const depth = (left, cable) => placed[left].filter(other =>
            other.top < cable.bottom + 2 && cable.top < other.bottom + 2).length;

        [...cables].sort((a, b) => (b.bottom - b.top) - (a.bottom - a.top)).forEach(cable => {
            const mid = (cable.a.x + cable.b.x) / 2;
            const near = mid < width / 2;
            const crossing = FAR_SIDE_COST + FAR_SIDE_DISTANCE_COST * Math.abs(mid - width / 2) / (width / 2);
            const cost = left => (depth(left, cable) + 1) / (left ? fitLeft : fitRight) * Math.max(fitLeft, fitRight)
                + (left === near ? 0 : crossing);
            cable.left = cost(true) <= cost(false);
            placed[cable.left].push(cable);
        });
    }

    function draw(shell, connections) {
        const svg = shell && shell.querySelector('.rack-connections-svg');
        if (!svg) return;

        const width = shell.scrollWidth;
        const height = shell.scrollHeight;
        svg.setAttribute('width', width);
        svg.setAttribute('height', height);
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        svg.replaceChildren();

        // Screen pixels per SVG unit: the rack may be zoomed.
        const shellRect = shell.getBoundingClientRect();
        const scaleX = shell.offsetWidth > 0 ? shellRect.width / shell.offsetWidth : 1;
        const scaleY = shell.offsetHeight > 0 ? shellRect.height / shell.offsetHeight : scaleX;

        const local = rect => ({
            x: (rect.left - shellRect.left + rect.width / 2) / scaleX,
            y: (rect.top - shellRect.top + rect.height / 2) / scaleY,
            half: rect.height / scaleY / 2,
        });

        const frame = shell.querySelector('.rack-frame');
        let frameLeft = 15;
        let frameRight = width - 15;
        if (frame) {
            const rect = frame.getBoundingClientRect();
            frameLeft = (rect.left - shellRect.left) / scaleX;
            frameRight = (rect.right - shellRect.left) / scaleX;
        }

        const cables = [];
        (connections || []).forEach((connection, index) => {
            const first = findPort(shell, connection.endpoint_a_element_id || connection.switch_element_id);
            const second = findPort(shell, connection.endpoint_b_element_id || connection.patch_element_id);
            if (!first || !second) return;

            const a = local(first.getBoundingClientRect());
            const b = local(second.getBoundingClientRect());
            const dirA = direction(first);
            const dirB = direction(second);
            const edgeA = a.y + dirA * a.half;
            const edgeB = b.y + dirB * b.half;
            const level = index % LEVELS;
            const outA = edgeA + dirA * (FIRST_LEVEL + level * LEVEL_STEP);
            const outB = edgeB + dirB * (FIRST_LEVEL + ((level + 1) % LEVELS) * LEVEL_STEP);

            cables.push({
                connection, a, b, edgeA, edgeB, outA, outB,
                top: Math.min(outA, outB),
                bottom: Math.max(outA, outB),
            });
        });

        const room = left => Math.max(0, (left ? frameLeft : width - frameRight) - GAP - 2);
        const fit = left => Math.max(1, Math.floor(room(left) / MIN_STEP) + 1);
        chooseSides(cables, width, fit(true), fit(false));

        [true, false].forEach(left => {
            const side = cables.filter(cable => cable.left === left);
            const count = assignLanes(side, fit(left));
            const step = count > 1 ? Math.min(MAX_STEP, room(left) / (count - 1)) : MAX_STEP;
            side.forEach(cable => {
                const offset = GAP + cable.lane * step;
                cable.x = left ? Math.max(1, frameLeft - offset) : Math.min(width - 1, frameRight + offset);
            });
        });

        const lines = document.createDocumentFragment();
        const hits = document.createDocumentFragment();
        const byId = new Map();
        cables.forEach(({ connection, a, b, edgeA, edgeB, outA, outB, x }) => {
            const d = `M ${a.x} ${edgeA} V ${outA} H ${x} V ${outB} H ${b.x} V ${edgeB}`;
            const path = document.createElementNS(SVG_NS, 'path');
            path.setAttribute('id', `connection-path-${connection.id}`);
            path.setAttribute('class', `connection-path connection-${connection.cable_type || 'ethernet'}`);
            path.dataset.connectionId = String(connection.id);
            path.setAttribute('d', d);
            lines.append(path);

            const hit = document.createElementNS(SVG_NS, 'path');
            hit.setAttribute('class', 'connection-hit');
            hit.dataset.connectionId = String(connection.id);
            hit.setAttribute('d', d);
            hits.append(hit);
            byId.set(String(connection.id), connection);
        });
        svg.append(lines, hits);
        cablesOf.set(shell, byId);
        listen(shell, svg);

        // Redrawn (zoom, side, live update): the clicked cable stays lit.
        if (pinned && pinned.shell === shell) {
            const connection = byId.get(String(pinned.connection.id));
            if (connection) {
                pinned.connection = connection;
                light(shell, connection, true);
            } else {
                pinned = null;
            }
        }
    }

    // --------------------------------------------------------
    // Hover and click on the lines themselves
    // --------------------------------------------------------

    const cablesOf = new WeakMap();      // shell -> Map(connection id -> connection)
    let pinned = null;                   // { shell, connection } lit by a click

    function cableAt(shell, target) {
        const node = target && target.closest ? target.closest('.connection-hit, .connection-path') : null;
        const byId = node && cablesOf.get(shell);
        return byId ? byId.get(node.dataset.connectionId) || null : null;
    }

    function listen(shell, svg) {
        if (svg.dataset.cableEvents) return;
        svg.dataset.cableEvents = '1';
        svg.addEventListener('mouseover', event => {
            const connection = cableAt(shell, event.target);
            if (connection) highlight(shell, connection, true);
        });
        svg.addEventListener('mouseout', event => {
            const connection = cableAt(shell, event.target);
            if (connection && cableAt(shell, event.relatedTarget) !== connection) highlight(shell, connection, false);
        });
    }

    function unpin() {
        if (!pinned) return;
        const { shell, connection } = pinned;
        pinned = null;
        light(shell, connection, false);
    }

    // One listener for every rack on the page: a click on a line lights it,
    // a click anywhere else puts it out.
    document.addEventListener('click', event => {
        const svg = event.target && event.target.closest ? event.target.closest('.rack-connections-svg') : null;
        const shell = svg ? svg.closest('[data-rack-component]') || svg.parentElement : null;
        const connection = shell ? cableAt(shell, event.target) : null;
        if (!connection) {
            unpin();
            return;
        }
        if (pinned && pinned.shell === shell && String(pinned.connection.id) === String(connection.id)) return;
        unpin();
        pinned = { shell, connection };
        light(shell, connection, true);
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') unpin();
    });

    // Hover: lights a cable while the mouse is over it or its port. The cable
    // lit by a click stays lit when the mouse leaves.
    function highlight(shell, connection, enabled) {
        if (!enabled && pinned && pinned.shell === shell && connection
            && String(pinned.connection.id) === String(connection.id)) return;
        light(shell, connection, enabled);
    }

    function light(shell, connection, enabled) {
        if (!shell || !connection) return;
        const svg = shell.querySelector('.rack-connections-svg');
        const path = svg ? svg.querySelector(`.connection-path[data-connection-id="${CSS.escape(String(connection.id))}"]`) : null;
        const ports = [
            findPort(shell, connection.endpoint_a_element_id),
            findPort(shell, connection.endpoint_b_element_id),
        ];

        [...ports, path].forEach(element => {
            if (element) element.classList.toggle('connection-highlight', enabled);
        });
        // The lit cable is drawn over the others (the click targets stay on top).
        const firstHit = svg ? svg.querySelector('.connection-hit') : null;
        if (enabled && path) svg.insertBefore(path, firstHit);
    }

    window.RackCables = { draw, highlight };
})();
