"""nodefw.py: which DroneCAN GNSS nodes leave GPS lag uncovered? An add-on to px4-gps-lag study
dronecan-2026, pre-registered in studies/dronecan-2026/PLAN-nodefw.md (reasoning in MECHANISM.md).

It takes the DroneCAN rows that gnss-2026, the first dronecan pass and the extension already read
(applied delay, measured lag, self-stamped or not), downloads each of those public logs once more,
and reads only device_information (the DroneCAN node name and firmware version) and the GNSS
receivers' device ids. Each receiver is tied to its node name and sorted into a family: 'ap_periph'
if the name starts with 'org.ardupilot.' or is a CAN_APP_NODE_NAME in ArduPilot's hwdef files,
else 'other'. Graded on the extension's rows only; the earlier passes are reported beside.

No position is read or written, and device serial numbers are not written. Each log is deleted
after it is read. Requests are 6 s apart, and the pass stops at the first block.

    python nodefw.py --out-dir out --gnss-rows gnss-rows.jsonl --first-rows first-rows.jsonl
        --ext-rows ext-rows.jsonl [--plan PLAN-nodefw.md] [--budget-min 120] [--max-logs 60] [--wait-min 60]

Needs gnss_logs.py 0.1.0 and dronecan_logs.py 0.1.0 next to it.
By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import re
import statistics
import sys
import tarfile
import tempfile
import time

import dronecan_logs as dl
import gnss_logs as gn

__version__ = "0.1.0"

PLAN_URL = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/studies/dronecan-2026/PLAN-nodefw.md"
USER_AGENT = ("px4-gps-lag-nodefw/%s (MV2 of Munim, Inc.; mv2@munimtech.com; "
              "research on public logs)" % __version__)
HWDEF_TAR = "https://codeload.github.com/ArduPilot/ardupilot/tar.gz/refs/heads/master"
HWDEF_DIR = "libraries/AP_HAL_ChibiOS/hwdef/"
AP_PREFIX = "org.ardupilot."
NAME_RE = re.compile(rb'CAN_APP_NODE_NAME\s+"([^"\r\n]+)"')
GPS_TYPE = 4
PASSES = ("gnss-2026", "first pass", "extension")

# the plan's thresholds
SHORT_MS = 40.0
N1_SHARE = 0.6
N_MIN = 3
N2_MS = 40.0
N3_SHARE = 2.0 / 3.0
N4_MS = 20.0


# ---------------------------------------------------------------- the rows already read

def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def norm(rec, pass_name):
    """One earlier row in a common shape, or None if its log was not read OK."""
    m = rec.get("measure") or {}
    if m.get("read") != "ok":
        return None
    if pass_name == "gnss-2026":
        g = m.get("gps_lag") or {}
        bus = m.get("bus") or g.get("gps_bus")
        applied, lag, passed = m.get("receiver_minus_sample_ms"), g.get("lag_ms"), g.get("passed")
    else:
        bus = m.get("gps_bus")
        applied, lag, passed = m.get("stamp_minus_sample_ms"), m.get("lag_ms"), m.get("passed")
    applied, lag = _f(applied), _f(lag)
    params = dl.delay_params(rec)
    row = {"pass": pass_name, "order": rec.get("order"), "log_id": str(rec.get("log_id") or ""),
           "vehicle": rec.get("vehicle"), "sys_hw": rec.get("sys_hw"),
           "ver_sw_release": rec.get("ver_sw_release"), "log_date": rec.get("log_date"),
           "bus": bus, "device_id": int(m.get("device_id") or 0) & 0xFFFFFFFF,
           "applied_ms": applied, "lag_ms": lag, "passed": bool(passed) and lag is not None,
           "delay_params": params}
    row["self_stamped"] = self_stamped(applied, params)
    row["residual_ms"] = round(lag - applied, 1) if (lag is not None and applied is not None) else None
    row["short_self_report"] = bool(row["self_stamped"]) and applied < SHORT_MS
    return row


def self_stamped(applied, params):
    """dronecan_logs 0.1.0's rule: True if the applied delay is more than 1 ms from every delay
    parameter and from 110 ms, False if within 1 ms of one, None without both."""
    if applied is None or not params:
        return None
    return all(abs(applied - d) > dl.TOL_MS for d in list(params) + [dl.FALLBACK_MS])


def select(lines_by_pass):
    """{pass: iterable of JSON lines} -> DroneCAN rows read OK, in pass order then row order."""
    out = []
    for p in PASSES:
        rows = []
        for line in lines_by_pass.get(p) or []:
            line = line.strip()
            if not line:
                continue
            r = norm(json.loads(line), p)
            if r and r["bus"] == "uavcan" and r["log_id"]:
                rows.append(r)
        rows.sort(key=lambda r: (r["order"] is None, r["order"] or 0))
        out.extend(rows)
    return out


# ---------------------------------------------------------------- ArduPilot's node names

def hwdef_names(stream):
    """(set of lower-cased CAN_APP_NODE_NAME strings, files read) from a streamed ArduPilot tar.gz."""
    names, files = set(), 0
    with tarfile.open(fileobj=stream, mode="r|gz") as tf:
        for ti in tf:
            if not ti.isfile():
                continue
            parts = ti.name.split("/", 1)
            if len(parts) != 2 or not parts[1].startswith(HWDEF_DIR):
                continue
            f = tf.extractfile(ti)
            if f is None:
                continue
            files += 1
            for m in NAME_RE.finditer(f.read()):
                names.add(m.group(1).decode("ascii", "replace").strip().lower())
    return names, files


def family(name, ap_names):
    if not name:
        return None
    n = name.strip().lower()
    return "ap_periph" if n.startswith(AP_PREFIX) or n in ap_names else "other"


# ---------------------------------------------------------------- reading one log

def text_field(data, field, i):
    """A ULog char[] field of row i as text: pyulog splits it into field[0], field[1], ..."""
    if field in data:
        v = data[field][i]
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).split(b"\0")[0].decode("utf-8", "replace").strip()
        return str(v).strip()
    out = bytearray()
    k = 0
    while "%s[%d]" % (field, k) in data:
        b = int(data["%s[%d]" % (field, k)][i]) & 0xFF
        if b == 0:
            break
        out.append(b)
        k += 1
    return out.decode("utf-8", "replace").strip()


def device_entries(data):
    """The distinct device_information entries of one data set (no serial numbers), with counts."""
    n = len(data["timestamp"]) if "timestamp" in data else 0
    seen = {}
    for i in range(n):
        e = {"device_type": int(data["device_type"][i]) if "device_type" in data else None,
             "device_id": (int(data["device_id"][i]) & 0xFFFFFFFF) if "device_id" in data else 0,
             "name": text_field(data, "name", i),
             "firmware_version": text_field(data, "firmware_version", i),
             "hardware_version": text_field(data, "hardware_version", i)}
        key = json.dumps(e, sort_keys=True)
        if key not in seen:
            seen[key] = dict(e, samples=0)
        seen[key]["samples"] += 1
    return sorted(seen.values(), key=lambda e: (e["device_id"], e["name"], e["firmware_version"]))


def merge_entries(lists):
    out = {}
    for entries in lists:
        for e in entries:
            key = json.dumps({k: e[k] for k in e if k != "samples"}, sort_keys=True)
            if key in out:
                out[key]["samples"] += e.get("samples", 0)
            else:
                out[key] = dict(e)
    return sorted(out.values(), key=lambda e: (e["device_id"], e["name"], e["firmware_version"]))


def receivers(data_sets):
    """(topic, multi_id, most common non-zero device id) of each sensor_gps / sensor_gnss instance."""
    out = []
    for name, multi_id, ids in data_sets:
        ids = [int(x) & 0xFFFFFFFF for x in ids if int(x)]
        if ids:
            out.append({"topic": name, "multi_id": int(multi_id),
                        "device_id": max(sorted(set(ids)), key=ids.count)})
    return sorted(out, key=lambda r: (r["topic"], r["multi_id"]))


def read_nodes(path):
    from pyulog import ULog
    u = ULog(path, ["device_information", "sensor_gps", "sensor_gnss"], True)
    entries = merge_entries([device_entries(d.data) for d in u.data_list if d.name == "device_information"])
    rx = receivers([(d.name, d.multi_id, d.data["device_id"]) for d in u.data_list
                    if d.name in ("sensor_gps", "sensor_gnss") and "device_id" in d.data])
    return {"device_information": entries, "receivers": rx}


def match(device_id, entries):
    """(name or None, how, entries used) for the GPS sample's device id."""
    dev = int(device_id or 0) & 0xFFFFFFFF
    by_id = [e for e in entries if dev and e["device_id"] == dev and e["name"]]
    names = sorted({e["name"] for e in by_id})
    if len(names) == 1:
        return names[0], "device id", by_id
    if len(names) > 1:
        return None, "several names for the device id", by_id
    gps = [e for e in entries if e["device_type"] == GPS_TYPE and e["name"]]
    names = sorted({e["name"] for e in gps})
    if len(names) == 1:
        return names[0], "only GPS-type node", gps
    if names:
        return None, "several GPS-type nodes", gps
    return None, ("no device_information" if not entries else "no GPS node named"), []


