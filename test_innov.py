"""Tests for innov.py on synthetic flights whose GPS is late by L while EKF2
assumes P. By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import os
import tempfile
import unittest

import numpy as np

import innov
from test_gps_lag import synth, velocity


def innovations(log, lag_s, param_s=0.11, scale=1.0, noise=0.0, with_sample=True, seed=1):
    """What EKF2 would log, in PX4's sign (prediction minus measurement): GPS
    stamped at t_g reads v(t_g - L) and is fused at t_g - P against a state
    that knows v(t_g - P)."""
    t_g = np.asarray(log["gps_t"], dtype=float)
    t_s = t_g - param_s
    inn = scale * (velocity(t_s) - velocity(t_g - lag_s))
    if noise:
        inn = inn + np.random.default_rng(seed).normal(0.0, noise, inn.shape)
    return {"t_log": t_s + param_s, "t_sample": t_s if with_sample else None, "inn": inn,
            "topic": "estimator_innovations"}


class ImpliedExcess(unittest.TestCase):
    def test_late_gps_gives_a_positive_excess(self):
        log = synth()
        r = innov.measure_innov(log, innovations(log, 0.20))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["implied_excess_ms"] - 90.0), 12.0)
        self.assertEqual(r["time_source"], "timestamp_sample")
        self.assertGreater(r["r"], 0.9)      # late GPS: PX4's innovation follows acceleration

    def test_early_gps_gives_a_negative_excess(self):
        log = synth()
        r = innov.measure_innov(log, innovations(log, 0.05, noise=0.05))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["implied_excess_ms"] + 60.0), 12.0)

    def test_without_a_sample_time_the_param_is_used(self):
        log = synth()
        r = innov.measure_innov(log, innovations(log, 0.20, with_sample=False))
        self.assertEqual(r["time_source"], "timestamp - param")
        self.assertLess(abs(r["implied_excess_ms"] - 90.0), 12.0)

    def test_a_filter_that_follows_the_gps_shrinks_the_slope(self):
        log = synth()
        full = innov.measure_innov(log, innovations(log, 0.20))
        half = innov.measure_innov(log, innovations(log, 0.20, scale=0.5))
        self.assertAlmostEqual(half["implied_excess_ms"], full["implied_excess_ms"] / 2, delta=1.0)

    def test_repeated_and_zero_innovations_are_dropped(self):
        log = synth()
        inv = innovations(log, 0.20)
        base = innov.measure_innov(log, inv)["innov_samples"]
        inv["inn"][1::2] = inv["inn"][0::2][:len(inv["inn"][1::2])]     # every second sample repeats
        repeated = innov.measure_innov(log, inv)["innov_samples"]
        self.assertLess(repeated, base * 0.6)
        inv = innovations(log, 0.20)
        inv["inn"][:] = 0.0
        r = innov.measure_innov(log, inv)
        self.assertFalse(r["passed"])
        self.assertEqual(r["innov_samples"], 0)

    def test_landed_log_does_not_pass(self):
        log = synth(landed=1)
        r = innov.measure_innov(log, innovations(log, 0.20))
        self.assertFalse(r["passed"])
        self.assertEqual(r["reason"], "too few in-flight innovations")

    def test_window_clear(self):
        imu_t = np.concatenate([np.arange(0, 10, 0.01), np.arange(11, 20, 0.01)])
        keep = innov.window_clear(np.array([0.05, 5.0, 10.5, 10.95, 15.0, 19.95]), imu_t)
        self.assertEqual(list(keep), [False, True, False, False, True, False])


class Scoring(unittest.TestCase):
    def test_ranks_and_spearman(self):
        self.assertEqual(innov.ranks([3, 1, 2, 2]), [4.0, 1.0, 2.5, 2.5])
        self.assertAlmostEqual(innov.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(innov.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(innov.spearman([1, 2], [1, 2]))

    @staticmethod
    def rows(sign_of_far=1.0):
        rows = []
        for i in range(35):
            d = 60.0 + i
            rows.append({"passed": True, "lag_minus_param_ms": d, "implied_excess_ms": sign_of_far * 0.5 * d,
                         "implied_se_ms": 3.0, "time_source": "timestamp_sample"})
        for i in range(15):
            d = -60.0 - i
            rows.append({"passed": True, "lag_minus_param_ms": d, "implied_excess_ms": sign_of_far * 0.5 * d,
                         "implied_se_ms": 3.0, "time_source": "timestamp - param"})
        for i in range(20):
            rows.append({"passed": True, "lag_minus_param_ms": float(i), "implied_excess_ms": 2.0,
                         "implied_se_ms": 3.0, "time_source": "timestamp_sample"})
        rows.append({"passed": False, "reason": "too few in-flight innovations"})
        return rows

    def test_agreeing_innovations_decide_c1(self):
        s = innov.summarise(self.rows())
        self.assertEqual(s["validated"], 70)
        self.assertEqual(s["far"]["n"], 50)
        self.assertEqual(s["far"]["same_sign_share"], 1.0)
        self.assertEqual(s["far"]["median_ratio_implied_to_measured"], 0.5)
        self.assertEqual(s["checks"], {"VE1": True, "V1": True, "V2": True, "V3": True, "V4": True})
        self.assertEqual(s["decision"], "C1")
        self.assertEqual(s["time_source"], {"timestamp_sample": 55, "timestamp - param": 15})
        self.assertEqual(s["not_passed_reasons"], {"too few in-flight innovations": 1})

    def test_contrary_innovations_decide_c2(self):
        s = innov.summarise(self.rows(sign_of_far=-1.0))
        self.assertFalse(s["checks"]["V1"])
        self.assertFalse(s["checks"]["V2"])
        self.assertEqual(s["decision"], "C2")

    def test_too_few_is_a_pilot(self):
        s = innov.summarise(self.rows()[:30])
        self.assertFalse(s["checks"]["VE1"])
        self.assertEqual(s["decision"], "pilot")


class Sources(unittest.TestCase):
    def test_fleet_rows_pass_through(self):
        row = {"log_id": "a", "passed": True, "lag_ms": 150.0, "lag_minus_param_ms": 40.0}
        self.assertEqual(innov.source_row(row), row)

    def test_fleet_health_rows_are_read_from_lag(self):
        row = {"log_id": "a", "vehicle": "v", "health_ok": True,
               "lag": {"passed": True, "lag_ms": 67.3, "lag_minus_param_ms": -42.7, "gps_bus": "uavcan"}}
        s = innov.source_row(row)
        self.assertTrue(s["passed"])
        self.assertEqual((s["log_id"], s["vehicle"], s["lag_minus_param_ms"], s["gps_bus"]),
                         ("a", "v", -42.7, "uavcan"))
        self.assertFalse(innov.source_row({"log_id": "b", "lag": {"passed": False}})["passed"])

    def test_rescoring_0_1_0_rows_flips_every_signed_check(self):
        old = [dict(r) for r in Scoring.rows(sign_of_far=-1.0)]
        for r in old:
            if "implied_excess_ms" in r:
                r["implied_excess_ms"] = -r["implied_excess_ms"]   # as 0.1.0 wrote them
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "innov.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for r in old:
                    f.write(json.dumps(r) + "\n")
            s = innov.rescore_v010(path, os.path.join(tmp, "out"))
            self.assertTrue(os.path.exists(os.path.join(tmp, "out", "summary.json")))
        before = innov.summarise(old)
        self.assertAlmostEqual(s["spearman_rho"], -before["spearman_rho"])
        self.assertAlmostEqual(s["far"]["same_sign_share"], 1 - before["far"]["same_sign_share"])
        self.assertAlmostEqual(s["far"]["median_ratio_implied_to_measured"],
                               -before["far"]["median_ratio_implied_to_measured"])
        self.assertEqual(s["near"]["median_abs_implied_ms"], before["near"]["median_abs_implied_ms"])


if __name__ == "__main__":
    unittest.main()
