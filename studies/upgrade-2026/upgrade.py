"""upgrade.py: does the same PX4 multicopter's GPS lag drop when it moves from PX4 v1.16 to v1.17?

px4-gps-lag study upgrade-2026 (pre-registered in studies/upgrade-2026/PLAN.md). PX4's
rc.mc_defaults set GPS_UBX_DYNMODEL 6 (u-blox 'airborne <1g') for every multicopter up to v1.16;
PX4 PR #24831 removed that, so from v1.17 multicopters get the parameter default, 7 (<2g). A
default set with `param set-default` is not saved, so a vehicle that never set the parameter by
hand changes model when its firmware is upgraded. That makes the upgrade a natural experiment
inside one vehicle.

The script reads Flight Review's public log list once and keeps real multicopter logs of at least
120 s with a vehicle id, on a v1.16 or v1.17 build that is not a development build. It visits the
vehicles that have logs on both releases in a seeded random order. For each, it downloads that
vehicle's v1.16 logs in a seeded order until one passes gps_lag.py's checks with a serial u-blox
receiver (at most 3 tries), then its v1.17 logs until one passes with the same u-blox device type
(at most 3 tries). Logs are downloaded one at a time, 6 s apart, and deleted once measured. No
position is read. Vehicle ids are published only as a hash.

    python upgrade.py --out-dir out [--budget-min 180] [--max-vehicles 60] [--max-downloads 400]

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import statistics
import time

__version__ = "0.1.0"

DBINFO = "https://review.px4.io/dbinfo"
DOWNLOAD = "https://review.px4.io/download"
USER_AGENT = ("px4-gps-lag-upgrade/%s (MV2 of Munim, Inc.; mv2@munimtech.com; "
              "research on public logs)" % __version__)
SEED = 20261113            # vehicle order and log order
BOOT_SEED = 20261114       # bootstrap intervals
RESAMPLES = 2000
MIN_DURATION_S = 120
MAX_BYTES = 80 * 1000 * 1000
DELAY_S = 6.0
TRIES = 3
PRE, POST = "v1.16", "v1.17"
SERIAL_BUS = 5
# PX4 GPS driver device types for u-blox receivers (bits 16-23 of device_id)
UBLOX_DEVTYPES = {0xA5: "u-blox", 0xA6: "u-blox 6", 0xA7: "u-blox 7", 0xA8: "M8", 0xA9: "M9",
                  0xAA: "F9P", 0xAC: "M10"}
NOT_MULTICOPTER = ("vtol", "helicopter", "fixed", "wing", "rover", "boat", "submarine", "airship")


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- the public list

def is_multicopter(mav_type):
    t = str(mav_type or "").lower()
    if not t or any(w in t for w in NOT_MULTICOPTER):
        return False
    return "rotor" in t or "copter" in t


def release_series(value):
    """('v1.16', kind) from Flight Review's ver_sw_release text such as 'v1.16.0 255' or
    'v1.16.0 release'; kind is 'dev', 'pre' (alpha, beta or rc), 'release' or 'unknown'.
    None if no version can be read."""
    m = re.match(r"\s*v?(\d+)\.(\d+)\.(\d+)\s*\(?\s*([A-Za-z0-9]*)", str(value or ""))
    if not m:
        return None
    major, minor, _patch, kind = m.groups()
    k = kind.lower()
    if k in ("0", "dev", "development"):
        kind = "dev"
    elif k in ("255", "release", "stable"):
        kind = "release"
    elif k.isdigit() or k in ("alpha", "beta", "rc", "candidate"):
        kind = "pre"
    else:
        kind = "unknown"
    return "v%d.%d" % (int(major), int(minor)), kind


def log_release_ok(name, series):
    """gps_lag.release_name() of the log itself ('v1.16.2' or 'v1.16.0-192'): the right
    series and not a development build ('-0')."""
    if not name or not str(name).startswith(series + "."):
        return False
    return not str(name).endswith("-0")


def vehicle_hash(uuid):
    return hashlib.sha256(str(uuid).encode()).hexdigest()[:12] if uuid else None


def eligible(entry):
    """(series, '') for a log this study may draw, else (None, why)."""
    if "SITL" in str(entry.get("sys_hw") or "").upper():
        return None, "simulation"
    if "simul" in str(entry.get("type") or "").lower():
        return None, "simulation"
    if str(entry.get("source") or "").upper() == "CI":
        return None, "CI"
    if not entry.get("log_id"):
        return None, "no log id"
    if not entry.get("vehicle_uuid"):
        return None, "no vehicle id"
    try:
        duration = float(entry.get("duration_s") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration < MIN_DURATION_S:
        return None, "shorter than %d s" % MIN_DURATION_S
    if not is_multicopter(entry.get("mav_type")):
        return None, "not a multicopter"
    rs = release_series(entry.get("ver_sw_release"))
    if rs is None or rs[0] not in (PRE, POST):
        return None, "not v1.16 or v1.17"
    if rs[1] == "dev":
        return None, "development build"
    return rs[0], ""


def group(entries):
    """{vehicle hash: {PRE: [entries], POST: [entries]}} for vehicles with logs on both, plus counts."""
    counts = {"listed": 0, "eligible": 0, "excluded": {}}
    by_vehicle = {}
    for e in entries:
        counts["listed"] += 1
        series, why = eligible(e)
        if series is None:
            counts["excluded"][why] = counts["excluded"].get(why, 0) + 1
            continue
        counts["eligible"] += 1
        v = vehicle_hash(e.get("vehicle_uuid"))
        c = {"log_id": str(e["log_id"]), "log_date": str(e.get("log_date") or ""), "vehicle": v,
             "mav_type": str(e.get("mav_type") or ""), "sys_hw": str(e.get("sys_hw") or ""),
             "series": series, "duration_s": int(float(e.get("duration_s") or 0))}
        by_vehicle.setdefault(v, {PRE: [], POST: []})[series].append(c)
    both = {v: s for v, s in by_vehicle.items() if s[PRE] and s[POST]}
    counts["vehicles_eligible"] = len(by_vehicle)
    counts["vehicles_on_both"] = len(both)
    counts["vehicles_only_pre"] = sum(1 for s in by_vehicle.values() if s[PRE] and not s[POST])
    counts["vehicles_only_post"] = sum(1 for s in by_vehicle.values() if s[POST] and not s[PRE])
    return both, counts


def plan_order(both, seed=SEED):
    """Vehicles in a seeded random order, and each vehicle's logs per release in a seeded order."""
    rng = random.Random(seed)
    order = sorted(both)
    rng.shuffle(order)
    logs = {}
    for v in order:
        logs[v] = {}
        for side in (PRE, POST):
            xs = sorted(both[v][side], key=lambda c: c["log_id"])
            rng.shuffle(xs)
            logs[v][side] = xs
    return order, logs


