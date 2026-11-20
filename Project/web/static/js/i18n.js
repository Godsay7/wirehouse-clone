// t("Save") / t("{n} workplaces", {n: 5}): the interface text in the chosen
// language (window.I18N comes from /i18n/<lang>.js, see web/i18n.py).
// Messages from the server with names in them go through the same patterns.
(() => {
    'use strict';

    const data = window.I18N || { lang: 'en', messages: {}, patterns: [] };
    const toJs = replacement => replacement.replace(/\\(\d)/g, '$$$1');
    const patterns = (data.patterns || []).map(([source, replacement]) => [new RegExp(`^(?:${source})$`), toJs(replacement)]);
    const tokens = (data.tokens || []).map(([source, replacement]) => [new RegExp(source, 'g'), toJs(replacement)]);

    function fill(text, values) {
        if (!values) return text;
        return text.replace(/\{(\w+)\}/g, (match, key) => (key in values ? values[key] : match));
    }

    window.t = function (text, values) {
        const found = (data.messages || {})[text];
        return fill(typeof found === 'string' ? found : text, values);
    };

    // tn('{n} workplace', '{n} workplaces', n): Ukrainian keeps [one, few, many].
    function pluralIndex(lang, n) {
        n = Math.abs(Math.trunc(n));
        if (lang === 'uk') {
            if (n % 10 === 1 && n % 100 !== 11) return 0;
            if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return 1;
            return 2;
        }
        return n === 1 ? 0 : 1;
    }

    window.tn = function (singular, plural, n, values) {
        const forms = (data.messages || {})[singular];
        const all = { n, ...(values || {}) };
        if (Array.isArray(forms)) return fill(forms[Math.min(pluralIndex(data.lang, n), forms.length - 1)], all);
        return fill(n === 1 ? singular : plural, all);
    };

    // tm(message): a message built by the server ("Cable added: A — B").
    window.tm = function (text) {
        text = String(text ?? '');
        const exact = data.messages && data.messages[text];
        if (typeof exact === 'string') return exact;
        for (const [pattern, replacement] of patterns) {
            if (pattern.test(text)) { text = text.replace(pattern, replacement); break; }
        }
        for (const [pattern, replacement] of tokens) text = text.replace(pattern, replacement);
        return text;
    };

    window.I18N_LANG = data.lang || 'en';
})();
