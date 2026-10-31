"""confirm.py: does receiver-2026's M9 gap hold on vehicles it never saw?
Scores studies/receiver-2026/PLAN-confirm.md.

receiver-2026 found, exploratory only, that PX4 vehicles with a u-blox M9
showed about half the GPS lag of M8 and F9P vehicles. The two earlier
samples (fleet-2026, fleet-health-2026) were left out of that study, and
their lags were measured with the same gps_lag.py 0.1.0 and published before
it. This takes one passed log per vehicle from them, downloads it again,
reads its receiver class with receiver.py's read_receiver, and scores the
PLAN's checks on the published lags. The lag is measured again only to
check that it comes out the same (E0).

    python confirm.py --out-dir out --earlier fleet-2026.jsonl fleet-health-2026.jsonl --pool receiver-2026.jsonl
    python confirm.py --out-dir out --rescore logs.jsonl --pool receiver-2026.jsonl

Downloads use fleet.py (px4-gps-lag 0.1.1): 6 s apart, stop on 403/444;
each log is deleted once read. No position is read. Vehicle ids are
published only as a hash.

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time

import requests

import fleet
import gps_lag as gl
import receiver as rc

__version__ = "0.1.0"

MIN_CLASS = 10          # re-read logs a class needs (E1, C4)
GAP_MS = 20.0           # C1, C2: M9 at least this far below; C3: F9P no more than this below M8
AGREE_MS = 1.0          # E0: re-measured lag within this of the published one
AGREE_SHARE = 0.90
CORE = ("ubx_m8", "ubx_m9", "ubx_f9p")


def published_lag(r):
    """(passed, lag_ms) as published: fleet-2026 rows carry them at the top
    level, fleet-health-2026 rows under 'lag'."""
    lag = r["lag"] if isinstance(r.get("lag"), dict) else r
    return bool(lag.get("passed")), lag.get("lag_ms")


def earlier_sample(paths):
    """One passed log per vehicle (its earliest attempt), files in the order
    given; a vehicle already taken from an earlier file is not taken again.
    Logs without a vehicle id are each their own vehicle."""
    out, seen = [], set()
    for path in paths:
        study = os.path.splitext(os.path.basename(path))[0]
        best = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                passed, lag = published_lag(r)
                if not passed or lag is None:
                    continue
                key = r.get("vehicle") or "log:" + str(r["log_id"])
                if key in seen:
                    continue
                if key not in best or (r.get("attempt") or 0) < (best[key].get("attempt") or 0):
                    best[key] = r
        for key, r in best.items():
            out.append({"log_id": r["log_id"], "vehicle": r.get("vehicle"), "study": study,
                        "log_date": r.get("log_date"), "sys_hw": r.get("sys_hw"),
                        "lag_ms": float(published_lag(r)[1]),
                        "ver_sw_release": (r["lag"] if isinstance(r.get("lag"), dict) else r).get("ver_sw_release")})
        seen.update(best)
    return out


def _within(rows):
    """receiver.py's P4 rule on these rows: classes with MIN_CLASS logs, 110 ms
    against each vehicle's leave-one-out class median."""
    by = {}
    for r in rows:
        by.setdefault(r["receiver"], []).append(float(r["lag_ms"]))
    big = sorted(k for k, v in by.items() if len(v) >= MIN_CLASS and k not in ("unknown", "multiple")
                 and not k.startswith("other:"))
    pool = [r for r in rows if r["receiver"] in big]
    if not pool:
        return None, big

    def loo(r):
        others = list(by[r["receiver"]])
        others.remove(float(r["lag_ms"]))
        return statistics.median(others)
    p = {"n": len(pool), "within_50_at_110": round(rc.within_share(pool, lambda r: rc.DEFAULT_DELAY_MS), 4),
         "within_50_at_class_median": round(rc.within_share(pool, loo), 4)}
    p["gain"] = round(p["within_50_at_class_median"] - p["within_50_at_110"], 4)
    return p, big


def _classes(by):
    return {k: {"n": len(v), "median_lag_ms": rc._median(v),
                "p25": round(rc._pct(sorted(v), 0.25), 1), "p75": round(rc._pct(sorted(v), 0.75), 1)}
            for k, v in sorted(by.items())}


def pooled(rows, earlier_rows):
    """Class medians over receiver-2026's passed logs and this check's re-read logs."""
    by = {}
    for r in list(earlier_rows) + list(rows):
        by.setdefault(r.get("receiver") or "unknown", []).append(float(r["lag_ms"]))
    return {k: {"n": len(v), "median_lag_ms": rc._median(v)} for k, v in sorted(by.items())}


