"""fresh.py: the receiver gap on a fresh sample. Scores
studies/receiver-2026/PLAN-fresh.md.

receiver-2026 and receiver-confirm both saw u-blox M9 receivers about 70 ms
less late than M8 and F9P receivers on PX4, but both failed their
enough-data check (too few M8 logs), so the gap is still exploratory. This
draws a new random sample of Flight Review's public logs, leaving out every
log and vehicle of fleet-2026, fleet-health-2026 and receiver-2026, and on
each log measures the lag (gps_lag.py 0.1.0), reads the receiver
(receiver.py 0.1.0) and reads the measurement grid (rate.py 0.1.0), all
unchanged.

    python fresh.py --out-dir out --exclude a.jsonl b.jsonl c.jsonl --budget-min 215 --max-logs 1000
    python fresh.py --out-dir out --rescore logs.jsonl

Downloads use fleet.py (px4-gps-lag 0.1.1): 6 s apart, stop on 403/444;
each log is deleted once read. No position is read. Vehicle ids are
published only as a hash.

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import requests

import fleet
import gps_lag as gl
import rate as rt
import receiver as rc

__version__ = "0.1.0"

SEED = 20261102
MIN_CLASS = 15          # passed logs a class needs (E1 and every comparison)
MIN_NMEA = 12           # passed NMEA logs F4 needs
GAP_MS = 20.0           # F1, F2, F4
SAME_MS = 30.0          # F3
GAIN = 0.05             # F5
CORE = ("ubx_m8", "ubx_m9", "ubx_f9p")


def draw(candidates, skip_logs, skip_vehicles):
    """receiver.py's draw with this study's seed."""
    return rc.draw(candidates, skip_logs, skip_vehicles, seed=SEED)


def _passed(rows):
    return [r for r in rows if r.get("passed") and r.get("receiver") != "simulation"
            and r.get("lag_ms") is not None]


def _lags(rows, cls=None, among=None):
    return [float(r["lag_ms"]) for r in rows
            if (cls is None or r.get("receiver") == cls) and (among is None or r.get("receiver") in among)]


def _diff(a, b, need_a=MIN_CLASS, need_b=MIN_CLASS):
    return rc.boot_diff(a, b) if len(a) >= need_a and len(b) >= need_b else None


def summarise(rows):
    """The PLAN's checks, from the per-log rows."""
    passed = _passed(rows)
    m8, m9, f9p = _lags(passed, "ubx_m8"), _lags(passed, "ubx_m9"), _lags(passed, "ubx_f9p")
    nmea, ublox = _lags(passed, "nmea"), _lags(passed, among=rt.SERIAL_UBX)

    f1, f2, f3 = _diff(m9, m8), _diff(m9, f9p), _diff(f9p, m8)
    f4 = _diff(nmea, ublox, MIN_NMEA)
    rec = rc.summarise(rows)                     # receiver.py's class table and P4 rule
    p4 = rec["P4_class_default"]
    grid = rt.summarise([dict(r, download="ok") for r in passed])   # rate.py's Q1 and Q2 rules

    e1 = all(len(_lags(passed, k)) >= MIN_CLASS for k in CORE)
    checks = {
        "E1": e1,
        "F1": (f1["diff_ms"] <= -GAP_MS and f1["ci95_ms"][1] < 0) if f1 else None,
        "F2": (f2["diff_ms"] <= -GAP_MS and f2["ci95_ms"][1] < 0) if f2 else None,
        "F3": (abs(f3["diff_ms"]) <= SAME_MS) if f3 else None,
        "F4": (f4["diff_ms"] >= GAP_MS and f4["ci95_ms"][0] > 0) if f4 else None,
        "F5": (p4["gain"] >= GAIN) if p4 else None,
        "F6": grid["checks"]["Q1"],
    }
    checks = {k: (None if v is None else bool(v)) for k, v in checks.items()}
    return {
        "attempted": len(rows),
        "downloaded": sum(r.get("download") == "ok" for r in rows),
        "passed": len(passed),
        "classes": rec["classes"],
        "n_core": {k: len(_lags(passed, k)) for k in CORE},
        "F1_m9_minus_m8": f1,
        "F2_m9_minus_f9p": f2,
        "F3_f9p_minus_m8": f3,
        "F4_nmea_minus_serial_ublox": f4,
        "F4_n": [len(nmea), len(ublox)],
        "F5_class_default": p4,
        "F6_driver_grid": grid["Q1_driver_grid"],
        "R2_m9_minus_other_at_125": grid["Q2_m9_minus_other_at_125"],
        "R2_n": grid["Q2_n"],
        "R2": grid["checks"]["Q2"],
        "not_passed_reasons": rec["not_passed_reasons"],
        "checks": checks,
        "decision": {"D1_receiver_line_in_checkup": bool(e1 and checks["F1"] and checks["F2"]),
                     "D3_nmea_note": bool(checks["F4"])},
    }


def explore(rows):
    """Breakdowns the PLAN did not predict, labelled exploratory."""
    passed = _passed(rows)
    out = {"note": "not pre-registered; descriptive only"}
    out["receiver"] = rc.explore(rows)
    out["rate"] = rt.explore([dict(r, download="ok") for r in passed])
    return out


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score(rows, out_dir, extra):
    summary = summarise(rows)
    summary["exploratory"] = explore(rows)
    summary.update({"fresh_py": __version__, "receiver_py": rc.__version__, "rate_py": rt.__version__,
                    "gps_lag": gl.__version__, "fleet": fleet.__version__, "seed": SEED}, **extra)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True)
    p.add_argument("--exclude", nargs="*", default=[])
    p.add_argument("--budget-min", type=float, default=215)
    p.add_argument("--max-logs", type=int, default=1000)
    p.add_argument("--tmp", default="/tmp/px4-gps-lag-fresh")
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
                                                             "px4-gps-lag-fresh/%s" % __version__)
    candidates, counts = fleet.load_candidates(session=session)
    skip_logs, skip_vehicles = rc.excluded(args.exclude)
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
                time.sleep(rc.DELAY_S)
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
                    row.update({k: lag.get(k) for k in rc.LAG_KEYS})
                except Exception as exc:  # a log pyulog or gps_lag cannot read
                    row.update({"passed": False, "reason": "error: %s" % str(exc)[:200]})
                try:
                    row.update(rc.read_receiver(path))
                except Exception as exc:
                    row.update({"receiver": "unknown", "receiver_source": "error: %s" % str(exc)[:200]})
                try:
                    row.update(rt.read_rate(path))
                except Exception as exc:
                    row.update({"grid_ms": None, "grid_reason": "error: %s" % str(exc)[:200]})
                os.remove(path)
                if row.get("gps_bus") == "simulation" or row.get("receiver") == "simulation":
                    row.update({"passed": False, "reason": "simulated GPS"})
            else:
                row.update({"passed": False, "reason": "download " + row["download"]})
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
            print("%d %s %s %s lag %s ms grid %s (%s)" % (len(rows), c["log_id"], row.get("receiver"),
                                                         row.get("passed"), row.get("lag_ms"), row.get("grid_ms"),
                                                         row.get("reason")), flush=True)
    score(rows, args.out_dir, {"list": counts, "excluded_logs": len(skip_logs),
                               "excluded_vehicles": len(skip_vehicles), "blocked": blocked,
                               "wall_s": round(time.time() - started, 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
