"""gnss_logs.py: px4-gps-lag 0.2.0 on real PX4 main logs, which log vehicle_gnss instead of
vehicle_gps_position (px4-gps-lag study gnss-2026, pre-registered in studies/gnss-2026/PLAN.md).

PX4 PR #24399 (main since 2026-09-29) renamed the GPS topics: the selected receiver's sample is
now vehicle_gnss, with the receiver's own fields nested as 'receiver' and the velocity named
vel_north / vel_east. gps_lag.py 0.1.0 could not read those logs. 0.2.0 maps the new names to the
old ones (gnss_as_gps). Its synthetic tests pass, but no real log has been read through it. This
pass finds public PX4 main logs on Flight Review and reads them.

It reads Flight Review's public list once and keeps real logs (no simulation, no CI) of at least
60 s, dated 2026-09-29 or later, from v1.18 or newer or with no readable release. They are taken in
a fixed order: development builds first, then pre-releases, unknown and releases, newest first,
one log per vehicle. For each, it streams the log and reads only its definitions section (message
formats and initial parameters). If the formats have no vehicle_gnss, it closes the connection.
If they do (a 'main log'), it downloads the rest (at most 150 MB) to a temporary file, reads it
with gps_lag.py 0.2.0 and records the vehicle_gnss field names, the column map, the time stamps'
differences and gps_lag's result. No position is written out, and the log file is deleted after
it is read. Requests are 6 s apart, and the pass stops at the first block (403/429/444).

Before any log is read, it checks that studies/gnss-2026/PLAN.md on px4-gps-lag's main matches
the local copy (line endings normalised), waiting up to --wait-min minutes for it to appear.

    python gnss_logs.py --out-dir out [--budget-min 150] [--max-heads 300] [--max-full 30] [--wait-min 120]

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import statistics
import struct
import sys
import tempfile
import time

__version__ = "0.1.0"

DBINFO = "https://review.px4.io/dbinfo"
URL = "https://review.px4.io/download?log=%s"
PLAN_URL = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/studies/gnss-2026/PLAN.md"
USER_AGENT = ("px4-gps-lag-gnss/%s (MV2 of Munim, Inc.; mv2@munimtech.com; "
              "research on public logs)" % __version__)
SINCE = "2026-09-29"        # PX4 PR #24399 merged
MIN_SERIES = (1, 18)
MIN_DURATION_S = 60
SPACING_S = 6.0
MAX_HEAD_BYTES = 16 << 20
MAX_LOG_BYTES = 150 << 20
CHUNK = 1 << 16
KIND_ORDER = {"dev": 0, "pre": 1, "unknown": 2, None: 2, "release": 3}
PARAM_PREFIXES = ("SENS_GNSS", "SENS_GPS", "GPS_", "EKF2_GPS", "EKF2_GNSS")
MAGIC = b"ULog\x01\x12\x35"
GZIP_MAGIC = b"\x1f\x8b"
END_TYPES = frozenset(b"ALCD")   # first data-section message types (as census.py 0.1.1)
_F = 0x46                   # 'F': message format
_P = 0x50                   # 'P': parameter
FIRST_CHOICE = {"timestamp": "receiver.timestamp", "vel_n_m_s": "receiver.vel_north",
                "vel_e_m_s": "receiver.vel_east", "fix_type": "receiver.fix_type",
                "vel_ned_valid": "receiver.vel_ned_valid", "timestamp_sample": "timestamp_sample",
                "device_id": "receiver.device_id"}

# the plan's thresholds
P1_LOGS, P1_VEHICLES = 5, 3
P3_SHARE, P3_TOL_MS = 0.90, 1.0
P4_PASSED = 3
P5_MIN, P5_ABS_MS = 5, 50.0


# ---------------------------------------------------------------- reading responses (census.py 0.1.1)

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
    """`f` as a stream of its decoded bytes: gzip-decompressed if it starts with the gzip magic."""
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


# ---------------------------------------------------------------- the public list

def release_series(value):
    """((major, minor), kind) from Flight Review's ver_sw_release text (census.py 0.1.1's rule);
    kind is 'dev', 'pre', 'release' or 'unknown'. None if no version can be read."""
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
    return (int(major), int(minor)), kind


def vehicle_hash(uuid):
    return hashlib.sha256(str(uuid).encode()).hexdigest()[:12] if uuid else None


def eligible(entry):
    """(kind, '') for a log this pass may read, else (None, why)."""
    if "SITL" in str(entry.get("sys_hw") or "").upper():
        return None, "simulation"
    if "simul" in str(entry.get("type") or "").lower():
        return None, "simulation"
    if str(entry.get("source") or "").upper() == "CI":
        return None, "CI"
    if not entry.get("log_id"):
        return None, "no log id"
    if str(entry.get("log_date") or "")[:10] < SINCE:
        return None, "before %s" % SINCE
    try:
        duration = float(entry.get("duration_s") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration < MIN_DURATION_S:
        return None, "shorter than %d s" % MIN_DURATION_S
    rs = release_series(entry.get("ver_sw_release"))
    if rs is not None and rs[0] < MIN_SERIES:
        return None, "older than v1.18"
    return (rs[1] if rs else "unknown"), ""


def build(entries):
    """(candidates in the pass's order, counts)."""
    counts = {"listed": 0, "eligible": 0, "excluded": {}, "by_kind": {}}
    cands = []
    for e in entries:
        counts["listed"] += 1
        kind, why = eligible(e)
        if kind is None:
            counts["excluded"][why] = counts["excluded"].get(why, 0) + 1
            continue
        counts["eligible"] += 1
        counts["by_kind"][kind] = counts["by_kind"].get(kind, 0) + 1
        cands.append({"log_id": str(e["log_id"]), "log_date": str(e.get("log_date") or "")[:10],
                      "vehicle": vehicle_hash(e.get("vehicle_uuid")) or "log:" + str(e["log_id"]),
                      "mav_type": str(e.get("mav_type") or ""), "sys_hw": str(e.get("sys_hw") or ""),
                      "ver_sw_release": str(e.get("ver_sw_release") or ""),
                      "ver_sw": str(e.get("ver_sw") or "")[:12], "kind": kind,
                      "duration_s": int(float(e.get("duration_s") or 0))})
    cands.sort(key=lambda c: c["log_id"])
    cands.sort(key=lambda c: c["log_date"], reverse=True)
    cands.sort(key=lambda c: KIND_ORDER.get(c["kind"], 2))
    return cands, counts


# ---------------------------------------------------------------- reading one log

def parse_param(payload):
    """A ULog 'P' payload -> (name, value), or None (census.py 0.1.1)."""
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


def read_definitions(chunks, max_bytes=MAX_HEAD_BYTES):
    """(formats, params, raw, complete) from an iterator of ULog bytes. formats: {name: fields text}
    of every 'F' message; params: the initial parameters; raw: every byte taken from `chunks` so
    far; complete: the first data-section message was reached. Raises ValueError if the bytes do
    not start like a ULog file. Leaves the rest of `chunks` unread."""
    raw = bytearray()
    pos = 0
    started = False
    formats, params = {}, {}
    for chunk in chunks:
        raw += chunk
        if not started:
            if len(raw) < 16:
                continue
            if bytes(raw[:7]) != MAGIC:
                raise ValueError("not a ULog file")
            pos = 16
            started = True
        while len(raw) - pos >= 3:
            size = raw[pos] | (raw[pos + 1] << 8)
            mtype = raw[pos + 2]
            if mtype in END_TYPES:
                return formats, params, raw, True
            if len(raw) - pos - 3 < size:
                break
            body = bytes(raw[pos + 3:pos + 3 + size])
            if mtype == _F:
                name, _, fields = body.decode("ascii", "replace").partition(":")
                formats[name] = fields
            elif mtype == _P:
                kv = parse_param(body)
                if kv:
                    params[kv[0]] = kv[1]
            pos += 3 + size
        if len(raw) >= max_bytes:
            break
    return formats, params, raw, False


def pick(d):
    return {k: d[k] for k in sorted(d) if k.startswith(PARAM_PREFIXES)}


def fetch_one(log_id, path, opener=None, max_bytes=MAX_LOG_BYTES):
    """Streams one public log. Returns (info, path or None): the whole log is written to `path`
    only when its formats include vehicle_gnss and it is at most max_bytes."""
    import urllib.request
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(URL % log_id, headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=300) as resp:
        chunks = chunks_of(open_stream(resp))
        formats, params, raw, complete = read_definitions(chunks)
        info = {"head_complete": complete, "has_gnss": "vehicle_gnss" in formats,
                "has_gps_position": "vehicle_gps_position" in formats, "params": pick(params),
                "gnss_format": formats.get("vehicle_gnss"), "receiver_format": formats.get("sensor_gnss")}
        if not (complete and info["has_gnss"]):
            return info, None
        total = len(raw)
        with open(path, "wb") as f:
            f.write(raw)
            for c in chunks:
                total += len(c)
                if total > max_bytes:
                    break
                f.write(c)
    if total > max_bytes:
        os.remove(path)
        info["too_big"] = True
        return info, None
    info["bytes"] = total
    return info, path


def _median_ms(a, b, positive_b=False):
    import numpy as np
    a = np.asarray(a).astype(np.int64)
    b = np.asarray(b).astype(np.int64)
    keep = b > 0 if positive_b else np.ones(len(b), bool)
    if not np.any(keep):
        return None
    return round(float(np.median(a[keep] - b[keep])) / 1e3, 3)


def measure_file(path):
    """What this pass records about one downloaded main log (no positions)."""
    import numpy as np
    from pyulog import ULog
    import gps_lag as gl
    out = {}
    u = ULog(path, ["vehicle_gnss"], True)
    ds = [d for d in u.data_list if d.name == "vehicle_gnss"]
    out["gnss_instances"] = len(ds)
    d0 = next((d for d in ds if d.multi_id == 0), None)
    if d0 is None:
        out["read"] = "no vehicle_gnss data"
        return out
    g = d0.data
    out["gnss_fields"] = sorted(g)
    out["gnss_samples"] = int(len(g["timestamp"]))
    out["columns"] = {name: next((s for s in src if s in g), None) for name, src in gl.GNSS_COLUMNS}
    if "receiver.timestamp" in g:
        out["publish_minus_receiver_ms"] = _median_ms(g["timestamp"], g["receiver.timestamp"])
        if "timestamp_sample" in g:
            out["receiver_minus_sample_ms"] = _median_ms(g["receiver.timestamp"], g["timestamp_sample"], True)
    if "usable" in g:
        out["usable_share"] = round(float(np.mean(np.asarray(g["usable"]).astype(bool))), 4)
    if "receiver.device_id" in g:
        ids = [int(x) & 0xFFFFFFFF for x in g["receiver.device_id"] if int(x)]
        if ids:
            dev = max(sorted(set(ids)), key=ids.count)
            out["device_id"] = dev
            out["bus"] = gl.bus_type(dev)
            out["devtype"] = "0x%02X" % ((dev >> 16) & 0xFF)
    try:
        r = gl.measure(gl.read_log(path))
    except Exception as exc:
        out["read"] = "error: %s" % str(exc)[:200]
        return out
    out["read"] = "ok"
    out["gps_lag"] = {k: v for k, v in r.items() if _small(v)}
    return out


def _small(v):
    """True for a scalar, or a list or array of at most 10 values (gps_lag's result has no big ones,
    but none is written out if it ever does)."""
    n = getattr(v, "size", None)
    if n is None and isinstance(v, (list, tuple)):
        n = len(v)
    return n is None or n <= 10


def applied_ms(rec):
    """The delay PX4 applied (receiver time minus the corrected sample time), or None."""
    return (rec.get("measure") or {}).get("receiver_minus_sample_ms")


def delay_params(rec):
    p = rec.get("params") or {}
    return [float(p[k]) for k in ("SENS_GNSS0_DELAY", "SENS_GNSS1_DELAY") if k in p]


# ---------------------------------------------------------------- the pass

def wait_for_plan(local_path, get_fn, wait_s, sleep=time.sleep, clock=time.time, every_s=300):
    """True once PLAN.md on main equals the local copy (CRLF normalised), False after wait_s."""
    want = hashlib.sha256(open(local_path, "rb").read().replace(b"\r\n", b"\n")).hexdigest()
    t0 = clock()
    while True:
        try:
            got = hashlib.sha256(get_fn().replace(b"\r\n", b"\n")).hexdigest()
            if got == want:
                return True
            print("PLAN.md on main differs (%s, want %s)" % (got[:12], want[:12]), flush=True)
        except Exception as exc:
            print("PLAN.md not on main yet: %s" % str(exc)[:120], flush=True)
        if clock() - t0 >= wait_s:
            return False
        sleep(every_s)


def run(cands, fetch_fn, measure_fn, write, tmp_path, max_heads=300, max_full=30, sleep=time.sleep,
        clock=time.time, budget_s=150 * 60, spacing=SPACING_S):
    """Reads candidates in order, one per vehicle, until max_heads logs were requested, max_full
    main logs were read, the list or the budget ran out, or Flight Review blocked a request.
    write(rec) records every request."""
    import urllib.error
    t0 = clock()
    seen = set()
    state = {"requested": 0, "full": 0, "errors_in_a_row": 0, "stop": None}
    for c in cands:
        if c["vehicle"] in seen:
            continue
        if state["requested"] >= max_heads:
            state["stop"] = "max heads"
            break
        if state["full"] >= max_full:
            state["stop"] = "max full logs"
            break
        if clock() - t0 > budget_s:
            state["stop"] = "time budget"
            break
        if state["requested"]:
            sleep(spacing)
        state["requested"] += 1
        seen.add(c["vehicle"])
        rec = dict(c, order=state["requested"])
        try:
            info, path = fetch_fn(c["log_id"], tmp_path)
            rec.update(info)
            rec["status"] = "main log" if info.get("has_gnss") else "no vehicle_gnss"
            if info.get("too_big"):
                rec["status"] = "main log, too big"
            if path:
                state["full"] += 1
                try:
                    rec["measure"] = measure_fn(path)
                finally:
                    if os.path.exists(path):
                        os.remove(path)
            state["errors_in_a_row"] = 0
        except urllib.error.HTTPError as exc:
            rec["status"] = "http %d" % exc.code
            if exc.code in (403, 429, 444):
                state["stop"] = "blocked: http %d" % exc.code
        except ValueError as exc:
            rec["status"] = "error: %s" % str(exc)[:200]
        except Exception as exc:   # one bad log must not stop the pass; five in a row do
            rec["status"] = "error: %s: %s" % (type(exc).__name__, str(exc)[:200])
            state["errors_in_a_row"] += 1
            if state["errors_in_a_row"] >= 5:
                state["stop"] = "five errors in a row"
        write(rec)
        if state["stop"]:
            break
    return {"requested": state["requested"], "main_logs_read": state["full"],
            "stop": state["stop"] or "list exhausted"}


# ---------------------------------------------------------------- scoring

def summarise(recs):
    """The plan's predictions and the reported figures, from every record written."""
    main = [r for r in recs if r.get("has_gnss")]
    read = [r for r in main if (r.get("measure") or {}).get("gnss_samples")]
    ok = [r for r in read if (r.get("measure") or {}).get("read") == "ok"]
    passed = [r for r in ok if r["measure"]["gps_lag"].get("passed")]
    vehicles = {r["vehicle"] for r in main}
    p = {}
    p["P1"] = len(main) >= P1_LOGS and len(vehicles) >= P1_VEHICLES
    p["P2"] = (all(r["measure"].get("columns") == FIRST_CHOICE for r in read) if read else None)
    with_delay = [r for r in read if applied_ms(r) is not None and delay_params(r)]
    hits = [r for r in with_delay if any(abs(applied_ms(r) - d) <= P3_TOL_MS for d in delay_params(r))]
    p["P3"] = (len(hits) / len(with_delay) >= P3_SHARE) if with_delay else None
    p["P4"] = len(passed) >= P4_PASSED
    diffs = [r["measure"]["gps_lag"]["lag_ms"] - applied_ms(r) for r in passed if applied_ms(r) is not None]
    p["P5"] = (abs(statistics.median(diffs)) <= P5_ABS_MS) if len(diffs) >= P5_MIN else None
    rep = {
        "requests": len(recs),
        "status_counts": _counts(r.get("status", "") if not str(r.get("status", "")).startswith("error")
                                 else "error" for r in recs),
        "main_logs": len(main), "main_vehicles": len(vehicles), "main_logs_read": len(read),
        "read_log_ok": len(ok), "passed": len(passed),
        "fail_reasons": _counts(r["measure"]["gps_lag"].get("reason") for r in ok if r not in passed),
        "read_errors": [r["measure"].get("read") for r in read if r["measure"].get("read") != "ok"],
        "main_by_kind": _counts(r.get("kind") for r in main),
        "main_releases": _counts(r.get("ver_sw_release") for r in main),
        "main_mav_types": _counts(r.get("mav_type") for r in main),
        "main_receivers": _counts((r.get("measure") or {}).get("devtype") for r in read),
        "main_with_gps_position_too": sum(1 for r in main if r.get("has_gps_position")),
        "columns_seen": _counts(json.dumps(r["measure"].get("columns"), sort_keys=True) for r in read),
        "applied_matches_param": "%d of %d" % (len(hits), len(with_delay)),
        "applied_ms": _counts(applied_ms(r) for r in read),
        "publish_minus_receiver_ms_median": _med([(r.get("measure") or {}).get("publish_minus_receiver_ms") for r in read]),
        "lag_ms": sorted(r["measure"]["gps_lag"]["lag_ms"] for r in passed),
        "lag_minus_applied_ms": sorted(round(d, 1) for d in diffs),
        "lag_minus_applied_median_ms": round(statistics.median(diffs), 1) if diffs else None,
        "more_than_50_ms_off": sum(1 for d in diffs if abs(d) > 50),
        "non_main_by_kind": _counts(r.get("kind") for r in recs if not r.get("has_gnss")),
    }
    return {"gnss_logs": __version__, "predictions": p, "reported": rep}


def _counts(xs):
    out = {}
    for x in xs:
        k = str(x)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def plain(o):
    """json.dumps default: numpy scalars and arrays, and Decimal (from ijson), as plain values."""
    if hasattr(o, "item") and not hasattr(o, "__len__"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    if type(o).__name__ == "Decimal":
        return float(o)
    raise TypeError("not JSON serializable: %r" % type(o))


def main(argv=None):
    import ijson
    import urllib.request
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--plan", default="PLAN.md")
    ap.add_argument("--budget-min", type=float, default=150)
    ap.add_argument("--max-heads", type=int, default=300)
    ap.add_argument("--max-full", type=int, default=30)
    ap.add_argument("--wait-min", type=float, default=120)
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)

    def get_plan():
        req = urllib.request.Request(PLAN_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    if not wait_for_plan(args.plan, get_plan, args.wait_min * 60):
        print("PLAN.md is not on main: no log read", flush=True)
        with open(os.path.join(args.out_dir, "gnss-summary.json"), "w") as f:
            json.dump({"gnss_logs": __version__, "stop": "plan not on main; no log read"}, f, indent=1)
        return 3
    started = time.time()
    req = urllib.request.Request(DBINFO, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp:
        cands, counts = build(ijson.items(open_stream(resp), "item"))
    counts["candidates"] = len(cands)
    counts["candidate_vehicles"] = len({c["vehicle"] for c in cands})
    print(json.dumps(counts), flush=True)
    recs = []
    tmp = os.path.join(tempfile.gettempdir(), "gnss-log.ulg")
    with open(os.path.join(args.out_dir, "gnss-rows.jsonl"), "w", encoding="utf-8") as out:
        def write(rec):
            recs.append(rec)
            out.write(json.dumps(rec, default=plain) + "\n")
            out.flush()
            m = rec.get("measure") or {}
            print("%d %s %s %s %s %s" % (rec["order"], rec["kind"], rec["log_id"], rec["ver_sw_release"],
                                         rec["status"], (m.get("gps_lag") or {}).get("lag_ms")), flush=True)
        res = run(cands, fetch_one, measure_file, write, tmp, max_heads=args.max_heads,
                  max_full=args.max_full, budget_s=args.budget_min * 60)
    summary = summarise(recs)
    summary.update({"list": counts, "pass": res, "wall_s": round(time.time() - started, 1)})
    text = json.dumps(summary, indent=1, default=plain)
    with open(os.path.join(args.out_dir, "gnss-summary.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
