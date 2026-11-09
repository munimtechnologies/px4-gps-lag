"""Synthetic tests for nodefw.py (no network, no real log). By MV2 of Munim, Inc.; written with AI
agents. Apache-2.0."""

import io
import json
import tarfile
import unittest
import urllib.error

import nodefw as nf


def dc_row(order, applied, lag, passed=True, bus="uavcan", read="ok", params=None, dev=0x857D03, log_id=None):
    return {"order": order, "log_id": log_id or "log%d" % order, "vehicle": "v%d" % order, "sys_hw": "HW",
            "ver_sw_release": "v1.18.0", "params": {"SENS_GNSS0_DELAY": 110.0} if params is None else params,
            "measure": {"read": read, "gps_bus": bus, "stamp_minus_sample_ms": applied, "lag_ms": lag,
                        "passed": passed, "device_id": dev}}


def gnss_row(order, applied, lag, passed=True, bus="uavcan"):
    return {"order": order, "log_id": "g%d" % order, "vehicle": "g%d" % order, "sys_hw": "HW",
            "params": {"SENS_GNSS0_DELAY": 110.0, "SENS_GNSS1_DELAY": 110.0},
            "measure": {"read": "ok", "bus": bus, "device_id": 0x857D03, "receiver_minus_sample_ms": applied,
                        "gps_lag": {"lag_ms": lag, "passed": passed, "gps_bus": bus}}}


def chars(text, n):
    b = text.encode() + b"\0" * (n - len(text))
    return {"%d" % i: b[i] for i in range(n)}


def info_data(entries):
    """A pyulog-like data dict for device_information rows: (type, id, name, fw, hw)."""
    d = {"timestamp": [], "device_type": [], "device_id": []}
    for f, n in (("name", 80), ("firmware_version", 24), ("hardware_version", 24)):
        for i in range(n):
            d["%s[%d]" % (f, i)] = []
    for typ, dev, name, fw, hw in entries:
        d["timestamp"].append(1)
        d["device_type"].append(typ)
        d["device_id"].append(dev)
        for f, n, text in (("name", 80, name), ("firmware_version", 24, fw), ("hardware_version", 24, hw)):
            b = text.encode() + b"\0" * (n - len(text))
            for i in range(n):
                d["%s[%d]" % (f, i)].append(b[i])
    return d


class TestRows(unittest.TestCase):
    def test_norm_dronecan_self_stamped(self):
        r = nf.norm(dc_row(1, 10.2, 92.8), "extension")
        self.assertTrue(r["self_stamped"])
        self.assertTrue(r["short_self_report"])
        self.assertEqual(r["residual_ms"], 82.6)
        self.assertEqual(r["bus"], "uavcan")

    def test_norm_param_match_is_not_self_stamped(self):
        r = nf.norm(dc_row(1, 110.4, 150.0), "extension")
        self.assertFalse(r["self_stamped"])
        self.assertFalse(r["short_self_report"])
        r = nf.norm(dc_row(2, 60.0, 150.0, params={"SENS_GPS0_DELAY": 60.5}), "extension")
        self.assertFalse(r["self_stamped"])

    def test_norm_unknown_without_params(self):
        r = nf.norm(dc_row(1, 10.0, 90.0, params={}), "extension")
        self.assertIsNone(r["self_stamped"])
        self.assertFalse(r["short_self_report"])

    def test_norm_gnss_schema(self):
        r = nf.norm(gnss_row(176, 10.18, 92.8), "gnss-2026")
        self.assertEqual(r["applied_ms"], 10.18)
        self.assertEqual(r["lag_ms"], 92.8)
        self.assertTrue(r["passed"])
        self.assertTrue(r["self_stamped"])
        self.assertEqual(r["residual_ms"], 82.6)

    def test_norm_skips_unread(self):
        self.assertIsNone(nf.norm(dc_row(1, 10.0, 90.0, read="error: x"), "extension"))
        self.assertIsNone(nf.norm({"order": 3}, "first pass"))

    def test_select_keeps_dronecan_in_pass_order(self):
        lines = {"extension": [json.dumps(dc_row(2, 10, 90)), json.dumps(dc_row(1, 10, 90)),
                               json.dumps(dc_row(3, 110, 120, bus="serial")), ""],
                 "gnss-2026": [json.dumps(gnss_row(5, 85.65, 166.3))],
                 "first pass": [json.dumps(dc_row(9, 83.3, 155.3, read="error"))]}
        rows = nf.select(lines)
        self.assertEqual([(r["pass"], r["order"]) for r in rows],
                         [("gnss-2026", 5), ("extension", 1), ("extension", 2)])


