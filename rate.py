"""rate.py: does a PX4 vehicle's GPS measurement rate explain its GPS lag?
Scores studies/receiver-2026/PLAN-rate.md.

PX4's u-blox driver sets a different measurement interval per model
(PX4-GPSDrivers ubx.cpp, configureDevice: rate_meas = F9P ? 100 : 125 ms on
protocol 27+, and 125 ms in moving-base mode at v1.15.4; ubx.h
UBX_TX_CFG_RATE_MEASINTERVAL 200 ms on the older CFG-RATE path the M8 takes),
with epochs aligned to UTC (time reference 0). So the fraction of the UTC
second in each solution's time_utc_usec sits on the receiver's measurement
grid. This reads that grid from vehicle_gps_position, for logs whose lag
receiver-2026 and receiver-confirm already published, and scores the PLAN's
checks on those published lags. No lag is measured here.

    python rate.py --out-dir out --sample receiver-2026.jsonl confirm.jsonl
    python rate.py --out-dir out --rescore logs.jsonl

Downloads use fleet.py (px4-gps-lag 0.1.1): 6 s apart, stop on 403/444;
each log is deleted once read. No position is read. Vehicle ids are
published only as a hash.

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time

import numpy as np
import requests

import fleet
import receiver as rc

__version__ = "0.1.0"

STEPS_MS = (250, 200, 125, 100, 50)   # grids tried, coarsest first
TOL_MS = 5.0            # a time is on the grid if within this of a grid point
ON_SHARE = 0.90         # share of times that must sit on the grid
STEP_SHARE = 0.50       # share of consecutive times exactly one step apart
MIN_UTC = 50            # distinct receiver times a log needs
MIN_CLASS = 10          # gridded logs a core class needs (E1)
DRIVER_SHARE = 0.70     # Q1
E0_SHARE = 0.50
GAP_MS = 20.0           # Q2-Q4
MIN_Q2 = 8
MIN_Q3 = 8
MIN_Q4 = 5
CORE = ("ubx_m8", "ubx_m9", "ubx_f9p")
SERIAL_UBX = ("ubx_m8", "ubx_m9", "ubx_f9p", "ubx_10", "ubx_generic")


def driver_ms(receiver, ubx_mode=None):
    """The measurement intervals PX4's driver may set for a receiver class:
    M8 200 ms (CFG-RATE path), M9 and M10 125 ms, F9P 100 ms, or 125 ms when
    GPS_UBX_MODE is not 0 (moving base / heading, v1.15+)."""
    if receiver == "ubx_m8":
        return (200,)
    if receiver in ("ubx_m9", "ubx_10"):
        return (125,)
    if receiver == "ubx_f9p":
        return (100,) if not ubx_mode else (100, 125)
    return ()


def utc_times_ms(time_utc_usec):
    """Distinct non-zero receiver UTC times, in ms, in log order."""
    t = np.asarray(time_utc_usec).astype(np.int64)
    t = t[t > 0]
    if len(t) == 0:
        return np.zeros(0)
    t = t[np.concatenate(([True], np.diff(t) != 0))]
    return t / 1000.0


def grid(times_ms):
    """The receiver's measurement grid from its UTC times: the coarsest step
    in STEPS_MS on which ON_SHARE of the times sit (within TOL_MS of a
    multiple of the step within the second), which shows at least half of
    its slots, and for which STEP_SHARE of consecutive times are exactly one
    step apart. The last rule keeps a throttled log (PX4 v1.12-v1.14 log
    vehicle_gps_position every 500 ms) from passing for a slow receiver."""
    times = np.asarray(times_ms, dtype=float)
    n = len(times)
    out = {"utc_n": n, "grid_ms": None}
    if n < MIN_UTC:
        out["grid_reason"] = "too few receiver times"
        return out
    frac = np.mod(times, 1000.0)
    diffs = np.diff(times)
    steps = np.round(diffs / 5.0) * 5.0
    vals, counts = np.unique(steps, return_counts=True)
    out["utc_dt_mode_ms"] = float(vals[int(np.argmax(counts))])
    for s in STEPS_MS:
        r = np.mod(frac, s)
        on = np.minimum(r, s - r) <= TOL_MS
        share = float(on.mean())
        if share < ON_SHARE:
            continue
        slots = int(round(1000.0 / s))
        seen = len(np.unique(np.mod(np.round(frac[on] / s).astype(int), slots)))
        one_step = float(np.mean(np.abs(diffs - s) <= TOL_MS))
        if seen >= math.ceil(slots / 2) and one_step >= STEP_SHARE:
            out.update({"grid_ms": s, "on_share": round(share, 4), "slots_seen": seen,
                        "one_step_share": round(one_step, 4)})
            return out
    out["grid_reason"] = "no grid"
    return out


def read_rate(path):
    """Grid, logged interval and GPS_UBX_MODE of one log."""
    from pyulog import ULog
    ulog = ULog(path, ["vehicle_gps_position"], True)
    vgp = None
    for d in ulog.data_list:
        if d.name == "vehicle_gps_position" and d.multi_id == 0:
            vgp = d.data
    mode = ulog.initial_parameters.get("GPS_UBX_MODE")
    row = {"gps_ubx_mode": None if mode is None else int(mode)}
    if vgp is None or "time_utc_usec" not in vgp:
        row.update({"utc_n": 0, "grid_ms": None, "grid_reason": "no vehicle_gps_position"})
        return row
    stamps = np.asarray(vgp["timestamp"]).astype(np.int64)
    if len(stamps) > 1:
        row["logged_dt_ms"] = round(float(np.median(np.diff(stamps))) / 1000.0, 1)
    row.update(grid(utc_times_ms(vgp["time_utc_usec"])))
    return row


def sample(paths):
    """The logs to read: receiver-2026's passed logs and receiver-confirm's
    re-read logs, with their published lag and receiver class, in file
    order; a log id is taken once."""
    out, seen = [], set()
    for path in paths:
        study = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                ok = r.get("passed") if "passed" in r else r.get("download") == "ok"
                if not ok or r.get("lag_ms") is None or r.get("receiver") in (None, "simulation"):
                    continue
                if r["log_id"] in seen:
                    continue
                seen.add(r["log_id"])
                out.append({"log_id": r["log_id"], "vehicle": r.get("vehicle"), "study": study,
                            "receiver": r["receiver"], "lag_ms": float(r["lag_ms"]),
                            "ver_sw_release": r.get("ver_sw_release")})
    return out


def _lags(rows):
    return [float(r["lag_ms"]) for r in rows]


def _gap(a, b, need):
    return rc.boot_diff(_lags(a), _lags(b)) if len(a) >= need and len(b) >= need else None


def summarise(rows):
    """The PLAN's checks, from the per-log rows."""
    read = [r for r in rows if r.get("download") == "ok"]
    ubx = [r for r in read if r.get("receiver") in SERIAL_UBX]
    gridded = [r for r in read if r.get("grid_ms")]
    e0 = (sum(bool(r.get("grid_ms")) for r in ubx) / len(ubx)) if ubx else None

    core = {}
    for k in CORE:
        g = [r for r in gridded if r["receiver"] == k]
        on = sum(r["grid_ms"] in driver_ms(k, r.get("gps_ubx_mode")) for r in g)
        core[k] = {"gridded": len(g), "on_driver": on, "share": round(on / len(g), 4) if g else None}
    e1 = all(core[k]["gridded"] >= MIN_CLASS for k in CORE)

    at125 = [r for r in gridded if r["receiver"] in SERIAL_UBX and r["grid_ms"] == 125]
    q2 = _gap([r for r in at125 if r["receiver"] == "ubx_m9"],
              [r for r in at125 if r["receiver"] != "ubx_m9"], MIN_Q2)
    generic = [r for r in gridded if r["receiver"] == "ubx_generic"]
    q3 = _gap([r for r in generic if r["grid_ms"] == 200], [r for r in generic if r["grid_ms"] == 125], MIN_Q3)
    f9p = [r for r in gridded if r["receiver"] == "ubx_f9p"]
    q4 = _gap([r for r in f9p if r["grid_ms"] == 100], [r for r in f9p if r["grid_ms"] != 100], MIN_Q4)

    checks = {
        "E0": (e0 >= E0_SHARE) if e0 is not None else None,
        "E1": e1,
        "Q1": all(core[k]["share"] >= DRIVER_SHARE for k in CORE) if e1 else None,
        "Q2": (q2["diff_ms"] <= -GAP_MS and q2["ci95_ms"][1] < 0) if q2 else None,
        "Q3": (q3["diff_ms"] >= GAP_MS and q3["ci95_ms"][0] > 0) if q3 else None,
        "Q4": (q4["diff_ms"] >= GAP_MS and q4["ci95_ms"][0] > 0) if q4 else None,
    }
    checks = {k: (None if v is None else bool(v)) for k, v in checks.items()}
    downloads = {}
    for r in rows:
        downloads[r.get("download") or "?"] = downloads.get(r.get("download") or "?", 0) + 1
    return {
        "sample": len(rows),
        "downloads": downloads,
        "read": len(read),
        "E0_gridded_share_serial_ublox": None if e0 is None else round(e0, 4),
        "E0_serial_ublox": len(ubx),
        "Q1_driver_grid": core,
        "Q2_m9_minus_other_at_125": q2,
        "Q2_n": [sum(r["receiver"] == "ubx_m9" for r in at125), sum(r["receiver"] != "ubx_m9" for r in at125)],
        "Q3_generic_200_minus_125": q3,
        "Q3_n": [sum(r["grid_ms"] == 200 for r in generic), sum(r["grid_ms"] == 125 for r in generic)],
        "Q4_f9p_100_minus_other": q4,
        "Q4_n": [sum(r["grid_ms"] == 100 for r in f9p), sum(r["grid_ms"] != 100 for r in f9p)],
        "checks": checks,
        "decision": {"D1_rate_line_in_checkup": bool(checks["E0"] and checks["Q1"]),
                     "D2_rate_not_the_m9_story": checks["Q2"] if e1 else None},
    }


