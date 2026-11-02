"""floor.py: does EKF2's GPS position noise floor explain how small its GNSS
position NIS is on real flights? Scores studies/floor-2026/PLAN.md.

EKF2 fuses a GNSS horizontal position with an observation noise of
max(hacc, EKF2_GPS_P_NOISE), where hacc is the receiver's own accuracy
estimate (vehicle_gps_position.eph). Source, PX4 v1.15.4:
src/modules/ekf2/EKF/gps_control.cpp, Ekf::updateGnssPos():
    float pos_noise = math::max(gnss_sample.hacc, _params.gps_pos_noise);
and src/modules/ekf2/EKF2.cpp, UpdateGpsSample(): .hacc = vehicle_gps_position.eph.
(The noise is also capped at EKF2_NOAID_NOISE, default 10 m, when GPS is the
only horizontal aid; logs at or above 10 m are left out.)

So when eph is below EKF2_GPS_P_NOISE (default 0.5 m) the noise EKF2 assumes
is the parameter, not the receiver's estimate. Per log,

    q = eph / max(eph, EKF2_GPS_P_NOISE)        (1 when eph >= the floor)

If the real innovations scale with eph, a log's position NIS should scale
with q squared under the floor and stay flat above it. This reads only the
per-log rows written by nis.py 0.1.0 (nis_pos_median, nis_eph_median,
nis_param_EKF2_GPS_P_NOISE, ...); it downloads nothing.

    python floor.py --logs logs.jsonl --replicate fresh-logs.jsonl --out floor-summary.json

Standard library only. By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics

__version__ = "0.1.0"

SEED = 20261110
BOOT = 2000
DEFAULT_P_NOISE = 0.5   # EKF2_GPS_P_NOISE default (ekf2 module.yaml, v1.15.4)
NOAID = 10.0            # EKF2_NOAID_NOISE default; the cap described above
MIN_ALL = 150           # E0: usable logs
MIN_AT = 40             # E0: logs at or above the floor (q == 1)
MIN_UNDER = 60          # E0: logs under the floor (q < 1)
MIN_HALF = 30           # F3: logs with q <= 0.5
F1_RHO = 0.20
F2_MAX = 3.0
F3_RATIO = 2.0
F4_ABS = 0.25
FIX_NAMES = {3: "3D", 4: "DGPS/SBAS", 5: "RTK float", 6: "RTK fixed"}


# ---------------------------------------------------------------- helpers

def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def floor_q(eph, p_noise):
    """q = eph / max(eph, p_noise); None if eph is missing or not positive,
    or if the noise EKF2 would use reaches the 10 m cap. p_noise None means
    the default 0.5 m."""
    eph = _num(eph)
    if eph is None or eph <= 0:
        return None
    pn = _num(p_noise)
    if pn is None:
        pn = DEFAULT_P_NOISE
    noise = max(eph, pn)
    if noise >= NOAID:
        return None
    return eph / noise


def ranks(xs):
    """1-based ranks, ties get their average rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not (sxx > 0 and syy > 0):
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    return pearson(ranks(xs), ranks(ys))


