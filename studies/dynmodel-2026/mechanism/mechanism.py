"""mechanism: is u-blox dynamic model 6's extra GPS lag smoothing, or later delivery? (pre-registered)

Plan: studies/dynmodel-2026/PLAN-mechanism.md, committed before this code reads the two logs.
The logs are the two attached to PX4-Autopilot PR #24831 (one vehicle, serial u-blox F9P,
GPS_UBX_DYNMODEL 6 and 7; px4-gps-lag measured 214.2 and 110.5 ms of GPS lag).

1. Smoothing or delay. gps_lag.py fits one number: the delay that best lines up the change in GPS
   velocity over each GPS interval with the IMU's integrated north-east acceleration. Here the IMU
   velocity first goes through a first-order low-pass filter with time constant tau, then the
   delay D is applied, and (tau, D) is fitted on a grid: tau 0 to 250 ms in 10 ms steps, D -200 to
   +600 ms in 5 ms steps. The fit is otherwise gps_lag.py's (one constant acceleration bias per
   axis, the same GPS pairs). A pure delivery delay shows up as D; smoothing by the receiver's
   navigation filter, which also damps quick changes, shows up as tau. A moving-block bootstrap
   (blocks of 25 GPS pairs, 200 resamples) gives intervals.
2. EKF2's GPS velocity innovations against acceleration: innov.py's measure_innov, unchanged.
3. Descriptive: EKF2's GPS velocity and position test ratios, reset counters and rejection flags
   while flying.

    python mechanism.py --ulg-dir ulg --rows paired-rows.jsonl --out mechanism-summary.json

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import sys

import numpy as np

__version__ = "0.1.0"
SEED = 20261107
BLOCK = 25
RESAMPLES = 200
TAUS = np.round(np.arange(0.0, 0.2501, 0.01), 3)
LAGS = np.round(np.arange(-0.2, 0.6001, 0.005), 3)
RESET_FIELDS = ("reset_count_vel_ne", "reset_count_pos_ne", "reset_count_vel_d", "reset_count_pos_d",
                "reset_count_quat")
FLAG_FIELDS = ("reject_hor_vel", "reject_hor_pos", "cs_gps")


def plain(o):
    """JSON-safe copy: numpy scalars and arrays become Python types, non-finite floats None."""
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(v) for v in o]
    if isinstance(o, np.ndarray):
        return [plain(v) for v in o.tolist()]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if np.isfinite(f) else None
    return o


def ms(x):
    return round(float(x) * 1e3, 1)


def cumulative(t, a):
    """Running integral, as gps_lag.cumulative: each sample is the mean since the one before."""
    t = np.asarray(t, dtype=float)
    a = np.asarray(a, dtype=float)
    dt = np.concatenate([[0.0], np.diff(t)])
    return np.cumsum(a * dt[:, None], axis=0)


def lowpass(t, v, tau):
    """First-order low-pass of v (n, k) sampled at t, time constant tau (s), one step size (the
    median spacing), starting at rest at v[0]. tau 0 returns a copy of v."""
    v = np.asarray(v, dtype=float)
    if tau <= 0:
        return v.copy()
    from scipy.signal import lfilter
    dt = float(np.median(np.diff(np.asarray(t, dtype=float))))
    a = float(np.exp(-dt / tau))
    out = np.empty_like(v)
    for k in range(v.shape[1]):
        out[:, k], _ = lfilter([1.0 - a], [1.0, -a], v[:, k], zi=[a * v[0, k]])
    return out


def design(imu_t, V, t1, t2, taus=TAUS, lags=LAGS):
    """X[i, j, n, k]: change of the low-passed IMU velocity (taus[i]) over GPS pair n, axis k,
    shifted by lags[j]."""
    X = np.empty((len(taus), len(lags), len(t1), V.shape[1]))
    for i, tau in enumerate(taus):
        F = lowpass(imu_t, V, tau)
        for j, lag in enumerate(lags):
            for k in range(V.shape[1]):
                X[i, j, :, k] = (np.interp(t2 - lag, imu_t, F[:, k])
                                 - np.interp(t1 - lag, imu_t, F[:, k]))
    return X


def sse_grid(rr, rd, d, w):
    """SSE per (tau, lag), one constant acceleration bias per axis, GPS pairs weighted by w."""
    s2 = np.tensordot(rr, w, axes=([2], [0]))          # (taus, lags, axes)
    sd = np.tensordot(rd, w, axes=([2], [0]))
    sdd = float(np.sum(w * d * d))
    return np.sum(s2 - sd * sd / sdd, axis=2)


def argbest(sse):
    i, j = np.unravel_index(int(np.argmin(sse)), sse.shape)
    return int(i), int(j)


def block_indices(n, rng, block=BLOCK):
    """One moving-block resample of range(n): contiguous blocks of `block` pairs, cut to n."""
    if n <= block:
        return np.arange(n)
    k = -(-n // block)
    starts = rng.integers(0, n - block + 1, size=k)
    return np.concatenate([np.arange(s, s + block) for s in starts])[:n]


def pct3(x):
    x = np.asarray(x, dtype=float)
    return [round(float(np.percentile(x, q)), 1) for q in (2.5, 50, 97.5)]


def fit_grid(imu_t, a_ne, t1, t2, dv, resamples=RESAMPLES, seed=SEED, block=BLOCK):
    """Best (tau, D) for one flight, the tau = 0 fit, a profile over tau and bootstrap draws."""
    imu_t = np.asarray(imu_t, dtype=float)
    t1 = np.asarray(t1, dtype=float)
    t2 = np.asarray(t2, dtype=float)
    dv = np.asarray(dv, dtype=float)
    V = cumulative(imu_t, a_ne)
    d = t2 - t1
    X = design(imu_t, V, t1, t2)
    r = dv[None, None, :, :] - X
    rr = r * r
    rd = r * d[None, None, :, None]
    del r, X
    n = len(t1)
    sse = sse_grid(rr, rd, d, np.ones(n))
    sst = float(np.sum((dv - dv.mean(axis=0)) ** 2))
    i, j = argbest(sse)
    j0 = int(np.argmin(sse[0]))
    out = {"pairs": n, "tau_ms": ms(TAUS[i]), "lag_ms": ms(LAGS[j]), "sum_ms": ms(TAUS[i] + LAGS[j]),
           "r2": round(1.0 - float(sse[i, j]) / sst, 5),
           "lag_tau0_ms": ms(LAGS[j0]), "r2_tau0": round(1.0 - float(sse[0, j0]) / sst, 5),
           "tau_edge": i == len(TAUS) - 1, "lag_edge": j in (0, len(LAGS) - 1),
           "profile": [{"tau_ms": ms(TAUS[a]), "lag_ms": ms(LAGS[int(np.argmin(sse[a]))]),
                        "r2": round(1.0 - float(np.min(sse[a])) / sst, 5)} for a in range(len(TAUS))]}
    rng = np.random.default_rng(seed)
    taus, lags = [], []
    for _ in range(resamples):
        w = np.bincount(block_indices(n, rng, block), minlength=n).astype(float)
        bi, bj = argbest(sse_grid(rr, rd, d, w))
        taus.append(ms(TAUS[bi]))
        lags.append(ms(LAGS[bj]))
    taus, lags = np.asarray(taus), np.asarray(lags)
    out["boot"] = {"tau_ms": pct3(taus), "lag_ms": pct3(lags), "sum_ms": pct3(taus + lags),
                   "tau_at_edge_share": round(float(np.mean(taus >= ms(TAUS[-1]))), 3)}
    return out, taus, lags


def identified(f):
    """tau counts as identified when its bootstrap 95% interval is at most 100 ms wide and
    neither the fit nor more than 5% of the draws sit at the top of the grid."""
    lo, _, hi = f["boot"]["tau_ms"]
    return (hi - lo) <= 100.0 and not f["tau_edge"] and f["boot"]["tau_at_edge_share"] <= 0.05


def decide(f6, f7, taus6, taus7, lags6, lags7):
    """The plan's rules: 'smoothing', 'delivery', 'mixed' or 'not identified'."""
    dtau = f6["tau_ms"] - f7["tau_ms"]
    dlag = f6["lag_ms"] - f7["lag_ms"]
    m = min(len(taus6), len(taus7))
    btau = np.asarray(taus6[:m]) - np.asarray(taus7[:m])
    blag = np.asarray(lags6[:m]) - np.asarray(lags7[:m])
    res = {"tau_diff_ms": round(dtau, 1), "lag_diff_ms": round(dlag, 1),
           "sum_diff_ms": round(dtau + dlag, 1),
           "boot_tau_diff_ms": pct3(btau) if m else None, "boot_lag_diff_ms": pct3(blag) if m else None,
           "identified_6": identified(f6), "identified_7": identified(f7)}
    if not (res["identified_6"] and res["identified_7"]):
        res["outcome"] = "not identified"
    elif dtau >= 50.0 and m and res["boot_tau_diff_ms"][0] > 0.0:
        res["outcome"] = "smoothing"
    elif abs(dtau) <= 20.0 and dlag >= 70.0:
        res["outcome"] = "delivery"
    else:
        res["outcome"] = "mixed"
    return res