class TestNames(unittest.TestCase):
    def _tar(self, files):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in files:
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        buf.seek(0)
        return buf

    def test_hwdef_names(self):
        buf = self._tar([
            ("ardupilot-master/libraries/AP_HAL_ChibiOS/hwdef/HerePro/hwdef.dat",
             b'# x\ndefine CAN_APP_NODE_NAME "com.Vendor.HerePro"\n'),
            ("ardupilot-master/libraries/AP_HAL_ChibiOS/hwdef/X/hwdef.inc",
             b'define CAN_APP_NODE_NAME "org.cuav.gps"\r\n'),
            ("ardupilot-master/Tools/AP_Periph/AP_Periph.h", b'#define CAN_APP_NODE_NAME "elsewhere"\n')])
        names, files = nf.hwdef_names(buf)
        self.assertEqual(names, {"com.vendor.herepro", "org.cuav.gps"})
        self.assertEqual(files, 2)

    def test_family(self):
        ap = {"org.cuav.gps"}
        self.assertEqual(nf.family("org.ardupilot.CubeOrange-periph", ap), "ap_periph")
        self.assertEqual(nf.family("ORG.CUAV.GPS", ap), "ap_periph")
        self.assertEqual(nf.family("io.px4.ark.gps", ap), "other")
        self.assertIsNone(nf.family("", ap))
        self.assertIsNone(nf.family(None, ap))


class TestDeviceInformation(unittest.TestCase):
    def test_text_field(self):
        d = info_data([(4, 1, "org.ardupilot.HereX", "1.4.123", "2.0")])
        self.assertEqual(nf.text_field(d, "name", 0), "org.ardupilot.HereX")
        self.assertEqual(nf.text_field(d, "firmware_version", 0), "1.4.123")
        self.assertEqual(nf.text_field({"name": [b"abc\0\0"]}, "name", 0), "abc")
        self.assertEqual(nf.text_field({}, "name", 0), "")

    def test_device_entries_dedup(self):
        d = info_data([(4, 0x857D03, "gps.a", "1.0.1", "1.0"), (2, 0x20001, "esc", "2.0.0", "1.0"),
                       (4, 0x857D03, "gps.a", "1.0.1", "1.0")])
        e = nf.device_entries(d)
        self.assertEqual(len(e), 2)
        g = [x for x in e if x["device_type"] == 4][0]
        self.assertEqual(g["samples"], 2)
        self.assertNotIn("serial_number", g)
        m = nf.merge_entries([e, e])
        self.assertEqual([x["samples"] for x in m if x["device_type"] == 4], [4])

    def test_match(self):
        e = nf.device_entries(info_data([(4, 0x857D03, "gps.a", "1", "1"), (4, 0x857E03, "gps.b", "1", "1"),
                                         (2, 0x20001, "esc", "1", "1")]))
        self.assertEqual(nf.match(0x857D03, e)[:2], ("gps.a", "device id"))
        self.assertEqual(nf.match(0x111, e)[:2], (None, "several GPS-type nodes"))
        one = nf.device_entries(info_data([(4, 0x999, "gps.c", "1", "1")]))
        self.assertEqual(nf.match(0x857D03, one)[:2], ("gps.c", "only GPS-type node"))
        self.assertEqual(nf.match(0x857D03, [])[:2], (None, "no device_information"))
        esc = nf.device_entries(info_data([(2, 0x20001, "esc", "1", "1")]))
        self.assertEqual(nf.match(0x857D03, esc)[:2], (None, "no GPS node named"))

    def test_receivers(self):
        rx = nf.receivers([("sensor_gps", 1, [0, 5, 5, 7]), ("sensor_gps", 0, [0, 0])])
        self.assertEqual(rx, [{"topic": "sensor_gps", "multi_id": 1, "device_id": 5}])