def annotate(row, ap_names):
    if row.get("status") != "read":
        row.update({"node_name": None, "match": None, "family": None, "node_entries": []})
        return row
    name, how, used = match(row["device_id"], row.get("device_information") or [])
    row["node_name"] = name
    row["match"] = how
    row["node_entries"] = used
    row["family"] = family(name, ap_names)
    row["firmware_version"] = next((e["firmware_version"] for e in used if e["name"] == name), None) if name else None
    row["gps_type_nodes"] = sorted({e["name"] for e in row.get("device_information") or []
                                    if e["device_type"] == GPS_TYPE and e["name"]})
    row["device_information_entries"] = len(row.get("device_information") or [])
    row.pop("device_information", None)
    return row


# ---------------------------------------------------------------- the pass

def fetch_full(log_id, path, opener=None, max_bytes=gn.MAX_LOG_BYTES):
    """Downloads one public log to `path`; None (and no file) if it is bigger than max_bytes."""
    import urllib.request
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(gn.URL % log_id, headers={"User-Agent": USER_AGENT})
    total = 0
    with opener(req, timeout=300) as resp:
        with open(path, "wb") as f:
            for c in gn.chunks_of(gn.open_stream(resp)):
                total += len(c)
                if total > max_bytes:
                    break
                f.write(c)
    if total > max_bytes:
        os.remove(path)
        return None
    return path


