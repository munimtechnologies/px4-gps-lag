"""Tests for gps_lag.py on synthetic flights with a known GPS delay.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import math
import unittest

import numpy as np

import gps_lag as gl

G = 9.80665
W = [2 * math.pi * f for f in (0.13, 0.31, 0.21, 0.47)]


def velocity(t):
    """North and east velocity of the synthetic vehicle (m/s)."""
    t = np.asarray(t, dtype=float)
    vn = -1.5 / W[0] * np.cos(W[0] * t) - 0.8 / W[1] * np.cos(W[1] * t + 1.0)
    ve = -1.2 / W[2] * np.cos(W[2] * t + 0.5) - 0.6 / W[3] * np.cos(W[3] * t + 2.0)
    return np.column_stack([vn, ve])


def synth(delay_s=0.15, yaw_rate=0.2, yaw0=0.3, bias_body=(0.0, 0.0), t0=10.0,
          duration=300.0, imu_hz=200, att_hz=20, gps_dt=0.5, landed=0):
    imu_t = t0 + np.arange(int(duration * imu_hz) + 1) / imu_hz
    v = velocity(imu_t)
    a = np.empty_like(v)
    a[1:] = (v[1:] - v[:-1]) * imu_hz       # mean over each IMU interval
    a[0] = a[1]
    yaw = yaw0 + yaw_rate * imu_t
    c, s = np.cos(yaw), np.sin(yaw)
    fx = c * a[:, 0] + s * a[:, 1] + bias_body[0]
    fy = -s * a[:, 0] + c * a[:, 1] + bias_body[1]
    fz = np.full(len(imu_t), -G)
    att_t = t0 + np.arange(int(duration * att_hz) + 1) / att_hz
    ya = yaw0 + yaw_rate * att_t
    q = np.column_stack([np.cos(ya / 2), np.zeros(len(att_t)), np.zeros(len(att_t)), np.sin(ya / 2)])
    gps_t = np.arange(t0 + 5.0, t0 + duration - 2.0, gps_dt)
    return {
        "imu_t": imu_t, "f_body": np.column_stack([fx, fy, fz]), "att_t": att_t, "q": q,
        "gps_t": gps_t, "vel_ne": velocity(gps_t - delay_s), "usable": np.ones(len(gps_t), bool),
        "land_t": np.array([t0]), "landed": np.array([landed], dtype=np.int8),
        "facts": {"param_gps_delay_ms": 110.0, "gps_bus": "serial"},
    }


class RecoversDelay(unittest.TestCase):
    def test_on_grid_delay(self):
        r = gl.measure(synth(delay_s=0.15))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["lag_s"] - 0.15), 0.003)
        self.assertEqual(r["lag_minus_param_ms"], round(r["lag_ms"] - 110.0, 1))
        self.assertGreater(r["r2"], 0.99)

    def test_off_grid_delay(self):
        r = gl.measure(synth(delay_s=0.0625))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["lag_s"] - 0.0625), 0.003)

    def test_long_delay(self):
        r = gl.measure(synth(delay_s=0.42))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["lag_s"] - 0.42), 0.003)

    def test_constant_bias_is_absorbed(self):
        r = gl.measure(synth(delay_s=0.15, yaw_rate=0.0, bias_body=(0.2, -0.1)))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["lag_s"] - 0.15), 0.003)
        self.assertGreater(abs(r["bias_ne_m_s2"][0]) + abs(r["bias_ne_m_s2"][1]), 0.1)

    def test_fast_gps_logging(self):
        r = gl.measure(synth(delay_s=0.11, gps_dt=0.1))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["lag_s"] - 0.11), 0.003)

    def test_quaternion_sign_flips_change_nothing(self):
        log = synth(delay_s=0.15)
        base = gl.measure(log)
        log["q"] = log["q"].copy()
        log["q"][1::2] *= -1
        flipped = gl.measure(log)
        self.assertAlmostEqual(base["lag_s"], flipped["lag_s"], places=6)


class Selection(unittest.TestCase):
    def test_landed_log_has_no_pairs(self):
        r = gl.measure(synth(landed=1))
        self.assertFalse(r["passed"])
        self.assertEqual(r["pairs"], 0)
        self.assertEqual(r["reason"], "too few in-flight GPS pairs")

    def test_imu_gap_drops_pairs_but_not_the_answer(self):
        log = synth(delay_s=0.15)
        full = len(gl.gps_pairs(log["gps_t"], log["usable"], log["imu_t"]))
        keep = (log["imu_t"] < 110.0) | (log["imu_t"] > 111.0)
        log["imu_t"] = log["imu_t"][keep]
        log["f_body"] = log["f_body"][keep]
        idx = gl.gps_pairs(log["gps_t"], log["usable"], log["imu_t"])
        self.assertLess(len(idx), full)
        # no kept pair's IMU window touches the gap
        ws = log["gps_t"][idx] - gl.LAG_MAX_S
        we = log["gps_t"][idx + 1] - gl.LAG_MIN_S
        self.assertFalse(np.any((ws < 111.0) & (we > 110.0)))
        r = gl.measure(log)
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["lag_s"] - 0.15), 0.003)

    def test_pairs_need_both_samples_usable_and_close(self):
        gps_t = np.array([10.0, 10.5, 11.0, 13.0, 13.5])
        usable = np.array([True, True, False, True, True])
        imu_t = np.arange(0, 2000) * 0.01
        self.assertEqual(list(gl.gps_pairs(gps_t, usable, imu_t)), [0, 3])

    def test_flying_at(self):
        f = gl.flying_at([5, 15, 25, 35], np.array([10.0, 20.0, 30.0]), np.array([1, 0, 1]))
        self.assertEqual(list(f), [False, False, True, False])
        self.assertFalse(np.any(gl.flying_at([1, 2], None, None)))

    def test_gates(self):
        ok = {"pairs": 200, "excitation_m_s2": 0.5, "edge": False, "r2": 0.9, "se_s": 0.004}
        self.assertEqual(gl.passes(ok), (True, "ok"))
        self.assertFalse(gl.passes(dict(ok, pairs=99))[0])
        self.assertFalse(gl.passes(dict(ok, excitation_m_s2=0.2))[0])
        self.assertFalse(gl.passes(dict(ok, edge=True))[0])
        self.assertFalse(gl.passes(dict(ok, r2=0.5))[0])
        self.assertFalse(gl.passes(dict(ok, se_s=0.03))[0])
        self.assertFalse(gl.passes(dict(ok, se_s=float("inf")))[0])


class Pieces(unittest.TestCase):
    def test_yaw_90_maps_forward_to_east(self):
        h = math.sqrt(0.5)
        a = gl.ne_accel(np.array([1.0]), np.array([[1.0, 0.0, -G]]),
                        np.array([0.0, 2.0]), np.array([[h, 0, 0, h], [h, 0, 0, h]]))
        self.assertAlmostEqual(a[0, 0], 0.0, places=9)
        self.assertAlmostEqual(a[0, 1], 1.0, places=9)

    def test_level_gravity_has_no_horizontal_part(self):
        a = gl.ne_accel(np.array([1.0]), np.array([[0.0, 0.0, -G]]),
                        np.array([0.0, 2.0]), np.array([[1.0, 0, 0, 0], [1.0, 0, 0, 0]]))
        self.assertAlmostEqual(a[0, 0], 0.0, places=9)
        self.assertAlmostEqual(a[0, 1], 0.0, places=9)

    def test_bus_type(self):
        self.assertEqual(gl.bus_type(0), "unknown")
        self.assertEqual(gl.bus_type(5 | (1 << 3) | (0x42 << 16)), "serial")
        self.assertEqual(gl.bus_type(3 | (0x7C << 8)), "uavcan")
        self.assertEqual(gl.bus_type(None), "unknown")

    def test_release_name(self):
        self.assertEqual(gl.release_name(0x010E03FF), "v1.14.3")
        self.assertEqual(gl.release_name(0x010F0000), "v1.15.0-0")
        self.assertIsNone(gl.release_name(0))
        self.assertIsNone(gl.release_name("x"))

    def test_lag_grid(self):
        lags = gl.lag_grid()
        self.assertEqual(len(lags), 201)
        self.assertAlmostEqual(lags[0], -0.2)
        self.assertAlmostEqual(lags[-1], 0.8)


if __name__ == "__main__":
    unittest.main()
