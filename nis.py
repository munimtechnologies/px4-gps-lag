"""nis.py: are EKF2's GNSS innovations as small, and as independent from one
logged sample to the next, as EKF2's own variances say? Scores
studies/nis-2026/PLAN.md.

PX4 RFC #28837 argues, from simulation, that EKF2 treats GNSS samples as
independent although real GNSS errors are correlated for seconds to minutes,
so its normalised innovation squared (NIS) sits far below 1 and its gate is
far wider than the real innovations. This reads, per real flight log, the
horizontal GNSS position and velocity innovations (estimator_innovations)
and their variances (estimator_innovation_variances), in flight and while
EKF2 fuses GPS, and computes:

- NIS per sample, both axes: (innov_n^2 / var_n + innov_e^2 / var_e) / 2.
  For a consistent filter this is chi-square(2)/2: median ln 2 = 0.693,
  mean 1.
- The autocorrelation of the normalised innovations innov / sqrt(var) at
  1, 2, 5, 10 and 20 s (a consistent filter's innovations are white: about
  0 at every lag), and the lag where it first falls below 1/e.

    python nis.py --out-dir out --rescore logs.jsonl

Per-log reading (read_nis) is called by fresh_nis.py on each fresh-2026
log. No position is read: innovations are differences, not locations.

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

SEED = 20261104
LAGS_S = (1.0, 2.0, 5.0, 10.0, 20.0)
LAG_TOL = 0.25          # s, how far a pair may sit from the exact lag
MATCH_TOL = 0.3         # s, innovation sample <-> variance sample
MIN_SAMPLES = 60        # usable in-flight samples a log needs (about 30 s)
MIN_PAIRS = 30          # pairs one axis needs for one autocorrelation
CONSISTENT = math.log(2.0)   # median of chi-square(2)/2
LOW = CONSISTENT / 2.0       # N1 / N2 threshold, 0.3466
W_MIN = 0.2             # W1 / W2 threshold on the 1 s autocorrelation
MIN_E0 = 60
MIN_FLEET = 30          # logs a fleet figure needs
BOOT = 2000
INV_E = math.exp(-1.0)
DEFAULT_GATE = 5.0      # EKF2_GPS_P_GATE / _V_GATE default (module.yaml v1.15.4)
TOPICS = ("estimator_innovations", "estimator_innovation_variances", "vehicle_land_detected",
          "vehicle_gps_position", "estimator_status_flags")
PARAMS = ("EKF2_GPS_P_NOISE", "EKF2_GPS_P_GATE", "EKF2_GPS_V_NOISE", "EKF2_GPS_V_GATE")


# ---------------------------------------------------------------- helpers

def nearest(t_src, t_q, tol):
    """Index into sorted t_src of the sample nearest each t_q; -1 where none
    lies within tol. Ties go to the earlier sample."""
    t_src = np.asarray(t_src, dtype=float)
    t_q = np.asarray(t_q, dtype=float)
    out = np.full(t_q.shape, -1, dtype=np.int64)
    if len(t_src) == 0:
        return out
    j = np.searchsorted(t_src, t_q)
    lo = np.clip(j - 1, 0, len(t_src) - 1)
    hi = np.clip(j, 0, len(t_src) - 1)
    pick = np.where(np.abs(t_src[hi] - t_q) < np.abs(t_src[lo] - t_q), hi, lo)
    ok = np.abs(t_src[pick] - t_q) <= tol
    out[ok] = pick[ok]
    return out


def last_at(t_src, x_src, t_q):
    """x_src of the last sample at or before each t_q; nan before the first."""
    t_src = np.asarray(t_src, dtype=float)
    x_src = np.asarray(x_src, dtype=float)
    t_q = np.asarray(t_q, dtype=float)
    out = np.full(t_q.shape, np.nan)
    if len(t_src) == 0:
        return out
    idx = np.searchsorted(t_src, t_q, side="right") - 1
    ok = idx >= 0
    out[ok] = x_src[idx[ok]]
    return out


def autocorr(t, za, zb, ok, lag, tol=LAG_TOL):
    """Mean over the two axes of the autocorrelation at `lag` seconds.

    Usable samples are those with ok. Each usable sample i is paired with
    the usable sample nearest t_i + lag, if within tol. Per axis,
    d = z - mean(z) over usable samples and r = mean(d_i * d_j) / mean(d^2).
    None if there are fewer than MIN_PAIRS pairs or an axis is constant."""
    t = np.asarray(t, dtype=float)
    idx = np.flatnonzero(np.asarray(ok, dtype=bool))
    if len(idx) == 0:
        return None
    tu = t[idx]
    j = nearest(tu, tu + lag, tol)
    good = j >= 0
    if int(good.sum()) < MIN_PAIRS:
        return None
    rs = []
    for z in (za, zb):
        zu = np.asarray(z, dtype=float)[idx]
        d = zu - zu.mean()
        den = float(np.mean(d * d))
        if not den > 0:
            return None
        rs.append(float(np.mean(d[good] * d[j[good]])) / den)
    return round(sum(rs) / 2.0, 5)


def tau_e(acf):
    """First lag (s) where the autocorrelation falls below 1/e, linear
    between the listed lags (lag 0 counts as 1.0). Returns (tau, above):
    tau None and above = the last lag read if it never falls below 1/e;
    (None, None) if no lag could be read."""
    prev_l, prev_r = 0.0, 1.0
    last = None
    for lag in LAGS_S:
        r = acf.get("%g" % lag)
        if r is None:
            break
        if r < INV_E:
            if prev_r == r:
                return round(lag, 4), None
            return round(prev_l + (prev_r - INV_E) * (lag - prev_l) / (prev_r - r), 4), None
        prev_l, prev_r, last = lag, r, lag
    return None, last


def _mode(xs):
    xs = np.asarray(xs, dtype=float)
    xs = xs[np.isfinite(xs)]
    if len(xs) == 0:
        return None
    vals, counts = np.unique(xs, return_counts=True)
    return int(vals[int(np.argmax(counts))])


# ---------------------------------------------------------------- per log

def metrics(inn_t, pos_n, pos_e, vel_n, vel_e, var_t, vpos_n, vpos_e, vvel_n, vvel_e,
            air_t, landed, flag_t=None, cs_gps=None, gps_t=None, fix_type=None, eph=None,
            p_gate=None, v_gate=None):
    """Per-log figures from plain arrays (times in seconds)."""
    inn_t = np.asarray(inn_t, dtype=float)
    order = np.argsort(inn_t, kind="stable")
    inn_t = inn_t[order]
    var_t = np.asarray(var_t, dtype=float)
    vorder = np.argsort(var_t, kind="stable")
    var_t = var_t[vorder]
    out = {"nis_n_inn": int(len(inn_t)), "nis_gps_flag": flag_t is not None,
           "nis_p_gate": p_gate, "nis_v_gate": v_gate}
    k = nearest(var_t, inn_t, MATCH_TOL)
    has = k >= 0
    kk = np.where(has, k, 0)
    air = last_at(air_t, landed, inn_t) == 0
    if flag_t is None:
        fused = np.ones(len(inn_t), dtype=bool)
    else:
        fused = last_at(flag_t, cs_gps, inn_t) == 1
    base = has & air & fused
    out["nis_n_base"] = int(base.sum())
    for name, (a, b, va, vb), gate in (("pos", (pos_n, pos_e, vpos_n, vpos_e), p_gate),
                                       ("vel", (vel_n, vel_e, vvel_n, vvel_e), v_gate)):
        a = np.asarray(a, dtype=float)[order]
        b = np.asarray(b, dtype=float)[order]
        if len(var_t):
            va = np.asarray(va, dtype=float)[vorder][kk]
            vb = np.asarray(vb, dtype=float)[vorder][kk]
        else:
            va = np.full(len(inn_t), np.nan)
            vb = np.full(len(inn_t), np.nan)
        ok = (base & np.isfinite(a) & np.isfinite(b) & np.isfinite(va) & np.isfinite(vb)
              & (va > 0) & (vb > 0) & ~((a == 0) & (b == 0)))
        za = np.where(ok, a / np.sqrt(np.where(va > 0, va, 1.0)), np.nan)
        zb = np.where(ok, b / np.sqrt(np.where(vb > 0, vb, 1.0)), np.nan)
        s = 0.5 * (za ** 2 + zb ** 2)
        n = int(ok.sum())
        res = {"n": n, "median": None, "mean": None, "acf": None, "tau_s": None, "tau_above_s": None,
               "gate_sd": None}
        if n >= MIN_SAMPLES:
            res["median"] = round(float(np.median(s[ok])), 5)
            mean = float(np.mean(s[ok]))
            res["mean"] = round(mean, 5)
            acf = {"%g" % lag: autocorr(inn_t, za, zb, ok, lag) for lag in LAGS_S}
            res["acf"] = acf
            res["tau_s"], res["tau_above_s"] = tau_e(acf)
            g = DEFAULT_GATE if gate is None else max(float(gate), 1.0)
            if mean > 0:
                res["gate_sd"] = round(g / math.sqrt(mean), 3)
        for key, val in res.items():
            out["nis_%s_%s" % (name, key)] = val
    out["nis_ok"] = out["nis_pos_median"] is not None
    out["nis_reason"] = None if out["nis_ok"] else (
        "no matched variance" if not has.any() else
        "landed throughout" if not (has & air).any() else
        "too few samples (%d)" % out["nis_pos_n"])
    out["nis_fix_type_mode"] = None
    out["nis_eph_median"] = None
    if gps_t is not None and fix_type is not None:
        gps_t = np.asarray(gps_t, dtype=float)
        g_air = last_at(air_t, landed, gps_t) == 0
        if g_air.any():
            out["nis_fix_type_mode"] = _mode(np.asarray(fix_type, dtype=float)[g_air])
            if eph is not None:
                e = np.asarray(eph, dtype=float)[g_air]
                e = e[np.isfinite(e)]
                if len(e):
                    out["nis_eph_median"] = round(float(np.median(e)), 4)
    return out


def _t(d):
    key = "timestamp_sample" if "timestamp_sample" in d else "timestamp"
    return np.asarray(d[key], dtype=float) / 1e6


def read_nis(path):
    """Read the topics (first instance) from a .ulg and return metrics()."""
    from pyulog import ULog
    ulog = ULog(path, list(TOPICS), True)
    got = {}
    for d in ulog.data_list:
        if d.multi_id == 0 and d.name in TOPICS:
            got[d.name] = d.data
    for name in ("estimator_innovations", "estimator_innovation_variances", "vehicle_land_detected"):
        if name not in got:
            return {"nis_ok": False, "nis_reason": "missing " + name}
    inn, var, ld = got["estimator_innovations"], got["estimator_innovation_variances"], got["vehicle_land_detected"]
    fields = ("gps_hpos[0]", "gps_hpos[1]", "gps_hvel[0]", "gps_hvel[1]")
    if any(f not in inn or f not in var for f in fields) or "landed" not in ld:
        return {"nis_ok": False, "nis_reason": "missing field"}
    params = ulog.initial_parameters
    flags = got.get("estimator_status_flags")
    flag_args = (None, None)
    if flags is not None and "cs_gps" in flags:
        flag_args = (np.asarray(flags["timestamp"], dtype=float) / 1e6, flags["cs_gps"])
    gps = got.get("vehicle_gps_position")
    gps_args = (None, None, None)
    if gps is not None and "fix_type" in gps:
        gps_args = (np.asarray(gps["timestamp"], dtype=float) / 1e6, gps["fix_type"], gps.get("eph"))
    out = metrics(_t(inn), inn["gps_hpos[0]"], inn["gps_hpos[1]"], inn["gps_hvel[0]"], inn["gps_hvel[1]"],
                  _t(var), var["gps_hpos[0]"], var["gps_hpos[1]"], var["gps_hvel[0]"], var["gps_hvel[1]"],
                  np.asarray(ld["timestamp"], dtype=float) / 1e6, ld["landed"], *flag_args, *gps_args,
                  p_gate=params.get("EKF2_GPS_P_GATE"), v_gate=params.get("EKF2_GPS_V_GATE"))
    for p in PARAMS:
        val = params.get(p)
        out["nis_param_" + p] = None if val is None else round(float(val), 4)
    return out


# ---------------------------------------------------------------- scoring

def _pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def boot_median(xs, n=BOOT, seed=SEED):
    """Median with a seeded bootstrap 95% interval."""
    rng = random.Random(seed)
    m = len(xs)
    meds = [statistics.median([xs[rng.randrange(m)] for _ in range(m)]) for _ in range(n)]
    return {"n": m, "median": round(statistics.median(xs), 5),
            "ci95": [round(_pct(meds, 0.025), 5), round(_pct(meds, 0.975), 5)]}


def usable(rows):
    """Passing, non-simulated fresh-2026 logs whose NIS figures are usable."""
    return [r for r in rows if r.get("passed") and r.get("receiver") != "simulation"
            and r.get("nis_ok") and r.get("nis_pos_median") is not None]


def _acf1(r, name):
    acf = r.get("nis_%s_acf" % name) or {}
    return acf.get("1")


def summarise(rows):
    """The PLAN's checks, from the per-log rows."""
    use = usable(rows)
    pos = [float(r["nis_pos_median"]) for r in use]
    vel = [float(r["nis_vel_median"]) for r in use if r.get("nis_vel_median") is not None]
    w_pos = [float(_acf1(r, "pos")) for r in use if _acf1(r, "pos") is not None]
    w_vel = [float(_acf1(r, "vel")) for r in use if _acf1(r, "vel") is not None]
    fig = {k: (boot_median(xs) if len(xs) >= MIN_FLEET else None)
           for k, xs in (("N1", pos), ("N2", vel), ("W1", w_pos), ("W2", w_vel))}
    checks = {
        "E0": len(use) >= MIN_E0,
        "N1": (fig["N1"]["median"] < LOW and fig["N1"]["ci95"][1] < LOW) if fig["N1"] else None,
        "N2": (fig["N2"]["median"] < LOW and fig["N2"]["ci95"][1] < LOW) if fig["N2"] else None,
        "W1": (fig["W1"]["median"] > W_MIN and fig["W1"]["ci95"][0] > W_MIN) if fig["W1"] else None,
        "W2": (fig["W2"]["median"] > W_MIN and fig["W2"]["ci95"][0] > W_MIN) if fig["W2"] else None,
    }
    checks = {k: (None if v is None else bool(v)) for k, v in checks.items()}
    reasons = {}
    for r in rows:
        if r.get("passed") and r.get("receiver") != "simulation" and not r.get("nis_ok"):
            key = (r.get("nis_reason") or "not read").split(" (")[0]
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "usable": len(use),
        "N1_position_nis_median": fig["N1"],
        "N2_velocity_nis_median": fig["N2"],
        "W1_position_autocorr_1s": fig["W1"],
        "W2_velocity_autocorr_1s": fig["W2"],
        "thresholds": {"consistent_median_nis": round(CONSISTENT, 4), "N_low": round(LOW, 4), "W_min": W_MIN},
        "not_usable_reasons": reasons,
        "checks": checks,
        "decision": {"D1_comment_on_rfc_28837": bool(checks["E0"])},
    }


