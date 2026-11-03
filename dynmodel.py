"""dynmodel-2026: does the u-blox dynamic platform model (GPS_UBX_DYNMODEL) change the GPS lag
PX4 sees? (studies/dynmodel-2026/PLAN.md)

Two steps, standard library only:

    python dynmodel.py collect --sample receiver-2026=r.jsonl --sample fresh-2026=f.jsonl \
        --sample f9p-2026=g.jsonl --seen-extra f9p-extra.jsonl --out dynmodel-rows.jsonl [--budget-min 150]
    python dynmodel.py score --rows dynmodel-rows.jsonl --out dynmodel-summary.json

collect: for every usable u-blox serial log in the published per-log rows of earlier samples,
reads only the start of the log from PX4 Flight Review: the ULog definitions section, which
holds the initial parameters. It stops reading at the first data-section message and keeps
only GPS-related parameters (GPS_*, SER_GPS*, SENS_GPS*, EKF2_GPS_*). No flight data,
position or console message is read. Logs are 6 s apart; the pass stops at the first block
(403/429/444). Logs whose parameters were already looked at (f9p-2026's f9p-extra.jsonl)
are copied as "seen" and never scored.
score: the plan's checks, from collect's rows.

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import random
import re
import statistics
import struct
import sys
import time

__version__ = "0.1.0"

URL = "https://review.px4.io/download?log=%s"
USER_AGENT = "px4-gps-lag dynmodel/0.1.0 (MV2 of Munim, Inc.; mv2@munimtech.com)"
SPACING_S = 6.0
MAX_BYTES = 16 << 20        # never read more than 16 MB of one log
CHUNK = 1 << 16
ORDER_SEED = 20261111       # download order (so a cut-off hits every sample alike)
BOOT_SEED = 20261112        # bootstrap intervals
BOOT = 2000

UBX = ("ubx_m8", "ubx_m9", "ubx_f9p", "ubx_generic", "ubx_10")
PARAM_PREFIXES = ("GPS_", "SER_GPS", "SENS_GPS", "EKF2_GPS_")
LOW_DYN = 6                 # GPS_UBX_DYNMODEL 6: airborne with <1g acceleration
DEFAULT_DYN = 7             # PX4's default: airborne with <2g acceleration

MIN_LOW = 12                # E0: graded logs at 6
MIN_DEFAULT = 60            # E0: graded logs at 7
MIN_REF = 5                 # a receiver class needs this many 7-logs to be a reference
K1_MIN_MS = 30.0
K2_MIN_MS = 40.0
K2_MIN_LOW = 5
K2_MIN_DEFAULT = 10
K3_SHARE = 0.80
K3_MIN = 10
K3_MIN_LOW = 3
K4_MIN_MS = 20.0
K4_MIN_LOW = 8
LOW_MAX_MS = 150.0          # f9p-2026's low group
HIGH_MIN_MS = 175.0         # f9p-2026's high group
OFF_MS = 50.0

READ = ("ok", "incomplete")
MAGIC = b"ULog\x01\x12\x35"
# ULog file format (PX4 docs, "ULog File Format"): a 16-byte header, then messages of
# uint16 msg_size, uint8 msg_type, payload. The definitions section ('B', 'F', 'I', 'M',
# 'P', 'Q') ends where the data section starts: the first 'A' (add logged message),
# 'L' / 'C' (logged string) or 'D' (data) message, as in pyulog's _read_file_definitions.
END_TYPES = frozenset(b"ALCD")
_P = 0x50                   # 'P': parameter

_VER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(\d+))?")


# ---------------------------------------------------------------- reading the log's start

def parse_param(payload):
    """A ULog 'P' payload -> (name, value), or None.
    Layout: uint8 key_len, key 'type name' (key_len bytes), value (int32_t or float, little-endian)."""
    if not payload:
        return None
    n = payload[0]
    key = bytes(payload[1:1 + n]).decode("ascii", "replace")
    value = bytes(payload[1 + n:])
    typ, _, name = key.partition(" ")
    if not name or len(value) < 4:
        return None
    if typ == "int32_t":
        return name, struct.unpack("<i", value[:4])[0]
    if typ == "float":
        return name, round(struct.unpack("<f", value[:4])[0], 6)
    return None


def initial_params(chunks, max_bytes=MAX_BYTES):
    """Initial parameters from a ULog byte stream, reading the definitions section only.

    Returns (params, complete). complete is False if the stream ended, or max_bytes was
    reached, before the first data-section message. Raises ValueError if the stream does
    not start like a ULog file."""
    buf = bytearray()
    pos = 0
    total = 0
    started = False
    params = {}
    for chunk in chunks:
        buf += chunk
        total += len(chunk)
        if not started:
            if len(buf) < 16:
                continue
            if bytes(buf[:7]) != MAGIC:
                raise ValueError("not a ULog file")
            pos = 16
            started = True
        while len(buf) - pos >= 3:
            size = buf[pos] | (buf[pos + 1] << 8)
            mtype = buf[pos + 2]
            if mtype in END_TYPES:
                return params, True
            if len(buf) - pos - 3 < size:
                break
            if mtype == _P:
                kv = parse_param(buf[pos + 3:pos + 3 + size])
                if kv:
                    params[kv[0]] = kv[1]
            pos += 3 + size
        if pos:
            del buf[:pos]
            pos = 0
        if total >= max_bytes:
            break
    return params, False


def pick_params(params):
    """The GPS-related parameters, sorted by name."""
    return {k: params[k] for k in sorted(params) if k.startswith(PARAM_PREFIXES)}


def fetch(log_id):
    """Reads the start of one public log from PX4 Flight Review; closes the connection after the definitions."""
    import urllib.request
    req = urllib.request.Request(URL % log_id, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        def chunks():
            while True:
                b = resp.read(CHUNK)
                if not b:
                    return
                yield b
        return initial_params(chunks())


# ---------------------------------------------------------------- which logs

def new_driver(ver):
    """PX4 v1.16.x or v1.17.x, any build type (f9p.py 0.1.0's rule)."""
    m = _VER.match((ver or "").strip())
    return bool(m) and int(m.group(1)) == 1 and int(m.group(2)) in (16, 17)


def usable(row):
    """A passing, non-simulated log with exactly one GPS, a u-blox receiver PX4 identified, on a serial bus."""
    return (row.get("passed") is True and row.get("lag_ms") is not None
            and row.get("reason") != "simulated GPS" and row.get("receivers") == 1
            and row.get("receiver") in UBX and row.get("gps_bus") == "serial")


def f9p_5hz(row):
    """f9p-2026's qualifying F9P log: single receiver, v1.16/v1.17, 200 ms grid, not a moving base."""
    return (row.get("passed") is True and row.get("lag_ms") is not None
            and row.get("reason") != "simulated GPS" and row.get("receivers") == 1
            and new_driver(row.get("ver_sw_release")) and row.get("receiver") == "ubx_f9p"
            and row.get("grid_ms") == 200 and row.get("gps_ubx_mode") in (0, None))


def select(samples, extra=None):
    """samples: [(name, rows)] in the plan's order. Returns (todo, seen): the usable logs to read,
    in a seeded random order, and those whose parameters are in f9p-extra.jsonl (never scored)."""
    extra = {e.get("log_id"): e for e in (extra or []) if e.get("log_id")}
    todo, seen, ids = [], [], set()
    for si, (name, rows) in enumerate(samples):
        for ri, r in enumerate(rows):
            if not usable(r) or r.get("log_id") in ids:
                continue
            ids.add(r["log_id"])
            rec = {"sample": name, "sample_index": si, "row_index": ri, "log_id": r["log_id"],
                   "vehicle": r.get("vehicle"), "receiver": r["receiver"], "lag_ms": float(r["lag_ms"]),
                   "lag_minus_param_ms": r.get("lag_minus_param_ms"), "ver_sw_release": r.get("ver_sw_release"),
                   "grid_ms": r.get("grid_ms"), "gps_ubx_mode": r.get("gps_ubx_mode"), "f9p_5hz": f9p_5hz(r)}
            if r["log_id"] in extra:
                rec["status"] = "seen (f9p-extra)"
                rec["params"] = pick_params(extra[r["log_id"]].get("params") or {})
                seen.append(rec)
            else:
                todo.append(rec)
    random.Random(ORDER_SEED).shuffle(todo)
    return todo, seen


def collect(todo, fetch_fn, out, sleep=time.sleep, clock=time.time, budget_s=150 * 60, spacing=SPACING_S):
    """Reads each log's parameters; writes one JSON line per log (read or not). Returns status counts."""
    import urllib.error
    t0 = clock()
    blocked = None
    failures = 0
    requested = 0
    counts = {}
    for rec in todo:
        if blocked:
            rec["status"] = "not attempted (%s)" % blocked
        elif clock() - t0 > budget_s:
            rec["status"] = "not attempted (time budget)"
        else:
            if requested:
                sleep(spacing)
            requested += 1
            try:
                params, complete = fetch_fn(rec["log_id"])
                rec["params"] = pick_params(params)
                rec["status"] = "ok" if complete else "incomplete"
                failures = 0
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429, 444):
                    blocked = "blocked: http %d" % exc.code
                    rec["status"] = "not read (%s)" % blocked
                else:
                    rec["status"] = "http %d" % exc.code
            except ValueError as exc:
                rec["status"] = "error: %s" % str(exc)[:200]
            except Exception as exc:   # one bad log must not stop the pass; five in a row do
                rec["status"] = "error: %s: %s" % (type(exc).__name__, str(exc)[:200])
                failures += 1
                if failures >= 5:
                    blocked = "five network errors in a row"
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
        out.write(json.dumps(rec) + "\n")
        out.flush()
    return counts


