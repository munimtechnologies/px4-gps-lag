"""Tests for extend.py (upgrade-2026 extension). Standard library only: no network, no logs.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import unittest

import extend as x
import upgrade as up

PRE, POST = up.PRE, up.POST


def m(lag, model, devtype="0xAA", release="v1.16.0", passed=True, date="2026-05-01"):
    return {"download": "ok", "passed": passed, "reason": "ok" if passed else "too little manoeuvring",
            "lag_ms": lag, "dynmodel": model, "devtype": devtype, "serial_ublox": True,
            "receiver": "F9P", "ver_sw_release": release, "param_gps_delay_ms": 110.0, "log_date": date}


def v1row(log_id, v, side, attempt, **kw):
    r = {"log_id": log_id, "vehicle": v, "side": side, "attempt": attempt, "counts": False, "why": "old"}
    r.update(kw)
    return r


def listed(log_id, v, side):
    return {"log_id": log_id, "vehicle": v, "series": side, "log_date": "2026-01-01"}


def pair(v, pre_lag, post_lag, pre_model=6, post_model=7):
    return {"vehicle": v, "pre": m(pre_lag, pre_model),
            "post": m(post_lag, post_model, release="v1.17.0", date="2026-08-01")}


class FirstRun(unittest.TestCase):
    def test_v1_attempts_groups_in_attempt_order(self):
        rows = [v1row("b", "A", PRE, 2), v1row("a", "A", PRE, 1), v1row("c", "A", POST, 3),
                v1row("d", "B", PRE, 4)]
        t = x.v1_attempts(rows)
        self.assertEqual([r["log_id"] for r in t["A"][PRE]], ["a", "b"])
        self.assertEqual([r["log_id"] for r in t["A"][POST]], ["c"])
        self.assertEqual(t["B"][POST], [])


class Order(unittest.TestCase):
    def setUp(self):
        self.both = {"A": {PRE: [listed("A1", "A", PRE), listed("A2", "A", PRE), listed("A3", "A", PRE)],
                           POST: [listed("A4", "A", POST)]},
                     "B": {PRE: [listed("B1", "B", PRE)], POST: [listed("B2", "B", POST)]},
                     "P": {PRE: [listed("P1", "P", PRE)], POST: [listed("P2", "P", POST)]}}
        self.a2 = v1row("A2", "A", PRE, 1, **m(150, 6, passed=False))
        self.z1 = v1row("Z1", "Z", PRE, 2, **m(150, 6, passed=False))
        self.tried = {"A": {PRE: [self.a2], POST: []}, "Z": {PRE: [self.z1], POST: []}}

    def test_plan_x(self):
        order, cands = x.plan_x(self.both, self.tried, {"P"})
        self.assertEqual(sorted(order), ["A", "B", "Z"])                 # P was paired; Z was tried
        self.assertEqual(cands["A"][PRE][0], ("v1", self.a2))            # the first run's tries first
        self.assertEqual([k for k, _ in cands["A"][PRE]], ["v1", "new", "new"])
        self.assertEqual(sorted(c["log_id"] for _, c in cands["A"][PRE][1:]), ["A1", "A3"])  # A2 not twice
        self.assertEqual(cands["A"][POST], [("new", self.both["A"][POST][0])])
        self.assertEqual(cands["Z"][PRE], [("v1", self.z1)])
        self.assertEqual(cands["Z"][POST], [])
        o2, c2 = x.plan_x(self.both, self.tried, {"P"})
        self.assertEqual((order, cands), (o2, c2))                       # seeded


class Draw(unittest.TestCase):
    def setUp(self):
        fail = lambda lag=150, rel="v1.16.0": m(lag, 6, release=rel, passed=False)
        a_old = [("v1", v1row("A-o%d" % i, "A", PRE, i, **fail())) for i in range(3)]
        b_pre = [("v1", v1row("B-o0", "B", PRE, 10, **m(150, 6)))]
        b_post_old = [("v1", v1row("B-p%d" % i, "B", POST, 11 + i, **fail(100, "v1.17.0"))) for i in range(3)]
        c_old = [("v1", v1row("C-o%d" % i, "C", PRE, 20 + i, **fail())) for i in range(2)]
        n = lambda lid, v, side: ("new", listed(lid, v, side))
        self.order = ["A", "B", "C"]
        self.cands = {
            "A": {PRE: a_old + [n("A-n1", "A", PRE), n("A-n2", "A", PRE)], POST: [n("A-p1", "A", POST)]},
            "B": {PRE: b_pre, POST: b_post_old + [n("B-q1", "B", POST), n("B-q2", "B", POST)]},
            "C": {PRE: c_old + [n("C-n%d" % i, "C", PRE) for i in range(9)], POST: [n("C-p", "C", POST)]},
        }
        self.results = {
            "A-n1": m(150, 6, passed=False), "A-n2": m(160, 6),
            "A-p1": m(100, 7, release="v1.17.0"),
            "B-q1": m(90, 7, devtype="0xA9", release="v1.17.0"), "B-q2": m(90, 7, release="v1.17.0"),
            "C-n8": m(170, 6),                                   # the 11th candidate: never tried
            "C-p": m(100, 7, release="v1.17.0"),
        }
        for i in range(8):
            self.results["C-n%d" % i] = m(150, 6, passed=False)
        self.rows, self.sleeps = [], []

    def run_draw(self, results=None, **kw):
        res = results if results is not None else self.results

        def fetch(c):
            r = res.get(c["log_id"], {"download": "missing"})
            if isinstance(r, Exception):
                raise r
            return dict(r)
        return x.draw_x(self.order, self.cands, fetch, self.rows.append, sleep=self.sleeps.append, **kw)

    def test_reuse_retries_and_limit(self):
        res = self.run_draw()
        self.assertEqual([p["vehicle"] for p in res["pairs"]], ["A", "B"])
        self.assertEqual(x.d(res["pairs"][0]), 60)
        self.assertEqual(x.d(res["pairs"][1]), 60)
        self.assertEqual(res["pairs"][1]["pre"]["source"], "v1")         # reused, not downloaded
        # downloads: A-n1, A-n2, A-p1, B-q1, B-q2, C-n0..C-n7 (2 reused + 8 new = 10 tries)
        self.assertEqual(res["downloads"], 13)
        self.assertEqual(len(self.sleeps), 12)
        self.assertEqual(res["stop"], "list exhausted")
        self.assertEqual(res["visited"], 3)
        ids = [r["log_id"] for r in self.rows]
        self.assertNotIn("C-n8", ids)
        self.assertNotIn("C-p", ids)                                     # no v1.16 log counted for C
        self.assertEqual(sum(1 for r in self.rows if r["source"] == "v1"), 3 + 1 + 3 + 2)
        self.assertEqual(sum(1 for r in self.rows if r["source"] == "ext"), 13)
        q1 = [r for r in self.rows if r["log_id"] == "B-q1"][0]
        self.assertIn("receiver changed", q1["why"])
        self.assertEqual([r["counts"] for r in self.rows].count(True), 4)
        json.dumps(self.rows)

    def test_limits_and_blocks(self):
        res = self.run_draw(max_downloads=4)
        self.assertEqual([p["vehicle"] for p in res["pairs"]], ["A"])
        self.assertEqual(res["stop"], "max downloads")
        self.assertEqual(res["downloads"], 4)
        self.rows.clear()
        blocked = dict(self.results, **{"A-n2": up.Blocked("HTTP 444")})
        res = self.run_draw(blocked)
        self.assertEqual(res["pairs"], [])
        self.assertEqual(res["blocked"], "blocked: HTTP 444")
        self.assertEqual(res["downloads"], 2)
        self.rows.clear()
        res = self.run_draw(max_pairs=1)
        self.assertEqual(len(res["pairs"]), 1)
        self.assertEqual(res["stop"], "max pairs")
        self.rows.clear()
        res = self.run_draw(out_of_time=lambda: True)
        self.assertEqual(res["downloads"], 0)
        self.assertEqual(res["stop"], "budget")
        self.assertEqual(len(self.rows), 3)                              # A's reused tries only


class Scoring(unittest.TestCase):
    def test_dx1(self):
        s = x.score_x([pair("s%d" % i, 190 + i, 150) for i in range(8)])      # d = 40..47
        self.assertEqual(s["diff_pre_minus_post_ms"]["all"]["median"], 43.5)
        self.assertGreater(s["diff_pre_minus_post_ms"]["all"]["ci95"][0], 0)
        self.assertEqual(s["diff_pre_minus_post_ms"]["positive"], 8)
        self.assertEqual(s["checks"], {"X0": True, "X1": True, "X2": True, "X3": True, "X4": None})
        self.assertEqual(s["decision"], "DX1")
        json.dumps(s)

    def test_dx2(self):
        s = x.score_x([pair("s%d" % i, 150 + (i % 5) - 2, 150) for i in range(8)])  # d = -2,-1,0,1,2,-2,-1,0
        self.assertEqual(s["diff_pre_minus_post_ms"]["all"]["median"], -0.5)
        self.assertFalse(s["checks"]["X1"])
        self.assertFalse(s["checks"]["X3"])
        self.assertEqual(s["decision"], "DX2")

    def test_dx3(self):
        s = x.score_x([pair("s%d" % i, 200, 100) for i in range(7)])
        self.assertEqual(s["checks"], {"X0": False, "X1": None, "X2": None, "X3": None, "X4": None})
        self.assertEqual(s["decision"], "DX3")
        e = x.score_x([])
        self.assertEqual(e["new_pairs"], 0)
        self.assertEqual(e["decision"], "DX3")
        json.dumps(e)

    def test_dx4_when_no_model_switched(self):
        s = x.score_x([pair("u%d" % i, 190 + i, 150, 7, 7) for i in range(8)])
        self.assertEqual(s["checks"], {"X0": True, "X1": True, "X2": False, "X3": None, "X4": False})
        self.assertEqual(s["decision"], "DX4")

    def test_report_extra(self):
        v1 = [pair("a", 200, 100), pair("b", 190, 100)]
        r = x.report_extra([pair("c", 180, 100)], v1, seen=frozenset({"a"}))
        self.assertEqual(r["pooled_first_plan"]["vehicles"], 3)
        self.assertEqual(r["pooled_first_plan"]["diff_pre_minus_post_ms"]["all"]["median"], 90)
        self.assertEqual(r["pooled_first_plan"]["diff_pre_minus_post_ms"]["not_in_dynmodel_2026"]["n"], 2)
        self.assertEqual(r["new_post_log_not_before_pre_log"], 1)
        self.assertEqual(r["new_receivers"], {"F9P": 1})
        json.dumps(r)
        self.assertIsNone(x.report_extra([], v1)["new_pre"])


if __name__ == "__main__":
    unittest.main()
