"""Tests for dronecan_ext.py on synthetic list entries, synthetic ULog bytes and fake downloads.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import io
import json
import os
import tempfile
import unittest

import dronecan_ext as de
import dronecan_logs as dl
import gnss_logs as gn
from test_dronecan_logs import entry, rec, ulog_bytes


def opener_for(b):
    return lambda req, timeout: io.BytesIO(b)


class FirstPass(unittest.TestCase):
    def test_vehicles_from_rows(self):
        lines = [json.dumps({"vehicle": "aa", "order": 1}) + "\n", "\n", json.dumps({"vehicle": "bb"}),
                 json.dumps({"order": 3})]
        self.assertEqual(de.first_pass_vehicles(lines), frozenset({"aa", "bb"}))

    def test_build_leaves_out_first_pass_vehicles(self):
        es = [entry(log_id="a", vehicle_uuid="u1", log_date="2026-11-08"),
              entry(log_id="b", vehicle_uuid="u2", log_date="2026-11-07"),
              entry(log_id="c", vehicle_uuid="u1", log_date="2026-11-01"),
              entry(log_id="d", vehicle_uuid="u3", log_date="2026-05-01")]
        cands, counts = de.build(es, frozenset({gn.vehicle_hash("u1")}))
        self.assertEqual([c["log_id"] for c in cands], ["b"])
        self.assertEqual(counts["excluded"], {"before 2026-06-30": 1, "read in the first pass": 2})
        self.assertEqual(counts["eligible"], 1)
        self.assertEqual(counts["by_kind"], {"pre": 1})

    def test_nothing_left_out(self):
        cands, counts = de.build([entry(log_id="a")], frozenset())
        self.assertEqual(len(cands), 1)
        self.assertNotIn("read in the first pass", counts["excluded"])


class Downloadable(unittest.TestCase):
    def test_px4_v1_only(self):
        self.assertTrue(de.downloadable({"ver_sw_release": "v1.18.0 128"}))
        self.assertTrue(de.downloadable({"ver_sw_release": "v1.19.0 0"}))
        self.assertTrue(de.downloadable({"ver_sw_release": "v1.50.0 0"}))
        self.assertFalse(de.downloadable({"ver_sw_release": "v6.9.4 192"}))
        self.assertFalse(de.downloadable({"ver_sw_release": "v2.0.3 128"}))
        self.assertFalse(de.downloadable({"ver_sw_release": "v1.17.0 255"}))
        self.assertFalse(de.downloadable({"ver_sw_release": ""}))
        self.assertFalse(de.downloadable({}))


class Fetch(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "x.ulg")
        self.b = ulog_bytes(uavcan=2, data=b"\x07" * 100000)

    def fetch(self, log_id, path):
        return dl.fetch_one(log_id, path, opener=opener_for(self.b))

    def test_download(self):
        info, path = de.fetch_ext("a", self.path, True, fetch=self.fetch)
        self.assertEqual(path, self.path)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), self.b)
        self.assertNotIn("not_downloaded", info)

    def test_head_only(self):
        info, path = de.fetch_ext("a", self.path, False, fetch=self.fetch)
        self.assertIsNone(path)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(info["uavcan_enable"], 2)
        self.assertEqual(info["not_downloaded"], "release not PX4 v1.x")
        # the reader's own rule is back in place afterwards
        self.assertTrue(dl.uavcan_on({"UAVCAN_ENABLE": 2}))
        self.assertFalse(dl.uavcan_on({"UAVCAN_ENABLE": 0}))

    def test_label(self):
        self.assertEqual(de.label({"status": "uavcan on", "not_downloaded": "x"})["status"], de.NOT_V1)
        self.assertEqual(de.label({"status": "uavcan off", "not_downloaded": "x"})["status"], "uavcan off")
        self.assertEqual(de.label({"status": "uavcan on"})["status"], "uavcan on")


class Run(unittest.TestCase):
    def test_v1_downloaded_others_head_only(self):
        b = ulog_bytes(uavcan=2, data=b"\x07" * 5000)
        cands = [{"log_id": "l0", "vehicle": "v0", "kind": "pre", "ver_sw_release": "v1.18.0 128"},
                 {"log_id": "l1", "vehicle": "v1", "kind": "pre", "ver_sw_release": "v6.9.4 192"},
                 {"log_id": "l2", "vehicle": "v2", "kind": "unknown", "ver_sw_release": ""},
                 {"log_id": "l3", "vehicle": "v0", "kind": "pre", "ver_sw_release": "v1.18.0 128"}]
        tmp = os.path.join(tempfile.mkdtemp(), "g.ulg")
        measured = []
        recs = []
        res = de.run_ext(cands, lambda i, p: dl.fetch_one(i, p, opener=opener_for(b)),
                         lambda p: measured.append(os.path.exists(p)) or {"read": "ok"},
                         recs.append, tmp, sleep=lambda s: None)
        self.assertEqual([r["log_id"] for r in recs], ["l0", "l1", "l2"])
        self.assertEqual([r["status"] for r in recs], ["uavcan on", de.NOT_V1, de.NOT_V1])
        self.assertEqual(measured, [True])
        self.assertIn("measure", recs[0])
        self.assertNotIn("measure", recs[1])
        self.assertEqual(res, {"requested": 3, "downloaded": 1, "stop": "list exhausted"})
        self.assertFalse(os.path.exists(tmp))


class Receivers(unittest.TestCase):
    def test_receivers_of(self):
        # 8748291 = 0x857D03: DroneCAN GNSS (0x85) at node 125; 0xA8000D: a serial u-blox (bus type 5)
        serial = (0xA8 << 16) | (0 << 8) | (1 << 3) | 5
        rx = de.receivers_of([(1, [serial, serial, 0]), (0, [0, 8748291, 8748291]), (2, [0, 0])])
        self.assertEqual(rx, [
            {"multi_id": 0, "device_id": 8748291, "devtype": "0x85", "bus": "uavcan"},
            {"multi_id": 1, "device_id": serial, "devtype": "0xA8", "bus": "serial"}])

    def test_measure_ext(self):
        m = de.measure_ext("p", measure=lambda p: {"read": "ok"},
                           receivers=lambda p: [{"bus": "uavcan"}])
        self.assertEqual(m, {"read": "ok", "sensor_gps": [{"bus": "uavcan"}]})

        def boom(p):
            raise ValueError("no sensor_gps")
        m = de.measure_ext("p", measure=lambda p: {"read": "ok"}, receivers=boom)
        self.assertEqual(m, {"read": "ok", "sensor_gps_error": "no sensor_gps"})


class Summary(unittest.TestCase):
    def test_graded_on_extension_only(self):
        first = [rec("d0", "uavcan", 20.0, lag=100.0)]
        ext = [rec("d%d" % i, "uavcan", 20.0, lag=100.0) for i in range(1, 6)]
        s = de.summarise_all(first, ext)
        self.assertEqual(s["graded_on"], "extension only")
        self.assertEqual(s["extension"]["predictions"],
                         {"D1": False, "D2": True, "D3": True, "D4": True, "D5": None})
        self.assertEqual(s["extension"]["reported"]["dronecan_self_stamped_passed"], 5)
        self.assertEqual(s["pooled_not_the_grade"]["reported"]["dronecan_self_stamped_passed"], 6)
        self.assertEqual(s["extension"]["reported"]["hidden_dronecan_not_graded"], [])

    def test_too_few_in_extension_stays_ungraded(self):
        first = [rec("d%d" % i, "uavcan", 20.0, lag=100.0) for i in range(4)]
        ext = [rec("e0", "uavcan", 20.0, lag=100.0)]
        s = de.summarise_all(first, ext)
        self.assertIsNone(s["extension"]["predictions"]["D3"])
        self.assertTrue(s["pooled_not_the_grade"]["predictions"]["D3"])

    def test_hidden_dronecan(self):
        r = rec("h", "unknown", 81.85, lag=120.7)
        r["order"] = 7
        r["sys_hw"] = "PX4_FMU_V6XRT"
        r["measure"]["sensor_gps"] = [{"bus": "uavcan"}, {"bus": "uavcan"}]
        mixed = rec("m", "unknown", 110.0, lag=125.9)
        mixed["measure"]["sensor_gps"] = [{"bus": "uavcan"}, {"bus": "serial"}]
        none = rec("n", "unknown", 110.0, lag=125.9)
        h = de.hidden_dronecan([r, mixed, none])
        self.assertEqual(h, [{"order": 7, "sys_hw": "PX4_FMU_V6XRT", "receivers": 2, "applied_ms": 81.85,
                              "lag_ms": 120.7, "passed": True, "reason": "ok"}])
        # hidden logs never enter the graded classes
        s = de.summarise_all([], [r])
        self.assertEqual(s["extension"]["reported"]["dronecan_logs"], 0)


if __name__ == "__main__":
    unittest.main()
