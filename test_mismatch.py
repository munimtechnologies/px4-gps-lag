"""Tests for mismatch.py and fresh_mm.py on synthetic data (no logs, no network).
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import math
import os
import tempfile
import unittest

import numpy as np

import fresh_mm
import mismatch as mm


def flight(tr_last=None, landed=0):
    """200 s in flight: no acceleration for 100 s, then 3 m/s^2 north.
    Test ratio 0.01 while steady, 0.04 while accelerating; innovations lean
    0.055 s * acceleration (a 100 ms late GPS, seen at 0.55)."""
    lp_t = np.arange(0, 2000) * 0.1
    ax = np.where(lp_t < 100, 0.0, 3.0)
    ay = np.zeros_like(lp_t)
    tr_t = np.arange(1, 401) * 0.5
    tr_n = np.where(tr_t <= 100, 0.01, 0.04)
    if tr_last is not None:
        tr_n[-1] = tr_last
    tr_e = np.zeros_like(tr_t)          # older releases leave [1] at 0
    inn_n = 0.055 * mm.window_mean(lp_t, ax, tr_t)
    inn_e = np.zeros_like(tr_t)
    return mm.metrics(tr_t, tr_n, tr_e, lp_t, ax, ay, [0.0], [landed], tr_t, inn_n, inn_e)


def rows(n=80, lift=None, rejected_big=False):
    out = []
    for i in range(n):
        m = (i - 20) * 3.0                      # -60 .. +177 ms
        out.append({"passed": True, "receiver": "ubx_m9", "lag_minus_param_ms": m, "mm_ok": True,
                    "mm_lift": abs(m) / 1000.0 if lift is None else lift, "mm_slope_s": 0.00055 * m,
                    "mm_tr_hi": 0.02, "mm_p95": 0.05,
                    "mm_rejected": bool(rejected_big and abs(m) > 50)})
    return out


class TestPerLog(unittest.TestCase):
    def test_window_mean(self):
        got = mm.window_mean([0, 1, 2, 3], [1, 2, 3, 4], [2.0, -1.0], win=1.5)
        self.assertAlmostEqual(got[0], 2.5)
        self.assertTrue(math.isnan(got[1]))
        got = mm.window_mean([0, 1, 2, 3], [1, float("nan"), 3, 4], [2.0, 1.0], win=1.5)
        self.assertAlmostEqual(got[0], 3.0)
        self.assertAlmostEqual(got[1], 1.0)

    def test_in_air(self):
        got = mm.in_air_at([0, 10, 20], [1, 0, 1], [-1, 5, 10, 15, 25])
        self.assertEqual(list(got), [False, False, True, True, False])

    def test_metrics_bins_and_lift(self):
        r = flight()
        self.assertTrue(r["mm_ok"])
        self.assertIsNone(r["mm_reason"])
        self.assertGreaterEqual(r["mm_n_lo"], 190)
        self.assertGreaterEqual(r["mm_n_hi"], 190)
        self.assertAlmostEqual(r["mm_tr_lo"], 0.01)
        self.assertAlmostEqual(r["mm_tr_hi"], 0.04)
        self.assertAlmostEqual(r["mm_lift"], math.log10(0.0401 / 0.0101), places=4)
        self.assertAlmostEqual(r["mm_p95"], 0.04)
        self.assertFalse(r["mm_rejected"])

    def test_slope_recovers_lean(self):
        self.assertAlmostEqual(flight()["mm_slope_s"], 0.055, places=6)

    def test_rejection(self):
        r = flight(tr_last=2.0)
        self.assertTrue(r["mm_rejected"])
        self.assertAlmostEqual(r["mm_reject_share"], 1 / 400.0, places=5)

    def test_non_finite_ratio_left_out(self):
        r = flight(tr_last=float("inf"))
        self.assertFalse(r["mm_rejected"])
        self.assertEqual(r["mm_n_air"], flight()["mm_n_air"] - 1)

    def test_landed_throughout(self):
        r = flight(landed=1)
        self.assertFalse(r["mm_ok"])
        self.assertEqual(r["mm_n_air"], 0)
        self.assertEqual(r["mm_reason"], "landed throughout")
        self.assertIsNone(r["mm_p95"])


class TestStats(unittest.TestCase):
    def test_ranks_ties(self):
        self.assertEqual(mm.ranks([10, 20, 20, 5]), [2.0, 3.5, 3.5, 1.0])

    def test_spearman(self):
        self.assertAlmostEqual(mm.spearman([1, 2, 3], [2, 4, 9]), 1.0)
        self.assertAlmostEqual(mm.spearman([1, 2, 3], [9, 4, 2]), -1.0)
        self.assertIsNone(mm.spearman([1, 2, 3], [5, 5, 5]))


class TestSummarise(unittest.TestCase):
    def test_all_hold(self):
        s = mm.summarise(rows())
        self.assertEqual(s["usable"], 80)
        self.assertEqual(s["mismatched"], 47)
        self.assertEqual(s["matched"], 33)
        self.assertEqual(s["checks"], {"E0": True, "S0": True, "M1": True, "M2": True, "M3": True})
        self.assertAlmostEqual(s["S0_slope_vs_mismatch"]["rho"], 1.0)
        self.assertEqual(s["M3_rejected_share_mismatched_minus_matched"]["ci95"], [0.0, 0.0])
        self.assertTrue(s["decision"]["D1_checkup_line"])
        self.assertTrue(s["decision"]["D2_no_more_rejections_line"])

    def test_flat_lift(self):
        s = mm.summarise(rows(lift=0.3))
        self.assertIsNone(s["checks"]["M1"])
        self.assertFalse(s["checks"]["M2"])
        self.assertFalse(s["decision"]["D1_checkup_line"])

    def test_more_rejections(self):
        s = mm.summarise(rows(rejected_big=True))
        self.assertFalse(s["checks"]["M3"])
        self.assertTrue(s["decision"]["D1_checkup_line"])
        self.assertFalse(s["decision"]["D2_no_more_rejections_line"])

    def test_too_few(self):
        s = mm.summarise(rows(n=20))
        self.assertEqual(s["checks"], {"E0": False, "S0": None, "M1": None, "M2": None, "M3": None})
        self.assertFalse(s["decision"]["D1_checkup_line"])

    def test_unusable_rows_left_out(self):
        extra = [dict(rows(1)[0], receiver="simulation"),
                 dict(rows(1)[0], mm_ok=False, mm_lift=None, mm_reason="too few samples (hi 3, lo 40)"),
                 dict(rows(1)[0], passed=False)]
        s = mm.summarise(rows() + extra)
        self.assertEqual(s["usable"], 80)
        self.assertEqual(s["not_usable_reasons"], {"too few samples": 1})

    def test_score_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            mm.score(rows(), d, {"x": 1})
            with open(os.path.join(d, "mismatch-summary.json"), encoding="utf-8") as f:
                got = json.load(f)
        self.assertEqual(got["mismatch_py"], mm.__version__)
        self.assertEqual(got["x"], 1)
        self.assertIn("by_abs_mismatch", got["exploratory"])


class TestCombine(unittest.TestCase):
    def test_both_fields(self):
        f = fresh_mm.combine(lambda p: {"grid_ms": 125}, lambda p: {"mm_ok": True})
        self.assertEqual(f("x.ulg"), {"grid_ms": 125, "mm_ok": True})

    def test_rate_error_kept_as_fresh_sets_it(self):
        def bad(p):
            raise ValueError("x")
        f = fresh_mm.combine(bad, lambda p: {"mm_ok": True})
        self.assertEqual(f("x.ulg"), {"grid_ms": None, "grid_reason": "error: x", "mm_ok": True})

    def test_mismatch_error(self):
        def bad(p):
            raise ValueError("boom")
        f = fresh_mm.combine(lambda p: {"grid_ms": 125}, bad)
        self.assertEqual(f("x.ulg"), {"grid_ms": 125, "mm_ok": False, "mm_reason": "error: boom"})


if __name__ == "__main__":
    unittest.main()
