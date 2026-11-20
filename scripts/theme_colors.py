#!/usr/bin/env python3
"""Dark theme colours, written into the stylesheets themselves.

Every colour of the site that needs another value in the dark theme is
written as light-dark(<light>, <dark>) right where it is used; the browser
picks one by the theme (color-scheme: light / dark on <html>, see
css/common/tokens.css). Interface colours mostly come from the tokens
(var(--surface) …), which carry their dark values already.

This script holds the rules that turn a light colour into its dark twin:

* backgrounds: light surfaces become dark ones (white -> near black, pale
  tints -> dark tints of the same hue); strong colours (buttons, badges) and
  dark surfaces (header, racks) stay;
* text: dark text becomes light, keeping its hue (red stays red, green
  green); light text (on buttons, the header) stays;
* borders: light lines become dark grey ones;
* shadows and see-through overlays stay.

When a rule sets both a background and a text colour, the pair is checked:
if the translated text reads worse on the translated background than the
original text would, the original is kept.

    python3 scripts/theme_colors.py           # check: list colours with no dark value
    python3 scripts/theme_colors.py --fix     # write light-dark(…) for them

tests/test_dark_theme.py runs the check. Hand-made corrections the rules
cannot guess are in static/css/dark-fixes.css.
"""

import colorsys
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from Project.web.assets import CSS_BUNDLES  # noqa: E402

CSS_DIR = os.path.join(BASE_DIR, "Project", "web", "static", "css")
PREFIX = 'html[data-theme="dark"]'
# Not translated: the hand corrections, and the tokens (they carry their dark
# values themselves).
SKIP_FILES = {"dark-fixes.css", "tokens.css"}

NAMED = {"white": (255, 255, 255), "black": (0, 0, 0)}
COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b"
    r"|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+%?\s*)?\)"
    r"|\b(?:white|black)\b"
)


# ------------------------------------------------------------------
# Colours
# ------------------------------------------------------------------

def parse_color(text):
    """'#fff' / 'rgba(1,2,3,.5)' / 'white' -> (r, g, b, alpha) in 0..255 / 0..1."""

    text = text.strip().lower()
    if text in NAMED:
        return (*NAMED[text], 1.0)
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
        a = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return r, g, b, a
    parts = [p.strip() for p in text[text.index("(") + 1:-1].split(",")]
    r, g, b = (float(p) for p in parts[:3])
    a = 1.0
    if len(parts) > 3:
        a = float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3])
    return r, g, b, a


def format_color(r, g, b, a):
    r, g, b = (max(0, min(255, round(v))) for v in (r, g, b))
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"


