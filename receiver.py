"""receiver.py: does a PX4 vehicle's GPS lag depend on its receiver model?
Scores studies/receiver-2026/PLAN.md.

PX4's GPS driver records the receiver it found in the device type byte of the
GPS device_id (src/drivers/gps/gps.cpp sets DRV_GPS_DEVTYPE_UBX_8 for a
u-blox M8, _UBX_9 for M9, _UBX_F9P for F9P, ...; values in
src/drivers/drv_sensor.h; byte layout in src/lib/drivers/device/Device.hpp:
bus type 3 bits, bus 5 bits, address 8 bits, devtype 8 bits). ArduPilot
assumes 120 ms for u-blox 7/M8 ("based on flight logs") and the same 120 ms
for F9/M9/M10 ("F9 lag not verified yet from flight log",
libraries/AP_GPS/AP_GPS_UBLOX.cpp, get_lag). PX4 uses one EKF2_GPS_DELAY,
110 ms by default. This measures the lag (gps_lag.py) on a fresh random
sample of Flight Review's public logs, reads each log's receiver, and
compares the receiver classes.

    python receiver.py --out-dir out --exclude a.jsonl b.jsonl --budget-min 130 --max-logs 700
    python receiver.py --out-dir out --rescore logs.jsonl

Uses fleet.py (px4-gps-lag 0.1.1) for the public log list, the eligibility
rules and the download (stop on 403/444). One log per vehicle, leaving out
every log and vehicle an earlier study drew; 6 s between downloads; each log
is deleted once measured. No position is read. Vehicle ids are published only
as a hash.

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import time

import numpy as np
import requests

import fleet
import gps_lag as gl

__version__ = "0.1.0"

SEED = 20261101
DELAY_S = 6.0
DEFAULT_DELAY_MS = 110.0
OFF_MS = 50.0
E1_MIN = 25             # passed logs a u-blox class needs for E1
MIN_CLASS = 15          # passed logs a class needs to enter a comparison
BOOT = 2000
UBLOX = ("ubx_m8", "ubx_m9", "ubx_f9p", "ubx_10", "ubx_generic")

# src/drivers/drv_sensor.h (v1.15.4 and main)
DEVTYPES = {0xA0: "ashtech", 0xA1: "emlid_reach", 0xA2: "femtomes", 0xA3: "mtk", 0xA4: "sbf",
            0xA5: "ubx_generic", 0xA6: "ubx_6", 0xA7: "ubx_7", 0xA8: "ubx_m8", 0xA9: "ubx_m9",
            0xAA: "ubx_f9p", 0xAB: "nmea", 0xAC: "ubx_10", 0xAD: "ubx_x20", 0xAF: "simulation",
            0x85: "uavcan"}
LAG_KEYS = ("passed", "reason", "lag_ms", "se_ms", "param_gps_delay_ms", "lag_minus_param_ms",
            "gps_bus", "ver_sw_release", "gps_logged_dt_s", "stamp_minus_sample_ms", "pairs", "r2",
            "excitation_m_s2")


def devtype(device_id):
    """The device type byte of a PX4 device_id."""
    return (int(device_id) >> 16) & 0xFF


def receiver_class(device_id):
    """'ubx_m8', 'ubx_f9p', 'uavcan', ... for a GPS device_id; 'unknown' for 0."""
    if not device_id:
        return "unknown"
    bus = gl.bus_type(device_id)
    if bus == "uavcan":
        return "uavcan"
    if bus == "simulation":
        return "simulation"
    name = DEVTYPES.get(devtype(device_id))
    if name and bus == "serial":
        return name
    return "other:%s/0x%02X" % (bus, devtype(device_id))


def _usual_id(d):
    """The most common non-zero device_id of a topic, or 0."""
    if d is None or "device_id" not in d or len(d["device_id"]) == 0:
        return 0
    ids = np.asarray(d["device_id"]).astype(np.int64)
    ids = ids[ids != 0]
    if len(ids) == 0:
        return 0
    values, counts = np.unique(ids, return_counts=True)
    return int(values[int(np.argmax(counts))])


def receiver_facts(vgp, sensors):
    """Which receiver fed vehicle_gps_position: its own device_id if set,
    else the only sensor_gps instance with one. Several receivers with no
    selected id (PX4 clears it when blending) give 'multiple'."""
    sensor_ids = sorted({i for i in (_usual_id(d) for d in sensors.values()) if i})
    vid = _usual_id(vgp)
    if vid:
        source, did = "vehicle_gps_position", vid
    elif len(sensor_ids) == 1:
        source, did = "sensor_gps", sensor_ids[0]
    elif len(sensor_ids) > 1:
        source, did = "several sensor_gps", 0
    else:
        source, did = "none", 0
    cls = receiver_class(did) if did else ("multiple" if len(sensor_ids) > 1 else "unknown")
    fixes = None
    if vgp is not None and "fix_type" in vgp and len(vgp["fix_type"]):
        fixes = int(np.max(np.asarray(vgp["fix_type"]).astype(int)))
    return {"receiver": cls, "receiver_source": source, "gps_device_id": did,
            "receivers": len(sensor_ids), "receiver_classes": [receiver_class(i) for i in sensor_ids],
            "fix_type_max": fixes}


def read_receiver(path):
    from pyulog import ULog
    ulog = ULog(path, ["vehicle_gps_position", "sensor_gps"], True)
    vgp, sensors = None, {}
    for d in ulog.data_list:
        if d.name == "vehicle_gps_position" and d.multi_id == 0:
            vgp = d.data
        elif d.name == "sensor_gps":
            sensors[d.multi_id] = d.data
    return receiver_facts(vgp, sensors)


def excluded(paths):
    """Log ids and hashed vehicle ids that earlier studies drew."""
    logs, vehicles = set(), set()
    for path in paths or ():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    logs.add(str(r.get("log_id")))
                    if r.get("vehicle"):
                        vehicles.add(r["vehicle"])
    return logs, vehicles


def draw(candidates, skip_logs, skip_vehicles, seed=SEED):
    """One log per vehicle, vehicles in a seeded random order, nothing from
    skip_logs or skip_vehicles."""
    keep = [c for c in candidates
            if c["log_id"] not in skip_logs and (not c["vehicle"] or c["vehicle"] not in skip_vehicles)]
    order, by_vehicle = fleet.plan_order(keep, seed=seed)
    return [by_vehicle[key][0] for key in order]


def _median(xs):
    xs = [float(x) for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def _pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def boot_diff(a, b, n=BOOT, seed=SEED):
    """median(a) - median(b) with a seeded bootstrap 95% interval."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        ra = [a[rng.randrange(len(a))] for _ in a]
        rb = [b[rng.randrange(len(b))] for _ in b]
        diffs.append(statistics.median(ra) - statistics.median(rb))
    return {"diff_ms": round(statistics.median(a) - statistics.median(b), 1),
            "ci95_ms": [round(_pct(diffs, 0.025), 1), round(_pct(diffs, 0.975), 1)]}


