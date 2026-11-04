"""dynconf: an exploratory follow-up to dynmodel-2026 (NOT pre-registered).

PX4's own defaults tie GPS_UBX_DYNMODEL to the vehicle type and release: rc.mc_defaults set 6 for
multicopters up to v1.16 (removed by PX4 PR #24831, first in v1.17), rc.fw_defaults sets 8 for
fixed wings, and everything else keeps the parameter default 7. So dynmodel-2026's model-6 logs
are mostly multicopters on v1.16 or older. This script re-scores the same graded logs within
matched strata (receiver, vehicle class, release) to see how much of the +46 ms survives.

    python dynconf.py --map dynmap.txt --sample receiver-2026=r.jsonl --sample fresh-2026=f.jsonl \
        --sample f9p-2026=g.jsonl --seen-extra f9p-extra.jsonl --out dynconf-summary.json

dynmap.txt: one line per dynmodel-2026 row, "<first 8 hex of log_id> <GPS_UBX_DYNMODEL>",
transcribed from dynmodel-rows.jsonl. The script rebuilds dynmodel-2026's graded set with
dynmodel.py 0.1.0 and stops unless it reproduces the published summary exactly.

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import random
import re
import statistics
import sys

import dynmodel as dm

__version__ = "0.1.0"
SEED = 20261114
BOOT = 2000
MC_TYPES = {"quadrotor", "hexarotor", "octorotor", "tricopter", "coaxial helicopter", "dodecarotor", "decarotor"}
_VER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")

# what dynmodel-2026 published (dynmodel-summary.json); the rebuild must match these
EXPECT = {"graded": 244, "graded_dyn6": 106, "graded_dyn7": 60, "K1": 45.6, "K2": 43.4}


def mav_class(t):
    t = (t or "").strip().lower()
    if "vtol" in t:
        return "vtol"
    if t.startswith("fixed wing"):
        return "fw"
    if t in MC_TYPES or t.endswith("rotor"):
        return "mc"
    return "other"


def minor(ver):
    m = _VER.match((ver or "").strip())
    if not m or int(m.group(1)) != 1:
        return None
    return int(m.group(2))


def minor_group(mi):
    if mi is None:
        return "unknown"
    if mi <= 14:
        return "<=1.14"
    if mi >= 18:
        return ">=1.18"
    return "1.%d" % mi


def default_dyn(cls, mi):
    """PX4's default GPS_UBX_DYNMODEL for the vehicle class and release minor (None if unknown)."""
    if cls == "fw":
        return 8
    if cls == "vtol":
        return 7
    if cls == "mc":
        if mi is None:
            return None
        return 6 if mi <= 16 else 7
    return None


def load_map(lines):
    d = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        k, v = line.split()
        if k in d:
            raise ValueError("duplicate prefix %s" % k)
        d[k] = int(v)
    return d


def build(samples, extra, dmap):
    """dynmodel-2026's records, rebuilt with dynmodel.select and the transcribed model values."""
    todo, seen = dm.select(samples, extra)
    recs, missing = list(seen), 0
    for r in todo:
        v = dmap.get(r["log_id"][:8])
        if v is None:
            missing += 1
            r["status"] = "missing"
        else:
            r["status"] = "ok"
            r["params"] = {"GPS_UBX_DYNMODEL": v}
        recs.append(r)
    return recs, missing


def join(graded, rows_by_id):
    out = []
    for r in graded:
        row = rows_by_id.get(r["log_id"], {})
        cls = mav_class(row.get("mav_type"))
        mi = minor(row.get("ver_sw_release"))
        out.append({"log_id": r["log_id"], "sample": r["sample"], "receiver": r["receiver"],
                    "lag": float(r["lag_ms"]), "dyn": dm.dyn(r), "cls": cls, "mav_type": row.get("mav_type"),
                    "minor": mi, "mgroup": minor_group(mi), "sys_hw": row.get("sys_hw"),
                    "default": default_dyn(cls, mi), "lag_minus_param": r.get("lag_minus_param_ms")})
    return out


# ---------------------------------------------------------------- matched strata

def strata(rows, group, key):
    """{key: {"a": [lags], "b": [lags]}} for strata holding both groups. group(row) -> "a", "b" or None."""
    s = {}
    for r in rows:
        g = group(r)
        if g in ("a", "b"):
            s.setdefault(key(r), {"a": [], "b": []})[g].append(r["lag"])
    return {k: v for k, v in s.items() if v["a"] and v["b"]}


