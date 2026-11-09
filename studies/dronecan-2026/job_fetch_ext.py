"""For the px4-gps-lag-dronecan-ext job (published with the extension's plan). Waits until
px4-gps-lag's main has the first pass's rows (studies/dronecan-2026/dronecan-rows.jsonl, put there
with GRADE.md and PLAN-ext.md), then downloads the code the extension runs and those rows, and
records sha256 hashes (line endings normalised) in job-fetched-ext.json. Exits non-zero if the
rows do not appear within the wait, or if a version is not the planned one.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.request

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/%s"
ROWS = "studies/dronecan-2026/dronecan-rows.jsonl"
FILES = (("gps_lag.py", "gps_lag.py"), ("test_gps_lag.py", "test_gps_lag.py"),
         ("studies/gnss-2026/test_gps_lag_gnss.py", "test_gps_lag_gnss.py"),
         ("studies/gnss-2026/gnss_logs.py", "gnss_logs.py"),
         ("studies/dronecan-2026/dronecan_logs.py", "dronecan_logs.py"),
         ("studies/dronecan-2026/test_dronecan_logs.py", "test_dronecan_logs.py"),
         (ROWS, "first-rows.jsonl"))
VERSIONS = {"gps_lag.py": b'__version__ = "0.2.0"', "gnss_logs.py": b'__version__ = "0.1.0"',
            "dronecan_logs.py": b'__version__ = "0.1.0"'}
WAIT_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0


def get(path):
    req = urllib.request.Request(RAW % path, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


t0 = time.time()
while True:
    try:
        rows = get(ROWS)
        if rows.count(b"\n") >= 96:
            break
        print("the first pass's rows on main are incomplete", flush=True)
    except Exception as exc:
        print("first-pass rows not on main yet: %s" % str(exc)[:120], flush=True)
    if time.time() - t0 > WAIT_MIN * 60:
        sys.exit("studies/dronecan-2026/dronecan-rows.jsonl did not appear on px4-gps-lag's main")
    time.sleep(300)

fetched = {}
for path, local in FILES:
    data = rows if path == ROWS else get(path)
    with open(local, "wb") as f:
        f.write(data)
    fetched["px4-gps-lag/main/%s" % path] = {"sha256": sha(data), "bytes": len(data)}
for local, marker in VERSIONS.items():
    if marker not in open(local, "rb").read():
        sys.exit("%s on main is not the planned version" % local)
with open("job-fetched-ext.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched, indent=1), flush=True)