def _med(xs):
    xs = [float(x) for x in xs if x is not None]
    return round(statistics.median(xs), 5) if xs else None


def _group(sel):
    out = {"n": len(sel)}
    for name in ("pos", "vel"):
        out["%s_nis_median" % name] = _med([r.get("nis_%s_median" % name) for r in sel])
        out["%s_nis_mean_median" % name] = _med([r.get("nis_%s_mean" % name) for r in sel])
        out["%s_gate_sd_median" % name] = _med([r.get("nis_%s_gate_sd" % name) for r in sel])
        out["%s_tau_s_median" % name] = _med([r.get("nis_%s_tau_s" % name) for r in sel])
        out["%s_tau_above_n" % name] = sum(1 for r in sel if r.get("nis_%s_tau_above_s" % name) is not None)
        out["%s_acf_median" % name] = {"%g" % lag: _med([(r.get("nis_%s_acf" % name) or {}).get("%g" % lag)
                                                         for r in sel]) for lag in LAGS_S}
    out["eph_median"] = _med([r.get("nis_eph_median") for r in sel])
    return out


def explore(rows):
    """Breakdowns the PLAN did not predict, labelled exploratory."""
    use = usable(rows)
    fix_names = {3: "3D", 4: "DGPS/SBAS", 5: "RTK float", 6: "RTK fixed"}
    out = {"note": "not pre-registered; descriptive only", "all": _group(use), "by_fix_type": {},
           "by_receiver": {}, "by_grid_ms": {}}
    for code, label in fix_names.items():
        out["by_fix_type"][label] = _group([r for r in use if r.get("nis_fix_type_mode") == code])
    out["by_fix_type"]["other"] = _group([r for r in use if r.get("nis_fix_type_mode") not in fix_names])
    for rec in ("ubx_m8", "ubx_m9", "ubx_f9p"):
        out["by_receiver"][rec] = _group([r for r in use if r.get("receiver") == rec])
    out["by_receiver"]["other"] = _group([r for r in use if r.get("receiver") not in ("ubx_m8", "ubx_m9", "ubx_f9p")])
    for g in (100, 125, 200):
        out["by_grid_ms"][str(g)] = _group([r for r in use if r.get("grid_ms") == g])
    out["by_grid_ms"]["other"] = _group([r for r in use if r.get("grid_ms") not in (100, 125, 200)])
    out["gps_flag_read_n"] = sum(1 for r in use if r.get("nis_gps_flag"))
    return out


def score(rows, out_dir, extra=None):
    summary = summarise(rows)
    summary["exploratory"] = explore(rows)
    summary.update({"nis_py": __version__, "seed": SEED}, **(extra or {}))
    with open(os.path.join(out_dir, "nis-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True)
    p.add_argument("--rescore", required=True, help="a fresh-2026 logs.jsonl with the nis_ fields")
    args = p.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.rescore, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    score(rows, args.out_dir, {"rescored_from": os.path.basename(args.rescore)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
