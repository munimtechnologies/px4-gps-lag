"""Synthetic tests for defaults.py (no network). By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import unittest

import defaults as d

YAML = """groups:
  - name: PG_GPS_CONFIG
    members:
      - name: gps_provider
        default_value: "UBLOX"
      - name: gps_dyn_model
        description: "GPS navigation model"
        default_value: "AIR_2G"
        field: dynModel
        table: gps_dyn_model
        type: uint8_t
tables:
  - name: gps_dyn_model
    values: ["PEDESTRIAN", "AIR_2G"]
"""


class Find(unittest.TestCase):
    def test_after_lines(self):
        m = d.find(YAML, d.TARGETS[-1][4], 6)
        self.assertEqual(len(m), 2)
        self.assertEqual(m[0]["line"], 6)
        self.assertEqual(m[0]["after"][1], '        default_value: "AIR_2G"')
        self.assertEqual(m[1]["line"], 13)

    def test_plain_pattern(self):
        text = "a\nparam set-default GPS_UBX_DYNMODEL 6\nb\n"
        self.assertEqual(d.find(text, "GPS_UBX_DYNMODEL"),
                         [{"line": 2, "text": "param set-default GPS_UBX_DYNMODEL 6", "after": []}])
        self.assertEqual(d.find("nothing here", "GPS_UBX_DYNMODEL"), [])

    def test_record_and_markdown(self):
        def get(url, accept=None):
            if "api.github.com" in url:
                self.assertEqual(accept, "application/vnd.github.sha")
                return "0123456789abcdef0123456789abcdef01234567\n"
            self.assertIn("/0123456789abcdef0123456789abcdef01234567/", url)
            return "x\n  AP_GROUPINFO(\"_NAVFILTER\", 2, AP_GPS, _navfilter, GPS_ENGINE_AIRBORNE_4G),\n"
        row = d.record(d.TARGETS[4], get)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["matches"][0]["line"], 2)
        md = d.markdown([row])
        self.assertIn("GPS_ENGINE_AIRBORNE_4G", md)
        self.assertIn("`0123456789ab`", md)
        json.dumps(row)

    def test_error_is_recorded(self):
        def get(url, accept=None):
            raise OSError("down")
        row = d.record(d.TARGETS[0], get)
        self.assertTrue(row["status"].startswith("error: OSError"))
        self.assertIn("down", d.markdown([row]))


if __name__ == "__main__":
    unittest.main()
