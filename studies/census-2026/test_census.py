"""Synthetic tests for census.py (standard library only; no log or list is downloaded).
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import json
import struct
import unittest
import urllib.error

import census as cs


def msg(t, payload):
    return struct.pack("<HB", len(payload), ord(t)) + payload


def p_payload(typ, name, value):
    key = ("%s %s" % (typ, name)).encode()
    val = struct.pack("<i", value) if typ == "int32_t" else struct.pack("<f", value)
    return bytes([len(key)]) + key + val


def ulog(model=6, end=True, q_bits=3, q_value=7):
    data = cs.MAGIC + b"\x01" + struct.pack("<Q", 0)
    data += msg("F", b"vehicle_gps_position:uint64_t timestamp;")
    data += msg("P", p_payload("int32_t", "GPS_UBX_DYNMODEL", model))
    data += msg("P", p_payload("float", "EKF2_GPS_DELAY", 110.0))
    data += msg("P", p_payload("int32_t", "SYS_AUTOSTART", 4001))
    data += msg("Q", bytes([q_bits]) + p_payload("int32_t", "GPS_UBX_DYNMODEL", q_value))
    if end:
        data += msg("A", b"\x00" + struct.pack("<H", 0) + b"vehicle_gps_position")
        data += msg("P", p_payload("int32_t", "GPS_UBX_MODE", 1))   # after the definitions: not read
        data += msg("D", b"\x00\x00" + b"\x01" * 8)
    return data


class Reader(unittest.TestCase):
    def test_whole(self):
        params, defaults, complete = cs.initial_params([ulog()])
        self.assertTrue(complete)
        self.assertEqual(params["GPS_UBX_DYNMODEL"], 6)
        self.assertEqual(params["EKF2_GPS_DELAY"], 110.0)
        self.assertNotIn("GPS_UBX_MODE", params)
        self.assertEqual(defaults["GPS_UBX_DYNMODEL"], {"system": 7, "config": 7})
        self.assertEqual(cs.pick(params), {"EKF2_GPS_DELAY": 110.0, "GPS_UBX_DYNMODEL": 6})

    def test_byte_by_byte(self):
        data = ulog()
        self.assertEqual(cs.initial_params([data[i:i + 1] for i in range(len(data))]),
                         cs.initial_params([data]))

    def test_cut_short(self):
        params, defaults, complete = cs.initial_params([ulog(end=False)])
        self.assertFalse(complete)
        self.assertEqual(params["GPS_UBX_DYNMODEL"], 6)

    def test_config_default_only(self):
        _, defaults, _ = cs.initial_params([ulog(q_bits=2, q_value=6)])
        self.assertEqual(defaults["GPS_UBX_DYNMODEL"], {"config": 6})

    def test_max_bytes(self):
        params, _, complete = cs.initial_params([ulog()[:40], b"\x00" * 100], max_bytes=40)
        self.assertFalse(complete)

    def test_not_ulog(self):
        with self.assertRaises(ValueError):
            cs.initial_params([b"<html>not a log file</html>"])


def entry(log_id, uuid, rel, mav="Quadrotor", dur=300, hw="PX4_FMU_V5"):
    return {"log_id": log_id, "vehicle_uuid": uuid, "ver_sw_release": rel, "mav_type": mav,
            "duration_s": dur, "sys_hw": hw, "log_date": "2026-05-01"}


class List(unittest.TestCase):
    def test_eligible(self):
        self.assertEqual(cs.eligible(entry("a", "u", "v1.16.0 255")), (("v1.16", "release"), ""))
        self.assertEqual(cs.eligible(entry("a", "u", "v1.17.0 192")), (("v1.17", "pre"), ""))
        self.assertEqual(cs.eligible(entry("a", "u", "v1.17.0 0"))[1], "development build")
        self.assertEqual(cs.eligible(entry("a", "u", "v1.15.4 255"))[1], "not v1.16 or v1.17")
        self.assertEqual(cs.eligible(entry("a", "u", "v1.16.0 255", mav="VTOL Quadrotor"))[1], "not a multicopter")
        self.assertEqual(cs.eligible(entry("a", "u", "v1.16.0 255", mav="Fixed Wing"))[1], "not a multicopter")
        self.assertEqual(cs.eligible(entry("a", "u", "v1.16.0 255", dur=100))[1], "shorter than 120 s")
        self.assertEqual(cs.eligible(entry("a", "u", "v1.16.0 255", hw="PX4_SITL"))[1], "simulation")
        self.assertEqual(cs.eligible(entry("a", "", "v1.16.0 255"))[1], "no vehicle id")
        self.assertEqual(cs.eligible(entry("a", "u", "v1.16.0 255", mav="Hexarotor"))[0], ("v1.16", "release"))

    def test_build_and_plan(self):
        es = [entry("a1", "u1", "v1.16.0 255"), entry("a2", "u1", "v1.16.1 255"), entry("a3", "u1", "v1.17.0 255"),
              entry("b1", "u2", "v1.16.0 255"), entry("c1", "u3", "v1.17.0 255"), entry("x", "u4", "v1.17.0 0")]
        by_side, counts = cs.build(es)
        self.assertEqual(counts["listed"], 6)
        self.assertEqual(counts["eligible"], 5)
        self.assertEqual(counts["excluded"], {"development build": 1})
        self.assertEqual(counts["vehicles"], {"v1.16": 2, "v1.17": 2, "on_both": 1})
        p = cs.plan(by_side, seen=frozenset([cs.vehicle_hash("u2")]))
        self.assertEqual(p["v1.16"], [])
        self.assertEqual(p["left_out_seen"], {"v1.16": 1, "v1.17": 0})
        self.assertEqual([c["log_id"] for c in p["v1.17"]], ["c1"])
        self.assertEqual([c["log_id"] for c in p["both"]], ["a3"])
        self.assertEqual(p, cs.plan(by_side, seen=frozenset([cs.vehicle_hash("u2")])))

    def test_plan_one_log_per_vehicle(self):
        es = []
        for i in range(40):
            es += [entry("p%d-%d" % (i, j), "pre%d" % i, "v1.16.0 255") for j in range(3)]
            es += [entry("q%d" % i, "post%d" % i, "v1.17.0 255")]
        p = cs.plan(cs.build(es)[0])
        self.assertEqual(len(p["v1.16"]), 40)
        self.assertEqual(len({c["vehicle"] for c in p["v1.16"]}), 40)
        self.assertEqual(len(p["v1.17"]), 40)
        self.assertEqual(p["both"], [])


def fake_plan(n=10, both=3):
    return {"v1.16": [{"log_id": "pre-%d" % i, "series": "v1.16", "kind": "release"} for i in range(n)],
            "v1.17": [{"log_id": "post-%d" % i, "series": "v1.17", "kind": "release"} for i in range(n)],
            "both": [{"log_id": "both-%d" % i, "series": "v1.17", "kind": "release"} for i in range(both)]}


class Pass(unittest.TestCase):
    def go(self, fetch_fn, **kw):
        written, sleeps = [], []
        res = cs.run(fake_plan(), fetch_fn, written.append, sleep=sleeps.append, **kw)
        return res, written, sleeps

    def test_alternates_and_reads_both_last(self):
        res, w, sleeps = self.go(lambda i: ({"GPS_UBX_DYNMODEL": 6}, {}, True), target=3)
        self.assertEqual([r["log_id"] for r in w],
                         ["pre-0", "post-0", "pre-1", "post-1", "pre-2", "post-2", "both-0", "both-1", "both-2"])
        self.assertEqual([r["group"] for r in w], ["graded"] * 6 + ["both"] * 3)
        self.assertEqual(res["graded_with_model"], {"v1.16": 3, "v1.17": 3})
        self.assertEqual(res["graded_stop"], "graded draw complete")
        self.assertEqual(res["both_read"], 3)
        self.assertEqual(res["requests"], 9)
        self.assertEqual(len(sleeps), 8)

    def test_log_without_model_needs_another(self):
        def f(i):
            return ({}, {}, True) if i == "pre-1" else ({"GPS_UBX_DYNMODEL": 7}, {}, True)
        res, w, _ = self.go(f, target=3)
        self.assertEqual(res["graded_tries"], {"v1.16": 4, "v1.17": 3})
        self.assertEqual([r["log_id"] for r in w if r["group"] == "graded"],
                         ["pre-0", "post-0", "pre-1", "post-1", "pre-2", "post-2", "pre-3"])

    def test_max_tries_and_404(self):
        def f(i):
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        res, w, _ = self.go(f, target=3, max_tries=4)
        self.assertEqual(res["graded_tries"], {"v1.16": 4, "v1.17": 4})
        self.assertEqual(res["graded_with_model"], {"v1.16": 0, "v1.17": 0})
        self.assertEqual(w[0]["status"], "http 404")
        self.assertEqual(res["both_read"], 3)

    def test_block_stops_everything(self):
        def f(i):
            if i == "post-1":
                raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
            return {"GPS_UBX_DYNMODEL": 6}, {}, True
        res, w, _ = self.go(f, target=5)
        self.assertEqual([r["log_id"] for r in w], ["pre-0", "post-0", "pre-1", "post-1"])
        self.assertEqual(w[-1]["status"], "not read (blocked: http 403)")
        self.assertEqual(res["stop"], "blocked: http 403")
        self.assertEqual(res["graded_stop"], "blocked: http 403")
        self.assertEqual(res["both_read"], 0)

    def test_five_errors_in_a_row(self):
        def f(i):
            raise RuntimeError("connection reset")
        res, w, _ = self.go(f, target=5)
        self.assertEqual(len(w), 5)
        self.assertEqual(res["stop"], "five network errors in a row")
        self.assertTrue(w[0]["status"].startswith("error: RuntimeError"))

    def test_time_budget(self):
        ticks = [0, 0, 0]

        def clock():
            return ticks.pop(0) if ticks else 5
        res, w, _ = self.go(lambda i: ({"GPS_UBX_DYNMODEL": 6}, {}, True), target=5, clock=clock, budget_s=1)
        self.assertEqual([r["log_id"] for r in w], ["pre-0", "post-0"])
        self.assertEqual(res["stop"], "time budget")
        self.assertEqual(res["both_read"], 0)

    def test_records_are_copies(self):
        p = fake_plan()
        cs.run(p, lambda i: ({"GPS_UBX_DYNMODEL": 6}, {}, True), lambda r: None, target=1, sleep=lambda s: None)
        self.assertNotIn("status", p["v1.16"][0])


def recs(series, k6, n, group="graded", kind="release"):
    return [{"group": group, "series": series, "status": "ok", "kind": kind, "sys_hw": "B",
             "params": {"GPS_UBX_DYNMODEL": 6 if i < k6 else 7}} for i in range(n)]


class Score(unittest.TestCase):
    def test_wilson(self):
        lo, hi = cs.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)
        lo, hi = cs.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=3)
        self.assertIsNone(cs.wilson(0, 0))

    def test_h1(self):
        s = cs.summarise(recs("v1.16", 170, 200) + recs("v1.17", 20, 200))
        self.assertEqual(s["graded"]["v1.16"]["share6"], 0.85)
        self.assertEqual(s["graded"]["v1.17"]["share6"], 0.1)
        self.assertEqual(s["graded"]["difference_share6"], 0.75)
        self.assertEqual(s["graded"]["v1.17"]["models"], {"6": 20, "7": 180})
        self.assertEqual(s["checks"], {"E0": True, "C1": True, "C2": True, "C3": True})
        self.assertEqual(s["decisions"], {"H0": False, "H1": True, "H2": False, "H3": False})

    def test_h2(self):
        s = cs.summarise(recs("v1.16", 170, 200) + recs("v1.17", 50, 200))
        self.assertEqual(s["graded"]["v1.17"]["share6"], 0.25)
        self.assertFalse(s["checks"]["C2"])
        self.assertEqual(s["decisions"], {"H0": False, "H1": False, "H2": True, "H3": False})

    def test_c2_upper_edge_is_inside(self):
        s = cs.summarise(recs("v1.16", 170, 200) + recs("v1.17", 40, 200))
        self.assertTrue(s["checks"]["C2"])
        self.assertFalse(s["decisions"]["H2"])

    def test_h3(self):
        s = cs.summarise(recs("v1.16", 140, 200) + recs("v1.17", 20, 200))
        self.assertEqual(s["graded"]["v1.16"]["share6"], 0.7)
        self.assertFalse(s["checks"]["C1"])
        self.assertTrue(s["checks"]["C3"])
        self.assertEqual(s["decisions"], {"H0": False, "H1": False, "H2": False, "H3": True})

    def test_c3_fails(self):
        s = cs.summarise(recs("v1.16", 160, 200) + recs("v1.17", 40, 200))
        self.assertEqual(s["graded"]["difference_share6"], 0.6)
        s = cs.summarise(recs("v1.16", 150, 200) + recs("v1.17", 40, 200))
        self.assertEqual(s["graded"]["difference_share6"], 0.55)
        self.assertTrue(s["checks"]["C3"])
        s = cs.summarise(recs("v1.16", 160, 200) + recs("v1.17", 80, 200))
        self.assertFalse(s["checks"]["C3"])

    def test_e0_fails(self):
        s = cs.summarise(recs("v1.16", 170, 199) + recs("v1.17", 20, 200))
        self.assertEqual(s["checks"], {"E0": False, "C1": None, "C2": None, "C3": None})
        self.assertEqual(s["decisions"], {"H0": True, "H1": False, "H2": False, "H3": False})

    def test_only_graded_logs_with_a_model_count(self):
        extra = recs("v1.17", 200, 200, group="both")
        extra.append({"group": "graded", "series": "v1.17", "status": "http 404"})
        extra.append({"group": "graded", "series": "v1.17", "status": "ok", "params": {}})
        s = cs.summarise(recs("v1.16", 170, 200) + recs("v1.17", 20, 200) + extra)
        self.assertEqual(s["graded"]["v1.17"]["n"], 200)
        self.assertEqual(s["reported"]["on_both_v1_17"]["share6"], 1.0)
        self.assertEqual(s["reported"]["read_without_dynmodel"], 1)
        self.assertEqual(s["reported"]["status_counts"]["graded/http 404"], 1)

    def test_report_and_plain_json(self):
        rs = recs("v1.16", 170, 200) + recs("v1.17", 20, 200)
        rs[-1]["kind"] = "pre"
        rs[200]["defaults"] = {"GPS_UBX_DYNMODEL": {"config": 7}}
        rs[200]["params"]["GPS_1_PROTOCOL"] = 1
        s = cs.summarise(rs)
        r = s["reported"]
        self.assertEqual(r["dynmodel_vs_logged_config_default"]["v1.17 model 6, config default 7"], 1)
        self.assertEqual(r["v1_17_model6_boards"], {"B": 20})
        self.assertEqual(r["v1_17_by_build_kind"]["pre"]["n"], 1)
        self.assertEqual(r["gps_1_protocol"]["v1.17 GPS_1_PROTOCOL 1"], 1)
        json.dumps(s)


if __name__ == "__main__":
    unittest.main()
