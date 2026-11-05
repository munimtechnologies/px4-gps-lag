"""Tests for upgrade.py (study upgrade-2026). Standard library only: no network, no logs.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import unittest

import upgrade as up

F9P_SERIAL = (0xAA << 16) | 5          # 11141125, the device id of the PR #24831 logs
M9_SERIAL = (0xA9 << 16) | 5
F9P_UAVCAN = (0xAA << 16) | 3


def entry(log_id, uuid="veh-1", release="v1.16.0 255", mav="Quadrotor", duration=300, **kw):
    e = {"log_id": log_id, "log_date": "2026-01-01", "vehicle_uuid": uuid, "mav_type": mav,
         "sys_hw": "PX4_FMU_V6X", "ver_sw_release": release, "duration_s": duration,
         "source": "webui", "type": "flightreport"}
    e.update(kw)
    return e


def measured(lag, model, devtype="0xAA", release="v1.16.0", passed=True, serial=True):
    return {"download": "ok", "passed": passed, "reason": "ok" if passed else "too little manoeuvring",
            "lag_ms": lag, "dynmodel": model, "devtype": devtype, "serial_ublox": serial,
            "receiver": "F9P", "ver_sw_release": release, "param_gps_delay_ms": 110.0}


def pair(v, pre_lag, post_lag, pre_model=6, post_model=7):
    return {"vehicle": v, "pre": measured(pre_lag, pre_model), "post": measured(post_lag, post_model, release="v1.17.0")}


class Listing(unittest.TestCase):
    def test_is_multicopter(self):
        for t in ("Quadrotor", "Hexarotor", "Octorotor", "Tricopter", "quadrotor"):
            self.assertTrue(up.is_multicopter(t), t)
        for t in ("Fixed Wing", "VTOL Quadrotor", "VTOL Tiltrotor", "Coaxial helicopter", "Ground Rover",
                  "Boat", "", None):
            self.assertFalse(up.is_multicopter(t), t)

    def test_release_series(self):
        self.assertEqual(up.release_series("v1.16.0 255"), ("v1.16", "release"))
        self.assertEqual(up.release_series("v1.16.1 release"), ("v1.16", "release"))
        self.assertEqual(up.release_series("v1.17.0 192"), ("v1.17", "pre"))
        self.assertEqual(up.release_series("v1.17.0 rc"), ("v1.17", "pre"))
        self.assertEqual(up.release_series("v1.17.0 0"), ("v1.17", "dev"))
        self.assertEqual(up.release_series("v1.16.0 (dev)"), ("v1.16", "dev"))
        self.assertEqual(up.release_series("v1.16.0"), ("v1.16", "unknown"))
        self.assertEqual(up.release_series("v1.18.0 192"), ("v1.18", "pre"))
        self.assertIsNone(up.release_series(""))
        self.assertIsNone(up.release_series(None))

    def test_log_release_ok(self):
        self.assertTrue(up.log_release_ok("v1.16.2", "v1.16"))
        self.assertTrue(up.log_release_ok("v1.17.0-192", "v1.17"))
        self.assertFalse(up.log_release_ok("v1.17.0-0", "v1.17"))      # development build
        self.assertFalse(up.log_release_ok("v1.15.4", "v1.16"))
        self.assertFalse(up.log_release_ok("v1.160.0", "v1.16"))
        self.assertFalse(up.log_release_ok(None, "v1.16"))

    def test_eligible(self):
        self.assertEqual(up.eligible(entry("a")), ("v1.16", ""))
        self.assertEqual(up.eligible(entry("a", release="v1.17.1 255")), ("v1.17", ""))
        self.assertEqual(up.eligible(entry("a", release="v1.15.4 255"))[1], "not v1.16 or v1.17")
        self.assertEqual(up.eligible(entry("a", release="v1.17.0 0"))[1], "development build")
        self.assertEqual(up.eligible(entry("a", mav="Fixed Wing"))[1], "not a multicopter")
        self.assertEqual(up.eligible(entry("a", duration=119))[1], "shorter than 120 s")
        self.assertEqual(up.eligible(entry("a", uuid=""))[1], "no vehicle id")
        self.assertEqual(up.eligible(entry("a", sys_hw="PX4_SITL"))[1], "simulation")
        self.assertEqual(up.eligible(entry("a", source="CI"))[1], "CI")

    def test_group_keeps_vehicles_on_both_releases(self):
        es = [entry("a1", "A"), entry("a2", "A", release="v1.17.0 255"), entry("a3", "A", release="v1.17.1 255"),
              entry("b1", "B"), entry("c1", "C", release="v1.17.0 255"),
              entry("d1", "D", release="v1.16.0 0"), entry("d2", "D", release="v1.17.0 255")]
        both, counts = up.group(es)
        self.assertEqual(list(both), [up.vehicle_hash("A")])
        a = both[up.vehicle_hash("A")]
        self.assertEqual([c["log_id"] for c in a["v1.16"]], ["a1"])
        self.assertEqual(sorted(c["log_id"] for c in a["v1.17"]), ["a2", "a3"])
        self.assertEqual(counts["listed"], 7)
        self.assertEqual(counts["eligible"], 6)
        self.assertEqual(counts["vehicles_on_both"], 1)
        self.assertEqual(counts["vehicles_only_pre"], 1)
        self.assertEqual(counts["vehicles_only_post"], 2)            # C, and D (its v1.16 log is dev)
        self.assertEqual(counts["excluded"], {"development build": 1})

    def test_plan_order_is_seeded_and_complete(self):
        es = []
        for v in "ABCDEFGH":
            es += [entry(v + "1", v), entry(v + "2", v), entry(v + "3", v, release="v1.17.0 255")]
        both, _ = up.group(es)
        o1, l1 = up.plan_order(both)
        o2, l2 = up.plan_order(both)
        self.assertEqual(o1, o2)
        self.assertEqual(l1, l2)
        self.assertEqual(sorted(o1), sorted(both))
        for v in o1:
            self.assertEqual(sorted(c["log_id"] for c in l1[v]["v1.16"]), sorted(c["log_id"] for c in both[v]["v1.16"]))
        self.assertNotEqual(up.plan_order(both, seed=1)[0], o1)


class OneLog(unittest.TestCase):
    def test_gnss_facts(self):
        f = up.gnss_facts({"GPS_UBX_DYNMODEL": 6, "EKF2_GPS_DELAY": 110.0, "GPS_UBX_MODE": 0},
                          [0, F9P_SERIAL, F9P_SERIAL, M9_SERIAL])
        self.assertEqual(f["device_id"], 11141125)
        self.assertEqual(f["devtype"], "0xAA")
        self.assertEqual(f["receiver"], "F9P")
        self.assertTrue(f["serial_ublox"])
        self.assertEqual(f["dynmodel"], 6)
        self.assertEqual(f["param_gps_delay_ms"], 110.0)
        g = up.gnss_facts({}, [F9P_UAVCAN])
        self.assertFalse(g["serial_ublox"])
        self.assertIsNone(g["dynmodel"])
        neg = up.gnss_facts({}, [F9P_SERIAL - (1 << 32)])            # stored as a negative int32
        self.assertEqual(neg["device_id"], F9P_SERIAL)
        self.assertFalse(up.gnss_facts({}, [])["serial_ublox"])

    def test_usable(self):
        self.assertEqual(up.usable(measured(150, 6), "v1.16"), (True, "ok"))
        self.assertFalse(up.usable(measured(150, 6, passed=False), "v1.16")[0])
        self.assertFalse(up.usable(measured(150, 6, release="v1.15.4"), "v1.16")[0])
        self.assertFalse(up.usable(measured(150, 6, serial=False), "v1.16")[0])
        self.assertFalse(up.usable(measured(150, None), "v1.16")[0])
        self.assertEqual(up.usable(measured(100, 7, release="v1.17.0"), "v1.17", "0xAA"), (True, "ok"))
        ok, why = up.usable(measured(100, 7, devtype="0xA9", release="v1.17.0"), "v1.17", "0xAA")
        self.assertFalse(ok)
        self.assertIn("receiver changed", why)


class Draw(unittest.TestCase):
    def setUp(self):
        self.order = ["A", "B", "C"]
        c = lambda v, s, i: {"log_id": "%s-%s-%d" % (v, s, i), "vehicle": v, "series": s}
        self.logs = {v: {"v1.16": [c(v, "v1.16", i) for i in range(4)],
                         "v1.17": [c(v, "v1.17", i) for i in range(4)]} for v in self.order}
        self.rows = []

    def run_draw(self, results, **kw):
        def fetch(cand):
            r = results.get(cand["log_id"], {"download": "missing"})
            if isinstance(r, Exception):
                raise r
            return dict(r)
        return up.draw(self.order, self.logs, fetch, self.rows.append, **kw)

    def test_pairs_and_retries(self):
        res = self.run_draw({
            "A-v1.16-0": measured(150, 6, passed=False), "A-v1.16-1": measured(160, 6),
            "A-v1.17-0": measured(100, 7, devtype="0xA9", release="v1.17.0"),
            "A-v1.17-1": measured(105, 7, release="v1.17.0"),
            # B: no usable v1.16 log in 3 tries, so its v1.17 logs are never downloaded
            "B-v1.16-0": measured(150, 6, serial=False), "B-v1.16-3": measured(150, 6),
            "C-v1.16-0": measured(140, 7), "C-v1.17-0": measured(141, 7, release="v1.17.0")})
        self.assertEqual([p["vehicle"] for p in res["pairs"]], ["A", "C"])
        self.assertEqual(res["pairs"][0]["pre"]["lag_ms"], 160)
        self.assertEqual(res["pairs"][0]["post"]["lag_ms"], 105)
        self.assertEqual(res["downloads"], 4 + 3 + 2)
        self.assertEqual(res["stop"], "list exhausted")
        self.assertEqual(res["visited"], 3)
        self.assertFalse(any(r["log_id"].startswith("B-v1.17") for r in self.rows))
        self.assertFalse(any(r["log_id"] == "B-v1.16-3" for r in self.rows))   # only 3 tries
        self.assertEqual([r["counts"] for r in self.rows].count(True), 4)
        json.dumps(self.rows)

    def test_blocked_stops_everything(self):
        res = self.run_draw({"A-v1.16-0": measured(150, 6), "A-v1.17-0": up.Blocked("HTTP 403")})
        self.assertEqual(res["pairs"], [])
        self.assertTrue(res["stop"].startswith("blocked"))
        self.assertEqual(res["blocked"], res["stop"])
        self.assertEqual(res["downloads"], 2)

    def test_limits(self):
        ok = {"%s-v1.16-0" % v: measured(150, 6) for v in self.order}
        ok.update({"%s-v1.17-0" % v: measured(100, 7, release="v1.17.0") for v in self.order})
        res = self.run_draw(ok, max_vehicles=2)
        self.assertEqual(len(res["pairs"]), 2)
        self.assertEqual(res["stop"], "max vehicles")
        self.assertEqual(res["downloads"], 4)
        self.rows.clear()
        res = self.run_draw(ok, max_downloads=3)
        self.assertEqual(len(res["pairs"]), 1)
        self.assertEqual(res["stop"], "max downloads")
        self.rows.clear()
        res = self.run_draw(ok, out_of_time=lambda: True)
        self.assertEqual(res["downloads"], 0)
        self.assertEqual(res["stop"], "budget")


class Scoring(unittest.TestCase):
    def test_boot_median(self):
        xs = [1.0, 2.0, 3.0, 4.0, 100.0]
        a, b = up.boot_median(xs), up.boot_median(xs)
        self.assertEqual(a, b)
        self.assertLessEqual(a[0], 3.0)
        self.assertGreaterEqual(a[1], 3.0)
        self.assertIsNone(up.boot_median([1.0]))

    def test_d1(self):
        pairs = [pair("s%d" % i, 150 + 40 + i, 150) for i in range(8)]          # diffs 40..47
        pairs += [pair("u%d" % i, 120 + 5 + i, 120, 7, 7) for i in range(6)]     # diffs 5..10
        s = up.summarise(pairs, seen=frozenset({"s0", "u0"}))
        d = s["diff_pre_minus_post_ms"]
        self.assertEqual(s["vehicles"], 14)
        self.assertEqual(d["all"]["median"], 40.5)
        self.assertGreater(d["all"]["ci95"][0], 0)
        self.assertEqual(d["switched_6_to_7"]["n"], 8)
        self.assertEqual(d["switched_6_to_7"]["median"], 43.5)
        self.assertEqual(d["unchanged_model"]["median"], 7.5)
        self.assertEqual(d["not_in_dynmodel_2026"]["n"], 12)
        self.assertEqual(s["checks"], {"E0": True, "U1": True, "U2": True, "U3": True, "U4": True})
        self.assertEqual(s["decision"], "D1")
        self.assertEqual(s["pre"]["dynmodel"], {"6": 8, "7": 6})
        self.assertEqual(s["post"]["dynmodel"], {"7": 14})
        json.dumps(s)

    def test_d2_when_the_upgrade_changes_nothing(self):
        pairs = [pair("s%d" % i, 150 + (i % 5) - 2, 150) for i in range(10)]
        pairs += [pair("u%d" % i, 120 + (i % 3) - 1, 120, 7, 7) for i in range(4)]
        s = up.summarise(pairs)
        self.assertTrue(s["checks"]["E0"])
        self.assertFalse(s["checks"]["U1"])
        self.assertFalse(s["checks"]["U3"])
        self.assertIsNone(s["checks"]["U4"])                                       # 4 < 6 unchanged
        self.assertEqual(s["decision"], "D2")

    def test_d3_when_too_few_vehicles(self):
        s = up.summarise([pair("s%d" % i, 200, 100) for i in range(11)])
        self.assertFalse(s["checks"]["E0"])
        self.assertEqual({k: v for k, v in s["checks"].items() if k != "E0"},
                         {"U1": None, "U2": None, "U3": None, "U4": None})
        self.assertEqual(s["decision"], "D3")
        e = up.summarise([])
        self.assertEqual(e["vehicles"], 0)
        self.assertEqual(e["decision"], "D3")
        json.dumps(e)


if __name__ == "__main__":
    unittest.main()
