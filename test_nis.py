"""Tests for nis.py and fresh_nis.py on synthetic data (no logs, no network).
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import math
import os
import tempfile
import unittest

import numpy as np

import fresh_nis
import nis


def flight(flags=False, landed=0, n=400, var=True):
    """Innovations every 0.5 s (0.5 .. n/2 s), variances 10 ms later.
    Landed until 50 s. Position innovation 1 m on both axes with variance
    4 m^2 (NIS 0.25), except a 0/0 sample at the end; velocity innovation
    2 m/s with variance 1 (NIS 4). GPS fix 3D until 150 s, RTK fixed after."""
    t = np.arange(1, n + 1) * 0.5
    pos_n, pos_e = np.ones(n), np.ones(n)
    pos_n[-1] = pos_e[-1] = 0.0
    vel = np.full(n, 2.0)
    var_t = t + 0.01 if var else np.array([])
    vp = np.full(len(var_t), 4.0)
    vv = np.ones(len(var_t))
    gps_t = np.arange(0, 2000) * 0.1
    fix = np.where(gps_t < 150, 3, 6)
    eph = np.full(len(gps_t), 1.2)
    kw = {}
    if flags:
        kw.update(flag_t=[0.0, 100.0], cs_gps=[1, 0])
    air_t, ld = ([0.0, 50.0], [1, 0]) if landed == 0 else ([0.0], [1])
    return nis.metrics(t, pos_n, pos_e, vel, vel, var_t, vp, vp, vv, vv, air_t, ld,
                       gps_t=gps_t, fix_type=fix, eph=eph, **kw)


def ar1(n, phi, seed):
    rng = np.random.default_rng(seed)
    e = rng.standard_normal((2, n))
    z = np.zeros((2, n))
    z[:, 0] = e[:, 0]
    s = math.sqrt(1 - phi * phi)
    for i in range(1, n):
        z[:, i] = phi * z[:, i - 1] + s * e[:, i]
    return z


class TestHelpers(unittest.TestCase):
    def test_nearest(self):
        got = nis.nearest([0, 1, 2], [0.4, 0.6, 2.2, 5], 0.5)
        self.assertEqual(list(got), [0, 1, 2, -1])
        self.assertEqual(list(nis.nearest([], [1.0], 0.5)), [-1])

    def test_last_at(self):
        got = nis.last_at([0, 10], [1, 0], [-1, 0, 5, 10, 11])
        self.assertTrue(math.isnan(got[0]))
        self.assertEqual(list(got[1:]), [1.0, 1.0, 0.0, 0.0])

    def test_autocorr_by_hand(self):
        old = nis.MIN_PAIRS
        try:
            nis.MIN_PAIRS = 1
            z = np.array([1.0, 1.0, -1.0, -1.0])
            t = [0.0, 1.0, 2.0, 3.0]
            ok = np.ones(4, dtype=bool)
            self.assertAlmostEqual(nis.autocorr(t, z, z, ok, 1.0), 1 / 3.0, places=4)
            self.assertAlmostEqual(nis.autocorr(t, z, z, ok, 2.0), -1.0)
        finally:
            nis.MIN_PAIRS = old
        self.assertIsNone(nis.autocorr(t, z, z, ok, 1.0))

    def test_autocorr_white_and_ar1(self):
        rng = np.random.default_rng(1)
        n = 4000
        t = np.arange(n) * 0.5
        za, zb = rng.standard_normal(n), rng.standard_normal(n)
        ok = np.ones(n, dtype=bool)
        self.assertLess(abs(nis.autocorr(t, za, zb, ok, 1.0)), 0.1)
        z = ar1(8000, 0.9, 7)
        t = np.arange(8000) * 0.5
        ok = np.ones(8000, dtype=bool)
        acf = {"%g" % lag: nis.autocorr(t, z[0], z[1], ok, lag) for lag in nis.LAGS_S}
        self.assertGreater(acf["1"], 0.65)      # 0.9 ** 2 = 0.81
        tau, above = nis.tau_e(acf)             # e-folding 1 / (2 ln(1/0.9)) = 4.75 s
        self.assertIsNone(above)
        self.assertTrue(3.5 < tau < 6.5, tau)

    def test_tau_e(self):
        tau, above = nis.tau_e({"1": 0.8, "2": 0.6, "5": 0.3, "10": 0.1, "20": 0.0})
        self.assertAlmostEqual(tau, 2 + (0.6 - math.exp(-1)) * 3 / 0.3, places=3)
        self.assertIsNone(above)
        self.assertEqual(nis.tau_e({"1": 0.9, "2": 0.9, "5": 0.9, "10": 0.9, "20": 0.9}), (None, 20.0))
        self.assertEqual(nis.tau_e({"1": 0.9, "2": 0.9, "5": None}), (None, 2.0))
        self.assertEqual(nis.tau_e({"1": None}), (None, None))
        self.assertAlmostEqual(nis.tau_e({"1": 0.0})[0], 1 - math.exp(-1), places=3)


class TestMetrics(unittest.TestCase):
    def test_nis_values(self):
        r = flight()
        self.assertTrue(r["nis_ok"])
        self.assertIsNone(r["nis_reason"])
        self.assertEqual(r["nis_pos_n"], 300)     # 50.0 .. 199.5 s; the 0/0 sample left out
        self.assertEqual(r["nis_vel_n"], 301)
        self.assertAlmostEqual(r["nis_pos_median"], 0.25)
        self.assertAlmostEqual(r["nis_pos_mean"], 0.25)
        self.assertAlmostEqual(r["nis_vel_median"], 4.0)
        self.assertAlmostEqual(r["nis_pos_gate_sd"], 10.0)   # 5 / sqrt(0.25)
        self.assertAlmostEqual(r["nis_vel_gate_sd"], 2.5)
        self.assertIsNone(r["nis_pos_acf"]["1"])              # constant innovations
        self.assertEqual((r["nis_pos_tau_s"], r["nis_pos_tau_above_s"]), (None, None))
        self.assertEqual(r["nis_fix_type_mode"], 3)
        self.assertAlmostEqual(r["nis_eph_median"], 1.2)
        self.assertFalse(r["nis_gps_flag"])

    def test_gps_flag(self):
        r = flight(flags=True)
        self.assertTrue(r["nis_gps_flag"])
        self.assertEqual(r["nis_n_base"], 100)    # in flight from 50 s, GPS fused until 100 s
        self.assertEqual(r["nis_pos_n"], 100)

    def test_landed_throughout(self):
        r = flight(landed=1)
        self.assertFalse(r["nis_ok"])
        self.assertEqual(r["nis_reason"], "landed throughout")
        self.assertIsNone(r["nis_fix_type_mode"])

    def test_no_variance(self):
        r = flight(var=False)
        self.assertFalse(r["nis_ok"])
        self.assertEqual(r["nis_reason"], "no matched variance")

    def test_too_few(self):
        r = flight(n=200)                          # 0.5 .. 100 s: 101 in flight, 100 for position
        self.assertTrue(r["nis_ok"])
        r = flight(n=200, flags=True)              # 50.0 .. 99.5 s
        self.assertEqual(r["nis_pos_n"], 100)
        r = flight(n=210)
        self.assertTrue(r["nis_ok"])
        r = flight(n=150)                          # 50 .. 75 s: 51 samples, 50 for position
        self.assertFalse(r["nis_ok"])
        self.assertEqual(r["nis_reason"], "too few samples (50)")

    def test_gate_param_used(self):
        t = np.arange(1, 201) * 0.5
        one = np.ones(200)
        r = nis.metrics(t, one, one, one, one, t, one * 4, one * 4, one, one, [0.0], [0], p_gate=3.0, v_gate=0.5)
        self.assertAlmostEqual(r["nis_pos_gate_sd"], 6.0)    # 3 / sqrt(0.25)
        self.assertAlmostEqual(r["nis_vel_gate_sd"], 1.0)    # gate floored at 1, NIS 1


def rows(n=80, pos=None, vel=0.05, a_pos=0.8, a_vel=0.5):
    out = []
    for i in range(n):
        out.append({"passed": True, "receiver": "ubx_m9", "grid_ms": 125, "nis_ok": True,
                    "nis_pos_median": 0.1 + 0.001 * i if pos is None else pos, "nis_vel_median": vel,
                    "nis_pos_mean": 0.3, "nis_pos_gate_sd": 9.0, "nis_pos_tau_s": 4.0, "nis_pos_tau_above_s": None,
                    "nis_pos_acf": {"1": a_pos, "2": a_pos / 2}, "nis_vel_acf": {"1": a_vel},
                    "nis_fix_type_mode": 3 if i % 2 else 6, "nis_eph_median": 1.0})
    return out


class TestSummarise(unittest.TestCase):
    def test_all_hold(self):
        s = nis.summarise(rows())
        self.assertEqual(s["usable"], 80)
        self.assertEqual(s["checks"], {"E0": True, "N1": True, "N2": True, "W1": True, "W2": True})
        self.assertAlmostEqual(s["N1_position_nis_median"]["median"], 0.1395, places=5)
        self.assertEqual(s["W1_position_autocorr_1s"]["ci95"], [0.8, 0.8])
        self.assertTrue(s["decision"]["D1_comment_on_rfc_28837"])

    def test_consistent_and_white(self):
        s = nis.summarise(rows(pos=0.7, a_pos=0.0))
        self.assertFalse(s["checks"]["N1"])
        self.assertFalse(s["checks"]["W1"])
        self.assertTrue(s["checks"]["N2"])
        self.assertTrue(s["decision"]["D1_comment_on_rfc_28837"])

    def test_too_few(self):
        s = nis.summarise(rows(n=20))
        self.assertEqual(s["checks"], {"E0": False, "N1": None, "N2": None, "W1": None, "W2": None})
        self.assertFalse(s["decision"]["D1_comment_on_rfc_28837"])

    def test_unusable_rows_left_out(self):
        extra = [dict(rows(1)[0], receiver="simulation"),
                 dict(rows(1)[0], nis_ok=False, nis_pos_median=None, nis_reason="too few samples (12)"),
                 dict(rows(1)[0], passed=False)]
        s = nis.summarise(rows() + extra)
        self.assertEqual(s["usable"], 80)
        self.assertEqual(s["not_usable_reasons"], {"too few samples": 1})

    def test_explore_groups(self):
        e = nis.explore(rows())
        self.assertEqual(e["all"]["n"], 80)
        self.assertEqual(e["by_fix_type"]["3D"]["n"], 40)
        self.assertEqual(e["by_fix_type"]["RTK fixed"]["n"], 40)
        self.assertEqual(e["by_receiver"]["ubx_m9"]["n"], 80)
        self.assertEqual(e["by_grid_ms"]["125"]["n"], 80)
        self.assertAlmostEqual(e["all"]["pos_acf_median"]["2"], 0.4)
        self.assertIsNone(e["all"]["pos_acf_median"]["5"])

    def test_score_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            nis.score(rows(), d, {"x": 1})
            with open(os.path.join(d, "nis-summary.json"), encoding="utf-8") as f:
                got = json.load(f)
        self.assertEqual(got["nis_py"], nis.__version__)
        self.assertEqual(got["x"], 1)
        self.assertIn("by_fix_type", got["exploratory"])


class TestCombine(unittest.TestCase):
    def test_all_fields(self):
        f = fresh_nis.combine3(lambda p: {"grid_ms": 125}, lambda p: {"mm_ok": True}, lambda p: {"nis_ok": True})
        self.assertEqual(f("x.ulg"), {"grid_ms": 125, "mm_ok": True, "nis_ok": True})

    def test_nis_error(self):
        def bad(p):
            raise ValueError("boom")
        f = fresh_nis.combine3(lambda p: {"grid_ms": 125}, lambda p: {"mm_ok": True}, bad)
        self.assertEqual(f("x.ulg"), {"grid_ms": 125, "mm_ok": True, "nis_ok": False, "nis_reason": "error: boom"})

    def test_rate_error_kept(self):
        def bad(p):
            raise ValueError("x")
        f = fresh_nis.combine3(bad, lambda p: {"mm_ok": True}, lambda p: {"nis_ok": True})
        self.assertEqual(f("x.ulg"), {"grid_ms": None, "grid_reason": "error: x", "mm_ok": True, "nis_ok": True})


if __name__ == "__main__":
    unittest.main()
