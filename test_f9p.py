"""Tests for f9p.py (studies/f9p-2026/PLAN.md), on synthetic rows only. Standard library only.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import os
import tempfile
import unittest

import f9p

_n = [0]


def row(lag, rec="ubx_f9p", grid=200, ver="v1.16.1", receivers=1, mode=0, passed=True, param=110.0, **kw):
    _n[0] += 1
    r = {"log_id": "log-%d" % _n[0], "passed": passed, "reason": "ok", "lag_ms": lag,
         "param_gps_delay_ms": param,
         "lag_minus_param_ms": None if (param is None or lag is None) else round(lag - param, 1),
         "receiver": rec, "grid_ms": grid, "ver_sw_release": ver, "receivers": receivers,
         "gps_ubx_mode": mode}
    r.update(kw)
    return r


def base_f9p():
    # 6 low (<= 150), 6 high (>= 175): median (130 + 190) / 2 = 160
    return [row(x) for x in (120, 120, 120, 120, 130, 130, 190, 190, 190, 190, 200, 200)]


class Release(unittest.TestCase):
    def test_new_driver(self):
        for ver in ("v1.16.0", "v1.16.1-192", "v1.17.0-0", "1.17.0", "v1.16.2-64"):
            self.assertTrue(f9p.new_driver(ver), ver)
        for ver in ("v1.15.4", "v1.15.4-0", "v1.18.0-64", "v1.12.3", "v4.1.15", "", None, "main"):
            self.assertFalse(f9p.new_driver(ver), ver)


class Selection(unittest.TestCase):
    def test_f9p_5hz(self):
        self.assertTrue(f9p.f9p_5hz(row(180)))
        self.assertTrue(f9p.f9p_5hz(row(180, mode=None)))
        for bad in (row(180, grid=100), row(180, grid=None), row(180, receivers=2), row(180, mode=1),
                    row(180, passed=False), row(180, ver="v1.15.4"), row(180, ver="v1.18.0-128"),
                    row(180, rec="ubx_m9"), row(None), row(180, reason="simulated GPS")):
            self.assertFalse(f9p.f9p_5hz(bad), bad)

    def test_m9_10hz(self):
        self.assertTrue(f9p.m9_10hz(row(70, rec="ubx_m9", grid=100)))
        self.assertFalse(f9p.m9_10hz(row(70, rec="ubx_m9", grid=125)))
        self.assertFalse(f9p.m9_10hz(row(70, rec="ubx_m9", grid=100, ver="v1.15.4")))
        self.assertFalse(f9p.m9_10hz(row(70, rec="ubx_m9", grid=100, receivers=2)))


class Checks(unittest.TestCase):
    def test_all_hold(self):
        rows = base_f9p() + [row(70, rec="ubx_m9", grid=100) for _ in range(8)]
        s = f9p.summarise(rows)
        self.assertEqual((s["n_f9p"], s["n_m9"]), (12, 8))
        self.assertEqual(s["f9p_median_ms"], 160.0)
        lo, hi = s["f9p_median_ci95_ms"]
        self.assertTrue(120.0 <= lo <= 160.0 <= hi <= 200.0, (lo, hi))
        # lag - 110: six of 10/20 ms, six of 80/90 ms -> 6 of 12 more than 50 ms off
        self.assertEqual(s["off_share"], 0.5)
        self.assertEqual((s["low_share"], s["mid_share"], s["high_share"]), (0.5, 0.0, 0.5))
        self.assertEqual(s["P4_m9_minus_f9p"]["diff_ms"], -90.0)
        self.assertLess(s["P4_m9_minus_f9p"]["ci95_ms"][1], 0)
        self.assertEqual(s["checks"], {"E0": True, "P1": True, "P2": True, "P3": True, "P4": True,
                                       "R1": None, "R2": None})
        self.assertEqual(s["decision"], {"D1_report_f9p_5hz_figure": True, "D2_two_groups": "replicated",
                                         "D3_withdraw_f9p_figure": False})

    def test_too_few_f9p_leaves_everything_unscored(self):
        s = f9p.summarise(base_f9p()[:11] + [row(70, rec="ubx_m9", grid=100) for _ in range(8)])
        self.assertEqual(s["checks"]["E0"], False)
        for k in ("P1", "P2", "P3", "P4"):
            self.assertIsNone(s["checks"][k], k)
        self.assertFalse(s["decision"]["D1_report_f9p_5hz_figure"])
        self.assertIsNone(s["decision"]["D2_two_groups"])
        self.assertFalse(s["decision"]["D3_withdraw_f9p_figure"])

    def test_low_median_fails_p1_and_withdraws(self):
        s = f9p.summarise([row(x) for x in (115, 120, 125, 130, 135, 140, 145, 150, 155, 180, 190, 200)])
        self.assertEqual(s["f9p_median_ms"], 142.5)
        self.assertFalse(s["checks"]["P1"])
        self.assertTrue(s["decision"]["D3_withdraw_f9p_figure"])
        self.assertFalse(s["decision"]["D1_report_f9p_5hz_figure"])

    def test_p1_needs_the_interval_above_110(self):
        # median 155 but half the logs at 100: the bootstrap's 2.5% median is 100 or so
        s = f9p.summarise([row(x) for x in (100,) * 6 + (210,) * 6])
        self.assertEqual(s["f9p_median_ms"], 155.0)
        self.assertLessEqual(s["f9p_median_ci95_ms"][0], 110.0)
        self.assertFalse(s["checks"]["P1"])

    def test_filled_gap_fails_p3(self):
        lags = (120, 120, 120, 120, 160, 160, 160, 190, 190, 190, 200, 200)
        s = f9p.summarise([row(x) for x in lags])
        self.assertEqual(s["mid_share"], 0.25)
        self.assertFalse(s["checks"]["P3"])
        self.assertEqual(s["decision"]["D2_two_groups"], "not replicated")

    def test_boundaries(self):
        s = f9p.summarise([row(x) for x in (150.0,) * 6 + (175.0,) * 6])
        self.assertEqual((s["low_share"], s["mid_share"], s["high_share"]), (0.5, 0.0, 0.5))

    def test_p2_counts_only_more_than_50_off_and_skips_missing_settings(self):
        rows = [row(x) for x in (160.0,) * 6 + (161.0,) * 6]          # 50.0 and 51.0 ms off
        rows.append(row(300.0, param=None))                            # no setting: not in P2's base
        s = f9p.summarise(rows)
        self.assertEqual((s["off_base"], s["off_share"]), (12, 0.5))
        self.assertTrue(s["checks"]["P2"])
        s = f9p.summarise([row(x) for x in (160.0,) * 8 + (161.0,) * 4])
        self.assertAlmostEqual(s["off_share"], 0.3333, places=4)
        self.assertFalse(s["checks"]["P2"])

    def test_p4_needs_eight_m9_logs_and_the_gap(self):
        s = f9p.summarise(base_f9p() + [row(70, rec="ubx_m9", grid=100) for _ in range(7)])
        self.assertIsNone(s["checks"]["P4"])
        s = f9p.summarise(base_f9p() + [row(130, rec="ubx_m9", grid=100) for _ in range(8)])
        self.assertEqual(s["P4_m9_minus_f9p"]["diff_ms"], -30.0)
        self.assertFalse(s["checks"]["P4"])

    def test_replications_copy_the_pinned_checks(self):
        s = f9p.summarise(base_f9p(), {"checks": {"M2": True, "M3": False}}, {"checks": {"N1": False}})
        self.assertEqual((s["checks"]["R1"], s["checks"]["R2"]), (True, False))

    def test_seeded(self):
        a, b = f9p.summarise(base_f9p()), f9p.summarise(base_f9p())
        self.assertEqual(a["f9p_median_ci95_ms"], b["f9p_median_ci95_ms"])

    def test_bootstrap_of_a_constant(self):
        self.assertEqual(f9p.boot_median([150.0] * 5), [150.0, 150.0])
        self.assertEqual(f9p.boot_diff([70.0] * 3, [150.0] * 4), {"diff_ms": -80.0, "ci95_ms": [-80.0, -80.0]})


class Explore(unittest.TestCase):
    def test_groups_and_extra(self):
        rows = [row(120, fix_type_max=6, sys_hw="A"), row(160, fix_type_max=4, sys_hw="B"),
                row(190, fix_type_max=4, sys_hw="B"), row(70, rec="ubx_m9", grid=100)]
        extra = [{"log_id": rows[0]["log_id"], "params": {"GPS_1_GNSS": 0}, "sats_median": 30, "messages": []}]
        e = f9p.explore(rows, extra)
        self.assertEqual([p["group"] for p in e["per_log"]], ["low", "mid", "high"])
        self.assertEqual(e["per_log"][0]["params"], {"GPS_1_GNSS": 0})
        self.assertIsNone(e["per_log"][1]["params"])
        self.assertEqual(e["by_field"]["sys_hw"], {"A": {"low": 1, "mid": 0, "high": 0},
                                                   "B": {"low": 0, "mid": 1, "high": 1}})


class Fresh2Seed(unittest.TestCase):
    def test_new_seed_and_refusal(self):
        import types
        import fresh2
        self.assertEqual(fresh2.SEED, f9p.DRAW_SEED)
        self.assertNotEqual(fresh2.SEED, 20261102)          # fresh-2026's seed
        fake_fresh = types.SimpleNamespace(SEED=20261102)
        fake_rc = types.SimpleNamespace(draw=lambda cands, skip_logs, skip_veh, seed=None: ("drawn", seed))
        calls = fresh2.install(fake_fresh, fake_rc)
        self.assertEqual(fake_fresh.SEED, 20261109)
        self.assertEqual(fake_rc.draw([], set(), set(), seed=fake_fresh.SEED), ("drawn", 20261109))
        self.assertEqual(fake_rc.draw([], set(), set(), 20261109), ("drawn", 20261109))
        self.assertEqual(calls, [20261109, 20261109])
        with self.assertRaises(SystemExit):
            fake_rc.draw([], set(), set(), seed=20261102)
        with self.assertRaises(SystemExit):
            fake_rc.draw([], set(), set())


class Extra(unittest.TestCase):
    def test_pick_params(self):
        import f9p_extra
        p = {"GPS_1_GNSS": 0, "MC_ROLL_P": 6.5, "SER_GPS1_BAUD": 0, "EKF2_GPS_DELAY": 110.0,
             "EKF2_GPS_P_NOISE": 0.5, "SENS_GPS0_DELAY": 110.0, "EKF2_GPS_DELAX": 1}
        got = f9p_extra.pick_params(p)
        self.assertEqual(list(got), ["EKF2_GPS_DELAX", "EKF2_GPS_DELAY", "EKF2_GPS_P_NOISE", "GPS_1_GNSS",
                                     "SENS_GPS0_DELAY", "SER_GPS1_BAUD"])
        self.assertNotIn("MC_ROLL_P", got)

    def test_pick_messages(self):
        import f9p_extra
        long_one = "ubx " + "y" * 300
        got = f9p_extra.pick_messages(["[gps] u-blox firmware version: HPG 1.32", "Takeoff detected",
                                       "GPS 0: jamming detected", "GPS 0: jamming detected", "", None,
                                       long_one, "Preflight Fail: ekf2 missing data"])
        self.assertEqual(got, ["[gps] u-blox firmware version: HPG 1.32", "GPS 0: jamming detected",
                               long_one[:200]])
        self.assertEqual(len(f9p_extra.pick_messages("GPS %d" % i for i in range(100))), 40)

    def test_sats_and_wanted(self):
        import f9p_extra
        self.assertEqual(f9p_extra.sats_median([10, 20, 30, 40], [2, 3, 3, 6]), 30.0)
        self.assertIsNone(f9p_extra.sats_median([5, 6], [2, 0]))
        rows = [row(180), row(None), row(180, passed=False), row(70, rec="ubx_m9"),
                row(120, ver="v1.15.4", grid=100)]
        self.assertEqual(f9p_extra.wanted(rows), [rows[0]["log_id"], rows[4]["log_id"]])


class Main(unittest.TestCase):
    def test_writes_summary(self):
        with tempfile.TemporaryDirectory() as d:
            logs = os.path.join(d, "logs.jsonl")
            with open(logs, "w") as f:
                for r in base_f9p():
                    f.write(json.dumps(r) + "\n")
            out = os.path.join(d, "s.json")
            self.assertEqual(f9p.main(["--logs", logs, "--out", out]), 0)
            with open(out) as f:
                s = json.load(f)
            self.assertEqual((s["rows_read"], s["n_f9p"], s["checks"]["E0"]), (12, 12, True))
            self.assertEqual(len(s["explore"]["per_log"]), 12)


if __name__ == "__main__":
    unittest.main()
