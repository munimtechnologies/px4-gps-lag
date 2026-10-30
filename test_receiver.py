"""Tests for receiver.py. By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import os
import tempfile
import unittest

import numpy as np

import receiver as rc


def dev_id(bus_type, devtype, bus=1, address=0):
    """A PX4 device_id: bus type 3 bits, bus 5 bits, address 8, devtype 8 (Device.hpp)."""
    return bus_type | (bus << 3) | (address << 8) | (devtype << 16)


M8 = dev_id(5, 0xA8)
F9P = dev_id(5, 0xAA)
CAN = dev_id(3, 0x85, bus=0, address=125)


def row(cls, lag, passed=True, source="vehicle_gps_position", **extra):
    r = {"log_id": "%s-%s" % (cls, lag), "passed": passed, "reason": "ok" if passed else "too little manoeuvring",
         "lag_ms": lag if passed else None, "receiver": cls, "receiver_source": source,
         "param_gps_delay_ms": 110.0, "ver_sw_release": "v1.15.4", "receivers": 1, "fix_type_max": 3,
         "gps_logged_dt_s": 0.1, "stamp_minus_sample_ms": None, "download": "ok"}
    r.update(extra)
    return r


def spread(base, n):
    return [base + (i % 7) - 3 for i in range(n)]


class Classes(unittest.TestCase):
    def test_devtype_byte(self):
        self.assertEqual(rc.devtype(M8), 0xA8)
        self.assertEqual(rc.devtype(CAN), 0x85)

    def test_receiver_class(self):
        self.assertEqual(rc.receiver_class(M8), "ubx_m8")
        self.assertEqual(rc.receiver_class(F9P), "ubx_f9p")
        self.assertEqual(rc.receiver_class(dev_id(5, 0xA9)), "ubx_m9")
        self.assertEqual(rc.receiver_class(dev_id(5, 0xA5)), "ubx_generic")
        self.assertEqual(rc.receiver_class(CAN), "uavcan")
        self.assertEqual(rc.receiver_class(dev_id(3, 0x00)), "uavcan")
        self.assertEqual(rc.receiver_class(dev_id(4, 0xAF)), "simulation")
        self.assertEqual(rc.receiver_class(dev_id(5, 0x55)), "other:serial/0x55")
        self.assertEqual(rc.receiver_class(dev_id(1, 0xA8)), "other:i2c/0xA8")
        self.assertEqual(rc.receiver_class(0), "unknown")


class Facts(unittest.TestCase):
    def topic(self, ids, fix=3):
        return {"device_id": np.array(ids, dtype=np.uint32), "fix_type": np.array([fix] * len(ids))}

    def test_usual_id_skips_zeros(self):
        self.assertEqual(rc._usual_id(self.topic([0, M8, M8, F9P, 0])), M8)
        self.assertEqual(rc._usual_id(self.topic([0, 0])), 0)
        self.assertEqual(rc._usual_id(None), 0)
        self.assertEqual(rc._usual_id({"timestamp": np.array([1])}), 0)

    def test_vehicle_gps_position_id_wins(self):
        f = rc.receiver_facts(self.topic([M8] * 5, fix=6), {0: self.topic([F9P] * 3), 1: self.topic([M8] * 3)})
        self.assertEqual((f["receiver"], f["receiver_source"], f["receivers"]), ("ubx_m8", "vehicle_gps_position", 2))
        self.assertEqual(f["fix_type_max"], 6)

    def test_falls_back_to_the_only_sensor_gps(self):
        f = rc.receiver_facts(self.topic([0] * 5), {0: self.topic([F9P] * 3)})
        self.assertEqual((f["receiver"], f["receiver_source"], f["gps_device_id"]), ("ubx_f9p", "sensor_gps", F9P))

    def test_blended_with_two_receivers_is_multiple(self):
        f = rc.receiver_facts(self.topic([0] * 5), {0: self.topic([F9P] * 3), 1: self.topic([M8] * 3)})
        self.assertEqual((f["receiver"], f["receiver_source"]), ("multiple", "several sensor_gps"))
        self.assertEqual(sorted(f["receiver_classes"]), ["ubx_f9p", "ubx_m8"])

    def test_nothing_known(self):
        f = rc.receiver_facts(None, {})
        self.assertEqual((f["receiver"], f["receiver_source"], f["fix_type_max"]), ("unknown", "none", None))


class Draw(unittest.TestCase):
    def test_excludes_earlier_logs_and_vehicles(self):
        cands = [{"log_id": "a", "vehicle": "v1"}, {"log_id": "b", "vehicle": "v2"},
                 {"log_id": "c", "vehicle": "v2"}, {"log_id": "d", "vehicle": None},
                 {"log_id": "e", "vehicle": "v3"}]
        got = rc.draw(cands, {"e"}, {"v1"})
        self.assertEqual(len([c for c in got if c["vehicle"] == "v2"]), 1)
        ids = {c["log_id"] for c in got}
        self.assertNotIn("a", ids)
        self.assertNotIn("e", ids)
        self.assertIn("d", ids)
        self.assertEqual(len(got), 2)
        self.assertEqual(got, rc.draw(cands, {"e"}, {"v1"}))

    def test_excluded_reads_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "a.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"log_id": "x", "vehicle": "v9"}) + "\n\n")
                f.write(json.dumps({"log_id": "y", "vehicle": None}) + "\n")
            self.assertEqual(rc.excluded([p]), ({"x", "y"}, {"v9"}))
        self.assertEqual(rc.excluded([]), (set(), set()))


class Boot(unittest.TestCase):
    def test_difference_and_interval(self):
        b = rc.boot_diff(spread(90, 30), spread(120, 30), n=300)
        self.assertEqual(b["diff_ms"], -30.0)
        self.assertLess(b["ci95_ms"][0], -30.0 + 0.01)
        self.assertGreater(b["ci95_ms"][1], -30.0 - 0.01)
        self.assertLess(b["ci95_ms"][1], 0)
        self.assertEqual(b, rc.boot_diff(spread(90, 30), spread(120, 30), n=300))


class Summary(unittest.TestCase):
    def rows(self):
        rows = [row("ubx_m8", x) for x in spread(175, 30)]
        rows += [row("ubx_f9p", x) for x in spread(95, 30)]
        rows += [row("uavcan", x) for x in spread(80, 20)]
        rows += [row("unknown", 100.0, source="none") for _ in range(5)]
        rows += [row("ubx_m8", None, passed=False) for _ in range(4)]
        rows += [row("simulation", 10.0)]
        return rows

    def test_checks(self):
        s = rc.summarise(self.rows())
        self.assertEqual(s["passed"], 85)
        self.assertEqual(s["known_receiver"], 80)
        self.assertEqual(s["compared_classes"], ["uavcan", "ubx_f9p", "ubx_m8"])
        self.assertEqual(s["compared_models"], ["ubx_f9p", "ubx_m8"])
        self.assertEqual(s["classes"]["ubx_m8"]["median_lag_ms"], 175.0)
        c = s["checks"]
        self.assertTrue(c["E1"])
        self.assertFalse(c["P1"])                 # 175 is outside 80-160
        self.assertTrue(c["P2"])                  # F9P below M8
        self.assertEqual(s["P2_f9p_minus_m8"]["diff_ms"], -80.0)
        self.assertTrue(c["P3"])
        self.assertEqual((s["P3_largest_gap"]["high"], s["P3_largest_gap"]["low"]), ("ubx_m8", "ubx_f9p"))
        self.assertTrue(c["P4"])                  # M8 at 175 is off 110 but on its class median
        self.assertAlmostEqual(s["P4_class_default"]["within_50_at_110"], 50 / 80)
        self.assertEqual(s["P4_class_default"]["within_50_at_class_median"], 1.0)
        self.assertTrue(c["P5"])
        self.assertTrue(c["P6"])
        self.assertTrue(s["decision"]["D1_class_note_in_checkup"])
        self.assertEqual(s["not_passed_reasons"], {"too little manoeuvring": 4})
        json.dumps(s)

    def test_small_classes_leave_checks_unscored(self):
        rows = [row("ubx_m8", x) for x in spread(120, 10)] + [row("ubx_f9p", x) for x in spread(90, 30)]
        c = rc.summarise(rows)["checks"]
        self.assertFalse(c["E1"])
        for k in ("P1", "P2", "P3", "P5"):
            self.assertIsNone(c[k], k)
        self.assertFalse(c["P4"])                 # F9P alone: 90 and 110 are both within 50
        self.assertTrue(c["P6"])

    def test_no_rows(self):
        s = rc.summarise([])
        self.assertFalse(s["checks"]["E1"])
        self.assertIsNone(s["checks"]["P6"])
        self.assertIsNone(s["P4_class_default"])

    def test_explore_and_rescore(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "logs.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for r in self.rows():
                    f.write(json.dumps(r) + "\n")
            self.assertEqual(rc.main(["--out-dir", tmp, "--rescore", p]), 0)
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                s = json.load(f)
        self.assertEqual(s["rescored_from"], "logs.jsonl")
        self.assertEqual(s["exploratory"]["by_receiver_and_release"]["ubx_m8 v1.15"]["n"], 30)
        self.assertIn("ubx_f9p fix<=3", s["exploratory"]["by_receiver_and_fix"])


if __name__ == "__main__":
    unittest.main()