# ---------------------------------------------------------------- one log

def gnss_facts(params, device_ids):
    """The receiver and the parameters this study needs, from a log's initial parameters and its
    vehicle_gps_position device ids (most common non-zero id)."""
    ids = [int(i) & 0xFFFFFFFF for i in device_ids if int(i) != 0]
    dev = max(sorted(set(ids)), key=ids.count) if ids else 0
    devtype = (dev >> 16) & 0xFF
    model = params.get("GPS_UBX_DYNMODEL")
    delay = params.get("EKF2_GPS_DELAY")
    return {"device_id": dev, "devtype": "0x%02X" % devtype if dev else None,
            "receiver": UBLOX_DEVTYPES.get(devtype) if (dev & 0x7) == SERIAL_BUS else None,
            "serial_ublox": bool(dev) and (dev & 0x7) == SERIAL_BUS and devtype in UBLOX_DEVTYPES,
            "dynmodel": None if model is None else int(model),
            "param_gps_delay_ms": None if delay is None else float(delay),
            "gps_ubx_mode": None if params.get("GPS_UBX_MODE") is None else int(params["GPS_UBX_MODE"])}


def read_gnss(path):
    from pyulog import ULog
    ulog = ULog(path, ["vehicle_gps_position"], True)
    ids = []
    for d in ulog.data_list:
        if d.name == "vehicle_gps_position" and d.multi_id == 0 and "device_id" in d.data:
            ids = [int(x) for x in d.data["device_id"]]
    return gnss_facts(ulog.initial_parameters, ids)


def usable(row, series, want_devtype=None):
    """(True, 'ok') when a measured row counts for its side, else (False, why)."""
    if not row.get("passed"):
        return False, "lag: %s" % row.get("reason")
    if not log_release_ok(row.get("ver_sw_release"), series):
        return False, "log's own release is %s" % row.get("ver_sw_release")
    if not row.get("serial_ublox"):
        return False, "not a serial u-blox receiver"
    if row.get("dynmodel") is None:
        return False, "no GPS_UBX_DYNMODEL"
    if want_devtype is not None and row.get("devtype") != want_devtype:
        return False, "receiver changed (%s, was %s)" % (row.get("devtype"), want_devtype)
    return True, "ok"


# ---------------------------------------------------------------- scoring

