"""Tests for gps_lag.py 0.2.0's reading of PX4 main's vehicle_gnss topic (PX4 PR #24399), on the
synthetic flights of test_gps_lag.py, written as the topics pyulog would return.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import unittest
from unittest import mock

import numpy as np
import pyulog

import gps_lag as gl
from test_gps_lag import synth

DEVICE_ID = 0xAA0005     # u-blox F9P (device type 0xAA) on a serial bus (5)
DELAY_US = 110000


class _Data:
    def __init__(self, name, data, multi_id=0):
        self.name, self.data, self.multi_id = name, data, multi_id


def fake_ulog(topics, params=None, info=None):
    """A stand-in for pyulog.ULog that returns `topics` ({name: {field: array}})."""
    class FakeULog:
        def __init__(self, path, message_names=None, disable_str_exceptions=True):
            self.data_list = [_Data(n, d) for n, d in topics.items()
                              if message_names is None or n in message_names]
            self.initial_parameters = dict(params or {})
            self.msg_info_dict = dict(info or {})
    return FakeULog


def us(t):
    return np.round(np.asarray(t, dtype=float) * 1e6).astype(np.uint64)


def common(log):
    sc = {"timestamp": us(log["imu_t"])}
    for k in range(3):
        sc["accelerometer_m_s2[%d]" % k] = log["f_body"][:, k]
    att = {"timestamp": us(log["att_t"])}
    for k in range(4):
        att["q[%d]" % k] = log["q"][:, k]
    land = {"timestamp": us(log["land_t"]), "landed": log["landed"]}
    return {"sensor_combined": sc, "vehicle_attitude": att, "vehicle_land_detected": land}


def old_topics(log):
    n = len(log["gps_t"])
    t = us(log["gps_t"])
    out = common(log)
    out["vehicle_gps_position"] = {
        "timestamp": t, "timestamp_sample": t - np.uint64(DELAY_US),
        "device_id": np.full(n, DEVICE_ID, np.uint32), "fix_type": np.full(n, 3, np.uint8),
        "vel_n_m_s": log["vel_ne"][:, 0], "vel_e_m_s": log["vel_ne"][:, 1],
        "vel_ned_valid": np.ones(n, np.uint8)}
    return out


def gnss_topics(log, publish_us=2000):
    """PX4 main: vehicle_gnss, published by the sensors module `publish_us` after the receiver's
    sample, with the receiver's fields nested under 'receiver.' and the new velocity names."""
    n = len(log["gps_t"])
    t = us(log["gps_t"])
    out = common(log)
    out["vehicle_gnss"] = {
        "timestamp": t + np.uint64(publish_us), "timestamp_sample": t - np.uint64(DELAY_US),
        "receiver.timestamp": t, "receiver.timestamp_sample": t - np.uint64(DELAY_US),
        "receiver.device_id": np.full(n, DEVICE_ID, np.uint32),
        "receiver.fix_type": np.full(n, 3, np.uint8),
        "receiver.vel_north": log["vel_ne"][:, 0], "receiver.vel_east": log["vel_ne"][:, 1],
        "receiver.vel_down": np.zeros(n), "receiver.vel_ned_valid": np.ones(n, np.uint8),
        "usable": np.ones(n, np.uint8), "selected_instance": np.zeros(n, np.uint8)}
    return out


def read(topics, params=None):
    with mock.patch.object(pyulog, "ULog", fake_ulog(topics, params)):
        return gl.read_log("synthetic.ulg")


class Version(unittest.TestCase):
    def test_version_and_topics(self):
        self.assertEqual(gl.__version__, "0.2.0")
        self.assertIn("vehicle_gnss", gl.TOPICS)
        self.assertIn("vehicle_gps_position", gl.TOPICS)


