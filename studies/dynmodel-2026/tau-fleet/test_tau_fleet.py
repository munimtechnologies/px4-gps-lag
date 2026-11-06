"""Synthetic tests for tau_fleet.py (no log is read, no network). By MV2 of Munim, Inc.; written with
AI agents. Apache-2.0."""

import json
import unittest

import numpy as np

import mechanism as mc
import tau_fleet as tf


def synth(D, tau, T=120.0, seed=3, n_sin=40):
    """As test_mechanism.synth: 250 Hz IMU from sinusoids, 5 Hz GPS velocity through an exact
    first-order low-pass (tau) and then a delay (D)."""
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


class TestFit(unittest.TestCase):
    def test_same_as_mechanism(self):
        data = synth(0.05, 0.10)
        a, ta, la = mc.fit_grid(*data, resamples=5)
        b, tb, lb = tf.fit_lite(*data, resamples=5)
        for key in ("pairs", "tau_ms", "lag_ms", "sum_ms", "lag_tau0_ms", "tau_edge", "lag_edge"):
            self.assertEqual(a[key], b[key], key)
        self.assertAlmostEqual(a["r2"], b["r2"], places=4)
        self.assertAlmostEqual(a["r2_tau0"], b["r2_tau0"], places=4)
        np.testing.assert_array_equal(ta, tb)
        np.testing.assert_array_equal(la, lb)
        self.assertEqual(a["boot"]["tau_ms"], b["boot"]["tau_ms"])
        self.assertIn("identified", b)

    def test_pure_delay(self):
        f, _, _ = tf.fit_lite(*synth(0.15, 0.0), resamples=3)
        self.assertLessEqual(f["tau_ms"], 10.0)
        self.assertLessEqual(abs(f["sum_ms"] - 150.0), 10.0)

    def test_boot_weights(self):
        W = tf.boot_weights(60, resamples=4)
        self.assertEqual(W.shape, (5, 60))
        np.testing.assert_array_equal(W[0], np.ones(60))
        np.testing.assert_array_equal(W.sum(axis=1), np.full(5, 60.0))


def drow(i, vehicle, model, receiver="ubx_f9p", status="ok", lag=150.0):
    return {"sample": "s", "sample_index": 0, "row_index": i, "log_id": "log-%03d" % i, "vehicle": vehicle,
            "receiver": receiver, "lag_ms": lag, "ver_sw_release": "v1.16.0-255", "status": status,
            "params": {"GPS_UBX_DYNMODEL": model}}


class TestUnits(unittest.TestCase):
    def test_graded_six_and_seven_only(self):
        rows = [drow(0, "a", 6), drow(1, "a", 7), drow(2, "b", 7), drow(3, "c", 8),
                drow(4, "d", 6, status="http 404"), drow(5, "e", 6)]
        u = tf.units(rows)
        ids = sorted(x["log_id"] for x in u)
        self.assertEqual(ids, ["log-000", "log-002", "log-005"])      # one per vehicle, 8 and unread out
        self.assertEqual({x["log_id"]: x["dynmodel"] for x in u}, {"log-000": 6, "log-002": 7, "log-005": 6})
        self.assertEqual([x["log_id"] for x in tf.units(list(reversed(rows)))], [x["log_id"] for x in u])
        self.assertEqual(u[0]["published_lag_ms"], 150.0)


def frow(model, tau, lag, receiver="ubx_f9p", ident=True):
    return {"log_id": "x", "receiver": receiver, "dynmodel": model, "counts": True, "why": "ok",
            "reproduced": True, "gps_logged_dt_ms": 100.0,
            "fit": {"tau_ms": tau, "lag_ms": lag, "sum_ms": tau + lag, "r2": 0.99, "r2_tau0": 0.98,
                    "identified": ident, "tau_edge": False}}


