"""f9p-2026: the u-blox F9P at 5 Hz on PX4 v1.16/v1.17 (studies/f9p-2026/PLAN.md).

Scores the plan's checks from the per-log rows a fresh sample writes
(fresh2.py's logs.jsonl). Reads no flight log; standard library only.

    python f9p.py --logs logs.jsonl --out f9p-summary.json \
        [--mismatch mismatch-summary.json] [--nis nis-summary.json] [--extra f9p-extra.jsonl]

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import random
import re
import statistics

__version__ = "0.1.0"

DRAW_SEED = 20261109      # fresh2.py's sample draw (fresh-2026 used 20261102)
BOOT_SEED = 20261109      # bootstrap intervals
BOOT = 2000
MIN_F9P = 12              # E0: qualifying F9P logs at 5 Hz
MIN_M9 = 8                # P4: qualifying M9 logs at 10 Hz
DEFAULT_MS = 110.0        # PX4's default GPS delay (EKF2_GPS_DELAY up to v1.17)
MEDIAN_MIN_MS = 150.0     # P1
OFF_MS = 50.0             # P2: "more than 50 ms off", px4-gps-lag's rule D1
OFF_SHARE = 0.35          # P2
LOW_MAX_MS = 150.0        # P3: lag <= 150 is the low group
HIGH_MIN_MS = 175.0       # P3: lag >= 175 is the high group
SIDE_SHARE = 0.25         # P3: each group at least this share
GAP_SHARE = 0.15          # P3: at most this share strictly between 150 and 175
M9_GAP_MS = -50.0         # P4: median(M9 at 10 Hz) - median(F9P at 5 Hz)

_VER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(\d+))?")


def new_driver(ver):
    """True for PX4 v1.16.x and v1.17.x, any build type (development, alpha, beta, rc, release).

    PX4-GPSDrivers bbdd576 (F9P L1L2 at 200 ms, F9P L1L5 at 143 ms, others at 100 ms)
    ships in v1.16 and v1.17. v1.18 and later are left out: PX4 v1.18 moved the GPS
    delay to SENS_GPSn_DELAY, and later driver changes are not covered by this plan."""
    m = _VER.match((ver or "").strip())
    return bool(m) and int(m.group(1)) == 1 and int(m.group(2)) in (16, 17)


def _usable(row):
    return (row.get("passed") is True and row.get("lag_ms") is not None
            and row.get("reason") != "simulated GPS" and row.get("receivers") == 1
            and new_driver(row.get("ver_sw_release")))


def f9p_5hz(row):
    """A qualifying F9P log: single receiver, v1.16/v1.17, 200 ms grid, not a moving base."""
    return (_usable(row) and row.get("receiver") == "ubx_f9p" and row.get("grid_ms") == 200
            and row.get("gps_ubx_mode") in (0, None))


def m9_10hz(row):
    """A qualifying M9 log: single receiver, v1.16/v1.17, 100 ms grid."""
    return _usable(row) and row.get("receiver") == "ubx_m9" and row.get("grid_ms") == 100


def _pct(sorted_xs, q):
    return sorted_xs[int(round(q * (len(sorted_xs) - 1)))]


def boot_median(xs, seed=BOOT_SEED, n=BOOT):
    """Seeded percentile bootstrap 95% interval of the median."""
    rng = random.Random(seed)
    meds = sorted(statistics.median(rng.choices(xs, k=len(xs))) for _ in range(n))
    return [round(_pct(meds, 0.025), 1), round(_pct(meds, 0.975), 1)]


def boot_diff(a, b, seed=BOOT_SEED + 1, n=BOOT):
    """median(a) - median(b) with a seeded percentile bootstrap 95% interval."""
    rng = random.Random(seed)
    diffs = sorted(statistics.median(rng.choices(a, k=len(a))) - statistics.median(rng.choices(b, k=len(b)))
                   for _ in range(n))
    return {"diff_ms": round(statistics.median(a) - statistics.median(b), 1),
            "ci95_ms": [round(_pct(diffs, 0.025), 1), round(_pct(diffs, 0.975), 1)]}


def _check(summary, key, name):
    if not summary:
        return None
    return (summary.get("checks") or {}).get(name)


def summarise(rows, mismatch=None, nis=None):
    """The PLAN's checks, from the per-log rows."""
    f9p = [r for r in rows if f9p_5hz(r)]
    m9 = [r for r in rows if m9_10hz(r)]
    lags = [float(r["lag_ms"]) for r in f9p]
    out = {"f9p_version": __version__, "n_f9p": len(f9p), "n_m9": len(m9)}
    e0 = len(f9p) >= MIN_F9P
    checks = {"E0": e0, "P1": None, "P2": None, "P3": None, "P4": None}
    if lags:
        out["f9p_median_ms"] = round(statistics.median(lags), 1)
        out["f9p_median_ci95_ms"] = boot_median(lags)
        offs = [float(r["lag_minus_param_ms"]) for r in f9p if r.get("lag_minus_param_ms") is not None]
        out["off_base"] = len(offs)
        out["off_share"] = round(sum(1 for d in offs if d > OFF_MS) / len(offs), 4) if offs else None
        n = float(len(lags))
        out["low_share"] = round(sum(1 for x in lags if x <= LOW_MAX_MS) / n, 4)
        out["mid_share"] = round(sum(1 for x in lags if LOW_MAX_MS < x < HIGH_MIN_MS) / n, 4)
        out["high_share"] = round(sum(1 for x in lags if x >= HIGH_MIN_MS) / n, 4)
    if e0:
        checks["P1"] = out["f9p_median_ms"] >= MEDIAN_MIN_MS and out["f9p_median_ci95_ms"][0] > DEFAULT_MS
        checks["P2"] = out["off_share"] is not None and out["off_share"] >= OFF_SHARE
        checks["P3"] = (out["low_share"] >= SIDE_SHARE and out["high_share"] >= SIDE_SHARE
                        and out["mid_share"] <= GAP_SHARE)
        if len(m9) >= MIN_M9:
            d = boot_diff([float(r["lag_ms"]) for r in m9], lags)
            out["P4_m9_minus_f9p"] = d
            checks["P4"] = d["diff_ms"] <= M9_GAP_MS and d["ci95_ms"][1] < 0
    if m9:
        out["m9_median_ms"] = round(statistics.median(float(r["lag_ms"]) for r in m9), 1)
    checks["R1"] = _check(mismatch, "checks", "M2")
    checks["R2"] = _check(nis, "checks", "N1")
    out["checks"] = checks
    out["decision"] = {
        "D1_report_f9p_5hz_figure": bool(e0 and checks["P1"] and checks["P2"]),
        "D2_two_groups": None if checks["P3"] is None else ("replicated" if checks["P3"] else "not replicated"),
        "D3_withdraw_f9p_figure": checks["P1"] is False,
    }
    return out


