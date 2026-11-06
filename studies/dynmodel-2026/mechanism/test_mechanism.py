"""Synthetic tests for mechanism.py (no log is read). By MV2 of Munim, Inc.; written with AI agents.
Apache-2.0."""

import json
import unittest

import numpy as np

import mechanism as mc


def synth(D, tau, T=120.0, seed=3, n_sin=40):
    """IMU at 250 Hz from a sum of sinusoids (0.05-2.4 Hz) and 5 Hz GPS velocity that is the true
    velocity through a first-order low-pass (tau) and then a delay (D), both exact."""
    rng = np.random.default_rng(seed)
    imu_t = np.arange(0.0, T, 0.004)
    w = 2 * np.pi * rng.uniform(0.05, 2.4, size=(n_sin, 2))
    ph = rng.uniform(0, 2 * np.pi, size=(n_sin, 2))
    A = rng.uniform(0.5, 1.5, size=(n_sin, 2))
    a_ne = np.column_stack([(A[:, k] * np.sin(np.outer(imu_t, w[:, k]) + ph[:, k])).sum(axis=1)
                            for k in range(2)])
    gps_t = np.arange(2.0, T - 1.0, 0.2)
    s = gps_t - D
    g = 1.0 / np.sqrt(1.0 + (w * tau) ** 2)
    th = np.arctan(w * tau)
    vel = np.column_stack([(-(A[:, k] / w[:, k]) * g[:, k] * np.cos(np.outer(s, w[:, k]) + ph[:, k] - th[:, k]))
                           .sum(axis=1) for k in range(2)])
    return imu_t, a_ne, gps_t[:-1], gps_t[1:], np.diff(vel, axis=0)


class TestGrid(unittest.TestCase):
    def test_pure_delay_is_found_as_delay(self):
        f, taus, lags = mc.fit_grid(*synth(0.15, 0.0), resamples=3)
        self.assertLessEqual(f["tau_ms"], 10.0)
        self.assertLessEqual(abs(f["sum_ms"] - 150.0), 10.0)
        self.assertLessEqual(abs(f["lag_tau0_ms"] - 150.0), 10.0)
        self.assertGreater(f["r2"], 0.99)
        self.assertEqual(len(taus), 3)
        self.assertEqual(len(f["profile"]), len(mc.TAUS))

    def test_smoothing_is_found_as_tau(self):
        f, _, _ = mc.fit_grid(*synth(0.05, 0.10), resamples=3)
        self.assertLessEqual(abs(f["tau_ms"] - 100.0), 20.0)
        self.assertLessEqual(abs(f["lag_ms"] - 50.0), 15.0)
        self.assertGreater(f["r2"], 0.99)
        self.assertGreater(f["lag_tau0_ms"], 100.0)     # a delay-only fit sees most of tau as delay
        self.assertGreater(f["r2"], f["r2_tau0"])