# ---------------------------------------------------------------- scoring

def dyn(rec):
    """GPS_UBX_DYNMODEL of a read log, or None."""
    if rec.get("status") not in READ:
        return None
    v = (rec.get("params") or {}).get("GPS_UBX_DYNMODEL")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def graded(recs):
    """Read logs with a GPS_UBX_DYNMODEL, one per vehicle (the first in the plan's sample and row order)."""
    out, vehicles = [], set()
    for r in sorted(recs, key=lambda r: (r.get("sample_index", 0), r.get("row_index", 0))):
        if dyn(r) is None:
            continue
        v = r.get("vehicle") or r.get("log_id")
        if v in vehicles:
            continue
        vehicles.add(v)
        out.append(r)
    return out


def _pct(sorted_xs, q):
    return sorted_xs[int(round(q * (len(sorted_xs) - 1)))]


def by_class(recs):
    """{receiver: {dynmodel: [lag_ms, ...]}}"""
    d = {}
    for r in recs:
        d.setdefault(r["receiver"], {}).setdefault(dyn(r), []).append(float(r["lag_ms"]))
    return d


def _residuals(classes, low, pick=None):
    res = []
    for c in sorted(classes):
        g = classes[c]
        ref, lows = g.get(DEFAULT_DYN, []), g.get(low, [])
        if len(ref) >= MIN_REF and lows:
            m = statistics.median(pick(ref) if pick else ref)
            res.extend(x - m for x in (pick(lows) if pick else lows))
    return res