def _excludes_zero(ci):
    return ci[0] > 0 or ci[1] < 0


def within_share(rows, delay_of):
    """Share of rows whose lag is within 50 ms of delay_of(row)."""
    return sum(abs(float(r["lag_ms"]) - delay_of(r)) <= OFF_MS for r in rows) / len(rows) if rows else None


def summarise(rows):
    """The PLAN's checks, from the per-log rows."""
    passed = [r for r in rows if r.get("passed") and r.get("receiver") != "simulation"]
    by = {}
    for r in passed:
        by.setdefault(r.get("receiver") or "unknown", []).append(float(r["lag_ms"]))
    classes = {k: {"n": len(v), "median_lag_ms": _median(v),
                   "p25": round(_pct(sorted(v), 0.25), 1), "p75": round(_pct(sorted(v), 0.75), 1)}
               for k, v in sorted(by.items())}
    big = sorted(k for k, v in by.items() if len(v) >= MIN_CLASS and k not in ("unknown", "multiple")
                 and not k.startswith("other:"))
    models = [k for k in big if k != "uavcan"]     # serial receivers whose model PX4 detected
    known = [r for r in passed if r.get("receiver") not in ("unknown", "multiple")]

    def lags(k):
        return by.get(k, [])

    m8, f9p = lags("ubx_m8"), lags("ubx_f9p")
    serial = [float(r["lag_ms"]) for r in passed if r.get("receiver") in DEVTYPES.values()
              and r.get("receiver") not in ("uavcan", "simulation")]
    uavcan = lags("uavcan")

    p2 = boot_diff(f9p, m8) if len(f9p) >= MIN_CLASS and len(m8) >= MIN_CLASS else None
    spread = None
    if len(models) >= 2:
        meds = {k: statistics.median(by[k]) for k in models}
        hi, lo = max(models, key=lambda k: meds[k]), min(models, key=lambda k: meds[k])
        spread = dict(boot_diff(by[hi], by[lo]), high=hi, low=lo)
    p5 = boot_diff(uavcan, serial) if len(uavcan) >= MIN_CLASS and len(serial) >= MIN_CLASS else None

    p4 = None
    pool = [r for r in passed if r.get("receiver") in big]
    if pool:
        def loo(r):
            others = list(by[r["receiver"]])
            others.remove(float(r["lag_ms"]))
            return statistics.median(others)
        p4 = {"n": len(pool), "within_50_at_110": round(within_share(pool, lambda r: DEFAULT_DELAY_MS), 4),
              "within_50_at_class_median": round(within_share(pool, loo), 4)}
        p4["gain"] = round(p4["within_50_at_class_median"] - p4["within_50_at_110"], 4)

    e1 = sum(len(lags(k)) >= E1_MIN for k in UBLOX) >= 2
    checks = {
        "E1": e1,
        "P1": (80 <= statistics.median(m8) <= 160) if len(m8) >= MIN_CLASS else None,
        "P2": (p2["diff_ms"] <= 0) if p2 else None,
        "P3": (spread["diff_ms"] >= 20 and _excludes_zero(spread["ci95_ms"])) if spread else None,
        "P4": (p4["gain"] >= 0.05) if p4 else None,
        "P5": (p5["diff_ms"] < 0) if p5 else None,
        "P6": (len(known) / len(passed) >= 0.70) if passed else None,
    }
    checks = {k: (None if v is None else bool(v)) for k, v in checks.items()}
    reasons = {}
    for r in rows:
        if not r.get("passed"):
            reasons[r.get("reason") or "?"] = reasons.get(r.get("reason") or "?", 0) + 1
    return {
        "attempted": len(rows),
        "downloaded": sum(r.get("download") == "ok" for r in rows),
        "passed": len(passed),
        "known_receiver": len(known),
        "classes": classes,
        "compared_classes": big,
        "compared_models": models,
        "P2_f9p_minus_m8": p2,
        "P3_largest_gap": spread,
        "P4_class_default": p4,
        "P5_uavcan_minus_serial": p5,
        "receiver_source": {s: sum(r.get("receiver_source") == s for r in passed)
                            for s in sorted({r.get("receiver_source") for r in passed if r.get("receiver_source")})},
        "not_passed_reasons": reasons,
        "checks": checks,
        "decision": {"D1_class_note_in_checkup": bool(checks["E1"] and checks["P3"])},
    }


