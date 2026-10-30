"""Tests for innov.py on synthetic flights whose GPS is late by L while EKF2
assumes P. By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import unittest

import numpy as np

import innov
from test_gps_lag import synth, velocity


def innovations(log, lag_s, param_s=0.11, scale=1.0, noise=0.0, with_sample=True, seed=1):
    """What EKF2 would log: GPS stamped at t_g reads v(t_g - L) and is fused at
    t_g - P against a state that knows v(t_g - P)."""
    t_g = np.asarray(log["gps_t"], dtype=float)
    t_s = t_g - param_s
    inn = scale * (velocity(t_g - lag_s) - velocity(t_s))
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
        self.assertLess(r["r"], -0.9)        # late GPS: innovation opposes acceleration

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


if __name__ == "__main__":
    unittest.main()
