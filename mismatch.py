"""mismatch.py: does a wrong EKF2_GPS_DELAY show in EKF2's own GPS checks?
Scores studies/mismatch-2026/PLAN.md.

gps_lag.py measures how late a PX4 vehicle's GPS really is; about 30% of
public logs are more than 50 ms off their own EKF2_GPS_DELAY. A GPS sample
that is L late but fused as if it were P late leaves an innovation of about
a * (L - P) (times about 0.6, as the filter partly follows it), so the
mismatch should show most when the vehicle accelerates. This reads, per log,
EKF2's horizontal GPS velocity test ratio (estimator_innovation_test_ratios,
gps_hvel; test ratio = innovation^2 / (gate^2 * innovation variance), and a
value above 1 rejects the sample) in flight, when the vehicle accelerates
(1.5 to 5 m/s^2) and when it barely does (< 0.5 m/s^2), and asks whether
the lift between the two grows with the mismatch, and whether mismatched
logs see more GPS velocity rejections.

    python mismatch.py --out-dir out --rescore logs.jsonl

Per-log reading (read_mismatch) is called by fresh_mm.py on each fresh-2026
log, next to fresh.py's own readers. No position is read.

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics

import numpy as np

__version__ = "0.1.0"

SEED = 20261103
WIN_S = 0.4            # acceleration window before each logged sample, s
HI_LO, HI_HI = 1.5, 5.0   # "accelerating" bin, m/s^2 (horizontal)
LO_MAX = 0.5           # "steady" bin, m/s^2
MIN_HI, MIN_LO = 8, 20  # samples a log needs in each bin
EPS = 1e-4             # added to both medians before the ratio
OFF_MS = 50.0          # mismatched: |lag - EKF2_GPS_DELAY| > 50 ms
MIN_E0 = 60            # usable logs for E0
MIN_CORR = 30          # logs a rank correlation needs
MIN_GROUP = 15         # logs each side of M2 / M3 needs
S0_RHO = 0.5
M3_MAX = 0.10
BOOT = 2000
TOPICS = ("estimator_innovation_test_ratios", "estimator_innovations",
          "vehicle_local_position", "vehicle_land_detected")


# ---------------------------------------------------------------- per log

def window_mean(t_src, x_src, t_q, win=WIN_S):
    """Mean of the finite x_src values with t in (t_q - win, t_q]; nan if
    none. t_src must be sorted."""
    t_src = np.asarray(t_src, dtype=float)
    x_src = np.asarray(x_src, dtype=float)
    t_q = np.asarray(t_q, dtype=float)
    fin = np.isfinite(x_src)
    c = np.concatenate([[0.0], np.cumsum(np.where(fin, x_src, 0.0))])
    k = np.concatenate([[0], np.cumsum(fin.astype(np.int64))])
    hi = np.searchsorted(t_src, t_q, side="right")
    lo = np.searchsorted(t_src, t_q - win, side="right")
    n = k[hi] - k[lo]
    out = np.full(t_q.shape, np.nan)
    ok = n > 0
    out[ok] = (c[hi[ok]] - c[lo[ok]]) / n[ok]
    return out


def in_air_at(air_t, landed, t_q):
    """True where the last vehicle_land_detected sample at or before t_q says
    not landed."""
    air_t = np.asarray(air_t, dtype=float)
    landed = np.asarray(landed).astype(int)
    idx = np.searchsorted(air_t, np.asarray(t_q, dtype=float), side="right") - 1
    out = np.zeros(len(idx), dtype=bool)
    ok = idx >= 0
    out[ok] = landed[idx[ok]] == 0
    return out


def metrics(tr_t, tr_n, tr_e, lp_t, ax, ay, air_t, landed, inn_t=None, inn_n=None, inn_e=None):
    """Per-log figures from plain arrays (times in seconds).

    tr_n, tr_e: gps_hvel[0] and gps_hvel[1] of estimator_innovation_test_ratios
    (v1.15 fills both, one per axis; older releases put one horizontal ratio
    in [0]). The log's ratio is the larger of the two; non-finite or <= 0
    values (no fusion, resets) are left out."""
    tr_t = np.asarray(tr_t, dtype=float)
    tr = np.asarray(tr_n, dtype=float)
    if tr_e is not None:
        tr = np.fmax(tr, np.asarray(tr_e, dtype=float))
    a_n = window_mean(lp_t, ax, tr_t)
    a_e = window_mean(lp_t, ay, tr_t)
    amag = np.hypot(a_n, a_e)
    air = in_air_at(air_t, landed, tr_t)
    base = np.isfinite(tr) & (tr > 0) & air & np.isfinite(amag)
    hi = base & (amag >= HI_LO) & (amag < HI_HI)
    lo = base & (amag < LO_MAX)
    out = {"mm_n_air": int(base.sum()), "mm_n_hi": int(hi.sum()), "mm_n_lo": int(lo.sum()),
           "mm_tr_hi": None, "mm_tr_lo": None, "mm_lift": None, "mm_p95": None,
           "mm_rejected": None, "mm_reject_share": None, "mm_slope_s": None, "mm_slope_n": 0}
    if base.any():
        vals = tr[base]
        out["mm_p95"] = round(float(np.percentile(vals, 95)), 5)
        out["mm_rejected"] = bool(np.any(vals > 1.0))
        out["mm_reject_share"] = round(float(np.mean(vals > 1.0)), 5)
    ok = out["mm_n_hi"] >= MIN_HI and out["mm_n_lo"] >= MIN_LO
    if ok:
        th, tl = float(np.median(tr[hi])), float(np.median(tr[lo]))
        out.update({"mm_tr_hi": round(th, 6), "mm_tr_lo": round(tl, 6),
                    "mm_lift": round(math.log10((th + EPS) / (tl + EPS)), 5)})
    out["mm_ok"] = bool(ok)
    out["mm_reason"] = None if ok else (
        "landed throughout" if out["mm_n_air"] == 0 else "too few samples (hi %d, lo %d)"
        % (out["mm_n_hi"], out["mm_n_lo"]))
    if inn_t is not None and inn_n is not None and inn_e is not None:
        inn_t = np.asarray(inn_t, dtype=float)
        i_n, i_e = np.asarray(inn_n, dtype=float), np.asarray(inn_e, dtype=float)
        b_n = window_mean(lp_t, ax, inn_t)
        b_e = window_mean(lp_t, ay, inn_t)
        use = (in_air_at(air_t, landed, inn_t) & np.isfinite(i_n) & np.isfinite(i_e)
               & np.isfinite(b_n) & np.isfinite(b_e))
        strong = use & (np.hypot(b_n, b_e) >= HI_LO)
        den = float(np.sum(b_n[use] ** 2 + b_e[use] ** 2))
        out["mm_slope_n"] = int(use.sum())
        if int(strong.sum()) >= MIN_HI and den > 0:
            num = float(np.sum(i_n[use] * b_n[use] + i_e[use] * b_e[use]))
            out["mm_slope_s"] = round(num / den, 6)
    return out


def _t(d):
    key = "timestamp_sample" if "timestamp_sample" in d else "timestamp"
    return np.asarray(d[key], dtype=float) / 1e6


def read_mismatch(path):
    """read the four topics (first instance) from a .ulg and return metrics()."""
    from pyulog import ULog
    ulog = ULog(path, list(TOPICS), True)
    got = {}
    for d in ulog.data_list:
        if d.multi_id == 0 and d.name in TOPICS:
            got[d.name] = d.data
    for name in ("estimator_innovation_test_ratios", "vehicle_local_position", "vehicle_land_detected"):
        if name not in got:
            return {"mm_ok": False, "mm_reason": "missing " + name}
    tr, lp, ld = got["estimator_innovation_test_ratios"], got["vehicle_local_position"], got["vehicle_land_detected"]
    if "gps_hvel[0]" not in tr or "ax" not in lp or "landed" not in ld:
        return {"mm_ok": False, "mm_reason": "missing field"}
    inn = got.get("estimator_innovations")
    inn_args = (None, None, None)
    if inn is not None and "gps_hvel[0]" in inn and "gps_hvel[1]" in inn:
        inn_args = (_t(inn), inn["gps_hvel[0]"], inn["gps_hvel[1]"])
    lp_t = _t(lp)
    order = np.argsort(lp_t, kind="stable")
    air_t = np.asarray(ld["timestamp"], dtype=float) / 1e6
    return metrics(_t(tr), tr["gps_hvel[0]"], tr.get("gps_hvel[1]"), lp_t[order],
                   np.asarray(lp["ax"], dtype=float)[order], np.asarray(lp["ay"], dtype=float)[order],
                   air_t, ld["landed"], *inn_args)


# ---------------------------------------------------------------- scoring

def ranks(xs):
    """Average ranks (1-based), ties share their mean rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spearman(x, y):
    """Spearman rank correlation; None if either side is constant."""
    rx, ry = ranks(list(x)), ranks(list(y))
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def spearman_ci(x, y, n=BOOT, seed=SEED):
    """Spearman rho with a seeded bootstrap 95% interval (pairs resampled)."""
    rho = spearman(x, y)
    if rho is None:
        return None
    rng = random.Random(seed)
    m = len(x)
    boots = []
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        b = spearman([x[i] for i in idx], [y[i] for i in idx])
        if b is not None:
            boots.append(b)
    return {"n": m, "rho": round(rho, 4), "ci95": [round(_pct(boots, 0.025), 4), round(_pct(boots, 0.975), 4)]}