def run(rows, fetch_fn, read_fn, write, tmp_path, max_logs=60, sleep=time.sleep, clock=time.time,
        budget_s=120 * 60, spacing=gn.SPACING_S):
    """Reads each row's log once, in order. write(row) records every row, read or not."""
    import urllib.error
    t0 = clock()
    state = {"requested": 0, "read": 0, "errors_in_a_row": 0, "stop": None}
    for r in rows:
        rec = dict(r)
        if state["stop"]:
            rec["status"] = "not requested: %s" % state["stop"]
            write(rec)
            continue
        if state["requested"] >= max_logs:
            state["stop"] = "max logs"
        elif clock() - t0 > budget_s:
            state["stop"] = "time budget"
        if state["stop"]:
            rec["status"] = "not requested: %s" % state["stop"]
            write(rec)
            continue
        if state["requested"]:
            sleep(spacing)
        state["requested"] += 1
        try:
            path = fetch_fn(rec["log_id"], tmp_path)
            if path is None:
                rec["status"] = "too big"
            else:
                try:
                    rec.update(read_fn(path))
                    rec["status"] = "read"
                    state["read"] += 1
                finally:
                    if os.path.exists(path):
                        os.remove(path)
            state["errors_in_a_row"] = 0
        except urllib.error.HTTPError as exc:
            rec["status"] = "http %d" % exc.code
            if exc.code in (403, 429, 444):
                state["stop"] = "blocked: http %d" % exc.code
        except Exception as exc:   # one bad log must not stop the pass; five in a row do
            rec["status"] = "error: %s: %s" % (type(exc).__name__, str(exc)[:200])
            state["errors_in_a_row"] += 1
            if state["errors_in_a_row"] >= 5:
                state["stop"] = "five errors in a row"
        write(rec)
    return {"requested": state["requested"], "read": state["read"], "stop": state["stop"] or "list done"}


# ---------------------------------------------------------------- scoring

def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def score(rows):
    """The plan's predictions on `rows` and the reported figures."""
    reread = [r for r in rows if r.get("status") == "read"]
    named = [r for r in reread if r.get("node_name")]
    ss_pass = [r for r in rows if r.get("self_stamped") and r.get("passed") and r.get("residual_ms") is not None]
    short = [r for r in ss_pass if r["applied_ms"] < SHORT_MS]
    short_named = [r for r in short if r.get("node_name")]
    ap = [r["residual_ms"] for r in ss_pass if r.get("family") == "ap_periph"]
    other = [r["residual_ms"] for r in ss_pass if r.get("family") == "other"]
    p = {}
    p["N1"] = (len(named) / len(reread) >= N1_SHARE) if reread else None
    p["N2"] = (statistics.median([r["residual_ms"] for r in short]) > N2_MS) if len(short) >= N_MIN else None
    p["N3"] = (sum(1 for r in short_named if r["family"] == "ap_periph") / len(short_named) >= N3_SHARE
               if len(short_named) >= N_MIN else None)
    p["N4"] = ((statistics.median(ap) - statistics.median(other)) >= N4_MS
               if len(ap) >= N_MIN and len(other) >= N_MIN else None)
    table = [{"pass": r["pass"], "order": r.get("order"), "sys_hw": r.get("sys_hw"),
              "ver_sw_release": r.get("ver_sw_release"), "node_name": r.get("node_name"),
              "family": r.get("family"), "firmware_version": r.get("firmware_version"),
              "match": r.get("match"), "status": r.get("status"), "self_stamped": r.get("self_stamped"),
              "applied_ms": None if r.get("applied_ms") is None else round(r["applied_ms"], 2),
              "lag_ms": r.get("lag_ms"), "residual_ms": r.get("residual_ms"), "passed": r.get("passed")}
             for r in rows]
    rep = {"dronecan_rows": len(rows), "reread": len(reread), "named": len(named),
           "match_methods": dl._counts(r.get("match") for r in reread),
           "statuses": dl._counts(str(r.get("status", "")).split(":")[0] for r in rows),
           "self_stamped": sum(1 for r in rows if r.get("self_stamped")),
           "self_stamped_passed": len(ss_pass), "short_self_reports_passed": len(short),
           "short_residual_median_ms": _med([r["residual_ms"] for r in short]),
           "short_named": len(short_named),
           "short_named_ap_periph": sum(1 for r in short_named if r["family"] == "ap_periph"),
           "ap_periph_residuals_ms": sorted(ap), "other_residuals_ms": sorted(other),
           "names": dl._counts(r.get("node_name") for r in named),
           "table": table}
    return {"predictions": p, "reported": rep}


