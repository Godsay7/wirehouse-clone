// Rack Change editor: draw cables, connect/disconnect ports, port notes.
//
// The editor lives in #rack-change-root, which htmx replaces in place after
// every form submit, side/rack/room switch, connection change or data update
// (see templates/rack_change.html). init() runs on page load and again after
// every swap; listeners on window/document are registered only once.
(() => {
    // Interface language (static/js/i18n.js); plain text if it is not loaded.
    const t = (text, values) => (window.t ? window.t(text, values) : text);
    const tn = (one, many, n, values) => (window.tn ? window.tn(one, many, n, values) : (n === 1 ? one : many).replace('{n}', n));
    const tm = text => (window.tm ? window.tm(text) : text);
    // Changes need a signed-in user: otherwise js/auth.js shows "Sign in…".
    const canEdit = () => !window.WirehouseAuth || window.WirehouseAuth.ensure();

    const ROOT_ID = 'rack-change-root';
    const ROOT_SELECTOR = `#${ROOT_ID}`;

    // Functions of the currently initialised editor (used by global listeners).
    let current = null;

    // Re-render the editor in place (no full page reload).
    function refreshRack(url) {
        const target = url || currentUrlWithoutError();
        return htmx.ajax('GET', target, {
            target: ROOT_SELECTOR,
            select: ROOT_SELECTOR,
            swap: 'outerHTML',
        });
    }

    // Navigate to another rack/room through htmx so the URL is pushed too.
    function navigate(url) {
        const root = document.getElementById(ROOT_ID);
        if (!root || typeof htmx === 'undefined') {
            window.location.href = url;
            return;
        }
        const link = document.createElement('a');
        link.href = url;
        link.hidden = true;
        root.appendChild(link);
        htmx.process(link);
        link.click();
    }

    function currentUrlWithoutError() {
        const url = new URL(window.location.href);
        url.searchParams.delete('error');
        return url.pathname + url.search;
    }

    // Zoom of the rack being edited, remembered in the browser. 1 = natural size.
    const ZOOM_KEY = 'switch-inventory-rack-change-zoom';
    const ZOOM_MIN = 0.25;
    const ZOOM_MAX = 3;
    const ZOOM_STEP = 1.25;
    let rackZoom = 1;
    let zoomChosen = false;   // false: nothing saved yet, phones start with Fit
    let portMenuMode = false; // "Port menu" on: tapping a port opens its menu
    try {
        const saved = Number(localStorage.getItem(ZOOM_KEY));
        if (Number.isFinite(saved) && saved > 0) {
            rackZoom = saved;
            zoomChosen = true;
        }
    } catch (_error) { }

    function init() {
    const configNode = document.getElementById('rack-change-config');
    if (!configNode) return;

    const config = JSON.parse(configNode.textContent);
    const rackId = config.rackId;
    const currentSide = config.currentSide;
    const connections = config.connections || [];
    const shell = document.getElementById('rack-visual-shell');
    const statusBox = document.getElementById('connection-status');
    const rackSelector = document.getElementById('rack-selector');
    const serverRoomSelector = document.getElementById('server-room-selector');

    // Natural sort for rack names: Rack 1, Rack 2, ... Rack 10, Rack 11.
    // Plain alphabetical sorting would place Rack 10 immediately after Rack 1.
    if (rackSelector) {
        const collator = new Intl.Collator(undefined, {
            numeric: true,
            sensitivity: 'base'
        });
        const options = Array.from(rackSelector.options);
        options
            .sort((a, b) => collator.compare(a.textContent.trim(), b.textContent.trim()))
            .forEach(option => rackSelector.appendChild(option));
    }
    const clearSelectionButton = document.getElementById('clear-connection-selection');

    const selectionStorageKey = 'switch-inventory-rack-pending-endpoint-v18';
    let pendingEndpoint = loadPendingEndpoint();

    const connectionByElement = new Map();
    const connectionById = new Map();

    connections.forEach(connection => {
        connectionById.set(String(connection.id), connection);
        connectionByElement.set(connection.endpoint_a_element_id, connection);
        connectionByElement.set(connection.endpoint_b_element_id, connection);
    });

    if (serverRoomSelector) {
        serverRoomSelector.addEventListener('change', event => {
            navigate(`${config.homeUrl}?room_id=${encodeURIComponent(event.target.value)}&side=${currentSide}`);
        });
    }

    if (rackSelector) {
        rackSelector.addEventListener('change', event => {
            navigate(`/rack-change/${encodeURIComponent(event.target.value)}?side=${currentSide}`);
        });
    }

    function setStatus(text) {
        if (statusBox) statusBox.textContent = text;
    }

    function sideLabel(side) {
        return String(side || '').toLowerCase() === 'rear' ? t('Rear') : t('Front');
    }

    function formatLocation(roomName, rackName, side) {
        const parts = [];
        if (roomName) parts.push(roomName);
        if (rackName) parts.push(rackName);
        if (side) parts.push(sideLabel(side));
        return parts.length ? parts.join(' / ') : t('Rack location unknown');
    }

    function endpointElementId(endpoint) {
        if (!endpoint) return '';
        if (endpoint.type === 'switch') return `switch-${endpoint.switch_id}-port-${endpoint.switch_port}`;
        if (endpoint.type === 'patch') return `patch-${endpoint.patch_panel_id}-port-${endpoint.patch_port}`;
        if (endpoint.type === 'server') return `server-${endpoint.server_id}-port-${endpoint.server_port}`;
        if (endpoint.type === 'placeholder') return `placeholder-${endpoint.placeholder_id}-port-${endpoint.placeholder_port}`;
        return '';
    }

    function endpointFromElement(element) {
        const type = element.dataset.endpointType;
        const common = {
            type,
            label: element.dataset.endpointLabel || element.id,
            location: element.dataset.endpointLocation || '',
        };

        if (type === 'switch') {
            return { ...common, switch_id: Number(element.dataset.switchId), switch_port: Number(element.dataset.switchPort) };
        }
        if (type === 'patch') {
            return { ...common, patch_panel_id: Number(element.dataset.patchPanelId), patch_port: Number(element.dataset.patchPort), patch_type: normalizePatchType(element.dataset.patchType) };
        }
        if (type === 'server') {
            return { ...common, server_id: Number(element.dataset.serverId), server_port: Number(element.dataset.serverPort) };
        }
        if (type === 'placeholder') {
            return { ...common, placeholder_id: Number(element.dataset.placeholderId), placeholder_port: Number(element.dataset.placeholderPort) };
        }
        return null;
    }

    function normalizePatchType(value) {
        const normalized = String(value || 'ethernet').toLowerCase();
        return ['ethernet', 'sdi', 'odf'].includes(normalized) ? normalized : 'ethernet';
    }

    function endpointMedia(endpoint) {
        if (!endpoint) return '';
        if (endpoint.type === 'patch') return normalizePatchType(endpoint.patch_type);
        return 'ethernet'; 
    }

    function connectionCompatibilityError(first, second) {
        if (!first || !second) return t('Select two endpoints.');

        if (sameEndpoint(first, second)) {
            return t('Cannot connect a port to itself.');
        }

        const firstMedia = endpointMedia(first);
        const secondMedia = endpointMedia(second);
        const networkTypes = ['switch', 'server', 'placeholder'];
        const firstIsNetwork = networkTypes.includes(first.type);
        const secondIsNetwork = networkTypes.includes(second.type);

        // SDI is completely separate from network/fiber ports.
        if (firstMedia === 'sdi' || secondMedia === 'sdi') {
            if (first.type === 'patch' && second.type === 'patch'
                && firstMedia === 'sdi' && secondMedia === 'sdi') {
                return '';
            }
            return t('SDI ports can only connect to other SDI patch-panel ports.');
        }

        // ODF may connect directly to another ODF or to a switch/server port.
        if (firstMedia === 'odf' || secondMedia === 'odf') {
            const validFiberLink =
                (firstMedia === 'odf' && (secondMedia === 'odf' || secondIsNetwork))
                || (secondMedia === 'odf' && (firstMedia === 'odf' || firstIsNetwork));

            if (validFiberLink) return '';
            return t('ODF ports can only connect to ODF, switch, or server ports.');
        }

        if (firstMedia !== secondMedia) {
            return t('Media mismatch: {a} cannot connect to {b}.', { a: firstMedia.toUpperCase(), b: secondMedia.toUpperCase() });
        }

        return '';
    }

    function validPendingEndpoint(endpoint) {
        if (!endpoint || !endpoint.type) return false;
        // Port 0: the management port (mng) of a switch, like a server's.
        if (endpoint.type === 'switch') return Number(endpoint.switch_id) > 0 && Number(endpoint.switch_port) >= 0;
        if (endpoint.type === 'patch') {
            endpoint.patch_type = normalizePatchType(endpoint.patch_type);
            return Number(endpoint.patch_panel_id) > 0 && Number(endpoint.patch_port) > 0;
        }
        if (endpoint.type === 'server') return Number(endpoint.server_id) > 0 && Number(endpoint.server_port) >= 0;
        if (endpoint.type === 'placeholder') return Number(endpoint.placeholder_id) > 0 && Number(endpoint.placeholder_port) > 0;
        return false;
    }

    function loadPendingEndpoint() {
        try {
            const raw = localStorage.getItem(selectionStorageKey);
            if (!raw) return null;
            const endpoint = JSON.parse(raw);
            return validPendingEndpoint(endpoint) ? endpoint : null;
        } catch (_error) {
            return null;
        }
    }

    function savePendingEndpoint(endpoint) {
        pendingEndpoint = endpoint;
        try {
            localStorage.setItem(selectionStorageKey, JSON.stringify(endpoint));
        } catch (_error) {}
        syncSelectedPort();
        renderPendingStatus();
    }

    function clearPendingEndpoint() {
        pendingEndpoint = null;
        try {
            localStorage.removeItem(selectionStorageKey);
        } catch (_error) {}
        syncSelectedPort();
        renderPendingStatus();
    }

    function sameEndpoint(first, second) {
        if (!first || !second || first.type !== second.type) return false;
        if (first.type === 'switch') return Number(first.switch_id) === Number(second.switch_id) && Number(first.switch_port) === Number(second.switch_port);
        if (first.type === 'patch') return Number(first.patch_panel_id) === Number(second.patch_panel_id) && Number(first.patch_port) === Number(second.patch_port);
        if (first.type === 'server') return Number(first.server_id) === Number(second.server_id) && Number(first.server_port) === Number(second.server_port);
        if (first.type === 'placeholder') return Number(first.placeholder_id) === Number(second.placeholder_id) && Number(first.placeholder_port) === Number(second.placeholder_port);
        return false;
    }

    function syncSelectedPort() {
        document.querySelectorAll('.rack-port.selected').forEach(element => {
            element.classList.remove('selected');
        });
        if (pendingEndpoint) {
            const element = document.getElementById(endpointElementId(pendingEndpoint));
            if (element) element.classList.add('selected');
        }
        if (clearSelectionButton) {
            clearSelectionButton.classList.toggle('visible', Boolean(pendingEndpoint));
        }
    }

    function renderPendingStatus() {
        if (!pendingEndpoint) {
            setStatus(t('Select a port to start a connection. Ethernet and ODF may connect to switch/server ports.'));
            return;
        }

        let endpointType = '';
        if (pendingEndpoint.type === 'switch') endpointType = t('Switch port');
        else if (pendingEndpoint.type === 'server') endpointType = t('Server port');
        else if (pendingEndpoint.type === 'placeholder') endpointType = t('Temporary switch port');
        else endpointType = t('{media} patch-panel port', { media: endpointMedia(pendingEndpoint).toUpperCase() });

        const location = pendingEndpoint.location ? ` — ${pendingEndpoint.location}` : '';

        let hint = t('Select a compatible endpoint.');
        if (endpointMedia(pendingEndpoint) === 'sdi') {
            hint = t('Select another SDI patch-panel port.');
        } else if (endpointMedia(pendingEndpoint) === 'odf') {
            hint = t('Select an ODF patch-panel port, a switch port, or a server port.');
        } else {
            hint = t('Select an Ethernet patch-panel port, a switch port, or a server port.');
        }

        setStatus(t('{what} selected: {label}{location}. {hint}', { what: endpointType, label: pendingEndpoint.label, location, hint }));
    }

    function connectionSummary(connection) {
        return `${tm(connection.endpoint_a_label)} (${tm(connection.endpoint_a_location)}) ↔ `
            + `${tm(connection.endpoint_b_label)} (${tm(connection.endpoint_b_location)})`;
    }

    function remoteEndpointDescription(connection, localElementId) {
        if (localElementId === connection.endpoint_a_element_id) {
            return `${tm(connection.endpoint_b_label)} — ${tm(connection.endpoint_b_location)}`;
        }
        return `${tm(connection.endpoint_a_label)} — ${tm(connection.endpoint_a_location)}`;
    }

    function markConnections() {
        connections.forEach(connection => {
            const firstElement = document.getElementById(connection.endpoint_a_element_id);
            const secondElement = document.getElementById(connection.endpoint_b_element_id);
            const mediaClass = `connected-${connection.cable_type || 'ethernet'}`;

            [firstElement, secondElement].forEach(element => {
                if (!element) return;
                element.classList.add('connected', mediaClass);
                element.dataset.connectionId = connection.id;

                if (!element.dataset.connectionTooltipAdded) {
                    const remote = remoteEndpointDescription(connection, element.id);
                    element.title = `${element.title}\n${t('Connected to:')} ${remote}`;
                    element.dataset.connectionTooltipAdded = '1';
                }
            });
        });
    }

    // Cable lines: static/js/rack_cables.js
    function drawConnections() {
        if (shell) window.RackCables.draw(shell, connections);
    }

    function highlightConnection(connectionId, enabled) {
        window.RackCables.highlight(shell, connectionById.get(String(connectionId)), enabled);
    }

    async function connectEndpoints(firstEndpoint, secondEndpoint, replace = false) {
        const compatibilityError = connectionCompatibilityError(firstEndpoint, secondEndpoint);
        if (compatibilityError) {
            setStatus(t('Error: {message}', { message: compatibilityError }));
            return;
        }

        setStatus(t('Connecting {a} ({a_where}) ↔ {b} ({b_where})...', {
            a: firstEndpoint.label, a_where: firstEndpoint.location, b: secondEndpoint.label, b_where: secondEndpoint.location,
        }));

        try {
            const response = await fetch(config.connectUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    first_endpoint: firstEndpoint,
                    second_endpoint: secondEndpoint,
                    replace,
                }),
            });

            const result = await response.json();

            // A port already has a cable: replace it only if the user agrees.
            if (response.status === 409 && result.needs_confirm) {
                const lines = (result.conflicts || []).map(text => `• ${tm(text)}`).join('\n');
                if (window.confirm(`${t('This will remove the existing cable:')}\n${lines}\n\n${t('Replace it?')}`)) {
                    return connectEndpoints(firstEndpoint, secondEndpoint, true);
                }
                setStatus(t('Cancelled: the existing cable was kept.'));
                return;
            }

            if (!response.ok || !result.ok) {
                throw new Error(result.error || t('Connection failed'));
            }

            try {
                localStorage.removeItem(selectionStorageKey);
            } catch (_error) {}

            refreshRack();
        } catch (error) {
            setStatus(t('Error: {message}', { message: tm(error.message) }));
        }
    }

    async function disconnect(connectionId) {
        const response = await fetch(`/rack/disconnect/${connectionId}`, {
            method: 'POST',
        });

        const result = await response.json();

        if (!response.ok || !result.ok) {
            throw new Error(result.error || t('Disconnect failed'));
        }

        refreshRack();
    }

    if (clearSelectionButton) {
        clearSelectionButton.addEventListener('click', clearPendingEndpoint);
    }

    document.querySelectorAll('.rack-port').forEach(element => {
        element.addEventListener('mouseenter', () => {
            const connection = connectionByElement.get(element.id);
            if (!connection) return;

            highlightConnection(connection.id, true);
            setStatus(t('Connected: {what}', { what: connectionSummary(connection) }));
        });

        element.addEventListener('mouseleave', () => {
            const connection = connectionByElement.get(element.id);
            if (connection) highlightConnection(connection.id, false);
            renderPendingStatus();
        });

        // Port menu styles: css/rack/rack-devices.css

        let contextMenu = document.getElementById('port-context-menu');
        if (!contextMenu) {
            contextMenu = document.createElement('div');
            contextMenu.id = 'port-context-menu';
            document.body.appendChild(contextMenu);
            document.addEventListener('click', () => { contextMenu.style.display = 'none'; });
        }

        element.addEventListener('contextmenu', event => {
            event.preventDefault();
            openPortMenu(element, event.pageX, event.pageY);
        });

        element.addEventListener('click', event => {
            // Phones: with "Port menu" on, a tap opens the menu instead.
            if (!portMenuMode) return;
            event.stopPropagation();
            event.stopImmediatePropagation();
            const rect = element.getBoundingClientRect();
            openPortMenu(element, rect.left + window.scrollX, rect.bottom + window.scrollY + 4);
        });

        element.addEventListener('click', () => {
            if (portMenuMode) return;
            const clickedEndpoint = endpointFromElement(element);
            if (!clickedEndpoint) return;
            // Connecting ports needs a signed-in user (js/auth.js).
            if (!canEdit()) return;

            if (pendingEndpoint && sameEndpoint(pendingEndpoint, clickedEndpoint)) {
                clearPendingEndpoint();
                return;
            }

            if (!pendingEndpoint) {
                savePendingEndpoint(clickedEndpoint);
                return;
            }

            const compatibilityError = connectionCompatibilityError(pendingEndpoint, clickedEndpoint);

            if (compatibilityError) {
                setStatus(t('Error: {message}', { message: compatibilityError }));
                return;
            }

            element.classList.add('selected');
            connectEndpoints(pendingEndpoint, clickedEndpoint);
        });
    });

    // Menu of one port: description, cable path, disconnect. Opened by a
    // right click, or by a tap while "Port menu" is on.
    function openPortMenu(element, pageX, pageY) {
            const connection = connectionByElement.get(element.id);
            const clickedEndpoint = endpointFromElement(element);
            if (!clickedEndpoint) return;

            let contextMenu = document.getElementById('port-context-menu');
            if (!contextMenu) {
                contextMenu = document.createElement('div');
                contextMenu.id = 'port-context-menu';
                Object.assign(contextMenu.style, {
                    position: 'absolute', display: 'none', backgroundColor: '#111820',
                    border: '1px solid #687684', borderRadius: '6px',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.8)', zIndex: '9999',
                    padding: '4px 0', minWidth: '160px', fontFamily: 'sans-serif',
                    fontSize: '13px', color: '#f8fafc'
                });
                document.body.appendChild(contextMenu);
                document.addEventListener('click', () => { contextMenu.style.display = 'none'; });
            }

            contextMenu.innerHTML = '';

            const descBtn = document.createElement('div');
            descBtn.textContent = t('Edit Description');
            Object.assign(descBtn.style, { padding: '8px 16px', cursor: 'pointer' });
            descBtn.onmouseenter = () => descBtn.style.backgroundColor = '#293846';
            descBtn.onmouseleave = () => descBtn.style.backgroundColor = 'transparent';
            descBtn.onclick = async () => {
                if (!canEdit()) return;
                const newDesc = prompt(t('Enter custom note for {label}:', { label: clickedEndpoint.label }));
                if (newDesc !== null) {
                    try {
                        const response = await fetch('/rack/port/description', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ endpoint: clickedEndpoint, description: newDesc })
                        });
                        if (response.ok) refreshRack();
                        else alert('Failed to save description on server');
                    } catch (err) { alert('Request failed'); }
                }
            };
            contextMenu.appendChild(descBtn);

            if (window.CablePath && window.CablePath.canTrace(element)) {
                const pathBtn = document.createElement('div');
                pathBtn.textContent = t('Show Cable Path');
                Object.assign(pathBtn.style, { padding: '8px 16px', cursor: 'pointer' });
                pathBtn.onmouseenter = () => pathBtn.style.backgroundColor = '#293846';
                pathBtn.onmouseleave = () => pathBtn.style.backgroundColor = 'transparent';
                pathBtn.onclick = () => window.CablePath.open(element);
                contextMenu.appendChild(pathBtn);
            }

            if (connection) {
                const discBtn = document.createElement('div');
                discBtn.textContent = t('Disconnect');
                Object.assign(discBtn.style, { padding: '8px 16px', cursor: 'pointer', color: '#ff4d4d' });
                discBtn.onmouseenter = () => { discBtn.style.backgroundColor = '#ff4d4d'; discBtn.style.color = '#fff'; };
                discBtn.onmouseleave = () => { discBtn.style.backgroundColor = 'transparent'; discBtn.style.color = '#ff4d4d'; };
                discBtn.onclick = async () => {
                    if (!canEdit()) return;
                    if (!confirm(t('Disconnect {what}?', { what: connectionSummary(connection) }))) return;
                    try { await disconnect(connection.id); } 
                    catch (error) { setStatus(t('Error: {message}', { message: tm(error.message) })); }
                };
                contextMenu.appendChild(discBtn);
            }

            contextMenu.style.left = `${pageX}px`;
            contextMenu.style.top = `${pageY}px`;
            contextMenu.style.display = 'block';

            // Keep the menu on screen (phones are narrow).
            const menuRect = contextMenu.getBoundingClientRect();
            const overflowX = menuRect.right - (document.documentElement.clientWidth - 8);
            if (overflowX > 0) contextMenu.style.left = `${Math.max(8, pageX - overflowX)}px`;
    }

    // "Port menu" switch (shown on touch screens, where there is no right click).
    function syncPortMenuButton() {
        document.querySelectorAll('[data-rc-port-menu]').forEach(button => {
            button.classList.toggle('active', portMenuMode);
            button.setAttribute('aria-pressed', String(portMenuMode));
        });
        document.body.classList.toggle('rack-port-menu-mode', portMenuMode);
    }

    document.querySelectorAll('[data-rc-port-menu]').forEach(button => {
        button.addEventListener('click', event => {
            event.stopPropagation();
            portMenuMode = !portMenuMode;
            syncPortMenuButton();
            if (portMenuMode) setStatus(t('Port menu: tap a port to open its menu (description, cable path, disconnect).'));
            else renderPendingStatus();
        });
    });
    syncPortMenuButton();
    if (portMenuMode) setStatus(t('Port menu: tap a port to open its menu (description, cable path, disconnect).'));

    {
        document.querySelectorAll('.rack-add-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const targetId = this.getAttribute('data-target');
                const formPopup = document.getElementById(targetId);
            
                formPopup.style.display = 'block';
                this.style.display = 'none';
            });
        });

        document.querySelectorAll('.rack-form-close').forEach(closeBtn => {
            closeBtn.addEventListener('click', function() {
                const formPopup = this.closest('.rack-form-popup');
                const triggerId = formPopup.getAttribute('data-trigger');
                const triggerBtn = document.getElementById(triggerId);
            
                formPopup.style.display = 'none';
                if (triggerBtn) triggerBtn.style.display = 'block';
            });
        });
    }

    markConnections();
    syncSelectedPort();
    if (rackId) renderPendingStatus();

    requestAnimationFrame(() => {
        drawConnections();
        setTimeout(drawConnections, 120);
    });

    // ------------------------------------------------------------
    // Zoom
    // ------------------------------------------------------------

    const zoomViewport = shell ? shell.closest('.rack-viewport') : null;
    const rackScroller = shell ? shell.closest('.rack-main') : null;

    function applyZoom() {
        if (!shell) return;
        shell.style.zoom = String(rackZoom);
        document.querySelectorAll('.rack-change-zoom-level').forEach(label => {
            label.textContent = `${Math.round(rackZoom * 100)}%`;
        });
    }

    // action: 'in' | 'out' | 'reset' | 'fit' | a number. The point under
    // (clientX, clientY), or the middle of the window, stays in place.
    function setZoom(action, clientX, clientY) {
        if (!shell) return;

        let zoom = rackZoom;
        if (action === 'in') zoom = rackZoom * ZOOM_STEP;
        else if (action === 'out') zoom = rackZoom / ZOOM_STEP;
        else if (action === 'reset') zoom = 1;
        else if (action === 'fit') zoom = fitZoom();
        else if (typeof action === 'number') zoom = action;
        zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom));

        const anchorX = clientX === undefined ? window.innerWidth / 2 : clientX;
        const anchorY = clientY === undefined ? window.innerHeight / 2 : clientY;
        const before = shell.getBoundingClientRect();
        const relX = (anchorX - before.left) / (before.width || 1);
        const relY = (anchorY - before.top) / (before.height || 1);

        rackZoom = zoom;
        zoomChosen = true;
        try { localStorage.setItem(ZOOM_KEY, String(zoom)); } catch (_error) { }
        applyZoom();

        const after = shell.getBoundingClientRect();
        const dx = after.left + relX * after.width - anchorX;
        const dy = after.top + relY * after.height - anchorY;
        // On narrow screens the rack scrolls sideways inside .rack-main.
        if (rackScroller && rackScroller.scrollWidth > rackScroller.clientWidth) {
            rackScroller.scrollLeft += dx;
            window.scrollBy(0, dy);
        } else {
            window.scrollBy(dx, dy);
        }
        requestAnimationFrame(drawConnections);
    }

    // Zoom at which the rack is as wide as the space it has.
    function fitZoom() {
        const left = (zoomViewport || shell).getBoundingClientRect().left;
        let available = document.documentElement.clientWidth - Math.max(0, left) - 16;
        if (rackScroller && getComputedStyle(rackScroller).overflowX === 'auto') {
            available = Math.min(available, rackScroller.clientWidth - 4);
        }
        return available / (shell.offsetWidth || 1);
    }

    document.querySelectorAll('[data-rc-zoom]').forEach(button => {
        button.addEventListener('click', () => setZoom(button.dataset.rcZoom));
    });

    if (zoomViewport) {
        // Ctrl + wheel (or a touchpad pinch) zooms the rack around the pointer.
        zoomViewport.addEventListener('wheel', event => {
            if (!(event.ctrlKey || event.metaKey)) return;
            event.preventDefault();
            setZoom(rackZoom * Math.exp(-event.deltaY * 0.0025), event.clientX, event.clientY);
        }, { passive: false });
    }

    applyZoom();

    // First visit on a phone: show the whole rack width (not saved, so
    // the user's own choice still wins later).
    if (shell && !zoomChosen && window.matchMedia('(max-width: 720px)').matches) {
        rackZoom = Math.min(1, Math.max(ZOOM_MIN, fitZoom()));
        applyZoom();
    }

    current = { drawConnections, setZoom };
    }

    // ------------------------------------------------------------
    // Global listeners (registered once)
    // ------------------------------------------------------------

    // + / − / 0 zoom the rack (not while typing in a form field).
    document.addEventListener('keydown', event => {
        if (!current || !current.setZoom) return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.target.closest && event.target.closest('input, textarea, select, [contenteditable]')) return;
        if (event.key === '+' || event.key === '=') current.setZoom('in');
        else if (event.key === '-' || event.key === '_') current.setZoom('out');
        else if (event.key === '0') current.setZoom('reset');
    });

    window.addEventListener('resize', () => {
        if (current) current.drawConnections();
    });

    // Keep the scroll position of the rack viewport across swaps.
    let savedViewportScroll = null;

    document.addEventListener('htmx:beforeSwap', event => {
        if (!event.detail.target || event.detail.target.id !== ROOT_ID) return;
        const viewport = document.querySelector(`${ROOT_SELECTOR} .rack-viewport`);
        savedViewportScroll = viewport
            ? { top: viewport.scrollTop, left: viewport.scrollLeft }
            : null;
    });

    document.addEventListener('htmx:afterSettle', () => {
        if (!document.getElementById(ROOT_ID)) return;

        init();

        const viewport = document.querySelector(`${ROOT_SELECTOR} .rack-viewport`);
        if (viewport && savedViewportScroll) {
            viewport.scrollTop = savedViewportScroll.top;
            viewport.scrollLeft = savedViewportScroll.left;
        }
        savedViewportScroll = null;
    });

    // Somebody else changed racks (or the collector refreshed port states):
    // re-render, unless the user is in the middle of filling in a form.
    function refreshIfIdle() {
        const root = document.getElementById(ROOT_ID);
        if (!root) return;

        const formOpen = Array.from(root.querySelectorAll('.rack-form-popup'))
            .some(popup => popup.style.display !== 'none');
        const typing = root.contains(document.activeElement)
            && document.activeElement.matches('input, select, textarea');
        const menu = document.getElementById('port-context-menu');
        const menuOpen = menu && menu.style.display === 'block';

        if (!formOpen && !typing && !menuOpen) refreshRack();
    }

    document.addEventListener('rack-changed', refreshIfIdle);
    document.addEventListener('inventory-changed', refreshIfIdle);

    document.addEventListener('DOMContentLoaded', init);
})();

// Opened from the dashboard search (?focus=switch-3-port-12): show that port.
document.addEventListener('DOMContentLoaded', () => {
    const id = new URLSearchParams(window.location.search).get('focus');
    const element = id && document.getElementById(id);
    if (!element) return;
    setTimeout(() => {
        element.scrollIntoView({ block: 'center', inline: 'center' });
        element.classList.add('search-focus');
        setTimeout(() => element.classList.remove('search-focus'), 6000);
    }, 300);
});