def counter_increments(c):
    """How many times a uint8 reset counter stepped, wrap-around included."""
    c = np.asarray(c, dtype=np.int64)
    if len(c) < 2:
        return 0
    return int(np.sum(np.mod(np.diff(c), 256)))


def fresh(v):
    """True for each row that differs from the row before it (the first row counts)."""
    v = np.asarray(v, dtype=float)
    if len(v) == 0:
        return np.zeros(0, dtype=bool)
    return np.concatenate([[True], np.any(v[1:] != v[:-1], axis=1)])


def ratio_stats(x):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return None
    return {"n": int(len(x)), "p50": round(float(np.median(x)), 4),
            "p95": round(float(np.percentile(x, 95)), 4), "share_over_1": round(float(np.mean(x > 1.0)), 4)}


def flying_mask(flying, timestamps_us):
    """flying(t_seconds) as a bool array of the same length as timestamps_us."""
    t = np.asarray(timestamps_us, dtype=float) / 1e6
    return np.broadcast_to(np.asarray(flying(t), dtype=bool), t.shape)


def ekf_stats(data, flying):
    """data: {topic: {field: array}} (multi_id 0); flying(t_seconds) -> bool array."""
    out = {}
    tr = data.get("estimator_innovation_test_ratios")
    for key in ("gps_hvel", "gps_hpos"):
        cols = [key + "[0]", key + "[1]"]
        if tr is None or not all(c in tr for c in cols):
            out[key + "_test_ratio"] = None
            continue
        v = np.column_stack([np.asarray(tr[c], dtype=float) for c in cols])
        m = (fresh(v) & flying_mask(flying, tr["timestamp"]) & np.all(np.isfinite(v), axis=1)
             & np.any(v != 0, axis=1))
        out[key + "_test_ratio"] = ratio_stats(np.max(v[m], axis=1)) if m.any() else None
    st = data.get("estimator_status")
    resets = {}
    if st is not None:
        fl = flying_mask(flying, st["timestamp"])
        for name in RESET_FIELDS:
            if name in st:
                c = np.asarray(st[name])
                resets[name] = {"in_flight": counter_increments(c[fl]), "whole_log": counter_increments(c)}
    out["resets"] = resets or None
    sf = data.get("estimator_status_flags")
    flags = {}
    if sf is not None:
        fl = flying_mask(flying, sf["timestamp"])
        for name in FLAG_FIELDS:
            if name in sf and fl.any():
                flags[name] = {"share_in_flight": round(float(np.mean(np.asarray(sf[name])[fl] != 0)), 4),
                               "samples": int(fl.sum())}
    out["flags"] = flags or None
    return out