def summarise(rows):
    """The PLAN's checks, from the per-log rows."""
    read = [r for r in rows if r.get("download") == "ok" and r.get("receiver")
            and r["receiver"] != "simulation" and r.get("lag_ms") is not None]
    by = {}
    for r in read:
        by.setdefault(r["receiver"], []).append(float(r["lag_ms"]))
    m8, m9, f9p = (by.get(k, []) for k in CORE)
    enough = {k: len(by.get(k, [])) >= MIN_CLASS for k in CORE}

    again = [r for r in read if r.get("remeasured_lag_ms") is not None]
    agree = (sum(abs(float(r["remeasured_lag_ms"]) - float(r["lag_ms"])) <= AGREE_MS for r in again) / len(again)
             if again else None)

    c1 = rc.boot_diff(m9, m8) if enough["ubx_m9"] and enough["ubx_m8"] else None
    c2 = rc.boot_diff(m9, f9p) if enough["ubx_m9"] and enough["ubx_f9p"] else None
    c3 = rc.boot_diff(f9p, m8) if enough["ubx_f9p"] and enough["ubx_m8"] else None
    c4, big = _within(read)
    e1 = all(enough.values())
    checks = {
        "E0": (agree >= AGREE_SHARE) if agree is not None else None,
        "E1": e1,
        "C1": (c1["diff_ms"] <= -GAP_MS and c1["ci95_ms"][1] < 0) if c1 else None,
        "C2": (c2["diff_ms"] <= -GAP_MS and c2["ci95_ms"][1] < 0) if c2 else None,
        "C3": (c3["diff_ms"] >= -GAP_MS) if c3 else None,
        "C4": (c4["gain"] >= 0.05) if c4 else None,
        "C5": (statistics.median(m9) < rc.DEFAULT_DELAY_MS < min(statistics.median(m8), statistics.median(f9p)))
        if e1 else None,
    }
    checks = {k: (None if v is None else bool(v)) for k, v in checks.items()}
    downloads = {}
    for r in rows:
        downloads[r.get("download") or "?"] = downloads.get(r.get("download") or "?", 0) + 1
    return {
        "sample": len(rows),
        "downloads": downloads,
        "read": len(read),
        "classes": _classes(by),
        "compared_classes": big,
        "E0_agree_share": None if agree is None else round(agree, 4),
        "E0_remeasured": len(again),
        "C1_m9_minus_m8": c1,
        "C2_m9_minus_f9p": c2,
        "C3_f9p_minus_m8": c3,
        "C4_class_default": c4,
        "checks": checks,
        "decision": {"D1_class_line_in_checkup": bool(checks["E1"] and checks["C1"] and checks["C2"])},
    }


def explore(rows):
    read = [r for r in rows if r.get("download") == "ok" and r.get("receiver")
            and r["receiver"] != "simulation" and r.get("lag_ms") is not None]

    def groups(key):
        out = {}
        for r in read:
            out.setdefault(key(r), []).append(float(r["lag_ms"]))
        return {k: {"n": len(v), "median_lag_ms": rc._median(v)} for k, v in sorted(out.items())}
    return {"note": "not pre-registered; descriptive only",
            "by_receiver_and_study": groups(lambda r: "%s %s" % (r["receiver"], r.get("study"))),
            "by_receiver_and_release": groups(lambda r: "%s %s" % (r["receiver"], rc._major(r)))}


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score(rows, out_dir, extra, pool_path=None):
    summary = summarise(rows)
    summary["exploratory"] = explore(rows)
    if pool_path:
        earlier = [r for r in load_rows(pool_path) if r.get("passed") and r.get("lag_ms") is not None
                   and r.get("receiver") != "simulation"]
        read = [r for r in rows if r.get("download") == "ok" and r.get("receiver")
                and r["receiver"] != "simulation" and r.get("lag_ms") is not None]
        summary["exploratory"]["pooled_with_receiver_2026"] = pooled(read, earlier)
    summary.update({"confirm_py": __version__, "receiver_py": rc.__version__, "gps_lag": gl.__version__,
                    "fleet": fleet.__version__}, **extra)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True)
    p.add_argument("--earlier", nargs="*", default=[])
    p.add_argument("--pool", help="receiver-2026's logs.jsonl, for the pooled (exploratory) medians")
    p.add_argument("--budget-min", type=float, default=120)
    p.add_argument("--tmp", default="/tmp/px4-gps-lag-confirm")
    p.add_argument("--rescore", help="score an existing logs.jsonl instead of downloading")
    args = p.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    if args.rescore:
        score(load_rows(args.rescore), args.out_dir, {"rescored_from": os.path.basename(args.rescore)}, args.pool)
        return 0
    os.makedirs(args.tmp, exist_ok=True)
    started = time.time()
    session = requests.Session()
    session.headers["User-Agent"] = fleet.USER_AGENT.replace("px4-gps-lag/%s" % fleet.__version__,
                                                             "px4-gps-lag-confirm/%s" % __version__)
    queue = earlier_sample(args.earlier)
    print("%d vehicles to re-read" % len(queue), flush=True)

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
                    lag = gl.measure(gl.read_log(path))
                    row.update({"remeasured_lag_ms": lag.get("lag_ms"), "remeasured_passed": lag.get("passed")})
                except Exception as exc:  # a log pyulog or gps_lag cannot read
                    row.update({"remeasured_lag_ms": None, "remeasured_error": str(exc)[:200]})
                try:
                    row.update(rc.read_receiver(path))
                except Exception as exc:
                    row.update({"receiver": "unknown", "receiver_source": "error: %s" % str(exc)[:200]})
                os.remove(path)
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
            print("%d %s %s %s published %s re-measured %s" % (len(rows), c["log_id"], row["download"],
                                                               row.get("receiver"), row["lag_ms"],
                                                               row.get("remeasured_lag_ms")), flush=True)
    score(rows, args.out_dir, {"blocked": blocked, "not_reached_in_budget": out_of_time,
                               "wall_s": round(time.time() - started, 1)}, args.pool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
