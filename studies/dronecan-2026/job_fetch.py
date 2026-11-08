"""For the px4-gps-lag-dronecan job (published with the study). Waits until px4-gps-lag's main has
gps_lag.py 0.2.0 (released with gnss-2026's grade), then downloads gps_lag.py, test_gps_lag.py,
test_gps_lag_gnss.py and studies/gnss-2026/gnss_logs.py from main and records sha256 hashes (line
endings normalised) in job-fetched.json. Exits non-zero if 0.2.0 does not appear within --wait-min.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.request

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/%s"
FILES = (("gps_lag.py", "gps_lag.py"), ("test_gps_lag.py", "test_gps_lag.py"),
         ("studies/gnss-2026/test_gps_lag_gnss.py", "test_gps_lag_gnss.py"),
         ("studies/gnss-2026/gnss_logs.py", "gnss_logs.py"))
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
        main = get("gps_lag.py")
        if b'__version__ = "0.2.0"' in main and b"def gnss_as_gps" in main:
            break
        print("gps_lag.py on main is not 0.2.0 yet", flush=True)
    except Exception as exc:
        print("gps_lag.py not readable: %s" % str(exc)[:120], flush=True)
    if time.time() - t0 > WAIT_MIN * 60:
        sys.exit("gps_lag.py 0.2.0 did not appear on px4-gps-lag's main")
    time.sleep(300)

fetched = {}
for path, local in FILES:
    data = main if path == "gps_lag.py" else get(path)
    with open(local, "wb") as f:
        f.write(data)
    fetched["px4-gps-lag/main/%s" % path] = {"sha256": sha(data), "bytes": len(data)}
if b'__version__ = "0.1.0"' not in open("gnss_logs.py", "rb").read():
    sys.exit("studies/gnss-2026/gnss_logs.py on main is not 0.1.0")
with open("job-fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched, indent=1), flush=True)