def boot_diff(a, b, stat, n=BOOT, seed=SEED):
    """stat(a) - stat(b) with a seeded bootstrap 95% interval."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        ra = [a[rng.randrange(len(a))] for _ in a]
        rb = [b[rng.randrange(len(b))] for _ in b]
        diffs.append(stat(ra) - stat(rb))
    return {"diff": round(stat(a) - stat(b), 5), "ci95": [round(_pct(diffs, 0.025), 5), round(_pct(diffs, 0.975), 5)],
            "n": [len(a), len(b)]}


def _share(xs):
    return sum(1 for x in xs if x) / len(xs)


def usable(rows):
    """Passing, non-simulated fresh-2026 logs whose mismatch figures are usable."""
    return [r for r in rows if r.get("passed") and r.get("receiver") != "simulation"
            and r.get("lag_minus_param_ms") is not None and r.get("mm_ok") and r.get("mm_lift") is not None]


def summarise(rows):
    """The PLAN's checks, from the per-log rows."""
    use = usable(rows)
    off = [abs(float(r["lag_minus_param_ms"])) for r in use]
    lift = [float(r["mm_lift"]) for r in use]
    srows = [r for r in use if r.get("mm_slope_s") is not None]
    s0 = (spearman_ci([float(r["mm_slope_s"]) for r in srows], [float(r["lag_minus_param_ms"]) for r in srows])
          if len(srows) >= MIN_CORR else None)
    m1 = spearman_ci(off, lift) if len(use) >= MIN_CORR else None
    big = [r for r in use if abs(float(r["lag_minus_param_ms"])) > OFF_MS]
    small = [r for r in use if abs(float(r["lag_minus_param_ms"])) <= OFF_MS]
    m2 = m3 = None
    if len(big) >= MIN_GROUP and len(small) >= MIN_GROUP:
        m2 = boot_diff([float(r["mm_lift"]) for r in big], [float(r["mm_lift"]) for r in small], statistics.median)
        m3 = boot_diff([bool(r.get("mm_rejected")) for r in big], [bool(r.get("mm_rejected")) for r in small], _share)
    checks = {
        "E0": len(use) >= MIN_E0,
        "S0": (s0["rho"] >= S0_RHO) if s0 else None,
        "M1": (m1["rho"] > 0 and m1["ci95"][0] > 0) if m1 else None,
        "M2": (m2["diff"] > 0 and m2["ci95"][0] > 0) if m2 else None,
        "M3": (m3["ci95"][1] < M3_MAX) if m3 else None,
    }
    checks = {k: (None if v is None else bool(v)) for k, v in checks.items()}
    reasons = {}
    for r in rows:
        if r.get("passed") and r.get("receiver") != "simulation" and not r.get("mm_ok"):
            key = (r.get("mm_reason") or "not read").split(" (")[0]
            reasons[key] = reasons.get(key, 0) + 1
    decision = bool(checks["E0"] and checks["S0"] and checks["M1"])
    return {
        "usable": len(use),
        "mismatched": len(big),
        "matched": len(small),
        "S0_slope_vs_mismatch": s0,
        "M1_lift_vs_abs_mismatch": m1,
        "M2_lift_mismatched_minus_matched": m2,
        "M3_rejected_share_mismatched_minus_matched": m3,
        "median_lift": {"mismatched": round(statistics.median([float(r["mm_lift"]) for r in big]), 5) if big else None,
                        "matched": round(statistics.median([float(r["mm_lift"]) for r in small]), 5) if small else None},
        "rejected_share": {"mismatched": round(_share([bool(r.get("mm_rejected")) for r in big]), 4) if big else None,
                           "matched": round(_share([bool(r.get("mm_rejected")) for r in small]), 4) if small else None},
        "not_usable_reasons": reasons,
        "checks": checks,
        "decision": {"D1_checkup_line": decision, "D2_no_more_rejections_line": bool(decision and checks["M3"])},
    }


