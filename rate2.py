"""rate2.py: scores studies/receiver-2026/PLAN-rate2.md (rate2-2026) on the
fresh-2026 sample's logs.jsonl. It reads no log: the measurement grid of every
fresh log comes from rate.py 0.1.0's read_rate, which fresh.py already runs.

rate-2026 expected each u-blox class to run at the interval PX4 v1.15.4's
driver asks for. On PX4 v1.16 and v1.17 that driver (PX4-GPSDrivers
bbdd576, 2025-01-05, "ublox update F9P output rates") asks for something
else: 100 ms by default (so the M9 runs at 10 Hz), 200 ms for an F9P L1L2 and
143 ms for an F9P L1L5. This scores the corrected, release-aware expectation.

    python rate2.py --logs fresh/logs.jsonl --out rate2-summary.json

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import re

__version__ = "0.1.0"

CORE = ("ubx_m8", "ubx_m9", "ubx_f9p")
MIN_CLASS = 8          # G0: gridded, era-known passing logs per core class
DRIVER_SHARE = 0.80    # G1
GAP_MS = 20.0          # G2
MIN_G2 = 8

_VER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(\d+))?")


def era(ver):
    """'old' (PX4 v1.12-v1.15 driver), 'new' (v1.16-v1.17 driver) or None.

    The type number after the dash is PX4's release type (0 development,
    64 alpha, 128 beta, 192 release candidate; no suffix: release). A v1.15
    development build may come from main after the January 2025 driver change
    or from the 1.15 release branch before it, so it gets None. Versions
    outside v1.12-v1.17, and forks with another major number, get None."""
    if not ver:
        return None
    m = _VER.match(str(ver).strip())
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2))
    typ = 255 if m.group(4) is None else int(m.group(4))
    if major != 1:
        return None
    if 12 <= minor <= 14:
        return "old"
    if minor == 15:
        return "old" if typ != 0 else None
    if 16 <= minor <= 17:
        return "new"
    return None


def expected_ms(receiver, era_, ubx_mode=None):
    """Grid intervals PX4's driver asks for, by receiver class and era.
    old (f512678 at v1.12.3, ad769ff at v1.15.4): M8 200 (CFG-RATE path),
    M9 and M10 125, F9P 100 (or 125 when GPS_UBX_MODE is not 0).
    new (4cea5de at v1.16.0/v1.16.1, 0b96958 at v1.17.0): M8 200, M9 and M10
    100 (the default), F9P 200 (L1L2; an L1L5 at 143 ms gets no grid)."""
    if era_ not in ("old", "new"):
        return ()
    if receiver == "ubx_m8":
        return (200,)
    if receiver in ("ubx_m9", "ubx_10"):
        return (125,) if era_ == "old" else (100,)
    if receiver == "ubx_f9p":
        if era_ == "new":
            return (200,)
        return (100,) if not ubx_mode else (100, 125)
    return ()


def passing(rows):
    return [r for r in rows if r.get("passed") and r.get("lag_ms") is not None
            and r.get("receiver") not in (None, "simulation")]


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0, 1)


def summarise(rows, boot_diff):
    """The PLAN's checks. boot_diff(a, b) is receiver.py's seeded bootstrap of
    median(a) - median(b), returning {"diff_ms": .., "ci95_ms": [lo, hi]}."""
    ok = passing(rows)
    scored = [r for r in ok if r.get("grid_ms") and era(r.get("ver_sw_release"))]
    core = {}
    for k in CORE:
        g = [r for r in scored if r["receiver"] == k]
        on = sum(r["grid_ms"] in expected_ms(k, era(r.get("ver_sw_release")), r.get("gps_ubx_mode")) for r in g)
        by_era = {}
        for e in ("old", "new"):
            ge = [r for r in g if era(r.get("ver_sw_release")) == e]
            by_era[e] = {"n": len(ge), "on_driver": sum(
                r["grid_ms"] in expected_ms(k, e, r.get("gps_ubx_mode")) for r in ge)}
        core[k] = {"scored": len(g), "on_driver": on, "share": round(on / len(g), 4) if g else None,
                   "by_era": by_era}
    g0 = all(core[k]["scored"] >= MIN_CLASS for k in CORE)
    g1 = all(core[k]["share"] >= DRIVER_SHARE for k in CORE) if g0 else None

    new = [r for r in scored if era(r.get("ver_sw_release")) == "new"]
    m9 = [float(r["lag_ms"]) for r in new if r["receiver"] == "ubx_m9" and r["grid_ms"] == 100]
    f9 = [float(r["lag_ms"]) for r in new if r["receiver"] == "ubx_f9p" and r["grid_ms"] == 200]
    g2_gap = boot_diff(m9, f9) if len(m9) >= MIN_G2 and len(f9) >= MIN_G2 else None
    g2 = (g2_gap["diff_ms"] <= -GAP_MS and g2_gap["ci95_ms"][1] < 0) if g2_gap else None

    def lags(sel):
        xs = [float(r["lag_ms"]) for r in scored if sel(r)]
        return {"n": len(xs), "median_lag_ms": _median(xs)}
    report = {
        "m9_old_125": lags(lambda r: r["receiver"] == "ubx_m9" and era(r.get("ver_sw_release")) == "old"
                           and r["grid_ms"] == 125),
        "m9_new_100": lags(lambda r: r["receiver"] == "ubx_m9" and era(r.get("ver_sw_release")) == "new"
                           and r["grid_ms"] == 100),
        "f9p_old_100": lags(lambda r: r["receiver"] == "ubx_f9p" and era(r.get("ver_sw_release")) == "old"
                            and r["grid_ms"] == 100),
        "f9p_new_200": lags(lambda r: r["receiver"] == "ubx_f9p" and era(r.get("ver_sw_release")) == "new"
                            and r["grid_ms"] == 200),
        "m10_on_driver": [sum(r["grid_ms"] in expected_ms("ubx_10", era(r.get("ver_sw_release"))) for r in scored
                              if r["receiver"] == "ubx_10"),
                          sum(r["receiver"] == "ubx_10" for r in scored)],
        "era_counts": {str(e): sum(era(r.get("ver_sw_release")) == e for r in ok) for e in ("old", "new", None)},
        "f9p_new_no_grid_dt_143_to_147": sum(1 for r in ok if r.get("receiver") == "ubx_f9p" and not r.get("grid_ms")
                                             and era(r.get("ver_sw_release")) == "new"
                                             and r.get("utc_dt_mode_ms") in (140.0, 145.0, 150.0)),
    }
    checks = {"G0": g0, "G1": None if g1 is None else bool(g1), "G2": None if g2 is None else bool(g2)}
    return {
        "passing": len(ok),
        "scored_gridded_era_known": len(scored),
        "G1_driver_grid": core,
        "G2_new_m9_100_minus_f9p_200": g2_gap,
        "G2_n": [len(m9), len(f9)],
        "checks": checks,
        "decision": {"D1_rate_line_in_checkup": bool(g0 and g1),
                     "D2_rate_not_the_m9_story_on_v1_16": checks["G2"]},
        "reported": report,
        "rate2_py": __version__,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--logs", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    import receiver as rc
    with open(args.logs, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    summary = summarise(rows, rc.boot_diff)
    summary["receiver_py"] = rc.__version__
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