def read_topics(path, names):
    from pyulog import ULog
    u = ULog(path, list(names))
    return {d.name: d.data for d in u.data_list if d.name in names and d.multi_id == 0}


def measure(path, published_ms):
    import gps_lag as gl
    import innov
    log = gl.read_log(path)
    flying_gps = gl.flying_at(log["gps_t"], log["land_t"], log["landed"])
    usable = np.asarray(log["usable"], dtype=bool) & np.asarray(flying_gps, dtype=bool)
    idx = gl.gps_pairs(log["gps_t"], usable, log["imu_t"])
    gps_t = np.asarray(log["gps_t"], dtype=float)
    vel = np.asarray(log["vel_ne"], dtype=float)
    imu_t = np.asarray(log["imu_t"], dtype=float)
    a_ne = gl.ne_accel(imu_t, log["f_body"], log["att_t"], log["q"])
    t1, t2 = gps_t[idx], gps_t[idx + 1]
    dv = vel[idx + 1] - vel[idx]
    whole = gl.fit_lag(imu_t, a_ne, t1, t2, dv)
    row = {"published_lag_ms": published_ms, "gps_lag_fit_ms": round(float(whole["lag_s"]) * 1e3, 1)}
    row["reproduced"] = abs(row["gps_lag_fit_ms"] - published_ms) <= 0.05
    fit, taus, lags = fit_grid(imu_t, a_ne, t1, t2, dv)
    row["grid"] = fit
    row["grid_tau0_close"] = abs(fit["lag_tau0_ms"] - published_ms) <= 5.0
    try:
        row["innov"] = innov.measure_innov(log, innov.read_innov(path))
    except Exception as exc:                         # reported, not hidden
        row["innov"] = {"passed": False, "reason": "error: %s" % exc}
    data = read_topics(path, ("estimator_innovation_test_ratios", "estimator_status", "estimator_status_flags"))
    row["ekf"] = ekf_stats(data, lambda t: gl.flying_at(t, log["land_t"], log["landed"]))
    row["param_gps_delay_ms"] = log["facts"].get("param_gps_delay_ms")
    return row, taus, lags


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
    rows, draws = {}, {}
    for name in sorted(os.listdir(args.ulg_dir)):
        base = name.split("_", 1)[1] if name[:3].isdigit() and name[3:4] == "_" else name
        if base in published:
            model, lag = published[base]
            row, taus, lags = measure(os.path.join(args.ulg_dir, name), lag)
            row["file"], row["dynmodel"] = base, model
            rows[model] = row
            draws[model] = (taus, lags)
            print("measured", base, "model", model, flush=True)
    if sorted(rows) != [6, 7]:
        sys.exit("expected one model-6 and one model-7 log, found %s" % sorted(rows))
    out = {"mechanism": __version__, "seed": SEED, "block": BLOCK, "resamples": RESAMPLES,
           "tau_grid_ms": [ms(TAUS[0]), ms(TAUS[-1]), 10.0], "lag_grid_ms": [ms(LAGS[0]), ms(LAGS[-1]), 5.0],
           "logs": {str(m): rows[m] for m in (6, 7)}}
    out["E1_reproduced"] = all(rows[m]["reproduced"] and rows[m]["grid_tau0_close"] for m in (6, 7))
    out["M1"] = decide(rows[6]["grid"], rows[7]["grid"], draws[6][0], draws[7][0], draws[6][1], draws[7][1])
    i6, i7 = rows[6]["innov"], rows[7]["innov"]
    out["M2"] = {"implied_excess_ms_6": i6.get("implied_excess_ms"), "implied_excess_ms_7": i7.get("implied_excess_ms"),
                 "held": bool(i6.get("passed") and i7.get("passed")
                              and i6.get("implied_excess_ms", 0) > 0 and i7.get("implied_excess_ms", 0) < 0)}
    out = plain(out)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    if not out["E1_reproduced"]:
        sys.exit("the published lags were not reproduced (E1); nothing else is graded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
