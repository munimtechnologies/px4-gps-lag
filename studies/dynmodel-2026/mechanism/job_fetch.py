"""For the dynmodel-2026 mechanism job only. Nothing is read from the logs before the plan is public:
wait (up to 150 min) for studies/dynmodel-2026/PLAN-mechanism.md on px4-gps-lag's main, check that
this folder's mechanism.py and test_mechanism.py are main's copies, fetch gps_lag.py and innov.py at
the commit px4-log-health's checkup pins, the published paired rows, and logs_dynmodel.zip from PX4
PR #24831 (checked against the sha256 the paired job recorded). Writes job-fetched.json.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/"
MAIN = RAW + "main/"
PIN = RAW + "967b5ad92d04ca6ac7e29684b411fbf5df243e05/"
STUDY = "studies/dynmodel-2026/"
MAIN_GPS_LAG = "3338d74392ad22939838c2252e38719ef8d1407d55cb6d8f9b12fb8c569c903d"
ZIP = ("https://github.com/user-attachments/files/20456409/logs_dynmodel.zip",
       "aa6997a9754d4a11149bb4aa23f9721e16450eba4dc4808c0644ed2e04343b49")
UA = "px4-gps-lag-mechanism/0.1.0 (MV2 of Munim, Inc.; mv2@munimtech.com)"


def get(url, timeout=120):
    sep = "&" if "?" in url else "?"
    if url.startswith(MAIN):
        url = url + sep + "t=%d" % time.time()
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
        data = get(MAIN + STUDY + "PLAN-mechanism.md")
        fetched["PLAN-mechanism.md"] = {"on_main": True, "sha256": sha(data), "waited_s": attempt * 90}
        break
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or attempt == 100:
            sys.exit("%sPLAN-mechanism.md is not on main (%s)" % (STUDY, exc.code))
        print("PLAN-mechanism.md not on main yet; waiting 90 s", flush=True)
        time.sleep(90)

for name in ("mechanism.py", "test_mechanism.py"):
    with open(name, "rb") as f:
        local = sha(f.read())
    remote = None
    for attempt in range(21):                      # the code may land a minute after the plan
        try:
            remote = sha(get(MAIN + STUDY + "mechanism/" + name))
            if remote == local:
                break
        except urllib.error.HTTPError:
            pass
        time.sleep(30)
    fetched[name] = {"local_sha256": local, "main_sha256": remote, "same_as_main": local == remote}
    if local != remote:
        sys.exit("%s here is not main's %smechanism/%s" % (name, STUDY, name))

for name, must in (("gps_lag.py", b'__version__ = "0.1.0"'), ("innov.py", b'__version__ = "0.2.0"')):
    src = get_retry(PIN + name)
    if must not in src:
        sys.exit("%s at the pinned commit is not the expected version" % name)
    fetched[PIN + name] = {"sha256": sha(src)}
    if name == "gps_lag.py":
        fetched[PIN + name]["same_as_main_pinned_copy"] = sha(src) == MAIN_GPS_LAG
    with open(name, "wb") as f:
        f.write(src)

rows = get_retry(MAIN + STUDY + "paired/paired-rows.jsonl")
fetched[STUDY + "paired/paired-rows.jsonl"] = {"sha256": sha(rows), "lines": rows.count(b"\n")}
with open("paired-rows.jsonl", "wb") as f:
    f.write(rows)

data = get(ZIP[0], timeout=600)
h = hashlib.sha256(data).hexdigest()
fetched[ZIP[0]] = {"sha256": h, "bytes": len(data), "matches_paired_job": h == ZIP[1]}
if h != ZIP[1]:
    sys.exit("logs_dynmodel.zip changed since the paired job (%s)" % h)
os.makedirs("ulg", exist_ok=True)
n = 0
with zipfile.ZipFile(io.BytesIO(data)) as z:
    for info in z.infolist():
        if info.is_dir() or not info.filename.lower().endswith(".ulg"):
            continue
        base = os.path.basename(info.filename.replace("\\", "/")) or "log.ulg"
        with z.open(info) as s, open(os.path.join("ulg", "%03d_%s" % (n, base)), "wb") as d:
            shutil.copyfileobj(s, d)
        n += 1
fetched["ulogs"] = n
with open("job-fetched.json", "w") as f:
    json.dump(fetched, f, indent=1)
print(json.dumps(fetched, indent=1), flush=True)
