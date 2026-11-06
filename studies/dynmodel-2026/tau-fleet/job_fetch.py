"""For the dynmodel-2026 fleet tau job only. Nothing is downloaded from Flight Review before the plan is
public: wait (up to 150 min) for studies/dynmodel-2026/PLAN-tau-fleet.md on px4-gps-lag's main, check
that this folder's tau_fleet.py and test_tau_fleet.py are main's copies, fetch mechanism.py (the copy
mechanism-v1 ran), gps_lag.py at the commit px4-log-health's checkup pins, dynmodel.py and the published
dynmodel-rows.jsonl. Writes job-fetched.json.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/"
MAIN = RAW + "main/"
PIN = RAW + "967b5ad92d04ca6ac7e29684b411fbf5df243e05/"
STUDY = "studies/dynmodel-2026/"
GPS_LAG_SHA = "3338d74392ad22939838c2252e38719ef8d1407d55cb6d8f9b12fb8c569c903d"
MECHANISM_SHA = "2c54577586bd17ebff624a38016bbe48dcb66f31ac5f586f7d532fd49896b44f"
UA = "px4-gps-lag-tau-fleet/0.1.0 (MV2 of Munim, Inc.; mv2@munimtech.com)"


def get(url, timeout=120):
    if url.startswith(MAIN):
        url = url + ("&" if "?" in url else "?") + "t=%d" % time.time()
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def get_retry(url, tries=21):
    for attempt in range(tries):
        try:
            return get(url)
        except urllib.error.HTTPError:
            if attempt == tries - 1:
                raise
            time.sleep(30)


fetched = {}
for attempt in range(101):
    try:
        data = get(MAIN + STUDY + "PLAN-tau-fleet.md")
        fetched["PLAN-tau-fleet.md"] = {"on_main": True, "sha256": sha(data), "waited_s": attempt * 90}
        break
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or attempt == 100:
            sys.exit("%sPLAN-tau-fleet.md is not on main (%s)" % (STUDY, exc.code))
        print("PLAN-tau-fleet.md not on main yet; waiting 90 s", flush=True)
        time.sleep(90)

for name in ("tau_fleet.py", "test_tau_fleet.py"):
    with open(name, "rb") as f:
        local = sha(f.read())
    remote = None
    for attempt in range(21):                      # the code may land a minute after the plan
        try:
            remote = sha(get(MAIN + STUDY + "tau-fleet/" + name))
            if remote == local:
                break
        except urllib.error.HTTPError:
            pass
        time.sleep(30)
    fetched[name] = {"local_sha256": local, "main_sha256": remote, "same_as_main": local == remote}
    if local != remote:
        sys.exit("%s here is not main's %stau-fleet/%s" % (name, STUDY, name))

src = get_retry(MAIN + STUDY + "mechanism/mechanism.py")
fetched[STUDY + "mechanism/mechanism.py"] = {"sha256": sha(src), "same_as_mechanism_v1": sha(src) == MECHANISM_SHA}
if sha(src) != MECHANISM_SHA:
    sys.exit("mechanism.py on main is not the copy mechanism-v1 ran")
with open("mechanism.py", "wb") as f:
    f.write(src)

src = get_retry(PIN + "gps_lag.py")
fetched[PIN + "gps_lag.py"] = {"sha256": sha(src), "same_as_mechanism_v1": sha(src) == GPS_LAG_SHA}
if sha(src) != GPS_LAG_SHA:
    sys.exit("gps_lag.py at the pinned commit is not the copy mechanism-v1 ran")
with open("gps_lag.py", "wb") as f:
    f.write(src)

src = get_retry(MAIN + "dynmodel.py")
if b'__version__ = "0.1.0"' not in src:
    sys.exit("dynmodel.py on main is not 0.1.0")
fetched["dynmodel.py"] = {"sha256": sha(src)}
with open("dynmodel.py", "wb") as f:
    f.write(src)

rows = get_retry(MAIN + STUDY + "dynmodel-rows.jsonl")
fetched[STUDY + "dynmodel-rows.jsonl"] = {"sha256": sha(rows), "lines": rows.count(b"\n")}
with open("dynmodel-rows.jsonl", "wb") as f:
    f.write(rows)

with open("job-fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched, indent=1), flush=True)
