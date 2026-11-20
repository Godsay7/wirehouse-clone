// Switch page: type a device's hostname in by hand (the ✎ next to it).
// The name is kept per MAC, so it follows the device to any port; an empty
// name removes it. Saved through POST /hosts/name (recorded in Rack History).
(() => {
    'use strict';

    const t = (text, values) => (window.t ? window.t(text, values) : text);
    const tm = text => (window.tm ? window.tm(text) : text);

    async function save(url, body, button) {
        button.disabled = true;
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
            window.location.reload();
        } catch (error) {
            button.disabled = false;
            window.alert(t('The hostname was not saved: {message}', { message: tm(error.message) }));
        }
    }

    // The name of a port as a whole: empty / uplink ports, or a name written
    // from the Cabling Check (POST /ports/name).
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-port-edit]');
        if (!button) return;
        event.preventDefault();
        const name = window.prompt(t('Name of the port (leave empty to remove):'), button.dataset.name || '');
        if (name === null) return;
        save('/ports/name', { switch_id: Number(button.dataset.switchId), port: Number(button.dataset.port), name }, button);
    });

    document.addEventListener('click', async event => {
        const button = event.target.closest('[data-host-edit]');
        if (!button) return;
        event.preventDefault();

        const mac = button.dataset.mac;
        const current = button.dataset.name || button.dataset.suggest || '';
        const name = window.prompt(t('Hostname of {mac} (leave empty to remove):', { mac }), current);
        if (name === null) return;

        button.disabled = true;
        try {
            const response = await fetch('/hosts/name', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ mac, name }),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
            window.location.reload();
        } catch (error) {
            button.disabled = false;
            window.alert(t('The hostname was not saved: {message}', { message: tm(error.message) }));
        }
    });
})();
