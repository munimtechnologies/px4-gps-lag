"""For the px4-gps-lag nodefw job (published with PLAN-nodefw.md). Waits until px4-gps-lag's main
has the extension's rows (studies/dronecan-2026/dronecan-ext-rows.jsonl, published with its grade),
then downloads the code nodefw runs, its plan and the three row files, and records sha256 hashes
(line endings normalised) in job-fetched-nodefw.json. Exits non-zero if the rows do not appear
within the wait, or if a version is not the planned one.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.request

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/%s"
EXT_ROWS = "studies/dronecan-2026/dronecan-ext-rows.jsonl"
FILES = (("studies/gnss-2026/gnss_logs.py", "gnss_logs.py"),
         ("studies/dronecan-2026/dronecan_logs.py", "dronecan_logs.py"),
         ("studies/dronecan-2026/nodefw.py", "nodefw.py"),
         ("studies/dronecan-2026/test_nodefw.py", "test_nodefw.py"),
         ("studies/dronecan-2026/PLAN-nodefw.md", "PLAN-nodefw.md"),
         ("studies/gnss-2026/gnss-rows.jsonl", "gnss-rows.jsonl"),
         ("studies/dronecan-2026/dronecan-rows.jsonl", "first-rows.jsonl"),
         (EXT_ROWS, "ext-rows.jsonl"))
VERSIONS = {"gnss_logs.py": b'__version__ = "0.1.0"', "dronecan_logs.py": b'__version__ = "0.1.0"',
            "nodefw.py": b'__version__ = "0.1.0"'}
WAIT_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0


def get(path):
    req = urllib.request.Request(RAW % path, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


t0 = time.time()
while True:
    try:
        rows = get(EXT_ROWS)
        if rows.count(b"\n") >= 1:
            break
        print("the extension's rows on main are empty", flush=True)
    except Exception as exc:
        print("extension rows not on main yet: %s" % str(exc)[:120], flush=True)
    if time.time() - t0 > WAIT_MIN * 60:
        sys.exit("%s did not appear on px4-gps-lag's main" % EXT_ROWS)
    time.sleep(300)

fetched = {}
for path, local in FILES:
    data = rows if path == EXT_ROWS else get(path)
    with open(local, "wb") as f:
        f.write(data)
    fetched["px4-gps-lag/main/%s" % path] = {"sha256": sha(data), "bytes": len(data)}
for local, marker in VERSIONS.items():
    if marker not in open(local, "rb").read():
        sys.exit("%s on main is not the planned version" % local)
with open("job-fetched-nodefw.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched, indent=1), flush=True)
