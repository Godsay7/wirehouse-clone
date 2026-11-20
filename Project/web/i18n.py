"""Interface language: Ukrainian (default) or English.

English text is the key. Templates use ``_("Text")`` for fixed strings and
``|tr`` for messages built by the server ("Cable added: SW-A Gi1/0/1 —
PP1 p3"), which are matched against the patterns of the catalog. The same
catalog is served to the browser as /i18n/<lang>.js for ``t()`` in JS.
The choice is kept in the "lang" cookie; the logo stays "Wirehouse".
"""

import json
import re

from flask import g, request

from .. import settings
from .translations import uk

LANGUAGES = {"uk": "УКР", "en": "EN"}
COOKIE = "lang"
COOKIE_MAX_AGE = 365 * 24 * 3600

CATALOGS = {"uk": uk.MESSAGES}
PATTERNS = {"uk": [(re.compile(pattern), replacement) for pattern, replacement in uk.PATTERNS]}
TOKENS = {"uk": [(re.compile(pattern), replacement) for pattern, replacement in uk.TOKENS]}


def default_language():
    return settings.DEFAULT_LANGUAGE if settings.DEFAULT_LANGUAGE in LANGUAGES else "uk"


def choose_language():
    """The language of this request: the cookie, else the default."""

    lang = request.cookies.get(COOKIE, "")
    return lang if lang in LANGUAGES else default_language()


def current_language():
    return getattr(g, "lang", None) or default_language()


def gettext(text, **values):
    """A fixed string: _("Save"), _("{n} workplaces", n=5)."""

    translated = CATALOGS.get(current_language(), {}).get(text, text)
    if not isinstance(translated, str):          # a plural entry used as plain text
        translated = translated[0]
    return translated.format(**values) if values else translated


def plural_index(lang, n):
    """Which plural form: English 0/1; Ukrainian one / few / many."""

    n = abs(int(n))
    if lang == "uk":
        if n % 10 == 1 and n % 100 != 11:
            return 0
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return 1
        return 2
    return 0 if n == 1 else 1


def ngettext(singular, plural, n, **values):
    """_n("{n} rack", "{n} racks", n): the catalog keeps [one, few, many] for Ukrainian."""

    values.setdefault("n", n)
    lang = current_language()
    forms = CATALOGS.get(lang, {}).get(singular)
    if isinstance(forms, list):
        text = forms[min(plural_index(lang, n), len(forms) - 1)]
    else:
        text = singular if plural_index("en", n) == 0 else plural
    return text.format(**values)


def translate_message(text):
    """A message built by the server: exact entry, else the first matching pattern."""

    text = "" if text is None else str(text)
    lang = current_language()
    catalog = CATALOGS.get(lang)
    if not catalog or not text:
        return text
    if isinstance(catalog.get(text), str):
        return catalog[text]
    for pattern, replacement in PATTERNS.get(lang, ()):
        match = pattern.fullmatch(text)
        if match:
            text = match.expand(replacement)
            break
    # Fragments inside messages: "(empty)", "U12 rear", "... is connected to ...".
    for pattern, replacement in TOKENS.get(lang, ()):
        text = pattern.sub(replacement, text)
    return text


def javascript_catalog(lang):
    """window.I18N for t() in the browser."""

    data = {"lang": lang if lang in LANGUAGES else default_language(),
            "messages": CATALOGS.get(lang, {}),
            "patterns": [[p.pattern, r] for p, r in PATTERNS.get(lang, [])],
            "tokens": [[p.pattern, r] for p, r in TOKENS.get(lang, [])]}
    return "window.I18N = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