def resid(classes, low=LOW_DYN, only=None, exclude=None, seed=BOOT_SEED):
    """Median of (lag - median lag of the same receiver class's 7-logs) over the class's `low`-logs,
    pooled over classes with at least MIN_REF 7-logs, with a seeded percentile bootstrap 95% interval
    (both groups resampled within each class). None if no class qualifies."""
    cl = {c: g for c, g in classes.items()
          if (only is None or c in only) and (exclude is None or c not in exclude)}
    res = _residuals(cl, low)
    if not res:
        return None
    rng = random.Random(seed)
    stats = sorted(statistics.median(_residuals(cl, low, lambda xs: rng.choices(xs, k=len(xs))))
                   for _ in range(BOOT))
    return {"n_low": len(res), "median_ms": round(statistics.median(res), 1),
            "ci95_ms": [round(_pct(stats, 0.025), 1), round(_pct(stats, 0.975), 1)]}


def boot_diff(a, b, seed=BOOT_SEED + 1):
    """median(a) - median(b) with a seeded percentile bootstrap 95% interval."""
    rng = random.Random(seed)
    diffs = sorted(statistics.median(rng.choices(a, k=len(a))) - statistics.median(rng.choices(b, k=len(b)))
                   for _ in range(BOOT))
    return {"n": [len(a), len(b)], "diff_ms": round(statistics.median(a) - statistics.median(b), 1),
            "ci95_ms": [round(_pct(diffs, 0.025), 1), round(_pct(diffs, 0.975), 1)]}