def _major(r):
    name = r.get("ver_sw_release") or ""
    parts = name.lstrip("v").split(".")
    return "v%s.%s" % (parts[0], parts[1]) if len(parts) >= 2 and name.startswith("v") else "unknown"


def explore(rows):
    """Breakdowns the PLAN did not predict, labelled exploratory."""
    passed = [r for r in rows if r.get("passed") and r.get("receiver") != "simulation"]

    def groups(key):
        out = {}
        for r in passed:
            out.setdefault(key(r), []).append(float(r["lag_ms"]))
        return {k: {"n": len(v), "median_lag_ms": _median(v)} for k, v in sorted(out.items())}
    return {
        "note": "not pre-registered; descriptive only",
        "by_receiver_and_release": groups(lambda r: "%s %s" % (r.get("receiver"), _major(r))),
        "by_receiver_and_fix": groups(lambda r: "%s fix<=%s" % (r.get("receiver"), r.get("fix_type_max"))),
        "by_receiver_count": groups(lambda r: "%s receiver(s)" % r.get("receivers")),
        "by_receiver_and_logged_interval": groups(
            lambda r: "%s %s" % (r.get("receiver"), "unknown" if r.get("gps_logged_dt_s") is None
                                 else ("<=0.15 s" if r["gps_logged_dt_s"] <= 0.15 else ">0.15 s"))),
        "param_by_receiver": groups(lambda r: "%s param %s" % (r.get("receiver"), r.get("param_gps_delay_ms"))),
        "stamp_minus_sample_by_receiver": {
            k: _median([r.get("stamp_minus_sample_ms") for r in passed if r.get("receiver") == k])
            for k in sorted({r.get("receiver") for r in passed})},
    }