def slope(xs, ys):
    """Least-squares slope of ys on xs."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx > 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def _pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def boot_ci(stat, groups, seed=SEED, n=BOOT):
    """Percentile 95% interval of stat(*resampled groups); each group (a list)
    is resampled with replacement on its own. None if fewer than half the
    resamples give a value."""
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        res = [[g[rng.randrange(len(g))] for _ in range(len(g))] for g in groups]
        v = stat(*res)
        if v is not None:
            vals.append(v)
    if len(vals) < n / 2:
        return None
    return [round(_pct(vals, 0.025), 5), round(_pct(vals, 0.975), 5)]


def _r(x, nd=5):
    return None if x is None else round(x, nd)


# ---------------------------------------------------------------- rows

def items(rows):
    """Usable logs: not simulated, nis.py read them (nis_ok), a positive
    position NIS median and a q (see floor_q)."""
    out = []
    for r in rows:
        if r.get("receiver") == "simulation" or not r.get("nis_ok"):
            continue
        nis = _num(r.get("nis_pos_median"))
        if nis is None or nis <= 0:
            continue
        q = floor_q(r.get("nis_eph_median"), r.get("nis_param_EKF2_GPS_P_NOISE"))
        if q is None:
            continue
        pn = _num(r.get("nis_param_EKF2_GPS_P_NOISE"))
        out.append({"q": q, "eph": float(r["nis_eph_median"]), "nis": nis,
                    "vel": _num(r.get("nis_vel_median")), "fix": r.get("nis_fix_type_mode"),
                    "p_noise": DEFAULT_P_NOISE if pn is None else pn,
                    "receiver": r.get("receiver")})
    return out


def _sp_pairs(pairs):
    return spearman([a for a, _ in pairs], [b for _, b in pairs])


def _slope_pairs(pairs):
    return slope([a for a, _ in pairs], [b for _, b in pairs])


def _ratio(at, half):
    if not at or not half:
        return None
    m = statistics.median(half)
    return statistics.median(at) / m if m > 0 else None


def summarise(rows):
    """The PLAN's checks, from per-log rows."""
    use = items(rows)
    at = [it for it in use if it["q"] >= 1.0]
    under = [it for it in use if it["q"] < 1.0]
    half = [it for it in use if it["q"] <= 0.5]
    e0 = len(use) >= MIN_ALL and len(at) >= MIN_AT and len(under) >= MIN_UNDER

    all_pairs = [(it["q"], it["nis"]) for it in use]
    rho = spearman([p[0] for p in all_pairs], [p[1] for p in all_pairs])
    f1 = {"n": len(use), "rho": _r(rho),
          "ci95": boot_ci(_sp_pairs, [all_pairs]) if rho is not None else None}

    log_pairs = [(math.log(it["q"]), math.log(it["nis"])) for it in under]
    b = slope([p[0] for p in log_pairs], [p[1] for p in log_pairs])
    f2 = {"n": len(under), "slope": _r(b), "theory": 2.0,
          "ci95": boot_ci(_slope_pairs, [log_pairs]) if b is not None else None}

    at_nis = [it["nis"] for it in at]
    half_nis = [it["nis"] for it in half]
    ratio = _ratio(at_nis, half_nis)
    f3 = {"n_at": len(at), "n_half": len(half),
          "median_nis_at": _r(statistics.median(at_nis)) if at_nis else None,
          "median_nis_half": _r(statistics.median(half_nis)) if half_nis else None,
          "ratio": _r(ratio),
          "ci95": boot_ci(_ratio, [at_nis, half_nis]) if ratio is not None and len(half) >= MIN_HALF else None}

    rho_at = spearman([it["eph"] for it in at], [it["nis"] for it in at])
    f4 = {"n": len(at), "rho": _r(rho_at)}

    def held(cond, ready):
        return None if not (e0 and ready) else bool(cond())

    checks = {
        "E0": bool(e0),
        "F1": held(lambda: rho >= F1_RHO and f1["ci95"][0] > 0, rho is not None and f1["ci95"] is not None),
        "F2": held(lambda: f2["ci95"][0] > 0 and b <= F2_MAX, b is not None and f2["ci95"] is not None),
        "F3": held(lambda: ratio >= F3_RATIO and f3["ci95"][0] > 1.0, ratio is not None and f3["ci95"] is not None),
        "F4": held(lambda: abs(rho_at) < F4_ABS, rho_at is not None),
    }
    return {
        "usable": len(use), "at_floor_or_above": len(at), "under_floor": len(under),
        "q_at_most_half": len(half),
        "F1_spearman_q_nis": f1, "F2_loglog_slope_under_floor": f2,
        "F3_nis_ratio_at_vs_half": f3, "F4_spearman_eph_nis_at_floor": f4,
        "thresholds": {"F1_rho": F1_RHO, "F2_max": F2_MAX, "F3_ratio": F3_RATIO, "F4_abs": F4_ABS,
                       "MIN_ALL": MIN_ALL, "MIN_AT": MIN_AT, "MIN_UNDER": MIN_UNDER, "MIN_HALF": MIN_HALF},
        "checks": checks,
        "decision": {"D1": bool(e0 and checks["F1"] and checks["F2"]),
                     "D2": bool(e0 and checks["F1"] is False)},
    }


def _group(sel):
    med = lambda xs: _r(statistics.median(xs)) if xs else None
    return {"n": len(sel), "median_q": med([it["q"] for it in sel]),
            "median_eph": med([it["eph"] for it in sel]),
            "median_pos_nis": med([it["nis"] for it in sel]),
            "share_under_floor": _r(sum(1 for it in sel if it["q"] < 1.0) / len(sel), 4) if sel else None}


def explore(rows):
    """Breakdowns the PLAN does not predict (descriptive only)."""
    use = items(rows)
    out = {"note": "not pre-registered; descriptive only", "all": _group(use), "by_fix_type": {},
           "p_noise_default": _group([it for it in use if it["p_noise"] == DEFAULT_P_NOISE]),
           "p_noise_changed": _group([it for it in use if it["p_noise"] != DEFAULT_P_NOISE])}
    for code, label in FIX_NAMES.items():
        out["by_fix_type"][label] = _group([it for it in use if it["fix"] == code])
    out["by_fix_type"]["other"] = _group([it for it in use if it["fix"] not in FIX_NAMES])
    vel = [it for it in use if it["vel"] is not None and it["vel"] > 0]
    out["velocity_nis_spearman_q"] = {"n": len(vel), "rho": _r(spearman([it["q"] for it in vel],
                                                                         [it["vel"] for it in vel]))}
    return out


def _read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--logs", required=True, help="the graded sample's logs.jsonl (nis_ fields)")
    p.add_argument("--replicate", default=None, help="an earlier sample's logs.jsonl, reported separately")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    rows = _read(args.logs)
    out = {"floor_py": __version__, "seed": SEED, "graded": summarise(rows), "graded_explore": explore(rows)}
    if args.replicate:
        rep = _read(args.replicate)
        out["replication"] = {"note": "earlier sample, reported only, not graded",
                              "summary": summarise(rep), "explore": explore(rep)}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