def k3(recs):
    """fresh-2026's qualifying F9P logs in its low (<= 150 ms) or high (>= 175 ms) group with a model read:
    share where 6 sits in the high group and any other model in the low group."""
    rows = [r for r in recs if r.get("sample") == "fresh-2026" and r.get("f9p_5hz") and dyn(r) is not None
            and (r["lag_ms"] <= LOW_MAX_MS or r["lag_ms"] >= HIGH_MIN_MS)]
    agree = sum(1 for r in rows if (dyn(r) == LOW_DYN) == (r["lag_ms"] >= HIGH_MIN_MS))
    n_low = sum(1 for r in rows if dyn(r) == LOW_DYN)
    table = {}
    for r in rows:
        g = "high" if r["lag_ms"] >= HIGH_MIN_MS else "low"
        table.setdefault(str(dyn(r)), {"low": 0, "high": 0})[g] += 1
    return {"n": len(rows), "n_dyn6": n_low, "agree": agree,
            "share": round(agree / len(rows), 4) if rows else None, "table": table}


def _off(recs):
    xs = [float(r["lag_minus_param_ms"]) for r in recs if r.get("lag_minus_param_ms") is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "later_than_setting_by_50": round(sum(1 for x in xs if x > OFF_MS) / len(xs), 4),
            "off_by_50_either_way": round(sum(1 for x in xs if abs(x) > OFF_MS) / len(xs), 4),
            "median_lag_minus_param_ms": round(statistics.median(xs), 1)}


def summarise(recs):
    """The plan's checks, from collect's rows."""
    g = graded(recs)
    classes = by_class(g)
    n_low = sum(1 for r in g if dyn(r) == LOW_DYN)
    n_def = sum(1 for r in g if dyn(r) == DEFAULT_DYN)
    out = {"dynmodel_py": __version__, "graded": len(g), "graded_dyn6": n_low, "graded_dyn7": n_def}
    e0 = n_low >= MIN_LOW and n_def >= MIN_DEFAULT
    checks = {"E0": e0, "K1": None, "K2": None, "K3": None, "K4": None}
    k1 = resid(classes)
    out["K1_all_ublox"] = k1
    f9 = classes.get("ubx_f9p", {})
    f6, f7 = f9.get(LOW_DYN, []), f9.get(DEFAULT_DYN, [])
    out["K2_f9p"] = boot_diff(f6, f7) if f6 and f7 else {"n": [len(f6), len(f7)]}
    out["K3_fresh_f9p_groups"] = k3(recs)
    k4 = resid(classes, exclude=("ubx_f9p",), seed=BOOT_SEED + 2)
    out["K4_other_ublox"] = k4
    if e0:
        checks["K1"] = bool(k1) and k1["median_ms"] >= K1_MIN_MS and k1["ci95_ms"][0] > 0
        if len(f6) >= K2_MIN_LOW and len(f7) >= K2_MIN_DEFAULT:
            d = out["K2_f9p"]
            checks["K2"] = d["diff_ms"] >= K2_MIN_MS and d["ci95_ms"][0] > 0
        t = out["K3_fresh_f9p_groups"]
        if t["n"] >= K3_MIN and t["n_dyn6"] >= K3_MIN_LOW:
            checks["K3"] = t["share"] >= K3_SHARE
        if k4 and k4["n_low"] >= K4_MIN_LOW:
            checks["K4"] = k4["median_ms"] >= K4_MIN_MS and k4["ci95_ms"][0] > 0
    out["checks"] = checks
    out["decision"] = {"D1": bool(e0 and checks["K1"] and checks["K2"]),
                       "D2": bool(e0 and checks["K1"] is False)}
    out["reported"] = report(recs, g, classes)
    return out


