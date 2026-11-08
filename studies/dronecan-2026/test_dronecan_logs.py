"""Tests for dronecan_logs.py on synthetic list entries, synthetic ULog bytes and fake downloads.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import io
import os
import struct
import tempfile
import unittest
import urllib.error

import dronecan_logs as dl
import gnss_logs as gn


def msg(t, body):
    return struct.pack("<HB", len(body), ord(t)) + body


def param_int(name, v):
    key = ("int32_t " + name).encode()
    return bytes([len(key)]) + key + struct.pack("<i", v)


def ulog_bytes(uavcan=2, data=b"\x07" * 5000):
    b = gn.MAGIC + b"\x01" + b"\x00" * 8
    b += msg("F", b"vehicle_gps_position:uint64_t timestamp;uint64_t timestamp_sample;float vel_n_m_s")
    b += msg("P", param_int("SENS_GPS0_DELAY", 110))
    if uavcan is not None:
        b += msg("P", param_int("UAVCAN_ENABLE", uavcan))
    b += msg("P", param_int("MC_AIRMODE", 1))
    b += msg("A", b"\x00\x00\x00vehicle_gps_position")
    return b + data


def entry(**kw):
    e = {"log_id": "a1", "log_date": "2026-10-20", "vehicle_uuid": "v1", "duration_s": 300,
         "mav_type": "Quadrotor", "sys_hw": "PX4_FMU_V6X", "ver_sw_release": "v1.18.0 128", "type": "personal"}
    e.update(kw)
    return e


class List(unittest.TestCase):
    def test_eligible(self):
        self.assertEqual(dl.eligible(entry()), ("pre", ""))
        self.assertEqual(dl.eligible(entry(ver_sw_release="")), ("unknown", ""))
        self.assertEqual(dl.eligible(entry(sys_hw="PX4_SITL"))[1], "simulation")
        self.assertEqual(dl.eligible(entry(source="CI"))[1], "CI")
        self.assertEqual(dl.eligible(entry(log_date="2026-06-29"))[1], "before 2026-06-30")
        self.assertEqual(dl.eligible(entry(log_date="2026-06-30"))[0], "pre")
        self.assertEqual(dl.eligible(entry(duration_s=59))[1], "shorter than 60 s")
        self.assertEqual(dl.eligible(entry(ver_sw_release="v1.17.0 255"))[1], "older than v1.18")

    def test_gnss_2026_vehicles_are_left_out(self):
        self.assertEqual(len(dl.EXCLUDED_VEHICLES), 11)
        real = entry(vehicle_uuid="some-vehicle")
        self.assertEqual(dl.eligible(real)[1], "")
        saved = dl.EXCLUDED_VEHICLES
        try:
            dl.EXCLUDED_VEHICLES = frozenset([gn.vehicle_hash("some-vehicle")])
            self.assertEqual(dl.eligible(real), (None, "read in gnss-2026"))
        finally:
            dl.EXCLUDED_VEHICLES = saved

    def test_order_newest_first(self):
        es = [entry(log_id="b", log_date="2026-10-01"),
              entry(log_id="c", log_date="2026-11-01"),
              entry(log_id="a", log_date="2026-11-01"),
              entry(log_id="old", log_date="2026-05-01")]
        cands, counts = dl.build(es)
        self.assertEqual([c["log_id"] for c in cands], ["a", "c", "b"])
        self.assertEqual(counts["excluded"], {"before 2026-06-30": 1})
        self.assertNotIn("vehicle_uuid", cands[0])


class Fetch(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "x.ulg")

    def test_uavcan_on_is_downloaded_whole(self):
        b = ulog_bytes(uavcan=2, data=b"\x07" * 200000)
        info, path = dl.fetch_one("a1", self.path, opener=lambda req, timeout: io.BytesIO(b))
        self.assertEqual(path, self.path)
        self.assertEqual(info["uavcan_enable"], 2)
        self.assertEqual(info["params"], {"SENS_GPS0_DELAY": 110, "UAVCAN_ENABLE": 2})
        self.assertTrue(info["has_gps_position"])
        self.assertFalse(info["has_gnss"])
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b)

    def test_uavcan_off_or_missing_is_not_downloaded(self):
        for v in (0, None):
            b = ulog_bytes(uavcan=v)
            info, path = dl.fetch_one("a1", self.path, opener=lambda req, timeout: io.BytesIO(b))
            self.assertIsNone(path)
            self.assertFalse(os.path.exists(self.path))

    def test_too_big(self):
        b = ulog_bytes(data=b"\x07" * 300000)
        info, path = dl.fetch_one("a1", self.path, opener=lambda req, timeout: io.BytesIO(b),
                                  max_bytes=100000)
        self.assertIsNone(path)
        self.assertTrue(info["too_big"])
        self.assertFalse(os.path.exists(self.path))


class Run(unittest.TestCase):
    def cands(self):
        return [{"log_id": "l%d" % i, "vehicle": "v%d" % (i // 2), "kind": "pre",
                 "ver_sw_release": "v1.18.0 128"} for i in range(8)]

    def test_one_log_per_vehicle_and_the_file_is_removed(self):
        tmp = os.path.join(tempfile.mkdtemp(), "g.ulg")

        def fetch(log_id, path):
            with open(path, "wb") as f:
                f.write(b"x")
            return {"params": {"UAVCAN_ENABLE": 3}}, path
        seen = []
        recs = []
        res = dl.run(self.cands(), fetch, lambda p: seen.append(os.path.exists(p)) or {"read": "ok"},
                     recs.append, tmp, sleep=lambda s: None)
        self.assertEqual([r["log_id"] for r in recs], ["l0", "l2", "l4", "l6"])
        self.assertEqual([r["status"] for r in recs], ["uavcan on"] * 4)
        self.assertEqual(seen, [True] * 4)
        self.assertFalse(os.path.exists(tmp))
        self.assertEqual(res, {"requested": 4, "downloaded": 4, "stop": "list exhausted"})

    def test_blocked_stops(self):
        def fetch(log_id, path):
            raise urllib.error.HTTPError("u", 429, "too many", {}, None)
        recs = []
        res = dl.run(self.cands(), fetch, None, recs.append, "unused", sleep=lambda s: None)
        self.assertEqual(len(recs), 1)
        self.assertEqual(res["stop"], "blocked: http 429")

    def test_limits(self):
        recs = []
        res = dl.run(self.cands(), lambda i, p: ({"params": {"UAVCAN_ENABLE": 0}}, None), None,
                     recs.append, "x", max_heads=2, sleep=lambda s: None)
        self.assertEqual(res["stop"], "max heads")
        self.assertEqual([r["status"] for r in recs], ["uavcan off", "uavcan off"])


def rec(vehicle, bus, applied, lag=None, passed=True, params=None):
    m = {"read": "ok", "gps_bus": bus, "stamp_minus_sample_ms": applied, "passed": passed,
         "reason": "ok" if passed else "too few in-flight GPS pairs"}
    if lag is not None:
        m["lag_ms"] = lag
    return {"vehicle": vehicle, "kind": "pre", "status": "uavcan on",
            "params": {"SENS_GNSS0_DELAY": 110} if params is None else params, "measure": m}


class Classes(unittest.TestCase):
    def test_self_stamped(self):
        self.assertFalse(dl.self_stamped(rec("a", "uavcan", 110.0)))
        self.assertFalse(dl.self_stamped(rec("a", "uavcan", 110.9)))
        self.assertTrue(dl.self_stamped(rec("a", "uavcan", 111.5)))
        self.assertTrue(dl.self_stamped(rec("a", "uavcan", 10.2)))
        # a set parameter counts, and so does the 110 ms default
        self.assertFalse(dl.self_stamped(rec("a", "uavcan", 50.3, params={"SENS_GPS1_DELAY": 50})))
        self.assertFalse(dl.self_stamped(rec("a", "uavcan", 110.0, params={"SENS_GPS0_DELAY": 50})))
        # unknown without a parameter or an applied delay
        self.assertIsNone(dl.self_stamped(rec("a", "uavcan", 10.0, params={})))
        self.assertIsNone(dl.self_stamped(rec("a", "uavcan", None)))

    def test_residual(self):
        self.assertAlmostEqual(dl.residual_ms(rec("a", "uavcan", 85.65, lag=166.3)), 80.65)


class Summary(unittest.TestCase):
    def test_all_hold(self):
        recs = [rec("d%d" % i, "uavcan", 20.0, lag=100.0 + i) for i in range(6)]   # residual 80-85
        recs += [rec("f%d" % i, "uavcan", 110.0, lag=120.0) for i in range(2)]      # fall back
        recs += [rec("s%d" % i, "serial", 110.0, lag=130.0) for i in range(5)]
        recs.append({"vehicle": "x", "kind": "pre", "status": "uavcan off"})
        s = dl.summarise(recs)
        self.assertEqual(s["predictions"], {"D1": True, "D2": True, "D3": True, "D4": True, "D5": True})
        r = s["reported"]
        self.assertEqual(r["dronecan_logs"], 8)
        self.assertEqual(r["dronecan_self_stamped"], "6 of 8")
        self.assertEqual(r["residual_median_ms"], 82.5)
        self.assertEqual(r["closer_to_110"], "6 of 6")
        self.assertEqual(r["dronecan_fallback_residual_ms"], [10.0, 10.0])
        self.assertEqual(r["serial_applied_matches"], "5 of 5")
        self.assertEqual(r["serial_residual_median_ms"], 20.0)
        self.assertEqual(r["buses"], {"serial": 5, "uavcan": 8})

    def test_a_few_ms_fails_d3_and_d4(self):
        # self-reported delay close to the measured lag, as PR #27427 expects
        recs = [rec("d%d" % i, "uavcan", 95.0, lag=98.0) for i in range(5)]
        s = dl.summarise(recs)["predictions"]
        self.assertFalse(s["D1"])          # 5 vehicles < 8
        self.assertTrue(s["D2"])
        self.assertFalse(s["D3"])          # residual 3 ms
        self.assertFalse(s["D4"])          # |98-110| = 12 > 3
        self.assertIsNone(s["D5"])         # no serial logs

    def test_too_few_to_grade(self):
        recs = [rec("d0", "uavcan", 20.0, lag=100.0), rec("d1", "uavcan", 20.0, passed=False),
                rec("d2", "uavcan", 110.0, lag=100.0), rec("s0", "serial", 60.0, lag=90.0)]
        s = dl.summarise(recs)
        p = s["predictions"]
        self.assertFalse(p["D1"])
        self.assertTrue(p["D2"])           # 2 of 3 self-stamped
        self.assertIsNone(p["D3"])
        self.assertIsNone(p["D4"])
        self.assertIsNone(p["D5"])
        self.assertEqual(s["reported"]["dronecan_self_stamped_passed"], 1)
        self.assertEqual(s["reported"]["fail_reasons_dronecan"], {"too few in-flight GPS pairs": 1})

    def test_serial_control_fails(self):
        recs = [rec("s%d" % i, "serial", 60.0 if i < 2 else 110.0, lag=120.0) for i in range(5)]
        self.assertFalse(dl.summarise(recs)["predictions"]["D5"])   # 3 of 5 match

    def test_nothing_found(self):
        s = dl.summarise([])["predictions"]
        self.assertEqual(s, {"D1": False, "D2": None, "D3": None, "D4": None, "D5": None})


if __name__ == "__main__":
    unittest.main()
