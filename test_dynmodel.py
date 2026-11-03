"""Tests for dynmodel.py (standard library only). By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import io
import struct
import unittest
import urllib.error

import dynmodel as dm


def msg(t, payload):
    return struct.pack("<HB", len(payload), ord(t)) + payload


def param(typ, name, val):
    key = ("%s %s" % (typ, name)).encode()
    v = struct.pack("<i", val) if typ == "int32_t" else struct.pack("<f", val)
    return msg("P", bytes([len(key)]) + key + v)


HEADER = dm.MAGIC + b"\x01" + struct.pack("<Q", 123456)
DEFS = (msg("B", bytes(40))
        + msg("I", bytes([len(b"char[4] sys_name")]) + b"char[4] sys_name" + b"PX4!")
        + msg("F", b"vehicle_gps_position:uint64_t timestamp;float eph;")
        + param("int32_t", "GPS_UBX_DYNMODEL", 6)
        + param("float", "EKF2_GPS_DELAY", 110.0)
        + param("int32_t", "SYS_AUTOSTART", 4001))
DATA = (msg("A", b"\x00\x01\x00vehicle_gps_position")
        + param("int32_t", "GPS_UBX_DYNMODEL", 8)       # a change in flight: not an initial parameter
        + msg("D", b"\x01\x00" + bytes(12)))
LOG = HEADER + DEFS + DATA
INITIAL = {"GPS_UBX_DYNMODEL": 6, "EKF2_GPS_DELAY": 110.0, "SYS_AUTOSTART": 4001}


def ones(data):
    return (data[i:i + 1] for i in range(len(data)))


class TestULog(unittest.TestCase):
    def test_whole(self):
        self.assertEqual(dm.initial_params([LOG]), (INITIAL, True))

    def test_byte_by_byte(self):
        self.assertEqual(dm.initial_params(ones(LOG)), (INITIAL, True))

    def test_odd_chunks(self):
        chunks = [LOG[i:i + 7] for i in range(0, len(LOG), 7)]
        self.assertEqual(dm.initial_params(chunks), (INITIAL, True))

    def test_stops_before_data(self):
        # the stream after the first data-section message is never needed
        cut = len(HEADER + DEFS) + 3
        self.assertEqual(dm.initial_params([LOG[:cut]]), (INITIAL, True))

    def test_truncated_before_data(self):
        self.assertEqual(dm.initial_params([HEADER + DEFS]), (INITIAL, False))

    def test_truncated_inside_a_parameter(self):
        cut = len(HEADER + DEFS) - len(param("int32_t", "SYS_AUTOSTART", 4001)) \
            - len(param("float", "EKF2_GPS_DELAY", 110.0)) + 5
        self.assertEqual(dm.initial_params([LOG[:cut]]), ({"GPS_UBX_DYNMODEL": 6}, False))

    def test_not_ulog(self):
        with self.assertRaises(ValueError):
            dm.initial_params([b"<html><body>gone</body></html>"])

    def test_short_stream(self):
        self.assertEqual(dm.initial_params([b"ULog"]), ({}, False))

    def test_max_bytes(self):
        self.assertEqual(dm.initial_params(ones(LOG), max_bytes=20), ({}, False))

    def test_parse_param(self):
        p = param("float", "EKF2_GPS_P_NOISE", 0.5)
        self.assertEqual(dm.parse_param(p[3:]), ("EKF2_GPS_P_NOISE", 0.5))
        key = b"uint8_t X"
        self.assertIsNone(dm.parse_param(bytes([len(key)]) + key + b"\x01\x00\x00\x00"))
        self.assertIsNone(dm.parse_param(b""))
        self.assertEqual(dm.parse_param(param("int32_t", "NEG", -5)[3:]), ("NEG", -5))

    def test_pick_params(self):
        self.assertEqual(dm.pick_params(dict(INITIAL, SER_GPS1_BAUD=0, SENS_GPS0_DELAY=110.0)),
                         {"EKF2_GPS_DELAY": 110.0, "GPS_UBX_DYNMODEL": 6, "SENS_GPS0_DELAY": 110.0,
                          "SER_GPS1_BAUD": 0})


def row(i, receiver="ubx_f9p", lag=120.0, ver="v1.16.1-0", grid=200, mode=0, bus="serial", receivers=1,
        passed=True, vehicle=None):
    return {"log_id": "L%d" % i, "vehicle": vehicle or "V%d" % i, "passed": passed, "reason": "ok",
            "lag_ms": lag, "lag_minus_param_ms": lag - 110.0, "gps_bus": bus, "ver_sw_release": ver,
            "receiver": receiver, "receivers": receivers, "grid_ms": grid, "gps_ubx_mode": mode}


class TestSelect(unittest.TestCase):
    def test_usable(self):
        self.assertTrue(dm.usable(row(1)))
        self.assertTrue(dm.usable(row(1, receiver="ubx_generic")))
        self.assertFalse(dm.usable(row(1, receiver="uavcan")))
        self.assertFalse(dm.usable(row(1, bus="unknown")))
        self.assertFalse(dm.usable(row(1, receivers=2)))
        self.assertFalse(dm.usable(row(1, passed=False)))
        r = row(1)
        r["lag_ms"] = None
        self.assertFalse(dm.usable(r))
        r = row(1)
        r["reason"] = "simulated GPS"
        self.assertFalse(dm.usable(r))

    def test_f9p_5hz(self):
        self.assertTrue(dm.f9p_5hz(row(1)))
        self.assertTrue(dm.f9p_5hz(row(1, ver="v1.17.0", mode=None)))
        self.assertFalse(dm.f9p_5hz(row(1, ver="v1.18.0-192")))
        self.assertFalse(dm.f9p_5hz(row(1, ver="v1.15.4")))
        self.assertFalse(dm.f9p_5hz(row(1, grid=100)))
        self.assertFalse(dm.f9p_5hz(row(1, mode=1)))
        self.assertFalse(dm.f9p_5hz(row(1, receiver="ubx_m9")))

    def test_select(self):
        a = [row(1), row(2, receiver="uavcan", bus="uavcan"), row(3, receiver="ubx_m9", grid=100)]
        b = [row(1), row(4, receiver="ubx_m8"), row(5)]
        extra = [{"log_id": "L5", "params": {"GPS_UBX_DYNMODEL": 6, "MC_X": 1}}]
        todo, seen = dm.select([("receiver-2026", a), ("f9p-2026", b)], extra)
        self.assertEqual(sorted(r["log_id"] for r in todo), ["L1", "L3", "L4"])
        self.assertEqual([r["log_id"] for r in seen], ["L5"])
        self.assertEqual(seen[0]["params"], {"GPS_UBX_DYNMODEL": 6})
        self.assertEqual(seen[0]["status"], "seen (f9p-extra)")
        l1 = [r for r in todo if r["log_id"] == "L1"][0]
        self.assertEqual((l1["sample"], l1["sample_index"], l1["row_index"], l1["f9p_5hz"]),
                         ("receiver-2026", 0, 0, True))
        todo2, _ = dm.select([("receiver-2026", a), ("f9p-2026", b)], extra)
        self.assertEqual([r["log_id"] for r in todo], [r["log_id"] for r in todo2])


class TestCollect(unittest.TestCase):
    def test_statuses_and_block(self):
        todo = [{"log_id": "A"}, {"log_id": "B"}, {"log_id": "C"}, {"log_id": "D"}, {"log_id": "E"}]
        calls, sleeps = [], []

        def fetch(log_id):
            calls.append(log_id)
            if log_id == "A":
                return {"GPS_UBX_DYNMODEL": 6, "SYS_X": 1}, True
            if log_id == "B":
                raise urllib.error.HTTPError("u", 404, "Not Found", None, None)
            if log_id == "C":
                raise ValueError("not a ULog file")
            if log_id == "D":
                raise urllib.error.HTTPError("u", 403, "Forbidden", None, None)
            return {}, True

        out = io.StringIO()
        counts = dm.collect(todo, fetch, out, sleep=sleeps.append, clock=lambda: 0.0)
        self.assertEqual(calls, ["A", "B", "C", "D"])
        self.assertEqual(len(sleeps), 3)
        self.assertEqual([r["status"] for r in todo],
                         ["ok", "http 404", "error: not a ULog file", "not read (blocked: http 403)",
                          "not attempted (blocked: http 403)"])
        self.assertEqual(todo[0]["params"], {"GPS_UBX_DYNMODEL": 6})
        self.assertEqual(sum(counts.values()), 5)
        self.assertEqual(len(out.getvalue().strip().splitlines()), 5)

    def test_budget_and_network_errors(self):
        todo = [{"log_id": str(i)} for i in range(8)]

        def fetch(log_id):
            raise ConnectionResetError("reset")

        dm.collect(todo, fetch, io.StringIO(), sleep=lambda s: None, clock=lambda: 0.0)
        self.assertEqual(sum(1 for r in todo if r["status"].startswith("error: ConnectionResetError")), 5)
        self.assertEqual(sum(1 for r in todo if r["status"] == "not attempted (five network errors in a row)"), 3)
        t = iter([0.0, 0.0, 10.0, 10.0])
        todo = [{"log_id": "x"}, {"log_id": "y"}, {"log_id": "z"}]
        dm.collect(todo, lambda i: ({}, False), io.StringIO(), sleep=lambda s: None,
                   clock=lambda: next(t), budget_s=5)
        self.assertEqual([r["status"] for r in todo],
                         ["incomplete", "not attempted (time budget)", "not attempted (time budget)"])


def rec(i, cls, dyn, lag, sample="fresh-2026", f5=False, status="ok", vehicle=None, si=1):
    return {"sample": sample, "sample_index": si, "row_index": i, "log_id": "L%d" % i,
            "vehicle": vehicle or "V%d" % i, "receiver": cls, "lag_ms": float(lag),
            "lag_minus_param_ms": float(lag) - 110.0, "f9p_5hz": f5, "status": status,
            "params": {} if dyn is None else {"GPS_UBX_DYNMODEL": dyn}}


def world(shift_f9p=90.0, shift_m9=40.0, n_f9p6=6, n_m96=8):
    """F9P: 12 logs at 7 (110 ms) and n_f9p6 at 6; M9: 50 at 7 (80 ms) and n_m96 at 6. All fresh-2026."""
    recs, i = [], 0
    for _ in range(12):
        recs.append(rec(i, "ubx_f9p", 7, 110, f5=True)); i += 1
    for _ in range(n_f9p6):
        recs.append(rec(i, "ubx_f9p", 6, 110 + shift_f9p, f5=True)); i += 1
    for _ in range(50):
        recs.append(rec(i, "ubx_m9", 7, 80)); i += 1
    for _ in range(n_m96):
        recs.append(rec(i, "ubx_m9", 6, 80 + shift_m9)); i += 1
    return recs


class TestScore(unittest.TestCase):
    def test_all_hold(self):
        s = dm.summarise(world())
        self.assertEqual((s["graded"], s["graded_dyn6"], s["graded_dyn7"]), (76, 14, 62))
        # residuals: 8 x 40 (M9) and 6 x 90 (F9P) -> median 40
        self.assertEqual(s["K1_all_ublox"]["median_ms"], 40.0)
        self.assertGreater(s["K1_all_ublox"]["ci95_ms"][0], 0)
        self.assertEqual(s["K2_f9p"]["diff_ms"], 90.0)
        self.assertEqual(s["K2_f9p"]["ci95_ms"], [90.0, 90.0])
        self.assertEqual(s["K3_fresh_f9p_groups"]["n"], 18)
        self.assertEqual(s["K3_fresh_f9p_groups"]["share"], 1.0)
        self.assertEqual(s["K4_other_ublox"]["median_ms"], 40.0)
        self.assertEqual(s["checks"], {"E0": True, "K1": True, "K2": True, "K3": True, "K4": True})
        self.assertEqual(s["decision"], {"D1": True, "D2": False})

    def test_no_effect(self):
        s = dm.summarise(world(shift_f9p=0.0, shift_m9=0.0))
        self.assertEqual(s["K1_all_ublox"]["median_ms"], 0.0)
        # no F9P log reaches 175 ms, so every 6-log sits in the low group: 12 of 18 agree
        self.assertEqual(s["K3_fresh_f9p_groups"]["share"], round(12 / 18, 4))
        self.assertEqual(s["checks"], {"E0": True, "K1": False, "K2": False, "K3": False, "K4": False})
        self.assertEqual(s["decision"], {"D1": False, "D2": True})

    def test_e0_fails(self):
        s = dm.summarise(world(n_f9p6=3, n_m96=3))
        self.assertFalse(s["checks"]["E0"])
        self.assertEqual([s["checks"][k] for k in ("K1", "K2", "K3", "K4")], [None] * 4)
        self.assertEqual(s["decision"], {"D1": False, "D2": False})

    def test_unscored_parts(self):
        # 14 6-logs but only 2 on F9P: K2 and K3 unscored, K4 scored on 12 M9 6-logs
        s = dm.summarise(world(n_f9p6=2, n_m96=12))
        self.assertTrue(s["checks"]["E0"])
        self.assertIsNone(s["checks"]["K2"])
        self.assertIsNone(s["checks"]["K3"])
        self.assertTrue(s["checks"]["K4"])

    def test_graded_rules(self):
        recs = world()
        # same vehicle as L0, earlier in the plan's order: it replaces L0 in the graded set
        recs.append(rec(500, "ubx_f9p", 6, 400, vehicle="V0", si=0))
        # seen and unread logs never count
        recs.append(rec(501, "ubx_f9p", 6, 400, status="seen (f9p-extra)"))
        recs.append(rec(502, "ubx_f9p", 6, 400, status="http 404"))
        recs.append(rec(503, "ubx_f9p", None, 400))
        g = dm.graded(recs)
        ids = {r["log_id"] for r in g}
        self.assertIn("L500", ids)
        self.assertNotIn("L0", ids)
        self.assertFalse(ids & {"L501", "L502", "L503"})
        s = dm.summarise(recs)
        self.assertEqual(s["reported"]["read_without_dynmodel"], 1)
        self.assertEqual(s["reported"]["seen_f9p_2026"], {"6": {"n": 1, "median_lag_ms": 400.0}})

    def test_k3_groups(self):
        recs = [rec(0, "ubx_f9p", 6, 200, f5=True), rec(1, "ubx_f9p", 7, 120, f5=True),
                rec(2, "ubx_f9p", 7, 190, f5=True), rec(3, "ubx_f9p", 6, 160, f5=True),
                rec(4, "ubx_f9p", 8, 140, f5=True), rec(5, "ubx_f9p", 6, 210, f5=True, sample="f9p-2026"),
                rec(6, "ubx_f9p", 6, 210, f5=False)]
        t = dm.k3(recs)
        # L3 is between the groups, L5 is another sample, L6 does not qualify
        self.assertEqual((t["n"], t["n_dyn6"], t["agree"]), (4, 1, 3))
        self.assertEqual(t["table"], {"6": {"low": 0, "high": 1}, "7": {"low": 1, "high": 1},
                                      "8": {"low": 1, "high": 0}})

    def test_bootstrap_is_seeded(self):
        recs = world()
        for i, r in enumerate(recs):
            r["lag_ms"] += (i * 37) % 23
        a, b = dm.summarise(recs), dm.summarise(recs)
        self.assertEqual(a["K1_all_ublox"], b["K1_all_ublox"])
        self.assertEqual(a["K2_f9p"], b["K2_f9p"])


if __name__ == "__main__":
    unittest.main()
