"""For the census-2026 job only. Nothing is read from Flight Review before the plan is public:
wait (up to 150 min) for studies/census-2026/PLAN.md on px4-gps-lag's main, check that this
folder's census.py and test_census.py are main's copies, and fetch dynmodel-2026's rows (their
vehicles are left out of the graded draw). Writes job-fetched.json.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/"
STUDY = "studies/census-2026/"
UA = "px4-gps-lag-census/0.1.0 (MV2 of Munim, Inc.; mv2@munimtech.com)"


def get(path):
    req = urllib.request.Request(BASE + path + "?t=%d" % time.time(),
                                 headers={"Cache-Control": "no-cache", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def get_retry(path, tries=21):
    for attempt in range(tries):
        try:
            return get(path)
        except urllib.error.HTTPError:
            if attempt == tries - 1:
                raise
            time.sleep(30)


fetched = {}
for attempt in range(101):
    try:
        data = get(STUDY + "PLAN.md")
        fetched["PLAN.md"] = {"on_main": True, "sha256": sha(data), "waited_s": attempt * 90}
        break
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or attempt == 100:
            sys.exit("%sPLAN.md is not on main (%s)" % (STUDY, exc.code))
        print("PLAN.md not on main yet; waiting 90 s", flush=True)
        time.sleep(90)

for name in ("census.py", "test_census.py"):
    with open(name, "rb") as f:
        local = sha(f.read())
    remote = None
    for attempt in range(21):                      # the code may land a minute after the plan
        try:
            remote = sha(get(STUDY + name))
            if remote == local:
                break
        except urllib.error.HTTPError:
            pass
        time.sleep(30)
    fetched[name] = {"local_sha256": local, "main_sha256": remote, "same_as_main": local == remote}
    if local != remote:
        sys.exit("%s here is not main's %s%s" % (name, STUDY, name))

path = "studies/dynmodel-2026/dynmodel-rows.jsonl"
data = get_retry(path)
fetched[path] = {"sha256": sha(data), "lines": data.count(b"\n")}
if sha(data) != "96bc66f6c0add13617ed664294a4973d7c81d6ea063e9603c16316d447326aa9":
    sys.exit("%s changed (%s)" % (path, sha(data)))
with open("dynmodel-rows.jsonl", "wb") as f:
    f.write(data)

with open("job-fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched, indent=1), flush=True)
