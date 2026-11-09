"""Synthetic tests for gnss_latency.py (no flight log needed).

    python -m unittest -v test_gnss_latency
"""
import math
import unittest

import numpy as np

import gnss_latency as gl

C45 = math.cos(math.pi / 4)


def vel(t):
    """A smooth horizontal velocity history (north, east), m/s."""
    vn = 2.0 * np.sin(2 * np.pi * 0.3 * t) + 1.0 * np.sin(2 * np.pi * 0.7 * t + 1.0)
    ve = 1.5 * np.sin(2 * np.pi * 0.45 * t + 0.5) + 0.5 * np.sin(2 * np.pi * 1.1 * t)
    return np.column_stack((vn, ve))


def synthetic(delay_s, yaw_deg=90.0, seed=1, bias=(0.05, -0.03), noise=0.3, gnss_dt=0.1):
    """IMU at 250 Hz, attitude at 100 Hz, GNSS every gnss_dt showing the velocity delay_s ago."""
    rng = np.random.default_rng(seed)
    imu_t = np.arange(0.0, 120.0, 0.004)
    v = vel(imu_t)
    a_ne = np.vstack((v[1] - v[0], np.diff(v, axis=0))) / 0.004  # mean since the previous sample
    psi = math.radians(yaw_deg)
    c, s = math.cos(psi), math.sin(psi)
    # body = R^T ned for a yaw-only attitude
    fx = c * a_ne[:, 0] + s * a_ne[:, 1] + bias[0]
    fy = -s * a_ne[:, 0] + c * a_ne[:, 1] + bias[1]
    fz = np.full(len(imu_t), -9.80665)
    f_body = np.column_stack((fx, fy, fz)) + rng.normal(0, noise, (len(imu_t), 3))
    att_t = np.arange(0.0, 120.0, 0.01)
    q = np.tile([math.cos(psi / 2), 0.0, 0.0, math.sin(psi / 2)], (len(att_t), 1))
    gnss_t = np.arange(0.05, 120.0, gnss_dt)
    vel_ne = vel(gnss_t - delay_s) + rng.normal(0, 0.03, (len(gnss_t), 2))
    return imu_t, f_body, att_t, q, gnss_t, vel_ne


class TestRotation(unittest.TestCase):
    def test_yaw90_body_x_points_east(self):
        q = np.array([[C45, 0.0, 0.0, C45]])
        ne = gl.quat_to_ne(q, np.array([[1.0, 0.0, -9.8]]))
        self.assertAlmostEqual(ne[0, 0], 0.0, places=9)
        self.assertAlmostEqual(ne[0, 1], 1.0, places=9)

    def test_level_gravity_has_no_horizontal_part(self):
        q = np.array([[1.0, 0.0, 0.0, 0.0]])
        ne = gl.quat_to_ne(q, np.array([[0.0, 0.0, -9.8]]))
        self.assertAlmostEqual(abs(ne).max(), 0.0, places=12)

    def test_interp_quat_handles_sign_flip(self):
        q = np.array([[C45, 0.0, 0.0, C45], [-C45, 0.0, 0.0, -C45]])
        out = gl.interp_quat(np.array([0.5]), np.array([0.0, 1.0]), q)
        self.assertAlmostEqual(float(np.linalg.norm(out[0])), 1.0, places=12)
        self.assertAlmostEqual(abs(out[0, 0]), C45, places=9)
        self.assertAlmostEqual(abs(out[0, 3]), C45, places=9)


