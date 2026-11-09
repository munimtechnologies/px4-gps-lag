"""dronecan_ext.py: the pre-registered extension of px4-gps-lag study dronecan-2026
(studies/dronecan-2026/PLAN-ext.md).

The first pass (dronecan_logs.py 0.1.0) stopped at 40 downloaded logs after 96 vehicles, with 4
DroneCAN receivers. This pass runs the same reader on the vehicles it did not request:

- every vehicle in the first pass's dronecan-rows.jsonl is left out (and gnss-2026's 11, as before);
- a log with UAVCAN_ENABLE >= 1 is downloaded only if its release reads as PX4 v1.x (v1.18+);
- for each downloaded log, the device ids of the logged sensor_gps instances are recorded too.

It is graded with dronecan_logs.summarise on its own rows; the pooled scores (first pass plus this
one) are reported beside them. Before any log is read it checks that studies/dronecan-2026/
PLAN-ext.md on px4-gps-lag's main matches the local copy.

    python dronecan_ext.py --out-dir out --first-rows first-rows.jsonl [--plan PLAN-ext.md]
        [--budget-min 300] [--max-heads 900] [--max-full 300] [--wait-min 240]

Needs dronecan_logs.py 0.1.0, gnss_logs.py 0.1.0 and gps_lag.py 0.2.0 next to it.
By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import sys
import tempfile
import time

import dronecan_logs as dl
import gnss_logs as gn

__version__ = "0.1.0"

PLAN_URL = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/studies/dronecan-2026/PLAN-ext.md"
NOT_V1 = "uavcan on, not v1.x"


# ---------------------------------------------------------------- the list

def first_pass_vehicles(lines):
    """Vehicle hashes of every request in the first pass's rows (an iterable of JSON lines)."""
    out = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        v = json.loads(line).get("vehicle")
        if v:
            out.add(str(v))
    return frozenset(out)


def build(entries, first):
    """dronecan_logs.build, then leaves out the first pass's vehicles."""
    cands, counts = dl.build(entries)
    kept = [c for c in cands if c["vehicle"] not in first]
    gone = len(cands) - len(kept)
    if gone:
        counts["excluded"]["read in the first pass"] = gone
    counts["eligible"] -= gone
    by_kind = {}
    for c in kept:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    counts["by_kind"] = by_kind
    return kept, counts


def downloadable(cand):
    """True if the candidate's release reads as PX4 v1.x, v1.18 or newer."""
    rs = gn.release_series(cand.get("ver_sw_release") or "")
    return rs is not None and rs[0][0] == 1 and rs[0] >= dl.MIN_SERIES


# ---------------------------------------------------------------- reading

def fetch_ext(log_id, path, download, fetch=None):
    """dronecan_logs.fetch_one; with download False only the definitions are read."""
    fetch = fetch or dl.fetch_one
    if download:
        return fetch(log_id, path)
    saved = dl.uavcan_on
    dl.uavcan_on = lambda params: False
    try:
        info, _ = fetch(log_id, path)
    finally:
        dl.uavcan_on = saved
    info["not_downloaded"] = "release not PX4 v1.x"
    return info, None


def label(rec):
    if rec.get("not_downloaded") and rec.get("status") == "uavcan on":
        rec["status"] = NOT_V1
    return rec


def receivers_of(instances):
    """instances: (multi_id, device ids) per sensor_gps instance. Returns one dict per instance with
    a non-zero device id (its most common one): multi_id, device_id, devtype, bus."""
    out = []
    for multi_id, ids in sorted(instances, key=lambda x: x[0]):
        ids = [int(x) & 0xFFFFFFFF for x in ids if int(x)]
        if not ids:
            continue
        dev = max(sorted(set(ids)), key=ids.count)
        out.append({"multi_id": int(multi_id), "device_id": dev, "devtype": "0x%02X" % ((dev >> 16) & 0xFF),
                    "bus": dl_bus(dev)})
    return out


def dl_bus(dev):
    return {0: "unknown", 1: "i2c", 2: "spi", 3: "uavcan", 4: "simulation", 5: "serial",
            6: "mavlink"}.get(int(dev) & 0x7, "unknown")


def sensor_gps_receivers(path):
    from pyulog import ULog
    u = ULog(path, ["sensor_gps"], True)
    return receivers_of([(d.multi_id, d.data["device_id"]) for d in u.data_list
                         if d.name == "sensor_gps" and "device_id" in d.data])


def measure_ext(path, measure=None, receivers=None):
    out = (measure or dl.measure_file)(path)
    try:
        out["sensor_gps"] = (receivers or sensor_gps_receivers)(path)
    except Exception as exc:
        out["sensor_gps_error"] = str(exc)[:200]
    return out


