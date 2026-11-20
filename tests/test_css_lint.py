"""The CSS passes stylelint (.stylelintrc.json: errors and deprecated things only).

Needs Node and `npm install` in the repository; skipped where they are absent
(the site itself does not need Node).
"""

import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLELINT = os.path.join(ROOT, "node_modules", ".bin", "stylelint")


def _node():
    return shutil.which("node") or next(
        (path for path in (os.path.expanduser("~/.local/bin/node"),) if os.access(path, os.X_OK)), None)


class CssLintTest(unittest.TestCase):

    def test_stylelint(self):
        node = _node()
        if not node or not os.path.exists(STYLELINT):
            self.skipTest("stylelint is not installed (Node and `npm install`)")
        env = dict(os.environ, PATH=os.path.dirname(node) + os.pathsep + os.environ.get("PATH", ""))
        result = subprocess.run(
            [STYLELINT, "Project/web/static/css/**/*.css", "--formatter", "json"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
        )
        # The JSON report goes to stderr, a crash message too.
        try:
            report = json.loads(result.stderr or result.stdout or "[]")
        except ValueError:
            self.fail(f"stylelint did not run: {result.stderr or result.stdout}")
        problems = [
            f"{os.path.relpath(entry['source'], ROOT)}:{w['line']}: {w['text']}"
            for entry in report for w in entry["warnings"]
        ]
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