def ranks(xs):
    """Ranks from 0, ties given their average rank (for Spearman)."""
    x = np.asarray(xs, dtype=float)
    order = np.argsort(x, kind="stable")
    sx, out = x[order], np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        out[order[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return out


def explore(rows):
    """Breakdowns the PLAN did not predict, labelled exploratory."""
    read = [r for r in rows if r.get("download") == "ok"]

    def groups(rows_, key):
        out = {}
        for r in rows_:
            out.setdefault(key(r), []).append(float(r["lag_ms"]))
        return {k: {"n": len(v), "median_lag_ms": rc._median(v)} for k, v in sorted(out.items())}
    gridded = [r for r in read if r.get("grid_ms")]
    ubx = [r for r in gridded if r["receiver"] in SERIAL_UBX]
    rho = None
    if len(ubx) >= 10:
        a, b = ranks([r["grid_ms"] for r in ubx]), ranks(_lags(ubx))
        rho = round(float(np.corrcoef(a, b)[0, 1]), 3) if np.std(a) > 0 and np.std(b) > 0 else None
    return {
        "note": "not pre-registered; descriptive only",
        "by_receiver_and_grid": groups(read, lambda r: "%s %s" % (r["receiver"], r.get("grid_ms") or "none")),
        "by_release_and_grid": groups(read, lambda r: "%s %s" % (rc._major(r), "grid" if r.get("grid_ms") else "none")),
        "dt_mode_without_grid": groups([r for r in read if not r.get("grid_ms")],
                                       lambda r: "%s dt %s" % (r["receiver"], r.get("utc_dt_mode_ms"))),
        "ubx_mode_by_receiver": groups(read, lambda r: "%s mode %s" % (r["receiver"], r.get("gps_ubx_mode"))),
        "rank_corr_grid_lag_serial_ublox": rho,
    }


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score(rows, out_dir, extra):
    summary = summarise(rows)
    summary["exploratory"] = explore(rows)
    summary.update({"rate_py": __version__, "receiver_py": rc.__version__, "fleet": fleet.__version__}, **extra)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True)
    p.add_argument("--sample", nargs="*", default=[])
    p.add_argument("--budget-min", type=float, default=150)
    p.add_argument("--tmp", default="/tmp/px4-gps-lag-rate")
    p.add_argument("--rescore", help="score an existing logs.jsonl instead of downloading")
    args = p.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    if args.rescore:
        score(load_rows(args.rescore), args.out_dir, {"rescored_from": os.path.basename(args.rescore)})
        return 0
    os.makedirs(args.tmp, exist_ok=True)
    started = time.time()
    session = requests.Session()
    session.headers["User-Agent"] = fleet.USER_AGENT.replace("px4-gps-lag/%s" % fleet.__version__,
                                                             "px4-gps-lag-rate/%s" % __version__)
    queue = sample(args.sample)
    print("%d logs to read" % len(queue), flush=True)

    rows, blocked, out_of_time = [], None, 0
    path = os.path.join(args.tmp, "log.ulg")
    with open(os.path.join(args.out_dir, "logs.jsonl"), "w", encoding="utf-8") as out:
        for c in queue:
            if time.time() - started > args.budget_min * 60:
                out_of_time = len(queue) - len(rows)
                break
            if rows:
                time.sleep(rc.DELAY_S)
            row = dict(c, attempt=len(rows) + 1)
            try:
                row["download"] = fleet.download(session, c["log_id"], path)
            except fleet.Blocked as exc:
                blocked = str(exc)
                break
            if row["download"] == "ok":
                try:
                    row.update(read_rate(path))
                except Exception as exc:  # a log pyulog cannot read
                    row.update({"grid_ms": None, "grid_reason": "error: %s" % str(exc)[:200]})
                os.remove(path)
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
            print("%d %s %s %s lag %s grid %s (%s)" % (len(rows), c["log_id"], row["download"], c["receiver"],
                                                      c["lag_ms"], row.get("grid_ms"), row.get("grid_reason", "")),
                  flush=True)
    score(rows, args.out_dir, {"blocked": blocked, "not_reached_in_budget": out_of_time,
                               "wall_s": round(time.time() - started, 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