def to_hls(r, g, b):
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def from_hls(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return r * 255, g * 255, b * 255


def luminance(r, g, b):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(c1, c2):
    l1, l2 = luminance(*c1[:3]), luminance(*c2[:3])
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def dark_background(rgba):
    r, g, b, a = rgba
    if a < 0.5:                       # see-through tints and overlays keep their look
        return rgba
    h, l, s = to_hls(r, g, b)
    if l >= 0.80:                     # light surface -> dark surface of the same tint
        new_l = 0.105 + (1.0 - l) * 0.55
        return (*from_hls(h, new_l, s * 0.55), a)
    if l >= 0.60 and s < 0.25:        # light grey (inactive buttons, wells) -> mid dark grey
        return (*from_hls(h, 0.17 + (1.0 - l) * 0.35, s * 0.6), a)
    return rgba                       # strong colours and dark surfaces stay


def dark_text(rgba):
    r, g, b, a = rgba
    h, l, s = to_hls(r, g, b)
    if l > 0.55:                      # already light (on buttons, on the header)
        return rgba
    if s < 0.15:                      # grey text: keep the order dark -> light
        return (*from_hls(h, 0.93 - l * 0.55, s), a)
    # Coloured text (links, statuses): a light tint of the same hue.
    return (*from_hls(h, max(0.68, 0.85 - l * 0.3), min(1.0, s * 0.9 + 0.1)), a)


def dark_border(rgba):
    r, g, b, a = rgba
    if a < 0.5:
        return rgba
    h, l, s = to_hls(r, g, b)
    if l >= 0.70:                     # light lines -> dark grey lines
        return (*from_hls(h, 0.22 + (1.0 - l) * 0.35, s * 0.5), a)
    return rgba


# ------------------------------------------------------------------
# Declarations
# ------------------------------------------------------------------

def role(prop):
    prop = prop.lower()
    if prop in ("color", "caret-color", "-webkit-text-fill-color", "text-decoration-color"):
        return "text"
    if prop in ("background", "background-color", "background-image"):
        return "background"
    if prop.startswith("border") or prop.startswith("outline") or prop == "column-rule":
        return "border"
    if prop in ("fill",):
        return "background"
    if prop in ("stroke",):
        return "border"
    return None                       # shadows, gradients in other props, custom properties


def custom_property_role(prop):
    """CSS variables: guess the role from the name (--fm-border, --fm-muted)."""

    name = prop.lower()
    if any(word in name for word in ("border", "line", "grid")):
        return "border"
    if any(word in name for word in ("bg", "background", "surface", "panel", "fill")):
        return "background"
    if any(word in name for word in ("muted", "text", "ink", "fg")):
        return "text"
    return None


TRANSLATE = {"text": dark_text, "background": dark_background, "border": dark_border}


def translate_value(value, kind):
    def replace(match):
        rgba = parse_color(match.group(0))
        return format_color(*TRANSLATE[kind](rgba))
    return COLOR_RE.sub(replace, value)


def dark_values(declarations):
    """[(prop, value, important)] -> {index: dark value} for the declarations
    whose colours change in the dark theme."""

    result = {}
    colors = {}
    # SVG text (labels on maps): fill is the text colour, stroke the halo around it.
    svg_text = any(prop.startswith(("font", "text-anchor", "dominant-baseline", "letter-spacing"))
                   for prop, _, _ in declarations)
    for index, (prop, value, _important) in enumerate(declarations):
        kind = custom_property_role(prop) if prop.startswith("--") else role(prop)
        if svg_text and prop == "fill":
            kind = "text"
        elif svg_text and prop == "stroke":
            kind = "background"
        if kind is None or "light-dark(" in value or not COLOR_RE.search(value):
            continue
        new_value = translate_value(value, kind)
        if kind in ("text", "background") and len(COLOR_RE.findall(value)) == 1:
            colors[kind] = (index, value, new_value)
        if _differs(value, new_value):
            result[index] = new_value

    # Text on a background set by the same rule: keep it readable.
    if "text" in colors and "background" in colors:
        text_index, old_text, new_text = colors["text"]
        _, _, new_bg = colors["background"]
        bg = parse_color(COLOR_RE.search(new_bg).group(0))
        if bg[3] >= 0.5:
            old_c = parse_color(COLOR_RE.search(old_text).group(0))
            new_c = parse_color(COLOR_RE.search(new_text).group(0))
            if contrast(old_c, bg) > contrast(new_c, bg):
                result.pop(text_index, None)
    return result


def _differs(value, dark):
    """Is any colour of ``dark`` really another colour (not just written differently)?"""

    return any(parse_color(a) != parse_color(b) for a, b in zip(COLOR_RE.findall(value), COLOR_RE.findall(dark)))


def light_dark(value, dark):
    """'1px solid #ddd', '1px solid #333' -> '1px solid light-dark(#ddd, #333)'."""

    dark_colors = COLOR_RE.findall(dark)
    parts, last = [], 0
    for i, match in enumerate(COLOR_RE.finditer(value)):
        parts.append(value[last:match.start()])
        light = match.group(0)
        same = parse_color(dark_colors[i]) == parse_color(light)
        parts.append(light if same else f"light-dark({light}, {dark_colors[i]})")
        last = match.end()
    parts.append(value[last:])
    return "".join(parts)


# ------------------------------------------------------------------
# Stylesheets
# ------------------------------------------------------------------

def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def split_selectors(selector_text):
    """Split on commas that are not inside parentheses (:is(a, b))."""

    parts, depth, current = [], 0, ""
    for char in selector_text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def prefix_selector(selector):
    selector = " ".join(selector.split())
    if selector.startswith(":root"):
        return selector.replace(":root", f':root[data-theme="dark"]', 1)
    if re.match(r"html\b", selector):
        return PREFIX + selector[4:]
    return f"{PREFIX} {selector}"


def parse_declarations(body):
    declarations = []
    for part in body.split(";"):
        if ":" not in part:
            continue
        prop, value = part.split(":", 1)
        prop, value = prop.strip(), value.strip()
        important = False
        if value.lower().endswith("!important"):
            important = True
            value = value[: -len("!important")].strip()
        if prop:
            declarations.append((prop, value, important))
    return declarations


def blocks(text):
    """Yield (header, body) of the top-level blocks: rules and at-rules."""

    i, n = 0, len(text)
    while i < n:
        start = text.find("{", i)
        if start == -1:
            return
        header = text[i:start].strip()
        depth, j = 1, start + 1
        while j < n and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        yield header, text[start + 1:j - 1]
        i = j


def _rewrite(text, found):
    """Walk the rules of a stylesheet (comments hidden); for each declaration
    that needs a dark value, record it in ``found`` and return the text with
    light-dark(…) written in."""

    out, i, n = [], 0, len(text)
    while i < n:
        start = text.find("{", i)
        if start == -1:
            out.append(text[i:])
            break
        header = text[i:start]
        depth, j = 1, start + 1
        while j < n and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[start + 1:j - 1]
        name = header.strip()
        if name.startswith(("@media", "@supports", "@container")):
            body = _rewrite(body, found)
        elif not name.startswith("@") and "{" not in body:
            segments = body.split(";")
            parsed = []
            for k, segment in enumerate(segments):
                if ":" in segment:
                    prop, value = segment.split(":", 1)
                    important = value.strip().lower().endswith("!important")
                    clean = value.strip()[:-len("!important")].strip() if important else value.strip()
                    if prop.strip():
                        parsed.append((k, prop.strip(), clean, important))
            darks = dark_values([(p, v, imp) for _, p, v, imp in parsed])
            for index, dark in darks.items():
                k, prop, value, _ = parsed[index]
                selector = " ".join(re.sub(r"/\*@\d+@\*/", "", name).split())
                found.append((selector, prop, value, dark))
                segments[k] = segments[k].replace(value, light_dark(value, dark), 1)
            body = ";".join(segments)
        out.append(text[i:start + 1] + body + "}")
        i = j
    return "".join(out)


def fix_text(text):
    """(new text, [(selector, property, light value, dark value)])."""

    comments = []

    def hide(match):
        comments.append(match.group(0))
        return f"/*@{len(comments) - 1}@*/"

    hidden = re.sub(r"/\*.*?\*/", hide, text, flags=re.S)
    found = []
    fixed = _rewrite(hidden, found)
    fixed = re.sub(r"/\*@(\d+)@\*/", lambda m: comments[int(m.group(1))], fixed)
    return fixed, found


def stylesheet_order():
    """Every stylesheet in the order pages load them: the bundles, then the rest."""

    ordered = [path for bundle in CSS_BUNDLES.values() for path in bundle
               if os.path.basename(path) not in SKIP_FILES]
    rest = []
    for root, _dirs, files in os.walk(CSS_DIR):
        for name in sorted(files):
            if not name.endswith(".css") or name in SKIP_FILES or name == "dark.css":
                continue
            rel = os.path.relpath(os.path.join(root, name), CSS_DIR).replace(os.sep, "/")
            if f"css/{rel}" not in ordered:
                rest.append(f"css/{rel}")
    return ordered + sorted(rest)


def stylesheets():
    """Every stylesheet that is checked, in the order pages load them."""

    return [os.path.join(CSS_DIR, path[len("css/"):]) for path in stylesheet_order()]


def main():
    fix = "--fix" in sys.argv[1:]
    total = 0
    for path in stylesheets():
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        fixed, found = fix_text(text)
        total += len(found)
        rel = os.path.relpath(path, BASE_DIR)
        for selector, prop, value, dark in found:
            print(f"{rel}: {selector[:70]} {{ {prop}: {value} }} -> {dark}")
        if fix and found:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(fixed)
    if fix:
        print(f"Wrote light-dark() for {total} declarations.")
    elif total:
        print(f"{total} colours have no dark value: run python3 scripts/theme_colors.py --fix")
    return 1 if total and not fix else 0


if __name__ == "__main__":
    sys.exit(main())
