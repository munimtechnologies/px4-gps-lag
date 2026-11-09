"""Fetches gnss_logs.py and dronecan_logs.py (the code nodefw.py builds on) from px4-gps-lag's main,
so nodefw's synthetic tests can run before any log is read. By MV2 of Munim, Inc.; written with AI
agents. Apache-2.0."""

import hashlib
import json
import urllib.request

RAW = "https://raw.githubusercontent.com/munimtechnologies/px4-gps-lag/main/%s"
out = {}
for path, local in (("studies/gnss-2026/gnss_logs.py", "gnss_logs.py"),
                    ("studies/dronecan-2026/dronecan_logs.py", "dronecan_logs.py")):
    req = urllib.request.Request(RAW % path, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    with open(local, "wb") as f:
        f.write(data)
    out[path] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
print(json.dumps(out, indent=1))