def strata_est(st, pick=None):
    """Weighted mean over strata of median(a) - median(b); weight na*nb/(na+nb)."""
    num = den = 0.0
    for v in st.values():
        a, b = v["a"], v["b"]
        if pick:
            a, b = pick(a), pick(b)
        w = len(a) * len(b) / (len(a) + len(b))
        num += w * (statistics.median(a) - statistics.median(b))
        den += w
    return num / den if den else None


def strata_report(rows, group, key, seed=SEED):
    st = strata(rows, group, key)
    if not st:
        return {"strata": 0}
    est = strata_est(st)
    rng = random.Random(seed)
    boots = sorted(strata_est(st, lambda xs: rng.choices(xs, k=len(xs))) for _ in range(BOOT))
    return {"strata": len(st), "n_a": sum(len(v["a"]) for v in st.values()),
            "n_b": sum(len(v["b"]) for v in st.values()), "diff_ms": round(est, 1),
            "ci95_ms": [round(dm._pct(boots, 0.025), 1), round(dm._pct(boots, 0.975), 1)],
            "by_stratum": [{"stratum": "/".join(str(x) for x in k), "n_a": len(v["a"]),
                            "median_a": round(statistics.median(v["a"]), 1), "n_b": len(v["b"]),
                            "median_b": round(statistics.median(v["b"]), 1)} for k, v in sorted(st.items(), key=str)]}


# ---------------------------------------------------------------- least squares

def solve(A, b):
    k = len(A)
    M = [list(A[i]) + [b[i]] for i in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-9:
            return None
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        M[c] = [x / piv for x in M[c]]
        for r in range(k):
            if r != c and M[r][c] != 0:
                f = M[r][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][k] for i in range(k)]


def ols(X, y):
    k = len(X[0])
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for xi, yi in zip(X, y):
        for i in range(k):
            if xi[i]:
                b[i] += xi[i] * yi
                for j in range(k):
                    A[i][j] += xi[i] * xi[j]
    return solve(A, b)


def _most_common(xs):
    c = {}
    for x in xs:
        c[x] = c.get(x, 0) + 1
    return max(sorted(c), key=lambda k: c[k])


def design(rows, ref_receiver=None, ref_cls=None, ref_group=None):
    """One-hot design (the most common level of each factor is the reference) plus dyn6 and dyn8."""
    ref_receiver = ref_receiver or _most_common(r["receiver"] for r in rows)
    ref_cls = ref_cls or _most_common(r["cls"] for r in rows)
    ref_group = ref_group or _most_common(r["mgroup"] for r in rows)
    recv = sorted({r["receiver"] for r in rows} - {ref_receiver})
    cls = sorted({r["cls"] for r in rows} - {ref_cls})
    grp = sorted({r["mgroup"] for r in rows} - {ref_group})
    names = ["intercept"] + ["rx:" + x for x in recv] + ["cls:" + x for x in cls] + ["rel:" + x for x in grp] + ["dyn6", "dyn8"]
    X = []
    for r in rows:
        X.append([1.0] + [1.0 if r["receiver"] == x else 0.0 for x in recv]
                 + [1.0 if r["cls"] == x else 0.0 for x in cls]
                 + [1.0 if r["mgroup"] == x else 0.0 for x in grp]
                 + [1.0 if r["dyn"] == 6 else 0.0, 1.0 if r["dyn"] == 8 else 0.0])
    return names, X


def ols_report(rows, seed=SEED + 1, boot=1000):
    rows = [r for r in rows if r["dyn"] in (6, 7, 8)]
    names, X = design(rows)
    y = [r["lag"] for r in rows]
    beta = ols(X, y)
    if beta is None:
        return {"error": "singular"}
    rng = random.Random(seed)
    b6, b8 = [], []
    for _ in range(boot):
        idx = [rng.randrange(len(rows)) for _ in rows]
        bb = ols([X[i] for i in idx], [y[i] for i in idx])
        if bb is not None:
            b6.append(bb[-2])
            b8.append(bb[-1])
    b6.sort()
    b8.sort()
    return {"n": len(rows), "coef_ms": {n: round(v, 1) for n, v in zip(names, beta)},
            "dyn6_ci95_ms": [round(dm._pct(b6, 0.025), 1), round(dm._pct(b6, 0.975), 1)] if b6 else None,
            "dyn8_ci95_ms": [round(dm._pct(b8, 0.025), 1), round(dm._pct(b8, 0.975), 1)] if b8 else None,
            "boot_ok": len(b6)}


# ---------------------------------------------------------------- the analysis

def crosstab(rows):
    t = {}
    for r in rows:
        c = t.setdefault(r["cls"], {}).setdefault(r["mgroup"], {})
        c[str(r["dyn"])] = c.get(str(r["dyn"]), 0) + 1
    return t


