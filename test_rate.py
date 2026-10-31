"""Tests for rate.py. By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import os
import random
import tempfile
import unittest

import rate as rt

START_US = 1_760_000_000 * 1_000_000      # a whole UTC second


def utc(step_ms, n=400, skip=0.0, jitter_ms=0.3, every=1, seed=1):
    """Receiver UTC times (us) on a step_ms grid with sub-ms jitter; skip
    drops epochs at random, every keeps only every n-th epoch (a throttled log)."""
    rng = random.Random(seed)
    out, k = [], 0
    while len(out) < n:
        k += 1
        if k % every or rng.random() < skip:
            continue
        out.append(START_US + int(k * step_ms * 1000 + rng.uniform(-jitter_ms, jitter_ms) * 1000))
    return out


def grid_of(times_us):
    return rt.grid(rt.utc_times_ms(times_us))


class Grid(unittest.TestCase):
    def test_driver_rates_are_found(self):
        for step in (100, 125, 200):
            g = grid_of(utc(step, skip=0.2, seed=step))
            self.assertEqual(g["grid_ms"], step, g)
            self.assertGreaterEqual(g["on_share"], 0.9)

    def test_one_and_two_hz_receivers_have_no_grid(self):
        for step in (500, 1000):
            g = grid_of(utc(step))
            self.assertIsNone(g["grid_ms"], g)
            self.assertEqual(g["utc_dt_mode_ms"], float(step))

    def test_throttled_logs_have_no_grid(self):
        # PX4 v1.12-v1.14 log vehicle_gps_position every 500 ms: an 8 Hz
        # receiver then shows every 4th epoch, a 10 Hz one every 6th.
        self.assertIsNone(grid_of(utc(125, every=4))["grid_ms"])
        self.assertIsNone(grid_of(utc(100, every=6))["grid_ms"])
        self.assertIsNone(grid_of(utc(100, every=5))["grid_ms"])

    def test_times_off_any_grid(self):
        rng = random.Random(7)
        times, t = [], START_US
        for _ in range(400):
            t += int(rng.uniform(80, 220) * 1000)
            times.append(t)
        g = grid_of(times)
        self.assertIsNone(g["grid_ms"])
        self.assertEqual(g["grid_reason"], "no grid")

    def test_too_few_times(self):
        g = grid_of(utc(125, n=30))
        self.assertIsNone(g["grid_ms"])
        self.assertEqual((g["utc_n"], g["grid_reason"]), (30, "too few receiver times"))

    def test_zeros_and_repeats_dropped(self):
        t = [0, 0] + utc(125, n=60)
        t = [x for x in t for _ in (0, 1)]           # every time logged twice
        ms = rt.utc_times_ms(t)
        self.assertEqual(len(ms), 60)
        self.assertEqual(rt.grid(ms)["grid_ms"], 125)

    def test_driver_intervals(self):
        self.assertEqual(rt.driver_ms("ubx_m8"), (200,))
        self.assertEqual(rt.driver_ms("ubx_m9"), (125,))
        self.assertEqual(rt.driver_ms("ubx_f9p", 0), (100,))
        self.assertEqual(rt.driver_ms("ubx_f9p", None), (100,))
        self.assertEqual(rt.driver_ms("ubx_f9p", 1), (100, 125))
        self.assertEqual(rt.driver_ms("uavcan"), ())

    def test_ranks_average_ties(self):
        self.assertEqual(list(rt.ranks([3, 1, 3, 2])), [2.5, 0.0, 2.5, 1.0])


def spread(base, n):
    return [base + (i % 7) - 3 for i in range(n)]


def row(cls, lag, grid, mode=None, download="ok"):
    r = {"log_id": "%s-%s-%s-%s" % (cls, lag, grid, mode), "receiver": cls, "lag_ms": float(lag),
         "ver_sw_release": "v1.15.4", "download": download, "study": "receiver-2026"}
    if download == "ok":
        r.update({"grid_ms": grid, "gps_ubx_mode": mode, "utc_dt_mode_ms": grid or 1000.0})
    return r


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class Summary(unittest.TestCase):
    def rows(self):
        rows = [row("ubx_m9", x, 125) for x in spread(70, 12)] + [row("ubx_m9", 80, None) for _ in range(2)]
        rows += [row("ubx_m8", x, 200) for x in spread(150, 12)]
        rows += [row("ubx_f9p", x, 100, 0) for x in spread(145, 10)]
        rows += [row("ubx_f9p", x, 125, 1) for x in spread(110, 5)]
        rows += [row("ubx_10", x, 125) for x in spread(120, 4)]
        rows += [row("ubx_generic", x, 125) for x in spread(120, 8)]
        rows += [row("ubx_generic", x, 200) for x in spread(160, 8)]
        rows += [row("uavcan", 95, None) for _ in range(5)]
        rows += [row("ubx_m8", 150, None, download="missing") for _ in range(2)]
        return rows

    def test_checks(self):
        s = rt.summarise(self.rows())
        self.assertEqual((s["sample"], s["read"]), (68, 66))
        self.assertEqual(s["downloads"], {"ok": 66, "missing": 2})
        self.assertEqual(s["E0_serial_ublox"], 61)
        self.assertAlmostEqual(s["E0_gridded_share_serial_ublox"], round(59 / 61, 4))
        q1 = s["Q1_driver_grid"]
        self.assertEqual([q1[k]["gridded"] for k in rt.CORE], [12, 12, 15])
        self.assertEqual([q1[k]["share"] for k in rt.CORE], [1.0, 1.0, 1.0])
        self.assertEqual(s["Q2_m9_minus_other_at_125"]["diff_ms"], -48.5)
        self.assertEqual(s["Q2_n"], [12, 17])
        self.assertEqual(s["Q3_generic_200_minus_125"]["diff_ms"], 40.0)
        self.assertEqual(s["Q3_n"], [8, 8])
        self.assertEqual(s["Q4_f9p_100_minus_other"]["diff_ms"], 35.0)
        self.assertEqual(s["Q4_n"], [10, 5])
        self.assertEqual(s["checks"], {"E0": True, "E1": True, "Q1": True, "Q2": True, "Q3": True, "Q4": True})
        self.assertEqual(s["decision"], {"D1_rate_line_in_checkup": True, "D2_rate_not_the_m9_story": True})
        json.dumps(s)

    def test_off_driver_grid_fails_q1(self):
        rows = self.rows()
        for r in rows:
            if r["receiver"] == "ubx_m8" and r.get("grid_ms") == 200 and r["lag_ms"] < 150:
                r["grid_ms"] = 125                     # 6 of 12 M8 logs off the driver's 200 ms
        s = rt.summarise(rows)
        self.assertEqual(s["Q1_driver_grid"]["ubx_m8"]["share"], 0.5)
        self.assertFalse(s["checks"]["Q1"])
        self.assertFalse(s["decision"]["D1_rate_line_in_checkup"])

    def test_small_groups_leave_checks_unscored(self):
        rows = [row("ubx_m9", x, 125) for x in spread(70, 5)]
        rows += [row("ubx_f9p", x, 100) for x in spread(145, 4)]
        rows += [row("ubx_generic", x, 200) for x in spread(160, 3)]
        s = rt.summarise(rows)
        c = s["checks"]
        self.assertFalse(c["E1"])
        for k in ("Q1", "Q2", "Q3", "Q4"):
            self.assertIsNone(c[k], k)
        self.assertIsNone(s["decision"]["D2_rate_not_the_m9_story"])

    def test_no_rows(self):
        s = rt.summarise([])
        self.assertIsNone(s["checks"]["E0"])
        self.assertFalse(s["checks"]["E1"])

    def test_sample_takes_published_lags_once(self):
        rec = [{"log_id": "a", "passed": True, "lag_ms": 70.0, "receiver": "ubx_m9", "vehicle": "v1",
                "ver_sw_release": "v1.15.4", "download": "ok"},
               {"log_id": "b", "passed": False, "lag_ms": None, "receiver": "ubx_m9", "download": "ok"},
               {"log_id": "s", "passed": True, "lag_ms": 5.0, "receiver": "simulation", "download": "ok"}]
        conf = [{"log_id": "c", "download": "ok", "lag_ms": 150.0, "receiver": "ubx_m8", "vehicle": "v2"},
                {"log_id": "a", "download": "ok", "lag_ms": 71.0, "receiver": "ubx_m9"},
                {"log_id": "d", "download": "missing", "lag_ms": 1.0, "receiver": "ubx_m8"}]
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "receiver-2026.jsonl"), os.path.join(tmp, "confirm.jsonl")
            write_jsonl(a, rec)
            write_jsonl(b, conf)
            got = rt.sample([a, b])
        self.assertEqual([(g["log_id"], g["study"], g["lag_ms"], g["receiver"]) for g in got],
                         [("a", "receiver-2026", 70.0, "ubx_m9"), ("c", "confirm", 150.0, "ubx_m8")])

    def test_rescore(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "logs.jsonl")
            write_jsonl(p, self.rows())
            self.assertEqual(rt.main(["--out-dir", tmp, "--rescore", p]), 0)
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                s = json.load(f)
        self.assertEqual(s["rescored_from"], "logs.jsonl")
        ex = s["exploratory"]
        self.assertEqual(ex["by_receiver_and_grid"]["ubx_f9p 125"]["n"], 5)
        self.assertEqual(ex["by_receiver_and_grid"]["uavcan none"]["n"], 5)
        self.assertEqual(ex["ubx_mode_by_receiver"]["ubx_f9p mode 1"]["n"], 5)
        self.assertIsNotNone(ex["rank_corr_grid_lag_serial_ublox"])


if __name__ == "__main__":
    unittest.main()
