"""Tests for paired.py (standard library only). By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import io
import json
import os
import tempfile
import unittest
import zipfile

import paired


def zbytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files:
            z.writestr(name, data)
    return buf.getvalue()


def row(vehicle, dyn, lag, passed=True):
    return {"vehicle": vehicle, "params": {"GPS_UBX_DYNMODEL": dyn}, "passed": passed, "lag_ms": lag}


class TestZip(unittest.TestCase):
    def test_extract_flat_nested_and_unsafe_names(self):
        inner = zbytes([("deep/c.ulg", b"C"), ("deeper.zip", zbytes([("d.ulg", b"D")]))])
        outer = zbytes([("logs/a.ulg", b"A"), ("../../evil/b.ULG", b"B"), ("notes.txt", b"x"),
                        ("more.zip", inner)])
        with tempfile.TemporaryDirectory() as d:
            got = paired.extract_ulogs(outer, d)
            names = [n for n, _ in got]
            self.assertEqual(names, ["logs/a.ulg", "../../evil/b.ULG", "more.zip/deep/c.ulg"])   # d.ulg: two levels down
            for _, p in got:
                self.assertEqual(os.path.dirname(p), d)   # never outside outdir
            self.assertEqual([open(p, "rb").read() for _, p in got], [b"A", b"B", b"C"])
            self.assertEqual(len(set(p for _, p in got)), 3)

    def test_run_records_errors(self):
        z = zbytes([("x.ulg", b"X"), ("y.ulg", b"Y")])

        def meta(path):
            if path.endswith("y.ulg"):
                raise ValueError("bad")
            return {"vehicle": "v", "params": {"GPS_UBX_DYNMODEL": 6}}

        def lag(path):
            return {"passed": True, "lag_ms": 150.0}

        with tempfile.TemporaryDirectory() as d:
            zp = os.path.join(d, "l.zip")
            with open(zp, "wb") as f:
                f.write(z)
            out = os.path.join(d, "rows.jsonl")
            info = paired.run(zp, os.path.join(d, "ulg"), out, meta, lag)
            self.assertEqual(info["ulogs"], 2)
            self.assertEqual(info["zip_bytes"], len(z))
            rows = [json.loads(line) for line in open(out)]
            self.assertEqual(rows[0]["vehicle"], "v")
            self.assertIn("meta_error", rows[1])
            self.assertEqual(rows[1]["lag_ms"], 150.0)


class TestMeta(unittest.TestCase):
    def test_release(self):
        self.assertEqual(paired.decode_release(0x011000FF), ("v1.16.0", 255))
        self.assertEqual(paired.decode_release(0x01100100), ("v1.16.1", 0))
        self.assertEqual(paired.decode_release(None), (None, None))

    def test_vehicle_hash(self):
        a = paired.vehicle_hash({"sys_uuid": "0001"})
        self.assertEqual(len(a), 12)
        self.assertEqual(a, paired.vehicle_hash({"sys_uuid": "0001", "ver_hw": "X"}))
        self.assertNotEqual(a, paired.vehicle_hash({"sys_uuid": "0002"}))
        self.assertEqual(paired.vehicle_hash({"ver_hw": "H", "sys_name": "PX4"}),
                         paired.vehicle_hash({"ver_hw": "H", "sys_name": "PX4"}))


class TestScore(unittest.TestCase):
    def test_holds(self):
        rows = [row("v", 6, 190.0), row("v", 6, 170.0), row("v", 7, 120.0), row("v", 7, 130.0), row("v", 8, 100.0),
                row("v", 6, 999.0, passed=False)]
        s = paired.score(rows)
        self.assertEqual(s["checks"], {"E0": True, "P1": True, "P2": True})
        self.assertEqual(s["median_within_vehicle_diff_ms"], 55.0)
        self.assertEqual(s["decision"], "D1")
        self.assertEqual(s["by_model"], {"6": 3, "7": 2, "8": 1})
        self.assertEqual(len(s["reported"]["per_log"]), 6)

    def test_small_difference_and_overlap(self):
        rows = [row("v", 6, 125.0), row("v", 6, 110.0), row("v", 7, 120.0), row("v", 7, 112.0)]
        s = paired.score(rows)
        self.assertEqual(s["median_within_vehicle_diff_ms"], 1.5)
        self.assertEqual(s["checks"], {"E0": True, "P1": False, "P2": False})
        self.assertEqual(s["decision"], "D2")

    def test_middle_and_p2_unscored(self):
        s = paired.score([row("v", 6, 140.0), row("v", 7, 120.0)])
        self.assertEqual(s["checks"], {"E0": True, "P1": False, "P2": None})
        self.assertEqual(s["decision"], "D3")

    def test_two_vehicles_median_of_diffs(self):
        rows = [row("a", 6, 150.0), row("a", 7, 100.0), row("b", 6, 110.0), row("b", 7, 100.0),
                row("c", 6, 300.0)]                       # c has no 7-log: not scored
        s = paired.score(rows)
        self.assertEqual(sorted(s["vehicles"]), ["a", "b"])
        self.assertEqual(s["median_within_vehicle_diff_ms"], 30.0)
        self.assertTrue(s["checks"]["P1"])

    def test_e0_fails(self):
        s = paired.score([row("a", 6, 150.0), row("b", 7, 100.0), row("a", 7, 90.0, passed=False)])
        self.assertEqual(s["checks"], {"E0": False, "P1": None, "P2": None})
        self.assertEqual(s["decision"], "not scored (E0 failed)")


if __name__ == "__main__":
    unittest.main()
