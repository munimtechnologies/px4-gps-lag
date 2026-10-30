"""Nothing is downloaded from Flight Review before the plan is public: wait (up
to 60 min) for studies/fleet-2026/PLAN-innov-confirm.md, GRADE-innov.md and
part 2's innov/innov.jsonl on px4-gps-lag's main, and for px4-log-health's
studies/fleet-health-2026/logs.jsonl and GRADE.md. Then fetch gps_lag.py,
test_gps_lag.py, fleet.py and test_fleet.py from px4-gps-lag's main unchanged,
save part 2's rows as v1-innov.jsonl and fleet-health-2026's rows as
health-logs.jsonl, and note whether this folder's innov.py and test_innov.py
match main's. Writes fetched.json.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

LAG = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/"
HEALTH = "https://raw.githubusercontent.com/munimtechnologies/px4-log-health/main/"
WAIT_FOR = ((LAG, "studies/fleet-2026/PLAN-innov-confirm.md"),
            (LAG, "studies/fleet-2026/GRADE-innov.md"),
            (LAG, "studies/fleet-2026/innov/innov.jsonl"),
            (HEALTH, "studies/fleet-health-2026/GRADE.md"),
            (HEALTH, "studies/fleet-health-2026/logs.jsonl"))


def get(base, path):
    req = urllib.request.Request(base + path, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


fetched = {}
for base, path in WAIT_FOR:
    key = ("px4-log-health/" if base == HEALTH else "") + path
    for attempt in range(41):
        try:
            data = get(base, path)
            fetched[key] = {"on_main": True, "sha256": sha(data), "waited_s": attempt * 90}
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or attempt == 40:
                sys.exit("%s is not on main (%s)" % (key, exc.code))
            print("%s not on main yet; waiting 90 s" % key, flush=True)
            time.sleep(90)

for base, path, local in ((LAG, "studies/fleet-2026/innov/innov.jsonl", "v1-innov.jsonl"),
                          (HEALTH, "studies/fleet-health-2026/logs.jsonl", "health-logs.jsonl")):
    rows = get(base, path)
    with open(local, "wb") as f:
        f.write(rows)
    fetched[("px4-log-health/" if base == HEALTH else "") + path]["lines"] = rows.count(b"\n")

for name in ("gps_lag.py", "test_gps_lag.py", "fleet.py", "test_fleet.py"):
    data = get(LAG, name)
    with open(name, "wb") as f:
        f.write(data)
    fetched[name] = {"from_main": True, "sha256": sha(data)}
if b'__version__ = "0.1.0"' not in get(LAG, "gps_lag.py"):
    sys.exit("gps_lag.py on main is not 0.1.0, the version both fleet runs measured with")

for name in ("innov.py", "test_innov.py"):
    with open(name, "rb") as f:
        local = sha(f.read())
    try:
        remote = sha(get(LAG, name))
    except urllib.error.HTTPError as exc:
        remote = "missing (%s)" % exc.code
    fetched[name] = {"local_sha256": local, "main_sha256": remote, "same_as_main": local == remote}

with open("fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched), flush=True)
