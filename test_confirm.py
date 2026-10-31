"""Tests for confirm.py. By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import os
import tempfile
import unittest

import confirm as cf


def spread(base, n):
    return [base + (i % 7) - 3 for i in range(n)]


def row(cls, lag, again=None, download="ok", study="fleet-2026"):
    r = {"log_id": "%s-%s-%s" % (cls, lag, again), "vehicle": None, "study": study, "lag_ms": float(lag),
         "ver_sw_release": "v1.15.4", "download": download}
    if download == "ok":
        r.update({"receiver": cls, "receiver_source": "vehicle_gps_position",
                  "remeasured_lag_ms": float(lag) + 0.2 if again is None else again})
    return r


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class Earlier(unittest.TestCase):
    def test_published_lag_both_formats(self):
        self.assertEqual(cf.published_lag({"passed": True, "lag_ms": 99.8}), (True, 99.8))
        self.assertEqual(cf.published_lag({"lag": {"passed": False, "lag_ms": 244.1}, "health_ok": True}),
                         (False, 244.1))

    def test_one_passed_log_per_vehicle_across_files(self):
        fleet = [{"log_id": "a1", "vehicle": "v1", "attempt": 1, "passed": False, "lag_ms": 10.0},
                 {"log_id": "a2", "vehicle": "v1", "attempt": 2, "passed": True, "lag_ms": 50.0,
                  "ver_sw_release": "v1.11.3-0"},
                 {"log_id": "a3", "vehicle": "v1", "attempt": 3, "passed": True, "lag_ms": 60.0},
                 {"log_id": "x", "vehicle": None, "attempt": 4, "passed": True, "lag_ms": 70.0},
                 {"log_id": "y", "vehicle": "v2", "attempt": 5, "passed": False, "lag_ms": None}]
        health = [{"log_id": "b1", "vehicle": "v1", "attempt": 1, "lag": {"passed": True, "lag_ms": 1.0}},
                  {"log_id": "b2", "vehicle": "v3", "attempt": 2,
                   "lag": {"passed": True, "lag_ms": 120.5, "ver_sw_release": "v1.16.0"}},
                  {"log_id": "b3", "vehicle": "v4", "attempt": 3, "lag": {"passed": False, "lag_ms": 300.0}}]
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "fleet-2026.jsonl"), os.path.join(tmp, "fleet-health-2026.jsonl")
            write_jsonl(a, fleet)
            write_jsonl(b, health)
            got = cf.earlier_sample([a, b])
        self.assertEqual([(g["log_id"], g["study"], g["lag_ms"]) for g in got],
                         [("a2", "fleet-2026", 50.0), ("x", "fleet-2026", 70.0), ("b2", "fleet-health-2026", 120.5)])
        self.assertEqual(got[0]["ver_sw_release"], "v1.11.3-0")
        self.assertEqual(got[2]["ver_sw_release"], "v1.16.0")


class Summary(unittest.TestCase):
    def rows(self):
        rows = [row("ubx_m9", x) for x in spread(70, 12)]
        rows[0]["remeasured_lag_ms"] = rows[0]["lag_ms"] + 5
        rows[1]["remeasured_lag_ms"] = rows[1]["lag_ms"] - 5
        rows += [row("ubx_m8", x) for x in spread(175, 12)]
        rows += [row("ubx_f9p", x, study="fleet-health-2026") for x in spread(140, 12)]
        rows += [row("uavcan", x) for x in spread(100, 10)]
        rows += [row("unknown", 90) for _ in range(3)]
        rows += [row("ubx_m8", 150, download="missing") for _ in range(2)]
        return rows

    def test_checks(self):
        s = cf.summarise(self.rows())
        self.assertEqual((s["sample"], s["read"]), (51, 49))
        self.assertEqual(s["downloads"], {"ok": 49, "missing": 2})
        self.assertEqual(s["compared_classes"], ["uavcan", "ubx_f9p", "ubx_m8", "ubx_m9"])
        self.assertEqual(s["classes"]["ubx_m9"]["median_lag_ms"], 69.5)
        self.assertEqual(s["E0_remeasured"], 49)
        self.assertAlmostEqual(s["E0_agree_share"], round(47 / 49, 4))
        self.assertEqual(s["C1_m9_minus_m8"]["diff_ms"], -105.0)
        self.assertEqual(s["C2_m9_minus_f9p"]["diff_ms"], -70.0)
        self.assertEqual(s["C3_f9p_minus_m8"]["diff_ms"], -35.0)
        self.assertAlmostEqual(s["C4_class_default"]["within_50_at_110"], round(34 / 46, 4))
        self.assertEqual(s["C4_class_default"]["within_50_at_class_median"], 1.0)
        c = s["checks"]
        self.assertEqual(c, {"E0": True, "E1": True, "C1": True, "C2": True, "C3": False, "C4": True, "C5": True})
        self.assertTrue(s["decision"]["D1_class_line_in_checkup"])
        json.dumps(s)

    def test_e0_fails_when_lags_differ(self):
        rows = [row("ubx_m9", x, again=x + 3) for x in spread(70, 12)]
        self.assertFalse(cf.summarise(rows)["checks"]["E0"])

    def test_small_classes_leave_checks_unscored(self):
        rows = [row("ubx_m9", x) for x in spread(70, 5)]
        rows += [row("ubx_m8", x) for x in spread(150, 10)] + [row("ubx_f9p", x) for x in spread(140, 10)]
        s = cf.summarise(rows)
        c = s["checks"]
        self.assertFalse(c["E1"])
        for k in ("C1", "C2", "C5"):
            self.assertIsNone(c[k], k)
        self.assertTrue(c["C3"])                  # -10 ms is not 20 ms faster
        self.assertFalse(s["decision"]["D1_class_line_in_checkup"])

    def test_no_rows(self):
        s = cf.summarise([])
        self.assertIsNone(s["checks"]["E0"])
        self.assertFalse(s["checks"]["E1"])
        self.assertIsNone(s["C4_class_default"])

    def test_rescore_with_pool(self):
        pool = [{"log_id": "p%d" % i, "passed": True, "lag_ms": 80.0, "receiver": "ubx_m9"} for i in range(3)]
        pool += [{"log_id": "q", "passed": False, "lag_ms": None, "receiver": "ubx_m9"},
                 {"log_id": "s", "passed": True, "lag_ms": 5.0, "receiver": "simulation"}]
        with tempfile.TemporaryDirectory() as tmp:
            p, q = os.path.join(tmp, "logs.jsonl"), os.path.join(tmp, "receiver-2026.jsonl")
            write_jsonl(p, self.rows())
            write_jsonl(q, pool)
            self.assertEqual(cf.main(["--out-dir", tmp, "--rescore", p, "--pool", q]), 0)
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                s = json.load(f)
        self.assertEqual(s["rescored_from"], "logs.jsonl")
        ex = s["exploratory"]
        self.assertEqual(ex["pooled_with_receiver_2026"]["ubx_m9"]["n"], 15)
        self.assertNotIn("simulation", ex["pooled_with_receiver_2026"])
        self.assertEqual(ex["by_receiver_and_study"]["ubx_f9p fleet-health-2026"]["n"], 12)
        self.assertEqual(ex["by_receiver_and_release"]["ubx_m8 v1.15"]["n"], 12)


if __name__ == "__main__":
    unittest.main()
