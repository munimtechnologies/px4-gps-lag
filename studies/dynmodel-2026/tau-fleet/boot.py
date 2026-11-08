"""Bootstrap for px4-gps-lag-tau-fleet: fetch the pre-registered code exactly as committed.

The plan, tau_fleet.py, test_tau_fleet.py and job_fetch.py were committed together to
munimtechnologies/px4-gps-lag in f2eb66b7 (2026-11-06T16:44:49Z), the only commit touching them.
This script downloads the three code files from that commit and checks each against the git blob
sha GitHub lists for it. Nothing is retyped. job_fetch.py then repeats its own checks against main.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import hashlib
import json
import sys
import time
import urllib.request

COMMIT = "f2eb66b7de860879c64513ee14291bba8bb5499a"
BASE = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/%s/studies/dynmodel-2026/tau-fleet/" % COMMIT
BLOBS = {
    "job_fetch.py": "c5ee68921a6a15e7d492130ca2cdf6185a4876b7",
    "tau_fleet.py": "60ce6f255e668622d71dcd111a71d02d9298cc5c",
    "test_tau_fleet.py": "c0aa8314dbd6dd7b88d9ee6ba6ae45af0f05cd98",
}
UA = "px4-gps-lag-tau-fleet-boot/0.1.0 (MV2 of Munim, Inc.; mv2@munimtech.com)"


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def get(url):
    for attempt in range(10):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as exc:  # network hiccup: retry, then give up
            if attempt == 9:
                raise
            print("retry %s: %s" % (url, exc), flush=True)
            time.sleep(30)


record = {"commit": COMMIT, "files": {}}
for name, want in BLOBS.items():
    data = get(BASE + name)
    got = blob_sha(data)
    record["files"][name] = {"blob_sha": got, "expected": want, "ok": got == want}
    if got != want:
        sys.exit("%s at %s has blob sha %s, expected %s" % (name, COMMIT[:7], got, want))
    with open(name, "wb") as f:
        f.write(data)

with open("boot-fetched.json", "w") as f:
    json.dump(record, f, indent=1)
print(json.dumps(record, indent=1), flush=True)
