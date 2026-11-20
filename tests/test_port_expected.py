"""Front panel: a down port is red only where something is expected on it."""

import unittest

from Project.bll.domain.ports import port_is_expected


class PortExpectedTest(unittest.TestCase):

    def test_free_port(self):
        self.assertFalse(port_is_expected({"device": "-", "cabled": False, "written": None, "last_mac": None}))
        self.assertFalse(port_is_expected({"device": "", "cabled": False}))

    def test_something_expected(self):
        self.assertTrue(port_is_expected({"device": "-", "cabled": True}))                    # a documented cable
        self.assertTrue(port_is_expected({"device": "uplink to SW3", "cabled": False}))        # a description
        self.assertTrue(port_is_expected({"device": "-", "written": "PC-17"}))                # a name typed in
        self.assertTrue(port_is_expected({"device": "-", "last_mac": "00:11:22:33:44:55"}))   # a device seen before


if __name__ == "__main__":
    unittest.main()
