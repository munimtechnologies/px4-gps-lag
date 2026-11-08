"""dronecan_logs.py: does a DroneCAN GNSS receiver's self-reported delay cover its measured GPS lag?
(px4-gps-lag study dronecan-2026, pre-registered in studies/dronecan-2026/PLAN.md).

Since PX4 PR #27427 (main and release/1.18), the DroneCAN GNSS bridge sets each sample's
timestamp_sample from the node's own Fix2 time stamps, and PX4 then ignores SENS_GPSn_DELAY /
SENS_GNSSn_DELAY for that receiver. gnss-2026 saw three such receivers 12-83 ms later than the
delay applied to them. This pass tests that on other vehicles.

It reads Flight Review's public list once and keeps real logs (no simulation, no CI) of at least
60 s, dated 2026-06-30 or later, from v1.18 or newer or with no readable release, newest first, one
log per vehicle, leaving out gnss-2026's 11 vehicles. For each it streams the log and reads only
its definitions section. If UAVCAN_ENABLE >= 1 it downloads the rest (at most 150 MB) to a
temporary file and runs gps_lag.py 0.2.0 on it. No position is written out, and the file is
deleted after it is read. Requests are 6 s apart, and the pass stops at the first block.

Before any log is read, it checks that studies/dronecan-2026/PLAN.md on px4-gps-lag's main matches
the local copy (line endings normalised), waiting up to --wait-min minutes for it to appear.

    python dronecan_logs.py --out-dir out [--budget-min 200] [--max-heads 400] [--max-full 40] [--wait-min 120]

Needs gnss_logs.py (studies/gnss-2026, 0.1.0) and gps_lag.py 0.2.0 next to it.
By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time

import gnss_logs as gn

__version__ = "0.1.0"

PLAN_URL = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/studies/dronecan-2026/PLAN.md"
USER_AGENT = ("px4-gps-lag-dronecan/%s (MV2 of Munim, Inc.; mv2@munimtech.com; "
              "research on public logs)" % __version__)
SINCE = "2026-06-30"        # PX4 PR #27427 merged 2026-06-29
MIN_SERIES = (1, 18)
MIN_DURATION_S = 60
# the 11 vehicles whose logs gnss-2026 read (its gnss-rows.jsonl)
EXCLUDED_VEHICLES = frozenset((
    "2f08843275f5", "64e928d30880", "0b411aa1ca5e", "e400836bc2a4", "6cc558338a9c", "dc42673d9e13",
    "d31f10d61b95", "614aa85a9ceb", "6a23014f23a7", "57a87ee83dc3", "d8b05c2405f1"))
DELAY_PARAMS = ("SENS_GNSS0_DELAY", "SENS_GNSS1_DELAY", "SENS_GPS0_DELAY", "SENS_GPS1_DELAY")
KEEP_PARAMS = gn.PARAM_PREFIXES + ("UAVCAN_ENABLE",)
FALLBACK_MS = 110.0
TOL_MS = 1.0

# the plan's thresholds
D1_LOGS = 8
D2_SHARE = 0.5
D3_MIN, D3_MS = 5, 20.0
D4_SHARE = 2.0 / 3.0
D5_MIN, D5_SHARE = 5, 0.90


# ---------------------------------------------------------------- the public list

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
    rs = gn.release_series(entry.get("ver_sw_release"))
    if rs is not None and rs[0] < MIN_SERIES:
        return None, "older than v1.18"
    if gn.vehicle_hash(entry.get("vehicle_uuid")) in EXCLUDED_VEHICLES:
        return None, "read in gnss-2026"
    return (rs[1] if rs else "unknown"), ""


def build(entries):
    """(candidates in the pass's order: newest first, then by log id; counts)."""
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
                      "vehicle": gn.vehicle_hash(e.get("vehicle_uuid")) or "log:" + str(e["log_id"]),
                      "mav_type": str(e.get("mav_type") or ""), "sys_hw": str(e.get("sys_hw") or ""),
                      "ver_sw_release": str(e.get("ver_sw_release") or ""),
                      "ver_sw": str(e.get("ver_sw") or "")[:12], "kind": kind,
                      "duration_s": int(float(e.get("duration_s") or 0))})
    cands.sort(key=lambda c: c["log_id"])
    cands.sort(key=lambda c: c["log_date"], reverse=True)
    return cands, counts


# ---------------------------------------------------------------- reading one log

def pick(params):
    return {k: params[k] for k in sorted(params) if k.startswith(KEEP_PARAMS)}


def uavcan_on(params):
    try:
        return int(params.get("UAVCAN_ENABLE") or 0) >= 1
    except (TypeError, ValueError):
        return False


