"""Tests for rate2.py (synthetic rows only; no log is read).
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import unittest

import rate2


def fake_boot(a, b):
    """Difference of medians with a fixed +-10 ms interval (stands in for
    receiver.py's bootstrap, which the scoring job uses)."""
    d = rate2._median(a) - rate2._median(b)
    return {"diff_ms": round(d, 1), "ci95_ms": [round(d - 10, 1), round(d + 10, 1)]}


def row(receiver, ver, grid, lag, mode=0, passed=True, dt=None):
    return {"receiver": receiver, "ver_sw_release": ver, "grid_ms": grid, "lag_ms": lag,
            "gps_ubx_mode": mode, "passed": passed, "download": "ok", "utc_dt_mode_ms": dt}


class TestEra(unittest.TestCase):
    def test_old(self):
        for v in ("v1.12.3", "v1.12.3-0", "v1.13.0-128", "v1.14.0-0", "v1.15.4", "v1.15.0-128", "v1.15.3-192"):
            self.assertEqual(rate2.era(v), "old", v)

    def test_new(self):
        for v in ("v1.16.0", "v1.16.0-0", "v1.16.1-192", "v1.17.0", "v1.17.0-64"):
            self.assertEqual(rate2.era(v), "new", v)

    def test_unknown(self):
        for v in (None, "", "v1.15.4-0", "v1.15.0-0", "v1.11.3", "v1.18.0-64", "v0.0.0", "v5.2.0", "v25.11.0",
                  "garbage"):
            self.assertIsNone(rate2.era(v), v)


class TestExpected(unittest.TestCase):
    def test_table(self):
        self.assertEqual(rate2.expected_ms("ubx_m8", "old"), (200,))
        self.assertEqual(rate2.expected_ms("ubx_m8", "new"), (200,))
        self.assertEqual(rate2.expected_ms("ubx_m9", "old"), (125,))
        self.assertEqual(rate2.expected_ms("ubx_m9", "new"), (100,))
        self.assertEqual(rate2.expected_ms("ubx_10", "new"), (100,))
        self.assertEqual(rate2.expected_ms("ubx_f9p", "old", 0), (100,))
        self.assertEqual(rate2.expected_ms("ubx_f9p", "old", 1), (100, 125))
        self.assertEqual(rate2.expected_ms("ubx_f9p", "new", 1), (200,))
        self.assertEqual(rate2.expected_ms("ubx_m9", None), ())
        self.assertEqual(rate2.expected_ms("uavcan", "new"), ())


class TestMedian(unittest.TestCase):
    def test_median(self):
        self.assertIsNone(rate2._median([]))
        self.assertEqual(rate2._median([3, 1, 2]), 2)
        self.assertEqual(rate2._median([4, 1, 2, 3]), 2.5)


def full_sample():
    rows = []
    # M8: 10 on 200 (5 old, 5 new) -> 10/10
    rows += [row("ubx_m8", "v1.15.4", 200, 150.0) for _ in range(5)]
    rows += [row("ubx_m8", "v1.16.0", 200, 150.0) for _ in range(5)]
    # M9: 5 old on 125, 9 new on 100, 1 new on 125 -> 14/15
    rows += [row("ubx_m9", "v1.15.4", 125, 75.0) for _ in range(5)]
    rows += [row("ubx_m9", "v1.16.0", 100, 65.0) for _ in range(9)]
    rows.append(row("ubx_m9", "v1.17.0-64", 125, 70.0))
    # F9P: 2 old on 100, 8 new on 200 -> 10/10
    rows += [row("ubx_f9p", "v1.15.4", 100, 140.0) for _ in range(2)]
    rows += [row("ubx_f9p", "v1.16.2", 200, 135.0) for _ in range(8)]
    # left out: not passing, no grid, unknown era, simulation
    rows.append(row("ubx_m9", "v1.16.0", 125, 300.0, passed=False))
    rows.append(row("ubx_f9p", "v1.16.0", None, 140.0, dt=145.0))
    rows.append(row("ubx_m9", "v1.15.4-0", 125, 80.0))
    rows.append(row("simulation", "v1.16.0", 100, 0.0))
    return rows


class TestSummarise(unittest.TestCase):
    def test_all_hold(self):
        s = rate2.summarise(full_sample(), fake_boot)
        c = s["G1_driver_grid"]
        self.assertEqual((c["ubx_m8"]["scored"], c["ubx_m8"]["on_driver"]), (10, 10))
        self.assertEqual((c["ubx_m9"]["scored"], c["ubx_m9"]["on_driver"]), (15, 14))
        self.assertEqual(c["ubx_m9"]["by_era"]["new"], {"n": 10, "on_driver": 9})
        self.assertEqual((c["ubx_f9p"]["scored"], c["ubx_f9p"]["on_driver"]), (10, 10))
        self.assertEqual(s["checks"], {"G0": True, "G1": True, "G2": True})
        self.assertEqual(s["G2_n"], [9, 8])
        self.assertEqual(s["G2_new_m9_100_minus_f9p_200"]["diff_ms"], -70.0)
        self.assertTrue(s["decision"]["D1_rate_line_in_checkup"])
        self.assertEqual(s["reported"]["f9p_new_no_grid_dt_143_to_147"], 1)
        self.assertEqual(s["reported"]["m9_old_125"], {"n": 5, "median_lag_ms": 75.0})
        # passing excludes the failed and simulated rows only
        self.assertEqual(s["passing"], len(full_sample()) - 2)

    def test_g1_fails_below_80(self):
        rows = full_sample()
        rows += [row("ubx_m9", "v1.16.0", 125, 65.0) for _ in range(4)]   # 14/19 = 0.737
        s = rate2.summarise(rows, fake_boot)
        self.assertFalse(s["checks"]["G1"])
        self.assertFalse(s["decision"]["D1_rate_line_in_checkup"])

    def test_g0_fails_unscored(self):
        rows = [r for r in full_sample() if r["receiver"] != "ubx_m8"][:]
        rows += [row("ubx_m8", "v1.16.0", 200, 150.0) for _ in range(7)]
        s = rate2.summarise(rows, fake_boot)
        self.assertFalse(s["checks"]["G0"])
        self.assertIsNone(s["checks"]["G1"])

    def test_g2_unscored_and_fails(self):
        rows = [r for r in full_sample() if not (r["receiver"] == "ubx_f9p" and r["ver_sw_release"] == "v1.16.2")]
        rows += [row("ubx_f9p", "v1.16.2", 200, 135.0) for _ in range(7)]
        self.assertIsNone(rate2.summarise(rows, fake_boot)["checks"]["G2"])
        rows.append(row("ubx_f9p", "v1.16.2", 200, 135.0))
        rows += [row("ubx_m9", "v1.16.0", 100, 125.0) for _ in range(12)]   # M9 new median rises to 125
        s = rate2.summarise(rows, fake_boot)
        self.assertEqual(s["G2_n"], [21, 8])
        self.assertFalse(s["checks"]["G2"])


if __name__ == "__main__":
    unittest.main()