class TestHelpers(unittest.TestCase):
    def test_parabolic_peak_exact_on_a_parabola(self):
        lags = np.arange(-0.1, 0.1001, 0.005)
        c = 1.0 - (lags - 0.0123) ** 2
        lag, peak, edge = gl.parabolic_peak(c, lags)
        self.assertFalse(edge)
        self.assertAlmostEqual(lag, 0.0123, places=9)

    def test_parabolic_peak_edge(self):
        lags = np.arange(0.0, 0.1, 0.01)
        lag, peak, edge = gl.parabolic_peak(lags.copy(), lags)
        self.assertTrue(edge)
        self.assertAlmostEqual(lag, lags[-1])

    def test_integrate_mean_since_previous(self):
        t = np.array([0.0, 1.0, 3.0])
        a = np.array([[5.0, 0.0], [1.0, 2.0], [0.5, -1.0]])
        v = gl.integrate(t, a)
        self.assertEqual(v[:, 0].tolist(), [0.0, 1.0, 2.0])
        self.assertEqual(v[:, 1].tolist(), [0.0, 2.0, 0.0])

    def test_air_intervals(self):
        t = np.array([0, 1, 2, 3, 4, 5], float)
        landed = np.array([1, 1, 0, 0, 1, 0], bool)
        self.assertEqual(gl.air_intervals(t, landed, 9.0), [(2.0, 4.0), (5.0, 9.0)])

    def test_gap_mask(self):
        t = np.array([0.0, 0.1, 0.2, 1.5, 1.6])
        grid = np.array([0.05, 0.15, 0.8, 1.55])
        self.assertEqual(gl.gap_mask(grid, t, 0.5).tolist(), [True, True, False, True])

    def test_increasing(self):
        t, a = gl.increasing(np.array([2.0, 1.0, 1.0, 3.0]), np.array([20, 10, 11, 30]))
        self.assertEqual(t.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(a.tolist(), [10, 20, 30])

    def test_bus_name(self):
        self.assertEqual(gl.bus_name(0x850003), "UAVCAN")
        self.assertEqual(gl.bus_name(0xAA0005), "serial")
        self.assertIsNone(gl.bus_name(None))


class TestAppliedDelay(unittest.TestCase):
    def test_ekf2_parameter_wins_up_to_v117(self):
        recv = np.array([1000000, 1100000])
        self.assertEqual(gl.applied_delay({"EKF2_GPS_DELAY": 110}, recv, recv - 5000),
                         (110.0, "EKF2_GPS_DELAY"))

    def test_sample_stamps_on_v118_and_main(self):
        recv = np.array([1000000, 1100000, 1200000])
        smp = recv - np.array([90000, 100000, 110000])
        self.assertEqual(gl.applied_delay({"SENS_GNSS0_DELAY": 110}, recv, smp),
                         (100.0, "timestamp - timestamp_sample"))

    def test_parameter_when_no_sample_stamps(self):
        recv = np.array([1000000, 1100000])
        self.assertEqual(gl.applied_delay({"SENS_GNSS0_DELAY": 110}, recv, np.zeros(2, np.int64)),
                         (110.0, "SENS_GNSS0_DELAY"))
        self.assertEqual(gl.applied_delay({}, recv, None), (None, None))


class TestEstimateDelay(unittest.TestCase):
    def check(self, delay_s, tol_s=0.003, **kw):
        imu_t, f_body, att_t, q, gnss_t, vel_ne = synthetic(delay_s, **kw)
        fit = gl.estimate_delay(imu_t, f_body, att_t, q, gnss_t, vel_ne, [(5.0, 115.0)])
        self.assertIsNotNone(fit)
        self.assertFalse(fit["edge"])
        self.assertLess(abs(fit["delay_s"] - delay_s), tol_s, fit["delay_s"])
        self.assertGreater(fit["r"], 0.9)
        return fit

    def test_150_ms(self):
        self.check(0.150)

    def test_40_ms_level_attitude(self):
        self.check(0.040, yaw_deg=0.0)

    def test_zero(self):
        self.check(0.0, yaw_deg=-30.0, seed=3)

    def test_210_ms_at_5_hz(self):
        self.check(0.210, gnss_dt=0.2, seed=4)

    def test_beyond_window_is_flagged_at_edge(self):
        imu_t, f_body, att_t, q, gnss_t, vel_ne = synthetic(0.45)
        fit = gl.estimate_delay(imu_t, f_body, att_t, q, gnss_t, vel_ne, [(5.0, 115.0)], max_lag_s=0.3)
        self.assertTrue(fit["edge"])

    def test_too_little_airborne_time(self):
        imu_t, f_body, att_t, q, gnss_t, vel_ne = synthetic(0.1)
        self.assertIsNone(gl.estimate_delay(imu_t, f_body, att_t, q, gnss_t, vel_ne, [(5.0, 15.0)]))


if __name__ == "__main__":
    unittest.main()