def report(recs, g, classes):
    """Breakdowns the plan does not score."""
    status = {}
    for r in recs:
        s = r.get("status", "")
        s = s if not s.startswith("error") else "error"
        status[s] = status.get(s, 0) + 1
    values = {}
    for r in g:
        values.setdefault(r["receiver"], {}).setdefault(str(dyn(r)), 0)
        values[r["receiver"]][str(dyn(r))] += 1
    medians = {c: {str(k): {"n": len(v), "median_lag_ms": round(statistics.median(v), 1)}
                   for k, v in sorted(gr.items())} for c, gr in sorted(classes.items())}
    seen = [r for r in recs if (r.get("status") or "").startswith("seen")]
    seen_tab = {}
    for r in seen:
        v = (r.get("params") or {}).get("GPS_UBX_DYNMODEL")
        seen_tab.setdefault(str(v), []).append(r["lag_ms"])
    by_sample = {}
    for r in g:
        by_sample.setdefault(r["sample"], {}).setdefault(str(dyn(r)), 0)
        by_sample[r["sample"]][str(dyn(r))] += 1
    return {
        "note": "not pre-registered; descriptive only",
        "status_counts": status,
        "read_without_dynmodel": sum(1 for r in recs if r.get("status") in READ and dyn(r) is None),
        "values_by_receiver": values,
        "graded_by_sample": by_sample,
        "median_lag_by_receiver_and_dynmodel": medians,
        "dyn8_vs_7": resid(classes, low=8, seed=BOOT_SEED + 3),
        "off_setting": {str(k): _off([r for r in g if dyn(r) == k]) for k in (6, 7, 8)},
        "seen_f9p_2026": {k: {"n": len(v), "median_lag_ms": round(statistics.median(v), 1)}
                          for k, v in sorted(seen_tab.items())},
    }


# ---------------------------------------------------------------- command line

def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--sample", action="append", required=True, help="NAME=logs.jsonl, in the plan's order")
    c.add_argument("--seen-extra")
    c.add_argument("--out", required=True)
    c.add_argument("--budget-min", type=float, default=150)
    s = sub.add_parser("score")
    s.add_argument("--rows", required=True)
    s.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        samples = []
        for spec in args.sample:
            name, _, path = spec.partition("=")
            samples.append((name, load_rows(path)))
        extra = load_rows(args.seen_extra) if args.seen_extra else None
        todo, seen = select(samples, extra)
        print("dynmodel: %d logs to read, %d already seen" % (len(todo), len(seen)), flush=True)
        with open(args.out, "w", encoding="utf-8") as out:
            for rec in seen:
                out.write(json.dumps(rec) + "\n")
            counts = collect(todo, fetch, out, budget_s=args.budget_min * 60)
        print(json.dumps(counts, indent=1), flush=True)
        return 0
    out = summarise(load_rows(args.rows))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