def summarise(rows, hwdef):
    ext = [r for r in rows if r["pass"] == "extension"]
    return {"nodefw": __version__, "graded_on": "extension only", "extension": score(ext),
            "earlier_passes_not_graded": score([r for r in rows if r["pass"] != "extension"]),
            "pooled_not_the_grade": score(rows), "hwdef": hwdef}


# ---------------------------------------------------------------- main

def main(argv=None):
    import urllib.request
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--gnss-rows", required=True)
    ap.add_argument("--first-rows", required=True)
    ap.add_argument("--ext-rows", required=True)
    ap.add_argument("--plan", default="PLAN-nodefw.md")
    ap.add_argument("--budget-min", type=float, default=120)
    ap.add_argument("--max-logs", type=int, default=60)
    ap.add_argument("--wait-min", type=float, default=60)
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    lines = {}
    for p, path in zip(PASSES, (args.gnss_rows, args.first_rows, args.ext_rows)):
        with open(path, encoding="utf-8") as f:
            lines[p] = f.readlines()
    rows = select(lines)
    counts = {p: sum(1 for r in rows if r["pass"] == p) for p in PASSES}
    print("DroneCAN rows read OK: %s" % json.dumps(counts), flush=True)
    if not counts["extension"]:
        print("no extension DroneCAN rows: nothing to grade, no log read", flush=True)
        return 4

    def get_plan():
        req = urllib.request.Request(PLAN_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    if not gn.wait_for_plan(args.plan, get_plan, args.wait_min * 60):
        print("PLAN-nodefw.md is not on main: no log read", flush=True)
        with open(os.path.join(args.out_dir, "nodefw-summary.json"), "w") as f:
            json.dump({"nodefw": __version__, "stop": "plan not on main; no log read"}, f, indent=1)
        return 3
    started = time.time()
    hwdef = {"url": HWDEF_TAR}
    try:
        req = urllib.request.Request(HWDEF_TAR, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=900) as resp:
            ap_names, files = hwdef_names(resp)
        hwdef.update({"files": files, "names": len(ap_names), "list": sorted(ap_names)})
    except Exception as exc:
        ap_names = set()
        hwdef["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    print("hwdef: %s" % json.dumps({k: v for k, v in hwdef.items() if k != "list"}), flush=True)
    done = []
    tmp = os.path.join(tempfile.gettempdir(), "nodefw-log.ulg")
    with open(os.path.join(args.out_dir, "nodefw-rows.jsonl"), "w", encoding="utf-8") as out:
        def write(rec):
            rec = annotate(rec, ap_names)
            done.append(rec)
            out.write(json.dumps(rec, default=gn.plain) + "\n")
            out.flush()
            print("%s %s %s %s %s %s %s %s" % (rec["pass"], rec.get("order"), rec["status"], rec.get("node_name"),
                                               rec.get("family"), rec.get("applied_ms"), rec.get("residual_ms"),
                                               rec.get("self_stamped")), flush=True)
        res = run(rows, fetch_full, read_nodes, write, tmp, max_logs=args.max_logs, budget_s=args.budget_min * 60)
    summary = summarise(done, hwdef)
    summary.update({"rows": counts, "pass": res, "wall_s": round(time.time() - started, 1)})
    text = json.dumps(summary, indent=1, default=gn.plain)
    with open(os.path.join(args.out_dir, "nodefw-summary.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