def _group(lag):
    if lag <= LOW_MAX_MS:
        return "low"
    return "high" if lag >= HIGH_MIN_MS else "mid"


def explore(rows, extra=None):
    """Breakdowns the PLAN did not predict, labelled exploratory: one line per qualifying F9P log,
    with the fields that might separate the two groups, and counts by each field."""
    extra = {e.get("log_id"): e for e in (extra or [])}
    per_log = []
    for r in rows:
        if not f9p_5hz(r):
            continue
        e = extra.get(r.get("log_id"), {})
        per_log.append({
            "log_id": r.get("log_id"), "lag_ms": r.get("lag_ms"), "group": _group(float(r["lag_ms"])),
            "lag_minus_param_ms": r.get("lag_minus_param_ms"), "ver_sw_release": r.get("ver_sw_release"),
            "fix_type_max": r.get("fix_type_max"), "gps_bus": r.get("gps_bus"), "sys_hw": r.get("sys_hw"),
            "mav_type": r.get("mav_type"), "gps_device_id": r.get("gps_device_id"),
            "params": e.get("params"), "sats_median": e.get("sats_median"), "messages": e.get("messages"),
        })
    by = {}
    for field in ("fix_type_max", "gps_bus", "sys_hw", "mav_type", "gps_device_id"):
        counts = {}
        for p in per_log:
            k = str(p.get(field))
            counts.setdefault(k, {"low": 0, "mid": 0, "high": 0})[p["group"]] += 1
        by[field] = counts
    return {"label": "exploratory, not predicted", "per_log": per_log, "by_field": by}


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_json(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mismatch")
    ap.add_argument("--nis")
    ap.add_argument("--extra")
    args = ap.parse_args(argv)
    rows = load_rows(args.logs)
    extra = load_rows(args.extra) if args.extra else None
    out = summarise(rows, _load_json(args.mismatch), _load_json(args.nis))
    out["explore"] = explore(rows, extra)
    out["rows_read"] = len(rows)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "explore"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