def run_ext(cands, fetch_fn, measure_fn, write, tmp_path, **kw):
    by_id = {c["log_id"]: c for c in cands}

    def fetch(log_id, path):
        return fetch_ext(log_id, path, downloadable(by_id[log_id]), fetch=fetch_fn)
    return dl.run(cands, fetch, measure_fn, lambda rec: write(label(rec)), tmp_path, **kw)


# ---------------------------------------------------------------- scoring

def hidden_dronecan(recs):
    """Read logs whose GPS sample has no bus but whose sensor_gps receivers are all DroneCAN."""
    out = []
    for r in recs:
        m = r.get("measure") or {}
        rx = m.get("sensor_gps") or []
        if m.get("read") == "ok" and m.get("gps_bus") == "unknown" and rx and all(x["bus"] == "uavcan" for x in rx):
            out.append({"order": r.get("order"), "sys_hw": r.get("sys_hw"), "receivers": len(rx),
                        "applied_ms": m.get("stamp_minus_sample_ms"), "lag_ms": m.get("lag_ms"),
                        "passed": m.get("passed"), "reason": m.get("reason")})
    return out


def summarise_all(first_recs, recs):
    ext = dl.summarise(recs)
    ext["reported"]["hidden_dronecan_not_graded"] = hidden_dronecan(recs)
    pooled = dl.summarise(list(first_recs) + list(recs))
    return {"dronecan_ext": __version__, "graded_on": "extension only", "extension": ext,
            "pooled_not_the_grade": pooled}


def main(argv=None):
    import ijson
    import urllib.request
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--first-rows", required=True)
    ap.add_argument("--plan", default="PLAN-ext.md")
    ap.add_argument("--budget-min", type=float, default=300)
    ap.add_argument("--max-heads", type=int, default=900)
    ap.add_argument("--max-full", type=int, default=300)
    ap.add_argument("--wait-min", type=float, default=240)
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.first_rows, encoding="utf-8") as f:
        first_lines = f.readlines()
    first = first_pass_vehicles(first_lines)
    first_recs = [json.loads(x) for x in first_lines if x.strip()]
    print("first pass: %d rows, %d vehicles" % (len(first_recs), len(first)), flush=True)
    if len(first_recs) != 96 or len(first) != 96:
        print("the first pass's rows are not the 96 graded ones: no log read", flush=True)
        return 4

    def get_plan():
        req = urllib.request.Request(PLAN_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    if not gn.wait_for_plan(args.plan, get_plan, args.wait_min * 60):
        print("PLAN-ext.md is not on main: no log read", flush=True)
        with open(os.path.join(args.out_dir, "dronecan-ext-summary.json"), "w") as f:
            json.dump({"dronecan_ext": __version__, "stop": "plan not on main; no log read"}, f, indent=1)
        return 3
    started = time.time()
    req = urllib.request.Request(gn.DBINFO, headers={"User-Agent": dl.USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp:
        cands, counts = build(ijson.items(gn.open_stream(resp), "item"), first)
    counts["candidates"] = len(cands)
    counts["candidate_vehicles"] = len({c["vehicle"] for c in cands})
    counts["downloadable_vehicles"] = len({c["vehicle"] for c in cands if downloadable(c)})
    print(json.dumps(counts), flush=True)
    recs = []
    tmp = os.path.join(tempfile.gettempdir(), "dronecan-ext-log.ulg")
    with open(os.path.join(args.out_dir, "dronecan-ext-rows.jsonl"), "w", encoding="utf-8") as out:
        def write(rec):
            recs.append(rec)
            out.write(json.dumps(rec, default=gn.plain) + "\n")
            out.flush()
            m = rec.get("measure") or {}
            print("%d %s %s %s %s %s %s %s %s" % (
                rec["order"], rec["kind"], rec["log_id"], rec["ver_sw_release"], rec["status"],
                m.get("gps_bus"), m.get("stamp_minus_sample_ms"), m.get("lag_ms"),
                ",".join(x["bus"] for x in m.get("sensor_gps") or [])), flush=True)
        res = run_ext(cands, dl.fetch_one, measure_ext, write, tmp, max_heads=args.max_heads,
                      max_full=args.max_full, budget_s=args.budget_min * 60)
    summary = summarise_all(first_recs, recs)
    summary.update({"list": counts, "pass": res, "wall_s": round(time.time() - started, 1)})
    text = json.dumps(summary, indent=1, default=gn.plain)
    with open(os.path.join(args.out_dir, "dronecan-ext-summary.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
