"""census.py: how many PX4 multicopters still run the u-blox dynamic model 6 after v1.17 changed
the default? (px4-gps-lag study census-2026, pre-registered in studies/census-2026/PLAN.md)

PX4's rc.mc_defaults set GPS_UBX_DYNMODEL 6 (u-blox 'airborne <1g') for every multicopter up to
v1.16. PX4 PR #24831 removed that line, so from v1.17 a multicopter gets the parameter default, 7
(<2g), unless 6 is stored in its parameters. dynmodel-2026 found model-6 logs a median 46 ms later
than model-7 logs. This census counts how many multicopters ran each model on v1.16 and on v1.17.

It reads Flight Review's public log list once and keeps real multicopter logs of at least 120 s
with a vehicle id, on a v1.16 or v1.17 build that is not a development build (upgrade.py 0.1.0's
filters). Vehicles with logs on both releases, and vehicles in dynmodel-2026's rows, are left out
of the graded draw. For each remaining vehicle (seeded order, the two releases taken in turn) it
reads one seeded-random log, and only the log's start: the ULog definitions section, which holds
the initial parameters ('P') and parameter defaults ('Q'). It stops at the first data-section
message and keeps only GPS-related parameters. No flight data, position or console message is
read. Requests are 6 s apart, and the pass stops at the first block (403/429/444).

0.1.1 (AMENDMENT-1.md, code only): Flight Review sends the list gzip-compressed, which 0.1.0 passed
to the JSON parser undecoded, so the 0.1.0 job stopped before any log was read. Responses that
start with the gzip magic bytes are now decompressed (the list and, if ever needed, a log).
Nothing in the plan's draw, measure or scoring changed.

    python census.py --out-dir out [--budget-min 170] [--target 250] [--max-tries 400] [--seen dynmodel-rows.jsonl]

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import re
import struct
import sys
import time

__version__ = "0.1.1"

DBINFO = "https://review.px4.io/dbinfo"
URL = "https://review.px4.io/download?log=%s"
USER_AGENT = ("px4-gps-lag-census/%s (MV2 of Munim, Inc.; mv2@munimtech.com; "
              "research on public logs)" % __version__)
SEED = 20261117             # vehicle order and log choice
SPACING_S = 6.0
MAX_BYTES = 16 << 20        # never read more than 16 MB of one log
CHUNK = 1 << 16
MIN_DURATION_S = 120
PRE, POST = "v1.16", "v1.17"
LOW_DYN = 6

# the plan's thresholds
E0_MIN = 200                # graded vehicles needed on each release
C1_MIN = 0.75               # v1.16: share at model 6 at least this
C2_LO, C2_HI = 0.02, 0.20   # v1.17: share at model 6 within this range
C3_MIN = 0.50               # share(v1.16) - share(v1.17) at model 6 at least this
H2_ABOVE = 0.20             # v1.17 share at 6 above this: stored 6 is common

NOT_MULTICOPTER = ("vtol", "helicopter", "fixed", "wing", "rover", "boat", "submarine", "airship")
PARAM_PREFIXES = ("GPS_", "SER_GPS", "SENS_GPS", "EKF2_GPS_")
READ = ("ok", "incomplete")
MAGIC = b"ULog\x01\x12\x35"
GZIP_MAGIC = b"\x1f\x8b"
END_TYPES = frozenset(b"ALCD")   # first data-section message types (as dynmodel.py 0.1.0)
_P = 0x50                   # 'P': parameter
_Q = 0x51                   # 'Q': parameter default (uint8 default_types, then as 'P')


# ---------------------------------------------------------------- reading responses (0.1.1)

class Prefixed:
    """A read-only stream: `head` (bytes already read) followed by the rest of `f`."""

    def __init__(self, head, f):
        self.head = bytes(head)
        self.f = f

    def read(self, n=-1):
        if n is None or n < 0:
            out = self.head + self.f.read()
            self.head = b""
            return out
        if self.head:
            out = self.head[:n]
            self.head = self.head[n:]
            if len(out) < n:
                out += self.f.read(n - len(out))
            return out
        return self.f.read(n)


def open_stream(f):
    """`f` as a stream of its decoded bytes: gzip-decompressed if it starts with the gzip magic
    bytes (Flight Review's /dbinfo does, whatever the request asks), else unchanged."""
    head = f.read(2)
    rest = Prefixed(head, f)
    if head == GZIP_MAGIC:
        return gzip.GzipFile(fileobj=rest, mode="rb")
    return rest


def chunks_of(f, size=CHUNK):
    while True:
        b = f.read(size)
        if not b:
            return
        yield b


# ---------------------------------------------------------------- the public list (upgrade.py 0.1.0)

def is_multicopter(mav_type):
    t = str(mav_type or "").lower()
    if not t or any(w in t for w in NOT_MULTICOPTER):
        return False
    return "rotor" in t or "copter" in t


def release_series(value):
    """('v1.16', kind) from Flight Review's ver_sw_release text; kind is 'dev', 'pre', 'release'
    or 'unknown'. None if no version can be read."""
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


def vehicle_hash(uuid):
    return hashlib.sha256(str(uuid).encode()).hexdigest()[:12] if uuid else None


def eligible(entry):
    """((series, kind), '') for a log this study may draw, else (None, why)."""
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
    return rs, ""


def build(entries):
    """({PRE: {vehicle: [logs]}, POST: {...}}, counts)."""
    counts = {"listed": 0, "eligible": 0, "excluded": {}}
    by_side = {PRE: {}, POST: {}}
    for e in entries:
        counts["listed"] += 1
        rs, why = eligible(e)
        if rs is None:
            counts["excluded"][why] = counts["excluded"].get(why, 0) + 1
            continue
        counts["eligible"] += 1
        v = vehicle_hash(e.get("vehicle_uuid"))
        c = {"log_id": str(e["log_id"]), "log_date": str(e.get("log_date") or ""), "vehicle": v,
             "mav_type": str(e.get("mav_type") or ""), "sys_hw": str(e.get("sys_hw") or ""),
             "series": rs[0], "kind": rs[1], "duration_s": int(float(e.get("duration_s") or 0))}
        by_side[rs[0]].setdefault(v, []).append(c)
    both = set(by_side[PRE]) & set(by_side[POST])
    counts["vehicles"] = {PRE: len(by_side[PRE]), POST: len(by_side[POST]), "on_both": len(both)}
    return by_side, counts


def plan(by_side, seen=frozenset(), seed=SEED):
    """The draw: for each release, the vehicles not on both releases and not in `seen`, in a
    seeded order, each with one seeded-random log; and the vehicles on both releases (in a seeded
    order, one v1.17 log each), read only after the graded draw. Returns {PRE: [...], POST: [...],
    'both': [...], 'left_out_seen': {PRE: n, POST: n}}."""
    rng = random.Random(seed)
    both = set(by_side[PRE]) & set(by_side[POST])
    out = {"left_out_seen": {}}
    for side in (PRE, POST):
        vs = sorted(v for v in by_side[side] if v not in both)
        out["left_out_seen"][side] = sum(1 for v in vs if v in seen)
        vs = [v for v in vs if v not in seen]
        rng.shuffle(vs)
        out[side] = [rng.choice(sorted(by_side[side][v], key=lambda c: c["log_id"])) for v in vs]
    bs = sorted(both)
    rng.shuffle(bs)
    out["both"] = [rng.choice(sorted(by_side[POST][v], key=lambda c: c["log_id"])) for v in bs]
    return out


# ---------------------------------------------------------------- reading the log's start

def parse_param(payload):
    """A ULog 'P' payload -> (name, value), or None (dynmodel.py 0.1.0).
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
    """(params, defaults, complete) from a ULog byte stream, reading the definitions section only.

    defaults: {name: {'system': v, 'config': v}} from 'Q' messages (bit 0 of default_types: the
    system default; bit 1: the default for the current configuration, e.g. the airframe).
    complete is False if the stream ended, or max_bytes was reached, before the first data-section
    message. Raises ValueError if the stream does not start like a ULog file."""
    buf = bytearray()
    pos = 0
    total = 0
    started = False
    params, defaults = {}, {}
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
                return params, defaults, True
            if len(buf) - pos - 3 < size:
                break
            body = buf[pos + 3:pos + 3 + size]
            if mtype == _P:
                kv = parse_param(body)
                if kv:
                    params[kv[0]] = kv[1]
            elif mtype == _Q and len(body) > 1:
                kv = parse_param(body[1:])
                if kv:
                    d = defaults.setdefault(kv[0], {})
                    if body[0] & 1:
                        d["system"] = kv[1]
                    if body[0] & 2:
                        d["config"] = kv[1]
            pos += 3 + size
        if pos:
            del buf[:pos]
            pos = 0
        if total >= max_bytes:
            break
    return params, defaults, False


def pick(d):
    return {k: d[k] for k in sorted(d) if k.startswith(PARAM_PREFIXES)}


def fetch(log_id):
    """Reads the start of one public log; closes the connection after the definitions."""
    import urllib.request
    req = urllib.request.Request(URL % log_id, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return initial_params(chunks_of(open_stream(resp)))


def dyn(rec):
    """GPS_UBX_DYNMODEL of a read log, or None."""
    if rec.get("status") not in READ:
        return None
    v = (rec.get("params") or {}).get("GPS_UBX_DYNMODEL")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


# ---------------------------------------------------------------- the pass

def read_one(rec, fetch_fn):
    """Fills rec['status'], 'params', 'defaults'. Returns 'blocked: ...' on 403/429/444, 'error' on
    another exception, else None."""
    import urllib.error
    try:
        params, defaults, complete = fetch_fn(rec["log_id"])
        rec["params"] = pick(params)
        rec["defaults"] = pick(defaults)
        rec["status"] = "ok" if complete else "incomplete"
        return None
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429, 444):
            rec["status"] = "not read (blocked: http %d)" % exc.code
            return "blocked: http %d" % exc.code
        rec["status"] = "http %d" % exc.code
        return None
    except ValueError as exc:
        rec["status"] = "error: %s" % str(exc)[:200]
        return None
    except Exception as exc:   # one bad log must not stop the pass; five in a row do
        rec["status"] = "error: %s: %s" % (type(exc).__name__, str(exc)[:200])
        return "error"


def run(p, fetch_fn, write, target=250, max_tries=400, sleep=time.sleep, clock=time.time,
        budget_s=170 * 60, spacing=SPACING_S):
    """The graded draw takes v1.16 and v1.17 vehicles in turn until each release has `target`
    vehicles with a model read, has had `max_tries` reads, or runs out of vehicles. Then, budget
    permitting, one v1.17 log of each vehicle on both releases (reported, not graded).
    write(rec) records every read. Returns a dict of counters and the stop reason."""
    t0 = clock()
    state = {"requested": 0, "errors_in_a_row": 0, "stop": None}
    got = {PRE: 0, POST: 0}
    tries = {PRE: 0, POST: 0}
    idx = {PRE: 0, POST: 0}

    def one(rec, group):
        if state["requested"]:
            sleep(spacing)
        state["requested"] += 1
        rec = dict(rec, group=group, order=state["requested"])
        res = read_one(rec, fetch_fn)
        if res == "error":
            state["errors_in_a_row"] += 1
            if state["errors_in_a_row"] >= 5:
                state["stop"] = "five network errors in a row"
        else:
            state["errors_in_a_row"] = 0
            if res:
                state["stop"] = res
        write(rec)
        return rec

    def side_open(side):
        return got[side] < target and tries[side] < max_tries and idx[side] < len(p[side])

    while not state["stop"] and (side_open(PRE) or side_open(POST)):
        for side in (PRE, POST):
            if state["stop"]:
                break
            if not side_open(side):
                continue
            if clock() - t0 > budget_s:
                state["stop"] = "time budget"
                break
            rec = one(p[side][idx[side]], "graded")
            idx[side] += 1
            tries[side] += 1
            if dyn(rec) is not None:
                got[side] += 1
    graded_stop = state["stop"] or "graded draw complete"
    both_read = 0
    for rec in p["both"]:
        if state["stop"]:
            break
        if clock() - t0 > budget_s:
            state["stop"] = "time budget"
            break
        one(rec, "both")
        both_read += 1
    return {"graded_with_model": dict(got), "graded_tries": dict(tries), "graded_stop": graded_stop,
            "both_read": both_read, "stop": state["stop"] or "list exhausted",
            "requests": state["requested"]}


# ---------------------------------------------------------------- scoring

def wilson(k, n, z=1.96):
    """95% Wilson score interval of k/n, or None."""
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def tally(recs):
    """{'n', 'models': {str(model): count}, 'share6', 'share6_ci95'} over records with a model read."""
    xs = [dyn(r) for r in recs if dyn(r) is not None]
    models = {}
    for m in xs:
        models[str(m)] = models.get(str(m), 0) + 1
    k6 = sum(1 for m in xs if m == LOW_DYN)
    return {"n": len(xs), "models": dict(sorted(models.items())),
            "share6": round(k6 / len(xs), 4) if xs else None, "share6_ci95": wilson(k6, len(xs))}


def summarise(recs):
    """The plan's checks and decisions, from every record written."""
    graded = [r for r in recs if r.get("group") == "graded"]
    pre = tally([r for r in graded if r.get("series") == PRE])
    post = tally([r for r in graded if r.get("series") == POST])
    e0 = pre["n"] >= E0_MIN and post["n"] >= E0_MIN
    s16, s17 = pre["share6"], post["share6"]
    checks = {"E0": e0, "C1": None, "C2": None, "C3": None}
    if e0:
        checks["C1"] = s16 >= C1_MIN
        checks["C2"] = C2_LO <= s17 <= C2_HI
        checks["C3"] = round(s16 - s17, 4) >= C3_MIN
    decisions = {"H0": not e0,
                 "H1": bool(e0 and checks["C1"] and checks["C2"] and checks["C3"]),
                 "H2": bool(e0 and s17 > H2_ABOVE),
                 "H3": bool(e0 and checks["C1"] is False)}
    return {"census": __version__, "seed": SEED,
            "graded": {PRE: pre, POST: post,
                       "difference_share6": round(s16 - s17, 4) if s16 is not None and s17 is not None else None},
            "checks": checks, "decisions": decisions, "reported": report(recs)}


def report(recs):
    """Breakdowns the plan does not score."""
    status = {}
    for r in recs:
        s = r.get("status", "")
        s = "error" if s.startswith("error") else s
        key = "%s/%s" % (r.get("group"), s)
        status[key] = status.get(key, 0) + 1
    graded = [r for r in recs if r.get("group") == "graded"]
    post = [r for r in graded if r.get("series") == POST]
    by_kind = {k: tally([r for r in post if str(r.get("kind")) == k])
               for k in sorted({str(r.get("kind")) for r in post})}
    boards6 = {}
    for r in post:
        if dyn(r) == LOW_DYN:
            boards6[r.get("sys_hw") or "?"] = boards6.get(r.get("sys_hw") or "?", 0) + 1
    q = {}
    for r in graded:
        m = dyn(r)
        if m is None:
            continue
        d = (r.get("defaults") or {}).get("GPS_UBX_DYNMODEL") or {}
        key = "%s model %s, config default %s" % (r.get("series"), m, d.get("config", "not logged"))
        q[key] = q.get(key, 0) + 1
    proto = {}
    for r in graded:
        if dyn(r) is None:
            continue
        key = "%s GPS_1_PROTOCOL %s" % (r.get("series"), (r.get("params") or {}).get("GPS_1_PROTOCOL", "absent"))
        proto[key] = proto.get(key, 0) + 1
    return {"note": "not pre-registered; descriptive only",
            "status_counts": dict(sorted(status.items())),
            "read_without_dynmodel": sum(1 for r in recs if r.get("status") in READ and dyn(r) is None),
            "v1_17_by_build_kind": by_kind,
            "v1_17_model6_boards": dict(sorted(boards6.items(), key=lambda kv: (-kv[1], kv[0]))),
            "dynmodel_vs_logged_config_default": dict(sorted(q.items())),
            "gps_1_protocol": dict(sorted(proto.items())),
            "on_both_v1_17": tally([r for r in recs if r.get("group") == "both"])}


def plain(o):
    """json.dumps default: anything with .item() or .tolist() as plain Python values; Decimal
    (from ijson) as float."""
    if hasattr(o, "item") and not hasattr(o, "__len__"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    if type(o).__name__ == "Decimal":
        return float(o)
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
    import urllib.request
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--budget-min", type=float, default=170)
    ap.add_argument("--target", type=int, default=250)
    ap.add_argument("--max-tries", type=int, default=400)
    ap.add_argument("--seen", default="dynmodel-rows.jsonl")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    started = time.time()
    seen = load_seen(args.seen)
    req = urllib.request.Request(DBINFO, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp:
        by_side, counts = build(ijson.items(open_stream(resp), "item"))
    p = plan(by_side, seen)
    counts["draw"] = {PRE: len(p[PRE]), POST: len(p[POST]), "both": len(p["both"]),
                      "left_out_seen": p["left_out_seen"], "dynmodel_2026_vehicles": len(seen)}
    print(json.dumps(counts), flush=True)
    recs = []
    with open(os.path.join(args.out_dir, "census-rows.jsonl"), "w", encoding="utf-8") as out:
        def write(rec):
            recs.append(rec)
            out.write(json.dumps(rec, default=plain) + "\n")
            out.flush()
            print("%d %s %s %s %s model %s" % (rec["order"], rec["group"], rec["series"], rec["log_id"],
                                               rec["status"], dyn(rec)), flush=True)
        res = run(p, fetch, write, target=args.target, max_tries=args.max_tries,
                  budget_s=args.budget_min * 60)
    summary = summarise(recs)
    summary.update({"list": counts, "pass": res, "wall_s": round(time.time() - started, 1)})
    text = json.dumps(summary, indent=1, default=plain)
    with open(os.path.join(args.out_dir, "census-summary.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
