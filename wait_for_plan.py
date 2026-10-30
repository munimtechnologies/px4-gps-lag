"""Nothing is downloaded before the plan is public: wait (up to 30 min) for
studies/fleet-2026/PLAN.md on px4-gps-lag's main, then note whether this
folder's gps_lag.py and fleet.py match main's copies. Writes fetched.json.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/"


def get(url):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


fetched = {}
for attempt in range(21):
    try:
        data = get(BASE + "studies/fleet-2026/PLAN.md")
        fetched["PLAN.md"] = {"on_main": True, "sha256": sha(data), "waited_s": attempt * 90}
        break
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or attempt == 20:
            sys.exit("studies/fleet-2026/PLAN.md is not on main (%s)" % exc.code)
        print("PLAN.md not on main yet; waiting 90 s", flush=True)
        time.sleep(90)

for name in ("gps_lag.py", "fleet.py"):
    with open(name, "rb") as f:
        local = sha(f.read())
    try:
        remote = sha(get(BASE + name))
    except urllib.error.HTTPError as exc:
        remote = "missing (%s)" % exc.code
    fetched[name] = {"local_sha256": local, "main_sha256": remote, "same_as_main": local == remote}

with open("fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched), flush=True)