def fetch_one(log_id, path, opener=None, max_bytes=gn.MAX_LOG_BYTES):
    """Streams one public log. Returns (info, path or None): the whole log is written to `path`
    only when its initial UAVCAN_ENABLE is 1 or more and it is at most max_bytes."""
    import urllib.request
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(gn.URL % log_id, headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=300) as resp:
        chunks = gn.chunks_of(gn.open_stream(resp))
        formats, params, raw, complete = gn.read_definitions(chunks)
        info = {"head_complete": complete, "uavcan_enable": params.get("UAVCAN_ENABLE"),
                "has_gnss": "vehicle_gnss" in formats,
                "has_gps_position": "vehicle_gps_position" in formats, "params": pick(params)}
        if not (complete and uavcan_on(params)):
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


def device_of(path):
    """The GPS sample's most common non-zero device id and its device type, or {}."""
    from pyulog import ULog
    u = ULog(path, ["vehicle_gps_position", "vehicle_gnss"], True)
    for d in u.data_list:
        if d.multi_id != 0:
            continue
        col = "device_id" if d.name == "vehicle_gps_position" else "receiver.device_id"
        if col in d.data:
            ids = [int(x) & 0xFFFFFFFF for x in d.data[col] if int(x)]
            if ids:
                dev = max(sorted(set(ids)), key=ids.count)
                return {"device_id": dev, "devtype": "0x%02X" % ((dev >> 16) & 0xFF)}
    return {}


def measure_file(path):
    """What this pass records about one downloaded log (no positions)."""
    import gps_lag as gl
    out = {}
    try:
        out.update(device_of(path))
    except Exception as exc:
        out["device_error"] = str(exc)[:200]
    try:
        r = gl.measure(gl.read_log(path))
    except Exception as exc:
        out["read"] = "error: %s" % str(exc)[:200]
        return out
    out.update({k: v for k, v in r.items() if gn._small(v)})
    out["read"] = "ok"
    return out


# ---------------------------------------------------------------- the pass

