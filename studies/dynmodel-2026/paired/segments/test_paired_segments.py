"""Tests for paired_segments.py on synthetic flights with known GPS lags.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import unittest

import numpy as np

import paired_segments as ps

W = [(2.0, 0.31, 0.0), (1.5, 0.73, 1.0), (0.8, 1.37, 2.0)]   # amplitude m/s^2, Hz, phase


def accel(t, shift=0.0):
    return sum(a * np.sin(2 * np.pi * f * t + p + shift) for a, f, p in W)


def vel(t, shift=0.0):
    return sum(-a / (2 * np.pi * f) * np.cos(2 * np.pi * f * t + p + shift) for a, f, p in W)


def synthetic(lag_s, seconds=150.0, gps_hz=5.0, bias=0.05, h=0.004):
    """A level vehicle (identity attitude) whose GPS velocity is the true velocity lag_s earlier.
    Each IMU sample is the mean acceleration since the one before it, as in sensor_combined."""
    imu_t = np.arange(h, seconds, h)
    mean_n = (vel(imu_t) - vel(imu_t - h)) / h
    mean_e = (vel(imu_t, 0.5) - vel(imu_t - h, 0.5)) / h
    f = np.column_stack([mean_n + bias, mean_e - bias, np.full(len(imu_t), -9.81)])
    gps_t = np.arange(2.0, seconds - 2.0, 1.0 / gps_hz)
    sample = gps_t - lag_s
    vel_ne = np.column_stack([vel(sample), vel(sample, 0.5)])
    return {"imu_t": imu_t, "f_body": f, "att_t": np.array([0.0, seconds]),
            "q": np.array([[1.0, 0, 0, 0], [1.0, 0, 0, 0]]), "gps_t": gps_t, "vel_ne": vel_ne,
            "usable": np.ones(len(gps_t), dtype=bool), "land_t": np.array([0.0]), "landed": np.array([0]),
            "facts": {}}


class Segments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p6 = ps.prepare(synthetic(0.200))
        cls.p7 = ps.prepare(synthetic(0.100))

    def test_whole_flight_recovers_the_lag(self):
        self.assertAlmostEqual(ps.fit(self.p6)["lag_ms"], 200.0, delta=3.0)
        self.assertAlmostEqual(ps.fit(self.p7)["lag_ms"], 100.0, delta=3.0)

    def test_thirds_cover_every_pair_once_in_order(self):
        n = len(self.p6["t1"])
        parts = ps.thirds(n)
        self.assertEqual(len(parts), 3)
        self.assertEqual(sum(parts, []), list(range(n)))
        for s in parts:
            self.assertAlmostEqual(ps.fit(self.p6, s)["lag_ms"], 200.0, delta=3.0)

    def test_block_indices(self):
        rng = np.random.default_rng(1)
        idx = ps.block_indices(103, rng, block=25)
        self.assertEqual(len(idx), 103)
        self.assertTrue(np.all((idx >= 0) & (idx < 103)))
        for k in range(0, 100, 25):            # every block is contiguous
            blk = idx[k:min(k + 25, 103)]
            self.assertTrue(np.all(np.diff(blk) == 1))
        self.assertEqual(list(ps.block_indices(10, rng, block=25)), list(range(10)))
        a = ps.block_indices(300, np.random.default_rng(ps.SEED))
        b = ps.block_indices(300, np.random.default_rng(ps.SEED))
        self.assertEqual(list(a), list(b))

    def test_pair_accel_matches_the_synthetic_motion(self):
        gps_acc, imu_acc = ps.pair_accel(self.p7)
        self.assertEqual(len(gps_acc), len(self.p7["t1"]))
        self.assertLess(float(np.max(imu_acc)), 9.0)       # at most about 4.4 m/s^2 per axis
        self.assertGreater(float(np.median(gps_acc)), 0.5)

    def test_analyse(self):
        out = ps.analyse({"a.ulg": self.p6, "b.ulg": self.p7},
                         {"a.ulg": (6, round(ps.fit(self.p6)["lag_ms"], 1)), "b.ulg": (7, round(ps.fit(self.p7)["lag_ms"], 1))})
        self.assertTrue(out["reproduced_all"])
        d = out["diff_6_minus_7"]
        self.assertAlmostEqual(d["whole_ms"], 100.0, delta=4.0)
        self.assertTrue(d["thirds_separated"])
        self.assertLessEqual(d["block_bootstrap_ms"]["p2.5"], d["block_bootstrap_ms"]["p97.5"])
        self.assertAlmostEqual(d["block_bootstrap_ms"]["p50"], 100.0, delta=4.0)
        self.assertAlmostEqual(d["low_accel_ms"], 100.0, delta=6.0)
        self.assertAlmostEqual(d["high_accel_ms"], 100.0, delta=6.0)
        self.assertEqual(out["logs"]["a.ulg"]["imu_horizontal_accel_m_s2"]["share_over_1g"], 0.0)

    def test_a_wrong_published_lag_is_caught(self):
        out = ps.analyse({"a.ulg": self.p6, "b.ulg": self.p7}, {"a.ulg": (6, 150.0), "b.ulg": (7, 100.0)})
        self.assertFalse(out["reproduced_all"])


if __name__ == "__main__":
    unittest.main()
