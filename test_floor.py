"""Tests for floor.py (standard library only). Apache-2.0.
By MV2 of Munim, Inc.; written with AI agents."""

import json
import os
import statistics
import tempfile
import unittest

import floor


def row(eph, nis, p_noise=0.5, receiver="ubx_m9", ok=True, fix=3, vel=0.03):
    return {"receiver": receiver, "nis_ok": ok, "nis_pos_median": nis, "nis_vel_median": vel,
            "nis_eph_median": eph, "nis_param_EKF2_GPS_P_NOISE": p_noise, "nis_fix_type_mode": fix}


def sample(under_eph=None, flat=False):
    """100 logs under the 0.5 m floor and 60 at or above it.
    Under: eph 0.01 + 0.0045 i, so q = 2 eph (0.02 to 0.9110), NIS = 0.02 q^2.
    At: eph 0.5 + 0.01 i, NIS 0.018 / 0.022 alternating (no trend with eph).
    flat: every NIS alternates 0.018 / 0.022, whatever q is."""
    rows = []
    for i in range(100):
        eph = under_eph(i) if under_eph else 0.01 + 0.0045 * i
        q = eph / 0.5
        nis = 0.02 * (1.1 if i % 2 else 0.9) if flat else 0.02 * q * q
        rows.append(row(eph, nis, fix=6 if eph < 0.0975 else 4))   # i = 0..19 are RTK fixed
    for i in range(60):
        rows.append(row(0.5 + 0.01 * i, 0.02 * (1.1 if i % 2 else 0.9)))
    return rows


class Pieces(unittest.TestCase):
    def test_floor_q(self):
        self.assertAlmostEqual(floor.floor_q(0.25, 0.5), 0.5)
        self.assertEqual(floor.floor_q(0.8, 0.5), 1.0)
        self.assertEqual(floor.floor_q(0.5, 0.5), 1.0)
        self.assertAlmostEqual(floor.floor_q(0.1, None), 0.2)       # default 0.5 m
        self.assertEqual(floor.floor_q(0.3, 0.05), 1.0)             # floor lowered below eph
        self.assertIsNone(floor.floor_q(12.0, 0.5))                 # at the 10 m cap
        self.assertIsNone(floor.floor_q(0.3, 10.0))
        self.assertIsNone(floor.floor_q(None, 0.5))
        self.assertIsNone(floor.floor_q(0.0, 0.5))
        self.assertIsNone(floor.floor_q("nan", 0.5))

    def test_ranks_average_ties(self):
        self.assertEqual(floor.ranks([10, 20, 20, 30]), [1.0, 2.5, 2.5, 4.0])
        self.assertEqual(floor.ranks([3, 1, 2]), [3.0, 1.0, 2.0])

    def test_spearman_and_pearson(self):
        self.assertAlmostEqual(floor.spearman([1, 2, 3, 4], [1, 4, 9, 100]), 1.0)
        self.assertAlmostEqual(floor.spearman([1, 2, 3, 4], [9, 7, 2, 1]), -1.0)
        self.assertIsNone(floor.spearman([1, 2, 3], [5, 5, 5]))
        self.assertIsNone(floor.spearman([1, 2], [1, 2]))
        self.assertAlmostEqual(floor.pearson([1, 2, 3], [2, 4, 6]), 1.0)

    def test_slope(self):
        self.assertAlmostEqual(floor.slope([0, 1, 2], [1, 3, 5]), 2.0)
        self.assertIsNone(floor.slope([1, 1, 1], [1, 2, 3]))

    def test_boot_ci_constant_and_seeded(self):
        self.assertEqual(floor.boot_ci(statistics.median, [[3.0] * 10]), [3.0, 3.0])
        xs = [float(i) for i in range(40)]
        a = floor.boot_ci(statistics.median, [xs], n=200)
        b = floor.boot_ci(statistics.median, [xs], n=200)
        self.assertEqual(a, b)
        self.assertLess(a[0], 19.5)
        self.assertGreater(a[1], 19.5)

    def test_items_filters(self):
        rows = [row(0.2, 0.01), row(0.2, 0.01, receiver="simulation"), row(0.2, 0.01, ok=False),
                row(0.2, 0.0), row(None, 0.01), row(0.2, None), row(0.2, 0.01, p_noise=None)]
        use = floor.items(rows)
        self.assertEqual(len(use), 2)
        self.assertEqual(use[1]["p_noise"], 0.5)
        self.assertAlmostEqual(use[0]["q"], 0.4)


class Checks(unittest.TestCase):
    def test_all_hold(self):
        s = floor.summarise(sample())
        self.assertEqual((s["usable"], s["at_floor_or_above"], s["under_floor"], s["q_at_most_half"]),
                         (160, 60, 100, 54))
        self.assertEqual(s["checks"], {"E0": True, "F1": True, "F2": True, "F3": True, "F4": True})
        self.assertAlmostEqual(s["F2_loglog_slope_under_floor"]["slope"], 2.0, places=4)
        self.assertAlmostEqual(s["F3_nis_ratio_at_vs_half"]["median_nis_at"], 0.02, places=6)
        # point-biserial by hand: 0.5 * (31 - 30) / sqrt((60^2 - 1) / 12) = 0.0289
        self.assertAlmostEqual(s["F4_spearman_eph_nis_at_floor"]["rho"], 0.0289, places=3)
        self.assertTrue(s["decision"]["D1"])
        self.assertFalse(s["decision"]["D2"])

    def test_flat_nis_fails_f1(self):
        s = floor.summarise(sample(flat=True))
        self.assertTrue(s["checks"]["E0"])
        self.assertFalse(s["checks"]["F1"])
        self.assertLess(abs(s["F1_spearman_q_nis"]["rho"]), 0.05)
        self.assertFalse(s["decision"]["D1"])
        self.assertTrue(s["decision"]["D2"])

    def test_too_few_leaves_everything_unscored(self):
        rows = sample()[:50] + sample()[100:110]
        s = floor.summarise(rows)
        self.assertEqual(s["checks"], {"E0": False, "F1": None, "F2": None, "F3": None, "F4": None})
        self.assertFalse(s["decision"]["D1"])
        self.assertFalse(s["decision"]["D2"])

    def test_f3_needs_logs_at_half_or_below(self):
        s = floor.summarise(sample(under_eph=lambda i: 0.3 + 0.0019 * i))
        self.assertTrue(s["checks"]["E0"])
        self.assertEqual(s["q_at_most_half"], 0)
        self.assertIsNone(s["checks"]["F3"])
        self.assertTrue(s["checks"]["F1"])


class Main(unittest.TestCase):
    def test_writes_summary_with_replication(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.jsonl")
            b = os.path.join(d, "b.jsonl")
            out = os.path.join(d, "floor-summary.json")
            for path, rows in ((a, sample()), (b, sample(flat=True))):
                with open(path, "w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r) + "\n")
            self.assertEqual(floor.main(["--logs", a, "--replicate", b, "--out", out]), 0)
            with open(out, encoding="utf-8") as f:
                got = json.load(f)
        self.assertEqual(got["floor_py"], "0.1.0")
        self.assertTrue(got["graded"]["checks"]["F1"])
        self.assertFalse(got["replication"]["summary"]["checks"]["F1"])
        self.assertEqual(got["graded_explore"]["by_fix_type"]["RTK fixed"]["n"], 20)


if __name__ == "__main__":
    unittest.main()