def explore(rows):
    """Breakdowns the PLAN did not predict, labelled exploratory."""
    use = usable(rows)

    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs), 5) if xs else None
    bands = {"<=25 ms": (0, 25), "25-50 ms": (25, 50), "50-100 ms": (50, 100), ">100 ms": (100, 1e9)}
    out = {"note": "not pre-registered; descriptive only", "by_abs_mismatch": {}}
    for name, (lo, hi) in bands.items():
        sel = [r for r in use if lo <= abs(float(r["lag_minus_param_ms"])) < hi or
               (lo == 0 and abs(float(r["lag_minus_param_ms"])) == 0)]
        out["by_abs_mismatch"][name] = {"n": len(sel), "median_lift": med([r["mm_lift"] for r in sel]),
                                        "median_tr_hi": med([r["mm_tr_hi"] for r in sel]),
                                        "median_p95": med([r.get("mm_p95") for r in sel])}
    signed = [r for r in use if r.get("mm_slope_s") is not None]
    out["late_vs_early"] = {
        "gps_later_than_set_n": sum(float(r["lag_minus_param_ms"]) > OFF_MS for r in use),
        "gps_earlier_than_set_n": sum(float(r["lag_minus_param_ms"]) < -OFF_MS for r in use)}
    if signed:
        out["slope_over_mismatch_median"] = med([float(r["mm_slope_s"]) / (float(r["lag_minus_param_ms"]) / 1000.0)
                                                 for r in signed if abs(float(r["lag_minus_param_ms"])) > OFF_MS])
    return out


def score(rows, out_dir, extra=None):
    summary = summarise(rows)
    summary["exploratory"] = explore(rows)
    summary.update({"mismatch_py": __version__, "seed": SEED}, **(extra or {}))
    with open(os.path.join(out_dir, "mismatch-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True)
    p.add_argument("--rescore", required=True, help="a fresh-2026 logs.jsonl with the mm_ fields")
    args = p.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.rescore, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    score(rows, args.out_dir, {"rescored_from": os.path.basename(args.rescore)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
