"""fleet.py: measure GPS lag (gps_lag.py) on a random sample of PX4 Flight
Review's public logs and score the predictions in studies/fleet-2026/PLAN.md.

Flight Review's public logs are CC BY 4.0 (PX4 Dronecode,
docs.px4.io/main/en/dev_log/flight_log_analysis_statistical). This reads the
public log list once, draws real (non-simulated) logs of at least 4 minutes
from 2025-10-01 on in a seeded random order, at most one log per vehicle plus
a second log of up to 60 vehicles whose first log passed, and downloads them
one at a time, 6 s apart (the default spacing of Flight Review's own
download_logs.py). It stops at once if the server signals a block. Each log is
deleted as soon as it is measured; no position is read. Vehicle ids are
published only as a hash.

    python fleet.py --out-dir out --budget-min 120 --max-logs 400

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import time

import ijson
import requests

import gps_lag as gl

__version__ = "0.1.0"

DBINFO = "https://review.px4.io/dbinfo"
DOWNLOAD = "https://review.px4.io/download"
USER_AGENT = ("px4-gps-lag/%s (MV2 of Munim, Inc.; mv2@munimtech.com; "
              "research on public logs)" % __version__)
SEED = 20261030
FIRST_DATE = "2025-10-01"
MIN_DURATION_S = 240
MAX_BYTES = 80 * 1000 * 1000
DELAY_S = 6.0
MAX_REPEATS = 60
DEFAULT_DELAY_MS = 110.0


class Blocked(Exception):
    pass


def eligible(entry):
    """(True, '') for a public log this study may draw, else (False, why)."""
    date = str(entry.get("log_date") or "")
    if date < FIRST_DATE:
        return False, "before %s" % FIRST_DATE
    if "SITL" in str(entry.get("sys_hw") or "").upper():
        return False, "simulation"
    if "simul" in str(entry.get("type") or "").lower():
        return False, "simulation"
    if str(entry.get("source") or "").upper() == "CI":
        return False, "CI"
    try:
        duration = float(entry.get("duration_s") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration < MIN_DURATION_S:
        return False, "shorter than %d s" % MIN_DURATION_S
    if not entry.get("log_id"):
        return False, "no log id"
    return True, ""


def vehicle_hash(uuid):
    return hashlib.sha256(str(uuid).encode()).hexdigest()[:12] if uuid else None


def load_candidates(url=DBINFO, session=None):
    """Stream the public log list and keep the few fields of eligible logs."""
    session = session or requests.Session()
    counts = {"listed": 0, "eligible": 0, "excluded": {}}
    keep = []
    with session.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        resp.raw.decode_content = True
        for entry in ijson.items(resp.raw, "item"):
            counts["listed"] += 1
            ok, why = eligible(entry)
            if not ok:
                counts["excluded"][why] = counts["excluded"].get(why, 0) + 1
                continue
            counts["eligible"] += 1
            keep.append({
                "log_id": str(entry["log_id"]),
                "log_date": str(entry.get("log_date")),
                "vehicle": vehicle_hash(entry.get("vehicle_uuid")),
                "mav_type": str(entry.get("mav_type") or ""),
                "sys_hw": str(entry.get("sys_hw") or ""),
                "duration_s": int(float(entry.get("duration_s") or 0)),
            })
    return keep, counts


def plan_order(candidates, seed=SEED):
    """Vehicles in a seeded random order, each with its logs in that order.
    Logs without a vehicle id are each their own vehicle."""
    rng = random.Random(seed)
    shuffled = sorted(candidates, key=lambda c: c["log_id"])
    rng.shuffle(shuffled)
    order, by_vehicle = [], {}
    for c in shuffled:
        key = c["vehicle"] or "log:" + c["log_id"]
        if key not in by_vehicle:
            by_vehicle[key] = []
            order.append(key)
        by_vehicle[key].append(c)
    return order, by_vehicle


def download(session, log_id, path):
    """'ok', 'missing', 'too large' or 'failed'. Raises Blocked on 403/444."""
    url = DOWNLOAD + "?log=" + log_id
    for attempt in range(5):
        try:
            with session.get(url, stream=True, timeout=600) as r:
                if r.status_code in (403, 444):
                    raise Blocked("HTTP %d" % r.status_code)
                if r.status_code == 404:
                    return "missing"
                if r.status_code == 503:
                    try:
                        wait = float(r.headers.get("Retry-After"))
                    except (TypeError, ValueError):
                        wait = min(30 * 2 ** attempt, 300)
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    time.sleep(10)
                    continue
                size = int(r.headers.get("Content-Length") or 0)
                if size > MAX_BYTES:
                    return "too large"
                n = 0
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        n += len(chunk)
                        if n > MAX_BYTES:
                            break
                        f.write(chunk)
                if n > MAX_BYTES:
                    os.remove(path)
                    return "too large"
                return "ok"
        except requests.RequestException:
            time.sleep(10)
    return "failed"


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def _quantile(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def summarise(rows):
    """Fleet figures and the PLAN's checks, from the per-log rows."""
    passed = [r for r in rows if r.get("passed")]
    lags = [r["lag_ms"] for r in passed]
    vehicles = {r.get("vehicle") or "log:" + r["log_id"] for r in passed}
    with_param = [r for r in passed if r.get("param_gps_delay_ms") is not None]
    diffs = [r["lag_ms"] - r["param_gps_delay_ms"] for r in with_param]
    at_default = [r for r in with_param if abs(r["param_gps_delay_ms"] - DEFAULT_DELAY_MS) < 0.5]
    bus = {}
    for r in passed:
        bus.setdefault(r.get("gps_bus") or "unknown", []).append(r["lag_ms"])
    first_two = {}
    for r in passed:
        if r.get("vehicle"):
            first_two.setdefault(r["vehicle"], []).append(r["lag_ms"])
    repeats = [abs(v[0] - v[1]) for v in first_two.values() if len(v) >= 2]
    reasons = {}
    for r in rows:
        if not r.get("passed"):
            reasons[r.get("reason") or "?"] = reasons.get(r.get("reason") or "?", 0) + 1

    n_serial = len(bus.get("serial", []))
    n_uavcan = len(bus.get("uavcan", []))
    share_over_50 = (sum(abs(d) > 50 for d in diffs) / len(diffs)) if diffs else None
    share_default = (len(at_default) / len(with_param)) if with_param else None
    median_lag = _median(lags)
    median_se = _median([r.get("se_ms") for r in passed])
    checks = {
        "E1": len(passed) >= 80 and len(vehicles) >= 50,
        "P1": median_lag is not None and 40 <= median_lag <= 160,
        "P2": share_over_50 is not None and share_over_50 >= 0.20,
        "P3": share_default is not None and share_default >= 0.70,
        "P4": ((statistics.median(bus["uavcan"]) > statistics.median(bus["serial"]))
               if n_serial >= 15 and n_uavcan >= 15 else None),
        "P5": (statistics.median(repeats) <= 25 if len(repeats) >= 15 else None),
        "P6": median_se is not None and median_se <= 10,
    }
    return {
        "attempted": len(rows),
        "downloaded": sum(r.get("download") == "ok" for r in rows),
        "passed": len(passed),
        "vehicles_passed": len(vehicles),
        "lag_ms": {"median": median_lag, "p10": _quantile(lags, 0.10), "p25": _quantile(lags, 0.25),
                   "p75": _quantile(lags, 0.75), "p90": _quantile(lags, 0.90),
                   "min": min(lags) if lags else None, "max": max(lags) if lags else None},
        "median_se_ms": median_se,
        "param": {"n": len(with_param), "share_default_110": share_default,
                  "values": sorted({r["param_gps_delay_ms"] for r in with_param})},
        "lag_minus_param_ms": {"median": _median(diffs), "share_abs_over_50": share_over_50},
        "by_bus": {k: {"n": len(v), "median_lag_ms": _median(v)} for k, v in sorted(bus.items())},
        "repeat_vehicles": {"n": len(repeats), "median_abs_diff_ms": _median(repeats)},
        "not_passed_reasons": reasons,
        "checks": checks,
        "decision": {"D1_suggest_param": bool(checks["E1"] and checks["P5"] is True)},
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True)
    p.add_argument("--budget-min", type=float, default=120)
    p.add_argument("--max-logs", type=int, default=400)
    p.add_argument("--tmp", default="/tmp/px4-gps-lag")
    args = p.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.tmp, exist_ok=True)
    started = time.time()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    candidates, counts = load_candidates(session=session)
    order, by_vehicle = plan_order(candidates)
    print("listed %d, eligible %d, vehicles %d (%.0f s)"
          % (counts["listed"], counts["eligible"], len(order), time.time() - started), flush=True)

    rows, repeats, blocked = [], 0, None
    queue = [(key, 0) for key in order]
    qi = 0
    path = os.path.join(args.tmp, "log.ulg")
    with open(os.path.join(args.out_dir, "logs.jsonl"), "w", encoding="utf-8") as out:
        while qi < len(queue) and len(rows) < args.max_logs:
            if time.time() - started > args.budget_min * 60:
                break
            key, k = queue[qi]
            qi += 1
            c = by_vehicle[key][k]
            if rows:
                time.sleep(DELAY_S)
            row = dict(c, attempt=len(rows) + 1, repeat=k > 0)
            t0 = time.time()
            try:
                row["download"] = download(session, c["log_id"], path)
            except Blocked as exc:
                blocked = str(exc)
                break
            row["download_s"] = round(time.time() - t0, 1)
            if row["download"] == "ok":
                row["size_mb"] = round(os.path.getsize(path) / 1e6, 1)
                t1 = time.time()
                try:
                    row.update(gl.measure(gl.read_log(path)))
                except Exception as exc:  # a log pyulog or gps_lag cannot read
                    row.update({"passed": False, "reason": "error: %s" % str(exc)[:200]})
                row["parse_s"] = round(time.time() - t1, 1)
                os.remove(path)
                if row.get("gps_bus") == "simulation":
                    row.update({"passed": False, "reason": "simulated GPS"})
            else:
                row.update({"passed": False, "reason": "download " + row["download"]})
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
            if (row.get("passed") and k == 0 and repeats < MAX_REPEATS
                    and c["vehicle"] and len(by_vehicle[key]) > 1):
                queue.insert(qi, (key, 1))
                repeats += 1
            print("%d %s %s lag %s ms (%s)" % (len(rows), c["log_id"], row.get("passed"),
                                              row.get("lag_ms"), row.get("reason")), flush=True)

    summary = summarise(rows)
    summary.update({"gps_lag": gl.__version__, "fleet": __version__, "seed": SEED,
                    "first_date": FIRST_DATE, "min_duration_s": MIN_DURATION_S,
                    "list": counts, "blocked": blocked,
                    "wall_s": round(time.time() - started, 1)})
    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
