"""Tests for gnss_logs.py on synthetic list entries, synthetic ULog bytes and fake downloads.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import io
import os
import struct
import tempfile
import unittest
import urllib.error

import gnss_logs as gn


def msg(t, body):
    return struct.pack("<HB", len(body), ord(t)) + body


def param_float(name, v):
    key = ("float " + name).encode()
    return bytes([len(key)]) + key + struct.pack("<f", v)


def ulog_bytes(gnss=True, data=b"\x07" * 5000):
    b = gn.MAGIC + b"\x01" + b"\x00" * 8
    b += msg("B", b"\x00" * 40)
    b += msg("F", b"sensor_gnss:uint64_t timestamp;float vel_north")
    if gnss:
        b += msg("F", b"vehicle_gnss:uint64_t timestamp;uint64_t timestamp_sample;sensor_gnss receiver")
    else:
        b += msg("F", b"vehicle_gps_position:uint64_t timestamp;float vel_n_m_s")
    b += msg("P", param_float("SENS_GNSS0_DELAY", 110.0))
    b += msg("P", param_float("MC_ROLL_P", 6.5))
    b += msg("A", b"\x00\x00\x00vehicle_gnss")
    return b + data


def entry(**kw):
    e = {"log_id": "a1", "log_date": "2026-10-20", "vehicle_uuid": "v1", "duration_s": 300,
         "mav_type": "Quadrotor", "sys_hw": "PX4_FMU_V6X", "ver_sw_release": "v1.18.0 (0)", "type": "personal"}
    e.update(kw)
    return e


class List(unittest.TestCase):
    def test_release_series(self):
        self.assertEqual(gn.release_series("v1.18.0 (0)"), ((1, 18), "dev"))
        self.assertEqual(gn.release_series("v1.19.0 (1)"), ((1, 19), "pre"))
        self.assertEqual(gn.release_series("v1.18.1 (255)"), ((1, 18), "release"))
        self.assertIsNone(gn.release_series(""))

    def test_eligible(self):
        self.assertEqual(gn.eligible(entry()), ("dev", ""))
        self.assertEqual(gn.eligible(entry(ver_sw_release="")), ("unknown", ""))
        self.assertEqual(gn.eligible(entry(sys_hw="PX4_SITL"))[1], "simulation")
        self.assertEqual(gn.eligible(entry(source="CI"))[1], "CI")
        self.assertEqual(gn.eligible(entry(log_date="2026-09-28"))[1], "before 2026-09-29")
        self.assertEqual(gn.eligible(entry(log_date="2026-09-29"))[0], "dev")
        self.assertEqual(gn.eligible(entry(duration_s=59))[1], "shorter than 60 s")
        self.assertEqual(gn.eligible(entry(ver_sw_release="v1.17.0 (255)"))[1], "older than v1.18")

    def test_order(self):
        es = [entry(log_id="r", ver_sw_release="v1.18.0 (255)", log_date="2026-11-05"),
              entry(log_id="d_old", log_date="2026-10-01"),
              entry(log_id="d_new", log_date="2026-11-01"),
              entry(log_id="p", ver_sw_release="v1.19.0 (1)", log_date="2026-11-06"),
              entry(log_id="u", ver_sw_release="", log_date="2026-11-07"),
              entry(log_id="old", ver_sw_release="v1.16.0 (255)")]
        cands, counts = gn.build(es)
        self.assertEqual([c["log_id"] for c in cands], ["d_new", "d_old", "p", "u", "r"])
        self.assertEqual(counts["eligible"], 5)
        self.assertEqual(counts["excluded"], {"older than v1.18": 1})
        self.assertEqual(cands[0]["vehicle"], gn.vehicle_hash("v1"))
        self.assertNotIn("vehicle_uuid", cands[0])


class Definitions(unittest.TestCase):
    def test_formats_and_params(self):
        formats, params, raw, complete = gn.read_definitions(iter([ulog_bytes()]))
        self.assertTrue(complete)
        self.assertIn("vehicle_gnss", formats)
        self.assertEqual(formats["sensor_gnss"], "uint64_t timestamp;float vel_north")
        self.assertEqual(params, {"SENS_GNSS0_DELAY": 110.0, "MC_ROLL_P": 6.5})
        self.assertEqual(gn.pick(params), {"SENS_GNSS0_DELAY": 110.0})

    def test_small_chunks_give_the_same(self):
        b = ulog_bytes()
        a = gn.read_definitions(iter([b]))
        chunks = iter([b[i:i + 5] for i in range(0, len(b), 5)])
        c = gn.read_definitions(chunks)
        self.assertEqual(a[:2], c[:2])
        self.assertTrue(c[3])
        rest = b"".join(chunks)
        self.assertEqual(bytes(c[2]) + rest, b)   # nothing taken from the stream is lost

    def test_not_a_ulog(self):
        with self.assertRaises(ValueError):
            gn.read_definitions(iter([b"<html>" + b"x" * 40]))

    def test_cut_short(self):
        b = ulog_bytes()
        formats, params, raw, complete = gn.read_definitions(iter([b[:60]]))
        self.assertFalse(complete)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "x.ulg")

    def test_a_main_log_is_written_whole(self):
        b = ulog_bytes(data=b"\x07" * 200000)
        info, path = gn.fetch_one("a1", self.path, opener=lambda req, timeout: io.BytesIO(b))
        self.assertEqual(path, self.path)
        self.assertTrue(info["has_gnss"] and info["head_complete"])
        self.assertEqual(info["bytes"], len(b))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b)

    def test_an_older_log_is_not_downloaded(self):
        b = ulog_bytes(gnss=False)
        info, path = gn.fetch_one("a1", self.path, opener=lambda req, timeout: io.BytesIO(b))
        self.assertIsNone(path)
        self.assertFalse(info["has_gnss"])
        self.assertTrue(info["has_gps_position"])
        self.assertFalse(os.path.exists(self.path))

    def test_too_big(self):
        b = ulog_bytes(data=b"\x07" * 300000)
        info, path = gn.fetch_one("a1", self.path, opener=lambda req, timeout: io.BytesIO(b),
                                  max_bytes=100000)
        self.assertIsNone(path)
        self.assertTrue(info["too_big"])
        self.assertFalse(os.path.exists(self.path))


class Plan(unittest.TestCase):
    def test_wait(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "PLAN.md")
        with open(p, "wb") as f:
            f.write(b"plan\nline two\n")
        self.assertTrue(gn.wait_for_plan(p, lambda: b"plan\r\nline two\r\n", 60, sleep=lambda s: None))
        t = [0.0]

        def clock():
            t[0] += 100
            return t[0]
        self.assertFalse(gn.wait_for_plan(p, lambda: b"other", 250, sleep=lambda s: None, clock=clock))


class Run(unittest.TestCase):
    def cands(self):
        return [{"log_id": "l%d" % i, "vehicle": "v%d" % (i // 2), "kind": "dev",
                 "ver_sw_release": "v1.18.0 (0)"} for i in range(8)]

    def test_one_log_per_vehicle_and_the_file_is_removed(self):
        tmp = os.path.join(tempfile.mkdtemp(), "g.ulg")

        def fetch(log_id, path):
            with open(path, "wb") as f:
                f.write(b"x")
            return {"has_gnss": True}, path
        seen = []
        recs = []
        res = gn.run(self.cands(), fetch, lambda p: seen.append(os.path.exists(p)) or {"read": "ok"},
                     recs.append, tmp, sleep=lambda s: None)
        self.assertEqual([r["log_id"] for r in recs], ["l0", "l2", "l4", "l6"])
        self.assertEqual(seen, [True] * 4)
        self.assertFalse(os.path.exists(tmp))
        self.assertEqual(res, {"requested": 4, "main_logs_read": 4, "stop": "list exhausted"})

    def test_blocked_stops(self):
        def fetch(log_id, path):
            raise urllib.error.HTTPError("u", 429, "too many", {}, None)
        recs = []
        res = gn.run(self.cands(), fetch, None, recs.append, "unused", sleep=lambda s: None)
        self.assertEqual(len(recs), 1)
        self.assertEqual(res["stop"], "blocked: http 429")

    def test_limits(self):
        recs = []
        res = gn.run(self.cands(), lambda i, p: ({"has_gnss": False}, None), None, recs.append, "x",
                     max_heads=2, sleep=lambda s: None)
        self.assertEqual(res["stop"], "max heads")
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["status"], "no vehicle_gnss")


def main_rec(vehicle, lag, applied=110.0, columns=None, passed=True):
    return {"vehicle": vehicle, "has_gnss": True, "kind": "dev", "status": "main log",
            "params": {"SENS_GNSS0_DELAY": 110.0},
            "measure": {"gnss_samples": 100, "read": "ok", "columns": columns or dict(gn.FIRST_CHOICE),
                        "receiver_minus_sample_ms": applied, "publish_minus_receiver_ms": 1.0,
                        "gps_lag": {"passed": passed, "lag_ms": lag, "reason": "" if passed else "too few"}}}


class Summary(unittest.TestCase):
    def test_all_hold(self):
        recs = [main_rec("a", 120), main_rec("b", 100), main_rec("c", 130), main_rec("d", 90),
                main_rec("e", 115), {"vehicle": "f", "has_gnss": False, "status": "no vehicle_gnss", "kind": "release"}]
        s = gn.summarise(recs)
        self.assertEqual(s["predictions"], {"P1": True, "P2": True, "P3": True, "P4": True, "P5": True})
        self.assertEqual(s["reported"]["lag_minus_applied_median_ms"], 5.0)
        self.assertEqual(s["reported"]["applied_matches_param"], "5 of 5")

    def test_failures(self):
        cols = dict(gn.FIRST_CHOICE, vel_n_m_s="receiver.vel_n_m_s")
        recs = [main_rec("a", 300, columns=cols), main_rec("a", 120, applied=140.0),
                main_rec("b", 100, passed=False)]
        s = gn.summarise(recs)["predictions"]
        self.assertFalse(s["P1"])          # 3 logs, 2 vehicles
        self.assertFalse(s["P2"])
        self.assertFalse(s["P3"])          # 2 of 3 match the parameter
        self.assertFalse(s["P4"])          # 2 passed
        self.assertIsNone(s["P5"])         # fewer than 5 passed

    def test_nothing_found(self):
        s = gn.summarise([])["predictions"]
        self.assertEqual(s, {"P1": False, "P2": None, "P3": None, "P4": False, "P5": None})


if __name__ == "__main__":
    unittest.main()
