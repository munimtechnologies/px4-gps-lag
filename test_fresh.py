"""Tests for fresh.py. By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import os
import tempfile
import unittest

import fresh as fr


def spread(base, n):
    """n lags around base (offsets -3..3 repeating); for n = 13 or 15 the median is base."""
    return [base + (i % 7) - 3 for i in range(n)]


def row(cls, lag, grid=None, mode=None, passed=True, vehicle=None):
    r = {"log_id": "%s-%s-%s" % (cls, lag, grid), "vehicle": vehicle, "receiver": cls, "passed": passed,
         "lag_ms": float(lag) if passed else None, "reason": None if passed else "too little excitation",
         "download": "ok", "ver_sw_release": "v1.15.4", "grid_ms": grid, "gps_ubx_mode": mode,
         "utc_dt_mode_ms": grid or 1000.0}
    return r


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class Summary(unittest.TestCase):
    def rows(self):
        rows = [row("ubx_m9", x, 125) for x in spread(70, 15)]
        rows += [row("ubx_m8", x, 200) for x in spread(170, 15)]
        rows += [row("ubx_f9p", x, 100, 0) for x in spread(145, 15)]
        rows += [row("ubx_generic", x, 125) for x in spread(125, 15)]
        rows += [row("uavcan", x) for x in spread(95, 15)]
        rows += [row("nmea", x) for x in spread(200, 13)]
        rows += [row("ubx_m8", 0, 200, passed=False) for _ in range(3)]
        rows += [row("simulation", 5)]
        rows += [{"log_id": "gone-%d" % i, "download": "missing", "passed": False,
                  "reason": "download missing"} for i in range(2)]
        return rows

    def test_checks(self):
        s = fr.summarise(self.rows())
        self.assertEqual((s["attempted"], s["downloaded"], s["passed"]), (94, 92, 88))
        self.assertEqual(s["n_core"], {"ubx_m8": 15, "ubx_m9": 15, "ubx_f9p": 15})
        self.assertEqual(s["F1_m9_minus_m8"]["diff_ms"], -100.0)
        self.assertEqual(s["F2_m9_minus_f9p"]["diff_ms"], -75.0)
        self.assertEqual(s["F3_f9p_minus_m8"]["diff_ms"], -25.0)
        # serial u-blox pooled: 60 lags; the 30th and 31st are 128 (generic) and 142 (F9P)
        self.assertEqual(s["F4_nmea_minus_serial_ublox"]["diff_ms"], 65.0)
        self.assertEqual(s["F4_n"], [13, 60])
        # 110 ms puts the 15 M8 (167-173 ms) more than 50 ms off; class medians put everyone within
        p4 = s["F5_class_default"]
        self.assertEqual((p4["n"], p4["within_50_at_110"], p4["within_50_at_class_median"], p4["gain"]),
                         (75, 0.8, 1.0, 0.2))
        self.assertEqual([s["F6_driver_grid"][k]["share"] for k in fr.CORE], [1.0, 1.0, 1.0])
        self.assertEqual(s["R2_m9_minus_other_at_125"]["diff_ms"], -55.0)
        self.assertEqual(s["R2_n"], [15, 15])
        self.assertTrue(s["R2"])
        self.assertEqual(s["checks"], {"E1": True, "F1": True, "F2": True, "F3": True, "F4": True,
                                       "F5": True, "F6": True})
        self.assertEqual(s["decision"], {"D1_receiver_line_in_checkup": True, "D3_nmea_note": True})
        self.assertEqual(s["classes"]["nmea"]["n"], 13)
        self.assertNotIn("simulation", s["classes"])
        json.dumps(s)

    def test_no_gap_fails_f1(self):
        rows = [r for r in self.rows() if r.get("receiver") != "ubx_m9"]
        rows += [row("ubx_m9", x, 125) for x in spread(170, 15)]
        s = fr.summarise(rows)
        self.assertEqual(s["F1_m9_minus_m8"]["diff_ms"], 0.0)
        self.assertFalse(s["checks"]["F1"])
        self.assertFalse(s["decision"]["D1_receiver_line_in_checkup"])

    def test_far_apart_f9p_and_m8_fail_f3(self):
        rows = [r for r in self.rows() if r.get("receiver") != "ubx_f9p"]
        rows += [row("ubx_f9p", x, 100, 0) for x in spread(130, 15)]
        s = fr.summarise(rows)
        self.assertEqual(s["F3_f9p_minus_m8"]["diff_ms"], -40.0)
        self.assertFalse(s["checks"]["F3"])

    def test_small_classes_leave_checks_unscored(self):
        rows = [row("ubx_m9", x, 125) for x in spread(70, 15)]
        rows += [row("ubx_f9p", x, 100, 0) for x in spread(145, 15)]
        rows += [row("ubx_m8", x, 200) for x in spread(170, 5)]
        rows += [row("nmea", x) for x in spread(200, 7)]
        s = fr.summarise(rows)
        c = s["checks"]
        self.assertFalse(c["E1"])
        self.assertIsNone(c["F1"])
        self.assertIsNone(c["F3"])
        self.assertIsNone(c["F4"])
        self.assertTrue(c["F2"])
        self.assertFalse(s["decision"]["D1_receiver_line_in_checkup"])

    def test_no_rows(self):
        s = fr.summarise([])
        self.assertEqual(s["passed"], 0)
        self.assertFalse(s["checks"]["E1"])
        for k in ("F1", "F2", "F3", "F4", "F5", "F6"):
            self.assertIsNone(s["checks"][k], k)

    def test_draw_uses_own_seed_and_exclusions(self):
        cands = [{"log_id": "l%d" % i, "vehicle": "v%d" % i} for i in range(40)]
        got = fr.draw(cands, {"l3"}, {"v5", "v7"})
        ids = {c["log_id"] for c in got}
        self.assertEqual(len(got), 37)
        self.assertFalse(ids & {"l3", "l5", "l7"})
        self.assertEqual(got, fr.draw(cands, {"l3"}, {"v5", "v7"}))
        self.assertEqual(got, fr.rc.draw(cands, {"l3"}, {"v5", "v7"}, seed=fr.SEED))

    def test_rescore(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "logs.jsonl")
            write_jsonl(p, self.rows())
            self.assertEqual(fr.main(["--out-dir", tmp, "--rescore", p]), 0)
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                s = json.load(f)
        self.assertEqual(s["rescored_from"], "logs.jsonl")
        self.assertEqual(s["seed"], 20261102)
        ex = s["exploratory"]
        self.assertEqual(ex["rate"]["by_receiver_and_grid"]["ubx_m8 200"]["n"], 15)
        self.assertEqual(ex["receiver"]["by_receiver_and_release"]["nmea v1.15"]["n"], 13)


if __name__ == "__main__":
    unittest.main()