class GnssAsGps(unittest.TestCase):
    def test_new_names_map_to_the_old_ones(self):
        g = gnss_topics(synth())["vehicle_gnss"]
        out = gl.gnss_as_gps(g)
        self.assertEqual(sorted(out), ["device_id", "fix_type", "timestamp", "timestamp_sample",
                                       "vel_e_m_s", "vel_n_m_s", "vel_ned_valid"])
        self.assertIs(out["timestamp"], g["receiver.timestamp"])       # the receiver's stamp, not the publish time
        self.assertIs(out["timestamp_sample"], g["timestamp_sample"])  # the delay-corrected time
        self.assertIs(out["vel_n_m_s"], g["receiver.vel_north"])
        self.assertIs(out["vel_e_m_s"], g["receiver.vel_east"])

    def test_fallbacks(self):
        g = {"timestamp": np.arange(3), "receiver.vel_n_m_s": np.zeros(3), "receiver.vel_e_m_s": np.ones(3),
             "receiver.fix_type": np.full(3, 3)}
        out = gl.gnss_as_gps(g)
        self.assertIs(out["timestamp"], g["timestamp"])
        self.assertIs(out["vel_n_m_s"], g["receiver.vel_n_m_s"])
        self.assertNotIn("timestamp_sample", out)
        self.assertNotIn("device_id", out)

    def test_a_missing_column_is_named(self):
        topics = gnss_topics(synth())
        del topics["vehicle_gnss"]["receiver.vel_north"]
        with self.assertRaises(ValueError) as cm:
            read(topics)
        self.assertIn("vel_n_m_s", str(cm.exception))


class ReadLog(unittest.TestCase):
    def test_same_flight_reads_the_same_from_either_topic(self):
        log = synth(delay_s=0.15)
        a = read(old_topics(log), {"EKF2_GPS_DELAY": 110.0})
        b = read(gnss_topics(log), {"SENS_GNSS0_DELAY": 110.0})
        for key in ("imu_t", "f_body", "att_t", "q", "gps_t", "vel_ne", "usable"):
            np.testing.assert_array_equal(a[key], b[key], err_msg=key)
        self.assertEqual(a["facts"]["stamp_minus_sample_ms"], 110.0)
        self.assertEqual(b["facts"]["stamp_minus_sample_ms"], 110.0)
        self.assertEqual(b["facts"]["gps_bus"], "serial")
        self.assertEqual(a["facts"]["param_gps_delay_ms"], 110.0)
        self.assertIsNone(b["facts"]["param_gps_delay_ms"])   # PX4 main has no EKF2_GPS_DELAY

    def test_the_old_topic_wins_when_both_are_there(self):
        log = synth(delay_s=0.15)
        topics = old_topics(log)
        g = gnss_topics(log)["vehicle_gnss"]
        g["receiver.vel_north"] = np.zeros(len(log["gps_t"]))
        topics["vehicle_gnss"] = g
        r = read(topics)
        np.testing.assert_array_equal(r["vel_ne"][:, 0], log["vel_ne"][:, 0])

    def test_no_gps_topic_at_all(self):
        topics = common(synth())
        with self.assertRaises(ValueError) as cm:
            read(topics)
        self.assertIn("no vehicle_gps_position in the log", str(cm.exception))

    def test_unusable_samples_stay_unusable(self):
        log = synth()
        topics = gnss_topics(log)
        topics["vehicle_gnss"]["receiver.fix_type"][:10] = 2
        topics["vehicle_gnss"]["receiver.vel_ned_valid"][10:20] = 0
        r = read(topics)
        self.assertEqual(int(np.sum(~r["usable"])), 20)


class Measure(unittest.TestCase):
    def test_recovers_the_delay_from_vehicle_gnss(self):
        r = gl.measure(read(gnss_topics(synth(delay_s=0.15)), {"SENS_GNSS0_DELAY": 110.0}))
        self.assertTrue(r["passed"], r)
        self.assertLess(abs(r["lag_s"] - 0.15), 0.003)
        self.assertNotIn("lag_minus_param_ms", r)

    def test_same_lag_from_either_topic(self):
        log = synth(delay_s=0.0625)
        a = gl.measure(read(old_topics(log)))
        b = gl.measure(read(gnss_topics(log)))
        self.assertTrue(a["passed"] and b["passed"])
        self.assertEqual(a["lag_ms"], b["lag_ms"])
        self.assertEqual(a["pairs"], b["pairs"])

    def test_the_publish_time_is_not_used(self):
        log = synth(delay_s=0.15)
        a = gl.measure(read(gnss_topics(log, publish_us=0)))
        b = gl.measure(read(gnss_topics(log, publish_us=40000)))
        self.assertEqual(a["lag_ms"], b["lag_ms"])


if __name__ == "__main__":
    unittest.main()