def run(cands, fetch_fn, measure_fn, write, tmp_path, max_heads=400, max_full=40, sleep=time.sleep,
        clock=time.time, budget_s=200 * 60, spacing=gn.SPACING_S):
    """Reads candidates in order, one per vehicle, until max_heads logs were requested, max_full
    logs were downloaded, the list or the budget ran out, or Flight Review blocked a request.
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
            rec["status"] = "uavcan on" if uavcan_on(info.get("params") or {}) else "uavcan off"
            if info.get("too_big"):
                rec["status"] = "uavcan on, too big"
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
    return {"requested": state["requested"], "downloaded": state["full"],
            "stop": state["stop"] or "list exhausted"}


# ---------------------------------------------------------------- scoring

def applied_ms(rec):
    """The delay PX4 applied (the GPS sample's timestamp minus timestamp_sample), or None."""
    return (rec.get("measure") or {}).get("stamp_minus_sample_ms")


def delay_params(rec):
    p = rec.get("params") or {}
    out = []
    for k in DELAY_PARAMS:
        if k in p and p[k] is not None:
            out.append(float(p[k]))
    return out


def self_stamped(rec):
    """True if the applied delay is more than TOL_MS from every delay parameter and from 110 ms,
    False if it is within TOL_MS of one, None (unknown) without an applied delay or a parameter."""
    a = applied_ms(rec)
    params = delay_params(rec)
    if a is None or not params:
        return None
    return all(abs(float(a) - d) > TOL_MS for d in params + [FALLBACK_MS])


def residual_ms(rec):
    return float(rec["measure"]["lag_ms"]) - float(applied_ms(rec))


def summarise(recs):
    """The plan's predictions and the reported figures, from every record written."""
    read = [r for r in recs if (r.get("measure") or {}).get("read") == "ok"]
    dc = [r for r in read if r["measure"].get("gps_bus") == "uavcan"]
    serial = [r for r in read if r["measure"].get("gps_bus") == "serial"]
    dc_known = [r for r in dc if self_stamped(r) is not None]
    dc_self = [r for r in dc_known if self_stamped(r)]
    dc_pass = [r for r in dc_self if r["measure"].get("passed") and r["measure"].get("lag_ms") is not None]
    resid = [residual_ms(r) for r in dc_pass]
    closer = [abs(float(r["measure"]["lag_ms"]) - FALLBACK_MS) < abs(residual_ms(r)) for r in dc_pass]
    serial_known = [r for r in serial if self_stamped(r) is not None]
    serial_match = [r for r in serial_known if not self_stamped(r)]
    p = {}
    p["D1"] = len({r["vehicle"] for r in dc}) >= D1_LOGS
    p["D2"] = (len(dc_self) / len(dc_known) >= D2_SHARE) if dc_known else None
    p["D3"] = (statistics.median(resid) > D3_MS) if len(resid) >= D3_MIN else None
    p["D4"] = (sum(closer) / len(closer) >= D4_SHARE) if len(closer) >= D3_MIN else None
    p["D5"] = (len(serial_match) / len(serial_known) >= D5_SHARE) if len(serial_known) >= D5_MIN else None
    dc_fallback_pass = [r for r in dc_known if not self_stamped(r) and r["measure"].get("passed")
                        and r["measure"].get("lag_ms") is not None]
    rep = {
        "requests": len(recs),
        "status_counts": _counts(r.get("status", "") if not str(r.get("status", "")).startswith("error")
                                 else "error" for r in recs),
        "read_ok": len(read),
        "read_errors": [r["measure"].get("read") for r in recs
                        if r.get("measure") and r["measure"].get("read") != "ok"],
        "buses": _counts(r["measure"].get("gps_bus") for r in read),
        "dronecan_logs": len(dc),
        "dronecan_self_stamped": "%d of %d" % (len(dc_self), len(dc_known)),
        "dronecan_unknown": len(dc) - len(dc_known),
        "dronecan_self_stamped_passed": len(dc_pass),
        "fail_reasons_dronecan": _counts(r["measure"].get("reason") for r in dc
                                         if not r["measure"].get("passed")),
        "self_stamped_rows": sorted(
            [{"order": r.get("order"), "sys_hw": r.get("sys_hw"), "kind": r.get("kind"),
              "devtype": r["measure"].get("devtype"), "device_id": r["measure"].get("device_id"),
              "applied_ms": round(float(applied_ms(r)), 2), "lag_ms": r["measure"]["lag_ms"],
              "se_ms": r["measure"].get("se_ms"), "residual_ms": round(residual_ms(r), 1)}
             for r in dc_pass], key=lambda x: x["residual_ms"]),
        "residual_median_ms": round(statistics.median(resid), 1) if resid else None,
        "closer_to_110": "%d of %d" % (sum(closer), len(closer)),
        "dronecan_fallback_residual_ms": sorted(round(residual_ms(r), 1) for r in dc_fallback_pass),
        "serial_applied_matches": "%d of %d" % (len(serial_match), len(serial_known)),
        "serial_residual_median_ms": _med([residual_ms(r) for r in serial_known
                                           if r["measure"].get("passed") and r["measure"].get("lag_ms") is not None]),
        "dronecan_by_kind": _counts(r.get("kind") for r in dc),
        "dronecan_devtypes": _counts(r["measure"].get("devtype") for r in dc),
    }
    return {"dronecan_logs": __version__, "predictions": p, "reported": rep}


def _counts(xs):
    out = {}
    for x in xs:
        k = str(x)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def main(argv=None):
    import ijson
    import urllib.request
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--plan", default="PLAN.md")
    ap.add_argument("--budget-min", type=float, default=200)
    ap.add_argument("--max-heads", type=int, default=400)
    ap.add_argument("--max-full", type=int, default=40)
    ap.add_argument("--wait-min", type=float, default=120)
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)

    def get_plan():
        req = urllib.request.Request(PLAN_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    if not gn.wait_for_plan(args.plan, get_plan, args.wait_min * 60):
        print("PLAN.md is not on main: no log read", flush=True)
        with open(os.path.join(args.out_dir, "dronecan-summary.json"), "w") as f:
            json.dump({"dronecan_logs": __version__, "stop": "plan not on main; no log read"}, f, indent=1)
        return 3
    started = time.time()
    req = urllib.request.Request(gn.DBINFO, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp:
        cands, counts = build(ijson.items(gn.open_stream(resp), "item"))
    counts["candidates"] = len(cands)
    counts["candidate_vehicles"] = len({c["vehicle"] for c in cands})
    print(json.dumps(counts), flush=True)
    recs = []
    tmp = os.path.join(tempfile.gettempdir(), "dronecan-log.ulg")
    with open(os.path.join(args.out_dir, "dronecan-rows.jsonl"), "w", encoding="utf-8") as out:
        def write(rec):
            recs.append(rec)
            out.write(json.dumps(rec, default=gn.plain) + "\n")
            out.flush()
            m = rec.get("measure") or {}
            print("%d %s %s %s %s %s %s %s" % (rec["order"], rec["kind"], rec["log_id"], rec["ver_sw_release"],
                                               rec["status"], m.get("gps_bus"), m.get("stamp_minus_sample_ms"),
                                               m.get("lag_ms")), flush=True)
        res = run(cands, fetch_one, measure_file, write, tmp, max_heads=args.max_heads,
                  max_full=args.max_full, budget_s=args.budget_min * 60)
    summary = summarise(recs)
    summary.update({"list": counts, "pass": res, "wall_s": round(time.time() - started, 1)})
    text = json.dumps(summary, indent=1, default=gn.plain)
    with open(os.path.join(args.out_dir, "dronecan-summary.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
