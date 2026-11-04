"""Tests for dynconf.py (standard library only; needs dynmodel.py 0.1.0 next to it).
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import unittest

import dynconf as dc


def row(lag, dyn, receiver="ubx_f9p", cls="mc", mi=16):
    return {"lag": float(lag), "dyn": dyn, "receiver": receiver, "cls": cls, "minor": mi,
            "mgroup": dc.minor_group(mi), "default": dc.default_dyn(cls, mi), "mav_type": "Quadrotor"}


class TestLabels(unittest.TestCase):
    def test_mav_class(self):
        self.assertEqual(dc.mav_class("Quadrotor"), "mc")
        self.assertEqual(dc.mav_class("Hexarotor"), "mc")
        self.assertEqual(dc.mav_class("Fixed Wing"), "fw")
        self.assertEqual(dc.mav_class("VTOL Tiltrotor"), "vtol")
        self.assertEqual(dc.mav_class("VTOL Quadrotor"), "vtol")
        self.assertEqual(dc.mav_class("Ground Rover"), "other")
        self.assertEqual(dc.mav_class(None), "other")

    def test_minor_and_default(self):
        self.assertEqual(dc.minor("v1.16.0"), 16)
        self.assertEqual(dc.minor("v1.17.0-rc2"), 17)
        self.assertIsNone(dc.minor("v2.0.0"))
        self.assertIsNone(dc.minor(None))
        self.assertEqual(dc.minor_group(13), "<=1.14")
        self.assertEqual(dc.minor_group(18), ">=1.18")
        self.assertEqual(dc.minor_group(None), "unknown")
        self.assertEqual(dc.default_dyn("mc", 16), 6)
        self.assertEqual(dc.default_dyn("mc", 17), 7)
        self.assertEqual(dc.default_dyn("fw", 15), 8)
        self.assertEqual(dc.default_dyn("vtol", 15), 7)
        self.assertIsNone(dc.default_dyn("other", 15))
        self.assertIsNone(dc.default_dyn("mc", None))

    def test_load_map(self):
        self.assertEqual(dc.load_map(["aa 6", "", "bb 7\n"]), {"aa": 6, "bb": 7})
        with self.assertRaises(ValueError):
            dc.load_map(["aa 6", "aa 7"])


class TestStrata(unittest.TestCase):
    def test_weighted_difference(self):
        rows = [row(110, 6), row(110, 6), row(100, 7), row(100, 7),           # stratum f9p: +10, w = 1
                row(200, 6, "ubx_m8"), row(170, 7, "ubx_m8"), row(170, 7, "ubx_m8"),  # m8: +30, w = 2/3
                row(50, 6, "ubx_m9")]                                           # m9: no 7-log, dropped
        g = lambda r: "a" if r["dyn"] == 6 else ("b" if r["dyn"] == 7 else None)
        st = dc.strata(rows, g, lambda r: (r["receiver"],))
        self.assertEqual(len(st), 2)
        self.assertAlmostEqual(dc.strata_est(st), (1 * 10 + (2 / 3) * 30) / (1 + 2 / 3))
        rep = dc.strata_report(rows, g, lambda r: (r["receiver"],))
        self.assertEqual((rep["strata"], rep["n_a"], rep["n_b"]), (2, 3, 4))
        self.assertEqual(rep, dc.strata_report(rows, g, lambda r: (r["receiver"],)))   # seeded
        self.assertLessEqual(rep["ci95_ms"][0], rep["ci95_ms"][1])

    def test_empty(self):
        self.assertEqual(dc.strata_report([row(1, 6)], lambda r: "a", lambda r: (1,)), {"strata": 0})


class TestOLS(unittest.TestCase):
    def test_recovers_exact_coefficients(self):
        rows = []
        for rx, off in (("ubx_m9", 0.0), ("ubx_f9p", 40.0), ("ubx_m8", 60.0)):
            for cls, coff in (("mc", 0.0), ("fw", -10.0)):
                for mi, moff in ((15, 0.0), (16, 5.0), (17, 7.0)):
                    for dyn, doff in ((6, 30.0), (7, 0.0), (8, 2.0)):
                        for k in range(2):
                            rows.append(row(80 + off + coff + moff + doff, dyn, rx, cls, mi))
        names, X = dc.design(rows, "ubx_m9", "mc", "1.15")
        beta = dc.ols(X, [r["lag"] for r in rows])
        coef = dict(zip(names, beta))
        self.assertAlmostEqual(coef["intercept"], 80.0, places=6)
        self.assertAlmostEqual(coef["dyn6"], 30.0, places=6)
        self.assertAlmostEqual(coef["dyn8"], 2.0, places=6)
        self.assertAlmostEqual(coef["rx:ubx_f9p"], 40.0, places=6)
        self.assertAlmostEqual(coef["cls:fw"], -10.0, places=6)
        self.assertAlmostEqual(coef["rel:1.17"], 7.0, places=6)
        rep = dc.ols_report(rows, boot=50)
        self.assertEqual(rep["coef_ms"]["dyn6"], 30.0)
        self.assertEqual(rep["dyn6_ci95_ms"], [30.0, 30.0])

    def test_singular(self):
        self.assertIsNone(dc.solve([[1.0, 1.0], [1.0, 1.0]], [1.0, 1.0]))


class TestBuild(unittest.TestCase):
    def test_rebuild_marks_seen_and_missing(self):
        base = {"passed": True, "reason": "", "receivers": 1, "gps_bus": "serial", "receiver": "ubx_f9p"}
        s = [dict(base, log_id="aaaaaaaa-1", vehicle="v1", lag_ms=100.0),
             dict(base, log_id="bbbbbbbb-2", vehicle="v2", lag_ms=180.0),
             dict(base, log_id="cccccccc-3", vehicle="v3", lag_ms=120.0),
             dict(base, log_id="dddddddd-4", vehicle="v4", lag_ms=120.0, passed=False)]
        extra = [{"log_id": "cccccccc-3", "params": {"GPS_UBX_DYNMODEL": 7}}]
        recs, missing = dc.build([("x", s)], extra, {"aaaaaaaa": 7})
        st = {r["log_id"]: r["status"] for r in recs}
        self.assertEqual(st, {"aaaaaaaa-1": "ok", "bbbbbbbb-2": "missing", "cccccccc-3": "seen (f9p-extra)"})
        self.assertEqual(missing, 1)
        rows = dc.join(dc.dm.graded(recs), {"aaaaaaaa-1": {"mav_type": "Fixed Wing", "ver_sw_release": "v1.15.4"}})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["cls"], rows[0]["minor"], rows[0]["default"], rows[0]["dyn"]), ("fw", 15, 8, 7))


if __name__ == "__main__":
    unittest.main()