def median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def boot_median(xs, seed=BOOT_SEED, resamples=RESAMPLES):
    """Percentile bootstrap interval (2.5, 97.5) of the median, resampling vehicles."""
    xs = list(xs)
    if len(xs) < 2:
        return None
    rng = random.Random(seed)
    meds = sorted(statistics.median(rng.choice(xs) for _ in xs) for _ in range(resamples))
    lo = meds[int(0.025 * resamples)]
    hi = meds[int(0.975 * resamples) - 1]
    return [round(lo, 1), round(hi, 1)]


def summarise(pairs, seen=frozenset()):
    """pairs: one dict per vehicle with 'pre' and 'post' rows (both usable). seen: vehicle hashes
    of px4-gps-lag's dynmodel-2026 rows."""
    d_all = [p["pre"]["lag_ms"] - p["post"]["lag_ms"] for p in pairs]
    switched = [p for p in pairs if p["pre"]["dynmodel"] == 6 and p["post"]["dynmodel"] == 7]
    unchanged = [p for p in pairs if p["pre"]["dynmodel"] == p["post"]["dynmodel"]]
    other = [p for p in pairs if p not in switched and p not in unchanged]
    d_sw = [p["pre"]["lag_ms"] - p["post"]["lag_ms"] for p in switched]
    d_un = [p["pre"]["lag_ms"] - p["post"]["lag_ms"] for p in unchanged]
    fresh = [p for p in pairs if p["vehicle"] not in seen]
    d_fresh = [p["pre"]["lag_ms"] - p["post"]["lag_ms"] for p in fresh]
    n = len(pairs)
    ci_all = boot_median(d_all)
    med_all, med_sw, med_un = median(d_all), median(d_sw), median(d_un)
    checks = {
        "E0": n >= 12,
        "U1": (med_all is not None and med_all >= 20 and ci_all is not None and ci_all[0] > 0) if n >= 12 else None,
        "U2": (len(switched) / n >= 0.5) if n >= 12 else None,
        "U3": (med_sw >= 30) if n >= 12 and len(switched) >= 8 else None,
        "U4": (abs(med_un) <= 20) if n >= 12 and len(unchanged) >= 6 else None,
    }
    if not checks["E0"]:
        decision = "D3"
    elif checks["U1"] and checks["U3"]:
        decision = "D1"
    else:
        decision = "D2"

    def side(key):
        rows = [p[key] for p in pairs]
        diffs = [r["lag_ms"] - r["param_gps_delay_ms"] for r in rows if r.get("param_gps_delay_ms") is not None]
        models = {}
        for r in rows:
            models[str(r["dynmodel"])] = models.get(str(r["dynmodel"]), 0) + 1
        return {"median_lag_ms": median([r["lag_ms"] for r in rows]), "dynmodel": models,
                "param_gps_delay_ms": sorted({r.get("param_gps_delay_ms") for r in rows
                                              if r.get("param_gps_delay_ms") is not None}),
                "share_over_50_past_setting": (round(sum(x > 50 for x in diffs) / len(diffs), 3)
                                               if diffs else None)}

    receivers = {}
    for p in pairs:
        receivers[p["pre"]["receiver"] or p["pre"]["devtype"]] = receivers.get(
            p["pre"]["receiver"] or p["pre"]["devtype"], 0) + 1
    return {
        "vehicles": n,
        "receivers": receivers,
        "diff_pre_minus_post_ms": {"all": {"n": n, "median": med_all, "ci95": ci_all},
                                   "switched_6_to_7": {"n": len(switched), "median": med_sw,
                                                       "ci95": boot_median(d_sw, BOOT_SEED + 1)},
                                   "unchanged_model": {"n": len(unchanged), "median": med_un,
                                                       "ci95": boot_median(d_un, BOOT_SEED + 2)},
                                   "other_change": {"n": len(other), "median": median(
                                       [p["pre"]["lag_ms"] - p["post"]["lag_ms"] for p in other])},
                                   "not_in_dynmodel_2026": {"n": len(fresh), "median": median(d_fresh),
                                                            "ci95": boot_median(d_fresh, BOOT_SEED + 3)}},
        "share_switched": round(len(switched) / n, 3) if n else None,
        "pre": side("pre"), "post": side("post"),
        "checks": checks, "decision": decision,
    }


# ---------------------------------------------------------------- network

def download(session, log_id, path):
    """'ok', 'missing', 'too large' or 'failed'. Raises Blocked on 403/444."""
    import requests
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
                if int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
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


def measure(path):
    import gps_lag as gl
    row = {}
    try:
        row.update(gl.measure(gl.read_log(path)))
    except Exception as exc:  # a log pyulog or gps_lag cannot read
        row.update({"passed": False, "reason": "error: %s" % str(exc)[:200]})
    try:
        row.update(read_gnss(path))
    except Exception as exc:
        row.update({"serial_ublox": False, "gnss_error": str(exc)[:200]})
    for k in ("lag_s", "se_s"):
        row.pop(k, None)
    return row