class TestHelpers(unittest.TestCase):
    def test_lowpass_step(self):
        t = np.arange(0.0, 1.0, 0.004)
        v = np.ones((len(t), 1))
        v[0, 0] = 0.0
        y = mc.lowpass(t, v, 0.1)
        self.assertAlmostEqual(y[0, 0], 0.0, places=9)
        self.assertAlmostEqual(y[25, 0], 1.0 - np.exp(-1.0), places=3)
        np.testing.assert_array_equal(mc.lowpass(t, v, 0.0), v)

    def test_lowpass_constant_stays(self):
        t = np.arange(0.0, 1.0, 0.004)
        v = np.full((len(t), 2), 3.0)
        np.testing.assert_allclose(mc.lowpass(t, v, 0.2), v)

    def test_block_indices(self):
        rng = np.random.default_rng(1)
        idx = mc.block_indices(100, rng, 25)
        self.assertEqual(len(idx), 100)
        np.testing.assert_array_equal(np.diff(idx[:25]), np.ones(24))
        np.testing.assert_array_equal(mc.block_indices(10, rng, 25), np.arange(10))

    def test_counter_increments_wrap(self):
        self.assertEqual(mc.counter_increments([250, 255, 2, 2]), 8)
        self.assertEqual(mc.counter_increments([4]), 0)

    def test_fresh(self):
        np.testing.assert_array_equal(mc.fresh([[1, 1], [1, 1], [2, 1]]), [True, False, True])

    def test_ekf_stats(self):
        ts = np.array([0, 1e6, 2e6, 3e6])
        data = {"estimator_innovation_test_ratios": {"timestamp": ts, "gps_hvel[0]": np.array([0.5, 0.5, 2.0, 0.1]),
                                                      "gps_hvel[1]": np.array([0.2, 0.2, 0.1, 0.3])},
                "estimator_status": {"timestamp": ts, "reset_count_vel_ne": np.array([0, 0, 1, 3], dtype=np.uint8)},
                "estimator_status_flags": {"timestamp": ts, "reject_hor_vel": np.array([0, 1, 0, 1], dtype=np.uint8)}}
        out = mc.ekf_stats(data, lambda t: t >= 1.0)
        hv = out["gps_hvel_test_ratio"]
        self.assertEqual(hv["n"], 2)
        self.assertEqual(hv["share_over_1"], 0.5)
        self.assertAlmostEqual(hv["p50"], 1.15)
        self.assertIsNone(out["gps_hpos_test_ratio"])
        self.assertEqual(out["resets"]["reset_count_vel_ne"], {"in_flight": 3, "whole_log": 3})
        self.assertEqual(out["flags"]["reject_hor_vel"]["share_in_flight"], 0.6667)
        out2 = mc.ekf_stats(data, lambda t: True)      # a scalar answer is broadcast
        self.assertEqual(out2["resets"]["reset_count_vel_ne"]["in_flight"], 3)
        json.dumps(mc.plain(out))

    def test_plain_round_trip(self):
        s = json.dumps(mc.plain({"a": np.float64(1.5), "b": np.bool_(True), "c": np.int64(3),
                                 "d": np.array([1.0, np.nan]), "e": float("inf"), 6: (1, 2)}))
        self.assertEqual(json.loads(s), {"a": 1.5, "b": True, "c": 3, "d": [1.0, None], "e": None, "6": [1, 2]})


def fake(tau, lag, lo, hi, edge=False, edge_share=0.0):
    return {"tau_ms": tau, "lag_ms": lag, "tau_edge": edge,
            "boot": {"tau_ms": [lo, tau, hi], "tau_at_edge_share": edge_share}}


class TestDecide(unittest.TestCase):
    def test_smoothing(self):
        r = mc.decide(fake(120, 90, 100, 140), fake(20, 90, 0, 40), [120, 110, 130], [20, 10, 30],
                      [90, 90, 90], [90, 90, 90])
        self.assertEqual(r["outcome"], "smoothing")
        self.assertEqual(r["tau_diff_ms"], 100)

    def test_smoothing_needs_interval_above_zero(self):
        r = mc.decide(fake(120, 90, 30, 125), fake(20, 90, 0, 40), [120, 30, 125], [20, 40, 30],
                      [90, 90, 90], [90, 90, 90])
        self.assertEqual(r["outcome"], "mixed")

    def test_delivery(self):
        r = mc.decide(fake(20, 190, 0, 40), fake(20, 90, 0, 40), [20, 20], [20, 20], [190, 190], [90, 90])
        self.assertEqual(r["outcome"], "delivery")

    def test_mixed(self):
        r = mc.decide(fake(60, 150, 40, 80), fake(20, 90, 0, 40), [60], [20], [150], [90])
        self.assertEqual(r["outcome"], "mixed")

    def test_not_identified(self):
        r = mc.decide(fake(120, 90, 0, 150), fake(20, 90, 0, 40), [120], [20], [90], [90])
        self.assertEqual(r["outcome"], "not identified")
        r = mc.decide(fake(250, 0, 200, 250, edge=True), fake(20, 90, 0, 40), [250], [20], [0], [90])
        self.assertEqual(r["outcome"], "not identified")
        json.dumps(mc.plain(r))


if __name__ == "__main__":
    unittest.main()