class TestScore(unittest.TestCase):
    def test_resid(self):
        c = {"A": {7: [10.0, 20.0, 30.0, 40.0, 50.0], 6: [60.0, 80.0]},
             "B": {7: [0.0, 0.0, 0.0, 0.0], 6: [500.0]}}                 # B has too few 7-logs
        r = tf.resid(c)
        self.assertEqual(r["n_low"], 2)
        self.assertEqual(r["median_ms"], 40.0)
        self.assertEqual(tf.ref_counts(c), (2, 5))
        self.assertIsNone(tf.resid({"B": c["B"]}))

    def rows(self, n6, tau6, lag6, n7=25):
        return [frow(7, 20.0, 95.0) for _ in range(n7)] + [frow(6, tau6, lag6) for _ in range(n6)]

    def test_h1(self):
        s = tf.summarise(self.rows(30, 100.0, 100.0))
        self.assertEqual(s["checks"], {"E0": True, "T1": True, "T2": True})
        self.assertEqual(s["decision"], "H1")
        self.assertEqual(s["T1_tau_resid"]["median_ms"], 80.0)
        self.assertEqual(s["T2_lag_resid"]["median_ms"], 5.0)
        self.assertEqual(s["sum_resid"]["median_ms"], 85.0)
        json.dumps(mc.plain(s))

    def test_h2_delay_bigger(self):
        s = tf.summarise(self.rows(30, 50.0, 150.0))
        self.assertEqual(s["checks"], {"E0": True, "T1": True, "T2": False})
        self.assertEqual(s["decision"], "H2")

    def test_h3_no_tau_gap(self):
        s = tf.summarise(self.rows(30, 20.0, 150.0))
        self.assertFalse(s["checks"]["T1"])
        self.assertEqual(s["decision"], "H3")

    def test_h3_threshold(self):
        s = tf.summarise(self.rows(30, 39.0, 95.0))                      # +19 ms: under the 20 ms line
        self.assertFalse(s["checks"]["T1"])
        s = tf.summarise(self.rows(30, 40.0, 95.0))                      # +20 ms: on it
        self.assertTrue(s["checks"]["T1"])

    def test_h0(self):
        s = tf.summarise(self.rows(29, 100.0, 100.0))
        self.assertEqual(s["checks"], {"E0": False, "T1": None, "T2": None})
        self.assertEqual(s["decision"], "H0")
        s = tf.summarise(self.rows(30, 100.0, 100.0, n7=24))
        self.assertEqual(s["decision"], "H0")

    def test_uncounted_rows_ignored(self):
        rows = self.rows(30, 100.0, 100.0)
        rows.append({"log_id": "y", "receiver": "ubx_f9p", "dynmodel": 6, "counts": False,
                     "why": "download missing"})
        s = tf.summarise(rows)
        self.assertEqual(s["fitted"], 55)
        self.assertEqual(s["reported"]["why_counts"]["download missing"], 1)


class TestLoop(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(tf.counts({"download": "missing"}), (False, "download missing"))
        self.assertEqual(tf.counts({"download": "ok", "error": "ValueError: x"}), (False, "error"))
        self.assertEqual(tf.counts({"download": "ok", "gps_lag_passed": False, "gps_lag_reason": "r2"}),
                         (False, "gps_lag: r2"))
        self.assertEqual(tf.counts({"download": "ok", "gps_lag_passed": True, "fit": None}),
                         (False, "too few GPS pairs"))
        self.assertEqual(tf.counts({"download": "ok", "gps_lag_passed": True, "fit": {"tau_ms": 1}}),
                         (True, "ok"))

    def test_blocked_stops_downloads(self):
        todo = [{"log_id": "a"}, {"log_id": "b"}, {"log_id": "c"}]
        out, slept = [], []

        def fetch(u):
            if u["log_id"] == "b":
                raise tf.Blocked("HTTP 403")
            return {"download": "ok", "gps_lag_passed": True, "fit": {"tau_ms": 1}}

        res = tf.run(todo, fetch, out.append, sleep=slept.append)
        self.assertEqual(res, {"attempted": 2, "stop": "blocked: HTTP 403"})
        self.assertEqual([r["counts"] for r in out], [True, False, False])
        self.assertTrue(out[2]["why"].startswith("not attempted"))
        self.assertEqual(slept, [tf.DELAY_S])

    def test_budget(self):
        out = []
        res = tf.run([{"log_id": "a"}, {"log_id": "b"}], lambda u: {"download": "missing"}, out.append,
                     out_of_time=lambda: True)
        self.assertEqual(res, {"attempted": 0, "stop": "budget"})
        self.assertEqual([r["why"] for r in out], ["not attempted (budget)", "not attempted (budget)"])


if __name__ == "__main__":
    unittest.main()
