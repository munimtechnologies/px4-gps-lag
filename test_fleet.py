"""Tests for fleet.py's sampling and scoring (no network).
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import os
import tempfile
import unittest

import numpy as np

import fleet


def entry(**kw):
    e = {"log_id": "a1", "log_date": "2026-03-01", "sys_hw": "PX4_FMU_V6C",
         "type": "personal", "source": "webui", "duration_s": 600, "vehicle_uuid": "u1"}
    e.update(kw)
    return e


def row(lag, vehicle, param=110.0, bus="serial", se=4.0, passed=True, log_id=None):
    return {"log_id": log_id or "%s-%s" % (vehicle, lag), "vehicle": vehicle, "passed": passed,
            "lag_ms": lag, "param_gps_delay_ms": param, "gps_bus": bus, "se_ms": se,
            "download": "ok", "reason": "ok" if passed else "too little manoeuvring"}


def fleet_rows():
    rows = []
    for i in range(60):
        rows.append(row(100.0 + (i % 5), "v%d" % i, bus="serial"))
    for i in range(30):
        rows.append(row(180.0, "w%d" % i, param=110.0 if i < 10 else 200.0, bus="uavcan"))
    for i in range(20):                          # second logs of 20 vehicles, 10 ms apart
        rows.append(row(110.0 + (i % 5), "v%d" % i, log_id="r%d" % i))
    rows.append(row(None, "x", passed=False))
    return rows


class Eligible(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(fleet.eligible(entry()), (True, ""))
        self.assertFalse(fleet.eligible(entry(log_date="2025-09-30"))[0])
        self.assertFalse(fleet.eligible(entry(sys_hw="PX4_SITL"))[0])
        self.assertFalse(fleet.eligible(entry(type="simulation"))[0])
        self.assertFalse(fleet.eligible(entry(source="CI"))[0])
        self.assertFalse(fleet.eligible(entry(duration_s=239))[0])
        self.assertFalse(fleet.eligible(entry(duration_s=None))[0])
        self.assertFalse(fleet.eligible(entry(log_id=""))[0])

    def test_vehicle_hash_hides_the_id(self):
        h = fleet.vehicle_hash("0001abcd")
        self.assertEqual(len(h), 12)
        self.assertNotIn("0001abcd", h)
        self.assertIsNone(fleet.vehicle_hash(""))


class Order(unittest.TestCase):
    def test_seeded_and_grouped(self):
        cands = [{"log_id": "l%d" % i, "vehicle": "v%d" % (i % 3) if i < 6 else None}
                 for i in range(8)]
        o1, by1 = fleet.plan_order(cands)
        o2, by2 = fleet.plan_order(list(reversed(cands)))
        self.assertEqual(o1, o2)
        self.assertEqual(len(o1), 5)                  # v0, v1, v2 and two logs without a vehicle
        self.assertEqual(sorted(len(v) for v in by1.values()), [1, 1, 2, 2, 2])


class Summary(unittest.TestCase):
    def test_checks(self):
        s = fleet.summarise(fleet_rows())
        self.assertEqual(s["passed"], 110)
        self.assertEqual(s["vehicles_passed"], 90)
        self.assertTrue(s["checks"]["E1"])
        self.assertEqual(s["by_bus"]["uavcan"]["n"], 30)
        self.assertTrue(s["checks"]["P4"])
        self.assertEqual(s["repeat_vehicles"]["n"], 20)
        self.assertEqual(s["repeat_vehicles"]["median_abs_diff_ms"], 10.0)
        self.assertTrue(s["checks"]["P5"])
        self.assertTrue(s["decision"]["D1_suggest_param"])
        # 20 of 110 logs use 200 ms; only the 10 DroneCAN logs at 110 ms differ by over 50 ms
        self.assertAlmostEqual(s["param"]["share_default_110"], 90 / 110)
        self.assertAlmostEqual(s["lag_minus_param_ms"]["share_abs_over_50"], 10 / 110)
        self.assertFalse(s["checks"]["P2"])
        self.assertEqual(s["not_passed_reasons"], {"too little manoeuvring": 1})

    def test_undecided_when_groups_are_small(self):
        s = fleet.summarise([row(100.0, "v1"), row(120.0, "v2", bus="uavcan")])
        self.assertIsNone(s["checks"]["P4"])
        self.assertIsNone(s["checks"]["P5"])
        self.assertFalse(s["checks"]["E1"])

    def test_numpy_lags_still_write_json(self):
        # 0.1.0 crashed here: gps_lag's refined lag is a numpy float, so 40 <= median <= 160
        # was a numpy bool, which json cannot write.
        rows = fleet_rows()
        for r in rows:
            if r["lag_ms"] is not None:
                r["lag_ms"] = np.float64(r["lag_ms"])
        s = fleet.summarise(rows)
        s["exploratory"] = fleet.explore(rows)
        text = json.dumps(s)
        self.assertIn('"P1": true', text)
        for v in s["checks"].values():
            self.assertIn(type(v), (bool, type(None)))

    def test_explore(self):
        rows = fleet_rows()
        for r in rows[:60]:
            r.update({"ver_sw_release": "v1.14.3", "gps_logged_dt_s": 0.5, "mav_type": "Quadrotor",
                      "r2": 0.9, "r2_at_zero": 0.85})
        e = fleet.explore(rows)
        self.assertEqual(e["by_release"]["v1.14"]["n"], 60)
        self.assertEqual(e["by_logged_gps_interval"]["0.15-0.7 s"]["n"], 60)
        self.assertEqual(e["mismatch_direction"], {"n": 110, "lag_over_param_by_50": 10,
                                                   "lag_under_param_by_50": 0})
        self.assertAlmostEqual(e["r2"]["median_gain_over_zero_lag"], 0.05, places=6)

    def test_rescore_writes_summary(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "logs.jsonl")
            with open(path, "w") as f:
                for r in fleet_rows():
                    f.write(json.dumps(r) + "\n")
            self.assertEqual(fleet.main(["--out-dir", d, "--rescore", path]), 0)
            with open(os.path.join(d, "summary.json")) as f:
                s = json.load(f)
            self.assertEqual(s["passed"], 110)
            self.assertEqual(s["rescored_from"], "logs.jsonl")
            self.assertTrue(s["checks"]["P5"])


if __name__ == "__main__":
    unittest.main()
