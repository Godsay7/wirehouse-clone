"""Dark theme: every colour has its dark value, the colour rules, the theme switch."""

import importlib.util
import os
import re
import tempfile
import unittest

from Project.web import create_app
from tests.test_web import create_inventory_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    spec = importlib.util.spec_from_file_location("theme_colors", os.path.join(ROOT, "scripts", "theme_colors.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ThemeColoursTest(unittest.TestCase):

    def test_every_colour_has_its_dark_value(self):
        tool = load_tool()
        missing = []
        for path in tool.stylesheets():
            with open(path, encoding="utf-8") as handle:
                _fixed, found = tool.fix_text(handle.read())
            missing += [f"{os.path.relpath(path, ROOT)}: {sel} {{ {prop}: {value} }}" for sel, prop, value, _ in found]
        self.assertEqual(missing, [], "\nColours with no dark value: run python3 scripts/theme_colors.py --fix\n"
                         + "\n".join(missing))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "Project", "web", "static", "css", "dark.css")))

    def test_colour_rules(self):
        t = load_tool()

        def dark(css):
            """The dark values written by --fix: [(light, dark)]."""
            fixed, _ = t.fix_text(css)
            return re.findall(r"light-dark\(([^,]+), ([^)]+)\)", fixed)

        # A light surface with dark text: dark surface, light text, readable.
        pairs = dict(dark(".card { background: #ffffff; color: #202124; border: 1px solid #d7dde3; }"))
        bg, fg = t.parse_color(pairs["#ffffff"]), t.parse_color(pairs["#202124"])
        self.assertLess(t.luminance(*bg[:3]), 0.05)
        self.assertGreater(t.contrast(fg, bg), 7)
        self.assertIn("#d7dde3", pairs)

        # Strong colours (buttons, statuses) stay as they are.
        self.assertEqual(dark(".tile.is-good { border-left-color: #198754; }"), [])
        self.assertEqual(dark(".button { background: #2563eb; color: #fff; }"), [])

        # Coloured text keeps its hue, light enough to read on a dark page.
        red = t.parse_color(dict(dark(".err { color: #b91c1c; }"))["#b91c1c"])
        self.assertGreater(red[0], red[1] + 60)
        self.assertGreater(t.contrast(red, (28, 32, 36, 1)), 4.5)

        # SVG text: fill is the text, stroke the halo.
        pairs = dict(dark(".label { fill: #0f172a; stroke: #ffffff; font-size: 1px; }"))
        self.assertGreater(t.luminance(*t.parse_color(pairs["#0f172a"])[:3]), 0.4)
        self.assertLess(t.luminance(*t.parse_color(pairs["#ffffff"])[:3]), 0.05)

        # Written in place: !important, @media and comments kept, keyframes and
        # values already themed (var(), light-dark()) left alone.
        fixed, _ = t.fix_text("/* a; b */ .x { color: #000 !important; } @media (max-width: 700px) { .y { background: #fff; } }"
                              " @keyframes k { 50% { color: #000; } } .z { color: var(--text); background: light-dark(#fff, #000); }")
        self.assertIn("/* a; b */", fixed)
        self.assertIn("color: light-dark(#000,", fixed)
        self.assertIn("!important", fixed)
        self.assertIn("@media (max-width: 700px) { .y { background: light-dark(#fff,", fixed)
        self.assertIn("50% { color: #000; }", fixed)
        self.assertIn("color: var(--text); background: light-dark(#fff, #000);", fixed)


class AccentsTest(unittest.TestCase):

    def test_lit_accents_stay_bright_in_dark(self):
        """A lit fibre cable or port must not turn dark: the hand corrections keep the light accent."""

        with open(os.path.join(ROOT, "Project", "web", "static", "css", "dark-fixes.css"), encoding="utf-8") as handle:
            fixes = handle.read()
        self.assertIn('html[data-theme="dark"] .connection-path.connection-fiber.connection-highlight {\n    stroke: #c4b5fd;', fixes)
        self.assertIn('html[data-theme="dark"] .rack-port.connected-fiber.connection-highlight {\n    outline-color: #c4b5fd;', fixes)
        self.assertIn('html[data-theme="dark"] .connection-path.connection-fiber {\n    stroke: rgba(167, 139, 250, 0.72);', fixes)


class ThemeSwitchTest(unittest.TestCase):

    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.addCleanup(os.unlink, self.db_path)
        create_inventory_db(self.db_path)
        self.client = create_app(self.db_path).test_client()

    def test_theme_from_cookie(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('<html lang="en">', page)                     # no choice: the system decides
        self.assertIn("data-theme-toggle", page)
        self.assertNotIn("css/dark.css", page)                       # colours of both themes are in the stylesheets
        self.assertIn("css/common/tokens.css", page)
        self.assertIn("js/theme.js", page)

        self.client.set_cookie("theme", "dark")
        self.assertIn('<html lang="en" data-theme="dark">', self.client.get("/").get_data(as_text=True))
        self.client.set_cookie("theme", "light")
        self.assertIn('<html lang="en" data-theme="light">', self.client.get("/dashboard").get_data(as_text=True))
        self.client.set_cookie("theme", '"><script>')
        self.assertIn('<html lang="en">', self.client.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
