"""paired: GPS lag on one vehicle flown with GPS_UBX_DYNMODEL 6 and 7 (studies/dynmodel-2026/PLAN-paired.md).

The logs are the ones a PX4 maintainer attached to PX4-Autopilot PR #24831 ("Use PX4 default <2g
ublox GNSS dynamic model also for multirotors", 2025-05-27) as logs_dynmodel.zip: similar
aggressive flights with the u-blox dynamic model at 6 (<1g) and at 7 (<2g). dynmodel-2026 found
model-6 logs later than model-7 logs across the public fleet; this asks the same question within
one vehicle, where vehicle type, airframe and release cannot differ.

    python paired.py run --zip logs_dynmodel.zip --work ulg/ --out paired-rows.jsonl
    python paired.py score --rows paired-rows.jsonl --out paired-summary.json

run: extracts every .ulg in the zip (and in zips inside it, one level), reads each log's initial
parameters and info, and measures its GPS lag with px4-gps-lag's gps_lag.py (read_log, measure).
No position is kept; the vehicle's sys_uuid is kept only as a 12-character hash.
score: the plan's checks.

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import statistics
import sys
import zipfile

__version__ = "0.1.0"

P1_MIN_MS = 30.0            # dynmodel-2026's K1 threshold
GPS_PARAMS = ("GPS_UBX_DYNMODEL", "EKF2_GPS_DELAY", "SENS_GPS0_DELAY", "GPS_UBX_MODE", "GPS_1_CONFIG")
LAG_KEYS = ("passed", "reason", "lag_ms", "se_ms", "param_gps_delay_ms", "lag_minus_param_ms", "gps_bus",
            "pairs", "r2", "excitation_m_s2", "duration_s", "gps_logged_dt_s", "grid_ms")


# ---------------------------------------------------------------- the zip

def extract_ulogs(zip_bytes, outdir, _depth=0, _start=0):
    """Writes every .ulg in the zip (and in zips inside it, one level down) to outdir as
    NNN_<basename>, never using the archive's own paths. Returns [(name in archive, path)]."""
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            low = name.lower()
            if low.endswith(".ulg"):
                base = os.path.basename(name.replace("\\", "/")) or "log.ulg"
                dest = os.path.join(outdir, "%03d_%s" % (_start + len(out), base))
                with z.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                out.append((name, dest))
            elif low.endswith(".zip") and _depth == 0:
                inner = extract_ulogs(z.read(info), outdir, 1, _start + len(out))
                out.extend((name + "/" + n, p) for n, p in inner)
    return out


# ---------------------------------------------------------------- one log

def decode_release(v):
    """ULog ver_sw_release (0xMMmmppTT) -> 'v1.16.0' plus the type byte (255 = release)."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None, None
    return "v%d.%d.%d" % ((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF), v & 0xFF


def vehicle_hash(info):
    key = info.get("sys_uuid") or "%s|%s" % (info.get("ver_hw"), info.get("sys_name"))
    return hashlib.sha256(str(key).encode()).hexdigest()[:12]


def _plain(x):
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if hasattr(x, "item"):
        return x.item()
    return str(x)


def read_meta(path):
    from pyulog import ULog
    u = ULog(path, ["vehicle_gps_position"], True)
    info = u.msg_info_dict
    rel, typ = decode_release(info.get("ver_sw_release"))
    params = {k: _plain(u.initial_parameters[k]) for k in GPS_PARAMS if k in u.initial_parameters}
    devtypes = []
    for d in u.data_list:
        if d.name == "vehicle_gps_position" and "device_id" in d.data:
            devtypes = sorted({(int(x) >> 16) & 0xFF for x in d.data["device_id"] if int(x)})
    return {"vehicle": vehicle_hash(info), "release": rel, "release_type": typ,
            "hw": info.get("ver_hw"), "params": params, "gps_devtypes": ["0x%02X" % t for t in devtypes]}


def measure(path):
    import gps_lag as gl
    r = gl.measure(gl.read_log(path))
    return {k: _plain(r.get(k)) for k in LAG_KEYS if k in r}


def run(zip_path, workdir, out_path, meta_fn=read_meta, lag_fn=measure):
    with open(zip_path, "rb") as f:
        data = f.read()
    os.makedirs(workdir, exist_ok=True)
    logs = extract_ulogs(data, workdir)
    rows = []
    for name, path in logs:
        row = {"file": os.path.basename(name.replace("\\", "/")), "size_mb": round(os.path.getsize(path) / 1e6, 2)}
        try:
            row.update(meta_fn(path))
        except Exception as exc:
            row["meta_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        try:
            row.update(lag_fn(path))
        except Exception as exc:
            row.update(passed=False, reason="error: %s: %s" % (type(exc).__name__, str(exc)[:200]))
        rows.append(row)
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return {"zip_sha256": hashlib.sha256(data).hexdigest(), "zip_bytes": len(data), "ulogs": len(rows)}


# ---------------------------------------------------------------- scoring

def dyn(row):
    v = (row.get("params") or {}).get("GPS_UBX_DYNMODEL")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def score(rows):
    """The plan's checks."""
    ok = [r for r in rows if r.get("passed") is True and r.get("lag_ms") is not None and dyn(r) is not None]
    by_v = {}
    for r in ok:
        by_v.setdefault(r.get("vehicle"), {}).setdefault(dyn(r), []).append(float(r["lag_ms"]))
    vehicles = {}
    for v, g in sorted(by_v.items(), key=lambda kv: str(kv[0])):
        if g.get(6) and g.get(7):
            a, b = sorted(g[6]), sorted(g[7])
            vehicles[v] = {"n6": len(a), "n7": len(b), "lags6_ms": a, "lags7_ms": b,
                           "median6_ms": round(statistics.median(a), 1), "median7_ms": round(statistics.median(b), 1),
                           "diff_ms": round(statistics.median(a) - statistics.median(b), 1),
                           "separated": (min(a) > max(b)) if (len(a) >= 2 and len(b) >= 2) else None}
    e0 = bool(vehicles)
    checks = {"E0": e0, "P1": None, "P2": None}
    diff = None
    if e0:
        diff = round(statistics.median([v["diff_ms"] for v in vehicles.values()]), 1)
        checks["P1"] = diff >= P1_MIN_MS
        seps = [v["separated"] for v in vehicles.values() if v["separated"] is not None]
        checks["P2"] = all(seps) if seps else None
    if not e0:
        decision = "not scored (E0 failed)"
    elif checks["P1"]:
        decision = "D1"
    elif diff < 10.0:
        decision = "D2"
    else:
        decision = "D3"
    return {"paired_py": __version__, "logs": len(rows), "passing_with_model": len(ok),
            "by_model": {str(k): sum(1 for r in rows if dyn(r) == k) for k in sorted({dyn(r) for r in rows if dyn(r) is not None})},
            "vehicles": vehicles, "median_within_vehicle_diff_ms": diff, "checks": checks, "decision": decision,
            "reported": {"note": "not pre-registered; descriptive only",
                         "per_log": [dict({k: r.get(k) for k in ("file", "vehicle", "release", "gps_devtypes", "passed",
                                                                 "reason", "lag_ms", "se_ms", "lag_minus_param_ms",
                                                                 "excitation_m_s2")}, dynmodel=dyn(r)) for r in rows]}}


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--zip", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("--rows", required=True)
    s.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        print(json.dumps(run(args.zip, args.work, args.out)), flush=True)
        return 0
    out = score(load_rows(args.rows))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