class TestRun(unittest.TestCase):
    def test_run_reads_and_stops_on_block(self):
        rows = [nf.norm(dc_row(i, 10, 90), "extension") for i in (1, 2, 3, 4)]
        written = []

        def fetch(log_id, path):
            if log_id == "log3":
                raise urllib.error.HTTPError("u", 429, "busy", {}, None)
            if log_id == "log2":
                return None
            return None if False else "nofile.ulg"

        res = nf.run(rows, fetch, lambda p: {"device_information": [], "receivers": []}, written.append,
                     "tmp.ulg", sleep=lambda s: None)
        self.assertEqual([w["status"] for w in written],
                         ["read", "too big", "http 429", "not requested: blocked: http 429"])
        self.assertEqual(res, {"requested": 3, "read": 1, "stop": "blocked: http 429"})

    def test_run_max_logs(self):
        rows = [nf.norm(dc_row(i, 10, 90), "extension") for i in (1, 2, 3)]
        written = []
        res = nf.run(rows, lambda a, b: None, None, written.append, "t", max_logs=2, sleep=lambda s: None)
        self.assertEqual([w["status"] for w in written], ["too big", "too big", "not requested: max logs"])
        self.assertEqual(res["stop"], "max logs")


def scored_row(order, applied, lag, name, fam, passed=True):
    r = nf.norm(dc_row(order, applied, lag, passed=passed), "extension")
    r.update({"status": "read", "node_name": name, "family": fam})
    return r


class TestScore(unittest.TestCase):
    def test_predictions_hold(self):
        rows = [scored_row(1, 10, 60, "org.ardupilot.a", "ap_periph"),     # short, residual 50
                scored_row(2, 12, 72, "org.ardupilot.a", "ap_periph"),     # short, residual 60
                scored_row(3, 9, 79, "x.other", "other"),                  # short, residual 70
                scored_row(4, 85, 95, "x.other", "other"),                 # residual 10
                scored_row(5, 90, 105, "x.other", "other"),                # residual 15
                scored_row(6, 80, 150, "org.ardupilot.b", "ap_periph"),    # residual 70
                scored_row(7, 110.2, 150, None, None)]                     # matches 110: not self-stamped
        s = nf.score(rows)
        p = s["predictions"]
        self.assertTrue(p["N1"])      # 6 of 7 named
        self.assertTrue(p["N2"])      # short residuals 50, 60, 70 -> median 60 > 40
        self.assertTrue(p["N3"])      # 2 of 3 short named are ap_periph
        self.assertTrue(p["N4"])      # ap 50, 60, 70 (median 60) vs other 70, 10, 15 (median 15): 45 >= 20
        self.assertEqual(s["reported"]["short_self_reports_passed"], 3)
        self.assertEqual(s["reported"]["ap_periph_residuals_ms"], [50.0, 60.0, 70.0])

    def test_not_graded_below_minimum(self):
        rows = [scored_row(1, 10, 30, "a", "other"), scored_row(2, 85, 95, None, None)]
        p = nf.score(rows)["predictions"]
        self.assertFalse(p["N1"])     # 1 of 2 named < 60%
        self.assertIsNone(p["N2"])
        self.assertIsNone(p["N3"])
        self.assertIsNone(p["N4"])

    def test_n2_fails_on_small_residuals(self):
        rows = [scored_row(i, 10, 30, "a", "other") for i in (1, 2, 3)]
        self.assertFalse(nf.score(rows)["predictions"]["N2"])

    def test_failed_gate_not_counted(self):
        rows = [scored_row(i, 10, 90, "a", "other", passed=False) for i in (1, 2, 3)]
        self.assertIsNone(nf.score(rows)["predictions"]["N2"])

    def test_summarise_grades_extension_only(self):
        early = scored_row(1, 10, 90, "org.ardupilot.a", "ap_periph")
        early["pass"] = "gnss-2026"
        s = nf.summarise([early], {"files": 0})
        self.assertIsNone(s["extension"]["predictions"]["N1"])
        self.assertEqual(s["earlier_passes_not_graded"]["reported"]["self_stamped_passed"], 1)
        json.dumps(s)

    def test_annotate(self):
        r = nf.norm(dc_row(1, 10, 90), "extension")
        r["status"] = "read"
        r["device_information"] = nf.device_entries(info_data([(4, 0x857D03, "org.ardupilot.HereX", "1.2.3", "1.0")]))
        r = nf.annotate(r, set())
        self.assertEqual((r["node_name"], r["family"], r["firmware_version"], r["match"]),
                         ("org.ardupilot.HereX", "ap_periph", "1.2.3", "device id"))
        self.assertNotIn("device_information", r)
        self.assertEqual(r["gps_type_nodes"], ["org.ardupilot.HereX"])
        u = nf.annotate({"status": "too big", "device_id": 1}, set())
        self.assertIsNone(u["family"])


if __name__ == "__main__":
    unittest.main()
