"""paired_segments: how robust is dynmodel-2026's paired result within each flight? (exploratory)

Not pre-registered. studies/dynmodel-2026/PLAN-paired.md was graded D1 on the two logs attached to
PX4-Autopilot PR #24831 (one vehicle, GPS_UBX_DYNMODEL 6 vs 7: 214.2 vs 110.5 ms). gps_lag.py's
standard error assumes independent GPS pairs, so it says little about how stable each figure is.
This re-fits each log's lag with px4-gps-lag's own gps_lag.py functions, unchanged:

- the whole flight (must reproduce the published lag to 0.05 ms, or the script stops);
- each third of the flight's GPS pairs, in time order;
- a moving-block bootstrap (blocks of 25 consecutive pairs, 400 resamples, seed 20261105);
- low- and high-acceleration pairs, split at the median of both logs pooled, so both flights are
  compared over the same acceleration range;
- how often each flight's horizontal acceleration (IMU, averaged over each GPS pair's interval)
  went over 1 g, the limit of u-blox's 'airborne <1g' model 6.

    python paired_segments.py --ulg-dir ulg --rows paired-rows.jsonl --out segments-summary.json

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import sys

import numpy as np

import gps_lag as gl

__version__ = "0.1.0"
SEED = 20261105
BLOCK = 25
RESAMPLES = 400
ONE_G = 9.80665


def prepare(log):
    """The in-flight GPS pairs of one log, as gps_lag.measure() selects them."""
    flying = gl.flying_at(log["gps_t"], log["land_t"], log["landed"])
    usable = np.asarray(log["usable"], dtype=bool) & flying
    idx = gl.gps_pairs(log["gps_t"], usable, log["imu_t"])
    gps_t = np.asarray(log["gps_t"], dtype=float)
    vel = np.asarray(log["vel_ne"], dtype=float)
    imu_t = np.asarray(log["imu_t"], dtype=float)
    a_ne = gl.ne_accel(imu_t, log["f_body"], log["att_t"], log["q"])
    return {"imu_t": imu_t, "a_ne": a_ne, "t1": gps_t[idx], "t2": gps_t[idx + 1],
            "dv": vel[idx + 1] - vel[idx]}


def fit(p, sel=None):
    sel = np.arange(len(p["t1"])) if sel is None else np.asarray(sel)
    r = gl.fit_lag(p["imu_t"], p["a_ne"], p["t1"][sel], p["t2"][sel], p["dv"][sel])
    se = r["se_s"]
    return {"lag_ms": round(r["lag_s"] * 1e3, 1),
            "se_ms": round(se * 1e3, 2) if np.isfinite(se) else None,
            "pairs": int(r["pairs"]), "excitation_m_s2": round(float(r["excitation_m_s2"]), 3),
            "r2": None if r["r2"] is None else round(float(r["r2"]), 4), "edge": bool(r["edge"])}


def thirds(n):
    return [list(map(int, s)) for s in np.array_split(np.arange(n), 3)]


def block_indices(n, rng, block=BLOCK):
    """One moving-block resample of range(n): contiguous blocks of `block` pairs, cut to n."""
    if n <= block:
        return np.arange(n)
    k = -(-n // block)
    starts = rng.integers(0, n - block + 1, size=k)
    return np.concatenate([np.arange(s, s + block) for s in starts])[:n]


def bootstrap(p, resamples=RESAMPLES, seed=SEED):
    rng = np.random.default_rng(seed)
    n = len(p["t1"])
    return [fit(p, block_indices(n, rng))["lag_ms"] for _ in range(resamples)]


def pair_accel(p):
    """Per GPS pair: |GPS velocity change| / interval, and the IMU's mean horizontal acceleration
    over the same interval (no lag shift), both in m/s^2."""
    d = p["t2"] - p["t1"]
    gps_acc = np.linalg.norm(p["dv"], axis=1) / d
    V = gl.cumulative(p["imu_t"], p["a_ne"])
    X = np.column_stack([np.interp(p["t2"], p["imu_t"], V[:, k]) - np.interp(p["t1"], p["imu_t"], V[:, k])
                         for k in (0, 1)])
    imu_acc = np.linalg.norm(X, axis=1) / d
    return gps_acc, imu_acc


def pct(x, q):
    return round(float(np.percentile(np.asarray(x, dtype=float), q)), 1)


def analyse(preps, published):
    """preps: {file: prepared log}; published: {file: (dynmodel, published lag_ms)}."""
    out = {"paired_segments": __version__, "seed": SEED, "block": BLOCK, "resamples": RESAMPLES,
           "note": "exploratory, not pre-registered", "logs": {}}
    accs = {f: pair_accel(p) for f, p in preps.items()}
    pooled = np.concatenate([a[0] for a in accs.values()])
    split = float(np.median(pooled))
    out["accel_split_m_s2"] = round(split, 3)
    boots = {}
    for f, p in sorted(preps.items()):
        model, pub = published[f]
        whole = fit(p)
        row = {"dynmodel": model, "published_lag_ms": pub, "whole": whole,
               "reproduced": abs(whole["lag_ms"] - pub) <= 0.05}
        row["thirds"] = [fit(p, s) for s in thirds(len(p["t1"]))]
        b = bootstrap(p)
        boots[model] = np.asarray(b)
        row["block_bootstrap_ms"] = {"p2.5": pct(b, 2.5), "p50": pct(b, 50), "p97.5": pct(b, 97.5)}
        gps_acc, imu_acc = accs[f]
        row["low_accel"] = fit(p, np.nonzero(gps_acc <= split)[0])
        row["high_accel"] = fit(p, np.nonzero(gps_acc > split)[0])
        row["imu_horizontal_accel_m_s2"] = {"p50": pct(imu_acc, 50), "p90": pct(imu_acc, 90),
                                            "p99": pct(imu_acc, 99), "max": round(float(np.max(imu_acc)), 1),
                                            "share_over_1g": round(float(np.mean(imu_acc > ONE_G)), 4)}
        out["logs"][f] = row
    out["reproduced_all"] = all(r["reproduced"] for r in out["logs"].values())
    if 6 in boots and 7 in boots:
        d = boots[6] - boots[7]
        out["diff_6_minus_7"] = {
            "whole_ms": round(next(r["whole"]["lag_ms"] for r in out["logs"].values() if r["dynmodel"] == 6)
                              - next(r["whole"]["lag_ms"] for r in out["logs"].values() if r["dynmodel"] == 7), 1),
            "block_bootstrap_ms": {"p2.5": pct(d, 2.5), "p50": pct(d, 50), "p97.5": pct(d, 97.5)},
            "thirds_separated": (min(t["lag_ms"] for r in out["logs"].values() if r["dynmodel"] == 6
                                     for t in r["thirds"])
                                 > max(t["lag_ms"] for r in out["logs"].values() if r["dynmodel"] == 7
                                       for t in r["thirds"])),
            "low_accel_ms": round(sum(r["low_accel"]["lag_ms"] * (1 if r["dynmodel"] == 6 else -1)
                                      for r in out["logs"].values()), 1),
            "high_accel_ms": round(sum(r["high_accel"]["lag_ms"] * (1 if r["dynmodel"] == 6 else -1)
                                       for r in out["logs"].values()), 1)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ulg-dir", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    published = {}
    with open(args.rows, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                published[r["file"]] = (int(r["params"]["GPS_UBX_DYNMODEL"]), float(r["lag_ms"]))
    preps = {}
    for name in sorted(os.listdir(args.ulg_dir)):
        base = name.split("_", 1)[1] if name[:3].isdigit() and name[3:4] == "_" else name
        if base in published:
            preps[base] = prepare(gl.read_log(os.path.join(args.ulg_dir, name)))
    if set(preps) != set(published):
        sys.exit("logs found %s do not match the published rows %s" % (sorted(preps), sorted(published)))
    out = analyse(preps, published)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    if not out["reproduced_all"]:
        sys.exit("the whole-flight fit did not reproduce the published lag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
