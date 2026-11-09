"""Smoke run of nodefw.py 0.1.0 on the DroneCAN logs that gnss-2026 and the first dronecan pass
already read (the logs that generated the hypotheses; never graded). It checks that the real
pyulog output of device_information is read as intended and that ArduPilot's hwdef names can be
collected, before the graded run on the extension's logs.

    python smoke_nodefw.py OUT_DIR

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0."""

import json
import os
import sys
import tempfile
import time
import urllib.request

import gnss_logs as gn
import nodefw as nf

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/%s"
SKIP = ("name[", "firmware_version[", "hardware_version[", "serial_number[")


def get(path):
    req = urllib.request.Request(RAW % path, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def read_fn(path):
    from pyulog import ULog
    out = nf.read_nodes(path)
    u = ULog(path, ["device_information"], True)
    keys = sorted({k for d in u.data_list if d.name == "device_information" for k in d.data})
    out["di_fields_sample"] = [k for k in keys if not k.startswith(SKIP)] + [k for k in keys if k.endswith("[0]")]
    return out


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    lines = {"gnss-2026": get("studies/gnss-2026/gnss-rows.jsonl").decode("utf-8").splitlines(),
             "first pass": get("studies/dronecan-2026/dronecan-rows.jsonl").decode("utf-8").splitlines()}
    rows = nf.select(lines)
    print("DroneCAN rows read OK in the earlier passes: %d" % len(rows), flush=True)
    t0 = time.time()
    hwdef = {"url": nf.HWDEF_TAR}
    try:
        req = urllib.request.Request(nf.HWDEF_TAR, headers={"User-Agent": nf.USER_AGENT})
        with urllib.request.urlopen(req, timeout=900) as resp:
            ap_names, files = nf.hwdef_names(resp)
        hwdef.update({"files": files, "names": len(ap_names), "list": sorted(ap_names),
                      "seconds": round(time.time() - t0, 1)})
    except Exception as exc:
        ap_names = set()
        hwdef["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    print("hwdef: %s" % json.dumps({k: v for k, v in hwdef.items() if k != "list"}), flush=True)
    done = []
    tmp = os.path.join(tempfile.gettempdir(), "nodefw-smoke.ulg")
    with open(os.path.join(out_dir, "nodefw-smoke-rows.jsonl"), "w", encoding="utf-8") as out:
        def write(rec):
            rec = nf.annotate(rec, ap_names)
            done.append(rec)
            out.write(json.dumps(rec, default=gn.plain) + "\n")
            out.flush()
            print(json.dumps({k: rec.get(k) for k in ("pass", "order", "sys_hw", "status", "node_name", "family",
                                                     "firmware_version", "match", "applied_ms", "residual_ms",
                                                     "self_stamped", "gps_type_nodes", "di_fields_sample")},
                             default=gn.plain), flush=True)
        res = nf.run(rows, nf.fetch_full, read_fn, write, tmp, max_logs=10, budget_s=60 * 60)
    summary = nf.summarise(done, hwdef)
    summary.update({"smoke": "earlier passes only; not graded", "pass": res})
    with open(os.path.join(out_dir, "nodefw-smoke-summary.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(summary, indent=1, default=gn.plain) + "\n")
    print(json.dumps(summary["earlier_passes_not_graded"], indent=1, default=gn.plain), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out"))
