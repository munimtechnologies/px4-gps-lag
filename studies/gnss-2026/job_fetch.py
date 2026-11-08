"""For the px4-gps-lag-gnss job only (not published). Downloads gps_lag.py and test_gps_lag.py from
px4-gps-lag's main branch, checks that gps_lag.py is 0.1.0, saves main's copy as gps_lag_main.py
(the patch step builds gps_lag.py 0.2.0 from it) and records sha256 hashes (line endings
normalised) in job-fetched.json.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/%s"


def get(path):
    req = urllib.request.Request(RAW % path, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


fetched = {}
for path, local in (("gps_lag.py", "gps_lag_main.py"), ("test_gps_lag.py", "test_gps_lag.py")):
    data = get(path)
    with open(local, "wb") as f:
        f.write(data)
    fetched["px4-gps-lag/main/%s" % path] = {"sha256": sha(data), "bytes": len(data)}
main = open("gps_lag_main.py", encoding="utf-8").read()
if '__version__ = "0.1.0"' not in main:
    sys.exit("gps_lag.py on px4-gps-lag's main is not 0.1.0")
with open("job-fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched, indent=1), flush=True)
