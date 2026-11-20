// Cable path modal: the full route of a cable through patch cords and
// ODF trunks (same-named ODFs in different server rooms, port N = port N).
// Used by Rack View and Rack Change: CablePath.canTrace(el), CablePath.open(el).
(() => {
    'use strict';

    // Interface language (static/js/i18n.js); plain text if it is not loaded.
    const t = (text, values) => (window.t ? window.t(text, values) : text);
    const tn = (one, many, n, values) => (window.tn ? window.tn(one, many, n, values) : (n === 1 ? one : many).replace('{n}', n));
    const tm = text => (window.tm ? window.tm(text) : text);

    // Translated when shown: this file may run before i18n.js.
    const END_MESSAGES = {
        not_patched: 'Port is not patched',
        no_trunk: 'No ODF with the same name in another server room',
        patch_panel: 'Patch panel: cabling behind it is not tracked',
        ambiguous: 'Several cables or same-named ODFs here — the path is ambiguous',
        loop: 'The path loops back to a port already on it',
        too_long: 'The path is too long to show',
    };

    const TYPE_LABELS = { switch: 'Switch', server: 'Server', patch: 'Patch panel', placeholder: 'Temporary switch' };

    function endpointQuery(element) {
        const data = element.dataset;
        const fields = {
            switch: [data.switchId, data.switchPort],
            patch: [data.patchPanelId, data.patchPort],
            server: [data.serverId, data.serverPort],
            placeholder: [data.placeholderId, data.placeholderPort],
        }[data.endpointType];

        if (!fields || fields.some(value => value === undefined || value === '')) return null;
        return new URLSearchParams({ type: data.endpointType, id: fields[0], port: fields[1] });
    }

    function canTrace(element) {
        if (!element || !endpointQuery(element)) return false;
        return element.dataset.patchType === 'odf' || element.classList.contains('connected-fiber');
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function typeLabel(endpoint) {
        if (endpoint.type === 'patch' && endpoint.patch_type === 'odf') return 'ODF';
        if (endpoint.type === 'patch' && endpoint.patch_type === 'sdi') return t('SDI patch');
        return TYPE_LABELS[endpoint.type] ? t(TYPE_LABELS[endpoint.type]) : endpoint.type;
    }

    function endpointText(endpoint) {
        return `${endpoint.name} · ${tm(endpoint.port_label)}`;
    }

    function renderEndpoint(endpoint, isStart) {
        const card = el('div', `cable-path-node cable-path-node-${endpoint.type}${endpoint.patch_type ? ` cable-path-node-${endpoint.patch_type}` : ''}${isStart ? ' is-start' : ''}`);

        const head = el('div', 'cable-path-node-head');
        head.append(el('span', 'cable-path-badge', typeLabel(endpoint)));
        head.append(el('span', 'cable-path-node-name', endpoint.name));
        head.append(el('span', 'cable-path-node-port', tm(endpoint.port_label)));
        if (isStart) head.append(el('span', 'cable-path-here', t('selected port')));
        card.append(head);

        const where = [endpoint.rack, endpoint.side && t(endpoint.side)].filter(Boolean).join(' · ');
        if (where) card.append(el('div', 'cable-path-node-meta', where));
        if (endpoint.description) card.append(el('div', 'cable-path-node-note', endpoint.description));

        return card;
    }

    function renderEnd(reason) {
        if (!reason || reason === 'device') return null;
        return el('div', 'cable-path-end', END_MESSAGES[reason] ? t(END_MESSAGES[reason]) : reason);
    }

    function renderPath(data) {
        const body = el('div', 'cable-path-body');
        const { endpoints, links, ends, start } = data;
        const startId = `${start.type}-${start.id}-port-${start.port}`;

        const first = endpoints[0];
        const last = endpoints[endpoints.length - 1];
        const summary = el('div', `cable-path-summary ${data.complete ? 'is-complete' : 'is-open'}`);
        summary.append(el('span', 'cable-path-status', data.complete ? t('Complete') : t('Incomplete')));
        summary.append(el('span', 'cable-path-summary-text',
            endpoints.length > 1 ? `${endpointText(first)}  →  ${endpointText(last)}` : endpointText(first)));
        const trunks = links.filter(link => link.kind === 'trunk').length;
        summary.append(el('span', 'cable-path-summary-meta',
            [tn('{n} port', '{n} ports', endpoints.length), tn('{n} patch cord', '{n} patch cords', links.length - trunks), tn('{n} trunk', '{n} trunks', trunks)].join(' · ')));
        body.append(summary);

        const startEnd = renderEnd(ends[0]);
        if (startEnd) body.append(startEnd);

        // One block per server room; trunks are drawn between the blocks.
        let room = null;
        endpoints.forEach((endpoint, index) => {
            if (index === 0 || links[index - 1].kind === 'trunk') {
                if (index > 0) {
                    const link = links[index - 1];
                    const trunk = el('div', 'cable-path-trunk');
                    trunk.append(el('span', 'cable-path-link-kind', link.from_room === link.to_room ? t('Trunk') : t('Trunk between rooms')));
                    trunk.append(el('span', 'cable-path-link-detail',
                        `${link.from_room || '?'} → ${link.to_room || '?'} · ${t('fibre {n}', { n: endpoint.port })}${link.trunk_name ? ` · ${link.trunk_name}` : ''}`));
                    body.append(trunk);
                }
                room = el('section', 'cable-path-room');
                room.append(el('div', 'cable-path-room-name', endpoint.room || t('Unknown room')));
                body.append(room);
            } else {
                const link = links[index - 1];
                const cord = el('div', `cable-path-cord cable-path-cord-${link.cable_type}`);
                cord.append(el('span', 'cable-path-link-kind', link.cable_type === 'fiber' ? t('Fibre patch cord') : t('Patch cord')));
                if (link.cable_label) cord.append(el('span', 'cable-path-link-detail', link.cable_label));
                room.append(cord);
            }

            room.append(renderEndpoint(endpoint, endpoint.element_id === startId));
        });

        const lastEnd = renderEnd(ends[1]);
        if (lastEnd) body.append(lastEnd);

        return body;
    }

    let dialog = null;

    function ensureDialog() {
        if (dialog) return dialog;

        dialog = el('div', 'cable-path-backdrop');
        dialog.hidden = true;
        dialog.innerHTML = `
            <div class="cable-path-dialog" role="dialog" aria-modal="true" aria-labelledby="cable-path-title">
                <div class="cable-path-header">
                    <h2 id="cable-path-title">${t('Cable path')}</h2>
                    <button type="button" class="cable-path-close" aria-label="${t('Close')}">×</button>
                </div>
                <div class="cable-path-content"></div>
            </div>`;

        dialog.addEventListener('click', event => {
            if (event.target === dialog || event.target.closest('.cable-path-close')) close();
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && dialog && !dialog.hidden) close();
        });
        document.body.append(dialog);
        return dialog;
    }

    function close() {
        if (dialog) dialog.hidden = true;
    }

    async function open(element) {
        const query = endpointQuery(element);
        if (!query) return;

        const backdrop = ensureDialog();
        const content = backdrop.querySelector('.cable-path-content');
        content.replaceChildren(el('div', 'cable-path-loading', t('Loading…')));
        backdrop.hidden = false;
        backdrop.querySelector('.cable-path-close').focus();

        try {
            const response = await fetch(`/rack/path?${query}`, { headers: { Accept: 'application/json' } });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
            content.replaceChildren(renderPath(data));
        } catch (error) {
            content.replaceChildren(el('div', 'cable-path-end', t('Could not load the path: {message}', { message: tm(error.message) })));
        }
    }

    window.CablePath = { canTrace, open, close };
})();