def medians(rows, key):
    d = {}
    for r in rows:
        d.setdefault(key(r), []).append(r["lag"])
    return {"/".join(str(x) for x in k): {"n": len(v), "median_lag_ms": round(statistics.median(v), 1)}
            for k, v in sorted(d.items(), key=str)}


def analyse(rows):
    six_seven = lambda r: "a" if r["dyn"] == 6 else ("b" if r["dyn"] == 7 else None)
    known = [r for r in rows if r["default"] is not None]
    out = {
        "dynconf_py": __version__,
        "note": "exploratory, after dynmodel-2026's results were seen; not pre-registered",
        "n": len(rows),
        "mav_types": medians(rows, lambda r: (r["cls"], r["mav_type"])),
        "crosstab_class_release_dyn": crosstab(rows),
        "on_default": {"n_known": len(known), "share": round(sum(1 for r in known if r["dyn"] == r["default"]) / len(known), 4) if known else None,
                       "explicit_by_class_and_dyn": medians([r for r in known if r["dyn"] != r["default"]], lambda r: (r["cls"], r["dyn"]))},
        "medians_class_dyn": medians(rows, lambda r: (r["cls"], r["dyn"])),
        "medians_receiver_class_dyn": medians(rows, lambda r: (r["receiver"], r["cls"], r["dyn"])),
        # 6 minus 7, matched on more and more
        "S0_receiver": strata_report(rows, six_seven, lambda r: (r["receiver"],)),
        "S1_receiver_class": strata_report(rows, six_seven, lambda r: (r["receiver"], r["cls"])),
        "S2_receiver_class_release": strata_report(rows, six_seven, lambda r: (r["receiver"], r["cls"], r["mgroup"])),
        "S3_mc_only_receiver_release": strata_report([r for r in rows if r["cls"] == "mc"], six_seven, lambda r: (r["receiver"], r["mgroup"])),
        # who chose the value: 6 set by hand (not the default) vs 7 as default, and the reverse
        "S4_explicit6_vs_default7": strata_report([r for r in known if (r["dyn"] == 6 and r["default"] != 6) or (r["dyn"] == 7 and r["default"] == 7)],
                                                   six_seven, lambda r: (r["receiver"],)),
        "S5_default6_vs_explicit7": strata_report([r for r in known if (r["dyn"] == 6 and r["default"] == 6) or (r["dyn"] == 7 and r["default"] != 7)],
                                                   six_seven, lambda r: (r["receiver"],)),
        # does the release alone move the lag, holding the model? (v1.16 vs v1.17, same receiver/class/model)
        "R1_release16_vs_17_same_model": strata_report([r for r in rows if r["minor"] in (16, 17)],
                                                       lambda r: "a" if r["minor"] == 16 else "b",
                                                       lambda r: (r["receiver"], r["cls"], r["dyn"])),
        # 8 minus 7 within receiver and class
        "S6_dyn8_vs_7_receiver_class": strata_report(rows, lambda r: "a" if r["dyn"] == 8 else ("b" if r["dyn"] == 7 else None),
                                                     lambda r: (r["receiver"], r["cls"])),
        # vehicle class alone, holding the model at 7 (mc vs fw/vtol)
        "C1_mc_vs_other_at_dyn7": strata_report([r for r in rows if r["dyn"] == 7],
                                                lambda r: "a" if r["cls"] == "mc" else "b", lambda r: (r["receiver"],)),
        "OLS": ols_report(rows),
    }
    return out


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", required=True)
    ap.add_argument("--sample", action="append", required=True)
    ap.add_argument("--seen-extra", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    samples = []
    for spec in args.sample:
        name, _, path = spec.partition("=")
        samples.append((name, load_rows(path)))
    with open(args.map, encoding="utf-8") as f:
        dmap = load_map(f)
    recs, missing = build(samples, load_rows(args.seen_extra), dmap)
    s = dm.summarise(recs)
    got = {"graded": s["graded"], "graded_dyn6": s["graded_dyn6"], "graded_dyn7": s["graded_dyn7"],
           "K1": s["K1_all_ublox"]["median_ms"], "K2": s["K2_f9p"]["diff_ms"]}
    print(json.dumps({"map_lines": len(dmap), "missing": missing, "rebuilt": got}), flush=True)
    if missing or got != EXPECT:
        sys.exit("the rebuild does not reproduce dynmodel-2026's summary: %s" % json.dumps(got))
    rows_by_id = {}
    for _, rows in samples:
        for row in rows:
            rows_by_id.setdefault(row.get("log_id"), row)
    rows = join(dm.graded(recs), rows_by_id)
    out = analyse(rows)
    out["rebuilt"] = got
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