def score(rows, out_dir, extra):
    summary = summarise(rows)
    summary["exploratory"] = explore(rows)
    summary.update({"receiver_py": __version__, "gps_lag": gl.__version__, "fleet": fleet.__version__,
                    "seed": SEED}, **extra)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True)
    p.add_argument("--exclude", nargs="*", default=[])
    p.add_argument("--budget-min", type=float, default=130)
    p.add_argument("--max-logs", type=int, default=700)
    p.add_argument("--tmp", default="/tmp/px4-gps-lag-receiver")
    p.add_argument("--rescore", help="score an existing logs.jsonl instead of downloading")
    args = p.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    if args.rescore:
        with open(args.rescore, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        score(rows, args.out_dir, {"rescored_from": os.path.basename(args.rescore)})
        return 0
    os.makedirs(args.tmp, exist_ok=True)
    started = time.time()
    session = requests.Session()
    session.headers["User-Agent"] = fleet.USER_AGENT.replace("px4-gps-lag/%s" % fleet.__version__,
                                                             "px4-gps-lag-receiver/%s" % __version__)
    candidates, counts = fleet.load_candidates(session=session)
    skip_logs, skip_vehicles = excluded(args.exclude)
    queue = draw(candidates, skip_logs, skip_vehicles)
    print("listed %d, eligible %d, left after exclusions %d vehicles (excluded %d logs, %d vehicles)"
          % (counts["listed"], counts["eligible"], len(queue), len(skip_logs), len(skip_vehicles)), flush=True)

    rows, blocked = [], None
    path = os.path.join(args.tmp, "log.ulg")
    with open(os.path.join(args.out_dir, "logs.jsonl"), "w", encoding="utf-8") as out:
        for c in queue[:args.max_logs]:
            if time.time() - started > args.budget_min * 60:
                break
            if rows:
                time.sleep(DELAY_S)
            row = dict(c, attempt=len(rows) + 1)
            try:
                row["download"] = fleet.download(session, c["log_id"], path)
            except fleet.Blocked as exc:
                blocked = str(exc)
                break
            if row["download"] == "ok":
                row["size_mb"] = round(os.path.getsize(path) / 1e6, 1)
                try:
                    lag = gl.measure(gl.read_log(path))
                    row.update({k: lag.get(k) for k in LAG_KEYS})
                except Exception as exc:  # a log pyulog or gps_lag cannot read
                    row.update({"passed": False, "reason": "error: %s" % str(exc)[:200]})
                try:
                    row.update(read_receiver(path))
                except Exception as exc:
                    row.update({"receiver": "unknown", "receiver_source": "error: %s" % str(exc)[:200]})
                os.remove(path)
                if row.get("gps_bus") == "simulation" or row.get("receiver") == "simulation":
                    row.update({"passed": False, "reason": "simulated GPS"})
            else:
                row.update({"passed": False, "reason": "download " + row["download"]})
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
            print("%d %s %s %s lag %s ms (%s)" % (len(rows), c["log_id"], row.get("receiver"), row.get("passed"),
                                                 row.get("lag_ms"), row.get("reason")), flush=True)
    score(rows, args.out_dir, {"list": counts, "excluded_logs": len(skip_logs),
                               "excluded_vehicles": len(skip_vehicles), "blocked": blocked,
                               "wall_s": round(time.time() - started, 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