def draw(order, logs, fetch, write, max_vehicles=60, max_downloads=400, out_of_time=lambda: False,
         sleep=lambda s: None):
    """Visit vehicles in order. fetch(candidate) returns a row with 'download' ('ok' or why not)
    and, when ok, the measured fields; it may raise Blocked. write(row) records every attempt.
    Returns {'pairs', 'downloads', 'visited', 'stop', 'blocked'}."""
    pairs, downloads, visited, stop, blocked = [], 0, 0, None, None
    for vi, v in enumerate(order):
        if len(pairs) >= max_vehicles:
            stop = "max vehicles"
            break
        visited = vi + 1
        got = {}
        for side in (PRE, POST):
            want = got[PRE]["devtype"] if side == POST else None
            for c in logs[v][side][:TRIES]:
                if downloads >= max_downloads:
                    stop = "max downloads"
                    break
                if out_of_time():
                    stop = "budget"
                    break
                if downloads:
                    sleep(DELAY_S)
                downloads += 1
                row = dict(c, attempt=downloads, vehicle_rank=vi + 1, side=side)
                try:
                    row.update(fetch(c))
                except Blocked as exc:
                    blocked = stop = "blocked: %s" % exc
                    break
                if row.get("download") == "ok":
                    ok, why = usable(row, side, want)
                else:
                    ok, why = False, "download %s" % row.get("download")
                row["counts"], row["why"] = ok, why
                write(row)
                if ok:
                    got[side] = row
                    break
            if stop or side not in got:
                break
        if PRE in got and POST in got:
            pairs.append({"vehicle": v, "pre": got[PRE], "post": got[POST]})
        if stop:
            break
    else:
        stop = "list exhausted"
    return {"pairs": pairs, "downloads": downloads, "visited": visited, "stop": stop, "blocked": blocked}


def plain(o):
    """json.dumps default: numpy scalars and arrays as plain Python values."""
    if hasattr(o, "item") and not hasattr(o, "__len__"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError("not JSON serializable: %r" % type(o))


def load_seen(path):
    seen = set()
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    v = json.loads(line).get("vehicle")
                    if v:
                        seen.add(v)
    return frozenset(seen)


def main(argv=None):
    import ijson
    import requests
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--budget-min", type=float, default=180)
    ap.add_argument("--max-vehicles", type=int, default=60)
    ap.add_argument("--max-downloads", type=int, default=400)
    ap.add_argument("--seen", default="dynmodel-rows.jsonl")
    ap.add_argument("--tmp", default="/tmp/px4-upgrade")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.tmp, exist_ok=True)
    started = time.time()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    with session.get(DBINFO, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        resp.raw.decode_content = True
        both, counts = group(ijson.items(resp.raw, "item"))
    order, logs = plan_order(both)
    print(json.dumps(counts), flush=True)

    path = os.path.join(args.tmp, "log.ulg")

    def fetch(c):
        row = {"download": download(session, c["log_id"], path)}     # raises Blocked
        if row["download"] == "ok":
            row.update(measure(path))
            os.remove(path)
        return row

    deadline = started + args.budget_min * 60
    with open(os.path.join(args.out_dir, "rows.jsonl"), "w", encoding="utf-8") as out:
        def write(row):
            out.write(json.dumps(row, default=plain) + "\n")
            out.flush()
            print("%d %s %s %s %s lag %s model %s (%s)" % (row["attempt"], row["vehicle"], row["side"],
                  row["log_id"], row["counts"], row.get("lag_ms"), row.get("dynmodel"), row["why"]),
                  flush=True)
        res = draw(order, logs, fetch, write, max_vehicles=args.max_vehicles,
                   max_downloads=args.max_downloads, out_of_time=lambda: time.time() > deadline,
                   sleep=time.sleep)

    pairs = res["pairs"]
    seen = load_seen(args.seen)
    summary = summarise(pairs, seen)
    summary.update({"upgrade": __version__, "seed": SEED, "boot_seed": BOOT_SEED,
                    "min_duration_s": MIN_DURATION_S, "list": counts, "downloads": res["downloads"],
                    "vehicles_visited": res["visited"], "stopped": res["stop"], "blocked": res["blocked"],
                    "dynmodel_2026_vehicles": len(seen), "wall_s": round(time.time() - started, 1)})
    with open(os.path.join(args.out_dir, "pairs.jsonl"), "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, default=plain) + "\n")
    text = json.dumps(summary, indent=1, default=plain)
    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
