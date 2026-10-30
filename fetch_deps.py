"""Nothing is downloaded from Flight Review before the plan is public: wait (up
to 60 min) for studies/fleet-2026/PLAN-innov.md, GRADE.md and v1/logs.jsonl
on px4-gps-lag's main, then fetch gps_lag.py and test_gps_lag.py from main
unchanged (0.1.0, as fleet-2026 measured with), save v1/logs.jsonl as
v1-logs.jsonl, and note whether this folder's fleet.py and innov.py match
main's. Writes fetched.json.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/"
WAIT_FOR = ("studies/fleet-2026/PLAN-innov.md", "studies/fleet-2026/GRADE.md",
            "studies/fleet-2026/v1/logs.jsonl")


def get(path):
    req = urllib.request.Request(BASE + path, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


fetched = {}
for path in WAIT_FOR:
    for attempt in range(41):
        try:
            data = get(path)
            fetched[path] = {"on_main": True, "sha256": sha(data), "waited_s": attempt * 90}
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or attempt == 40:
                sys.exit("%s is not on main (%s)" % (path, exc.code))
            print("%s not on main yet; waiting 90 s" % path, flush=True)
            time.sleep(90)

rows = get("studies/fleet-2026/v1/logs.jsonl")
with open("v1-logs.jsonl", "wb") as f:
    f.write(rows)
fetched["studies/fleet-2026/v1/logs.jsonl"]["lines"] = rows.count(b"\n")

for name in ("gps_lag.py", "test_gps_lag.py"):
    data = get(name)
    with open(name, "wb") as f:
        f.write(data)
    fetched[name] = {"from_main": True, "sha256": sha(data)}
if b'__version__ = "0.1.0"' not in get("gps_lag.py"):
    sys.exit("gps_lag.py on main is not 0.1.0, the version fleet-2026 measured with")

for name in ("fleet.py", "innov.py", "test_fleet.py", "test_innov.py"):
    with open(name, "rb") as f:
        local = sha(f.read())
    try:
        remote = sha(get(name))
    except urllib.error.HTTPError as exc:
        remote = "missing (%s)" % exc.code
    fetched[name] = {"local_sha256": local, "main_sha256": remote, "same_as_main": local == remote}

with open("fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched), flush=True)
