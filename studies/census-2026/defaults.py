"""defaults.py: records which u-blox dynamic model each major open flight stack asks for by default,
pinned to commit SHAs (context for px4-gps-lag's census-2026; descriptive, not a prediction).

For each (repository, ref, path, pattern) it resolves the ref to a commit SHA through the GitHub API,
reads the file at that SHA from raw.githubusercontent.com, and writes every matching line (with its
line number and `after` following lines) to defaults.json and defaults.md.

    python defaults.py --out-dir out

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import re
import sys
import time

UA = "px4-gps-lag-defaults/0.1.0 (MV2 of Munim, Inc.; mv2@munimtech.com)"

TARGETS = [
    # (stack, repo, ref, path, pattern, lines after each match)
    ("PX4 v1.16.0 multicopter defaults", "PX4/PX4-Autopilot", "v1.16.0",
     "ROMFS/px4fmu_common/init.d/rc.mc_defaults", r"GPS_UBX_DYNMODEL", 0),
    ("PX4 v1.17.0 multicopter defaults", "PX4/PX4-Autopilot", "v1.17.0",
     "ROMFS/px4fmu_common/init.d/rc.mc_defaults", r"GPS_UBX_DYNMODEL", 0),
    ("PX4 v1.17.0 fixed-wing defaults", "PX4/PX4-Autopilot", "v1.17.0",
     "ROMFS/px4fmu_common/init.d/rc.fw_defaults", r"GPS_UBX_DYNMODEL", 0),
    ("PX4 v1.17.0 parameter default", "PX4/PX4-Autopilot", "v1.17.0",
     "src/drivers/gps/params.c", r"PARAM_DEFINE_INT32\(GPS_UBX_DYNMODEL", 0),
    ("ArduPilot master", "ArduPilot/ardupilot", "master",
     "libraries/AP_GPS/AP_GPS.cpp", r"_NAVFILTER", 0),
    ("Betaflight master", "betaflight/betaflight", "master",
     "src/main/pg/gps.c", r"gps_ublox_(flight|acquire)_model", 0),
    ("INAV master", "iNavFlight/inav", "master",
     "src/main/fc/settings.yaml", r"^\s*-?\s*name:\s*gps_dyn_model\s*$", 6),
]


def find(text, pattern, after=0):
    """[{'line': n (1-based), 'text': line, 'after': [following lines]}] for lines matching pattern."""
    lines = text.splitlines()
    rx = re.compile(pattern)
    out = []
    for i, line in enumerate(lines):
        if rx.search(line):
            out.append({"line": i + 1, "text": line.rstrip(),
                        "after": [x.rstrip() for x in lines[i + 1:i + 1 + after]]})
    return out


def http_get(url, accept=None):
    import urllib.request
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", "replace")


def resolve(repo, ref, get=http_get):
    return get("https://api.github.com/repos/%s/commits/%s" % (repo, ref),
               accept="application/vnd.github.sha").strip()


def record(target, get=http_get):
    stack, repo, ref, path, pattern, after = target
    row = {"stack": stack, "repo": repo, "ref": ref, "path": path, "pattern": pattern}
    try:
        sha = resolve(repo, ref, get)
        row["sha"] = sha
        row["url"] = "https://github.com/%s/blob/%s/%s" % (repo, sha, path)
        text = get("https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, path))
        row["matches"] = find(text, pattern, after)
        row["status"] = "ok"
    except Exception as exc:
        row["status"] = "error: %s: %s" % (type(exc).__name__, str(exc)[:200])
    return row


def markdown(rows):
    out = ["# u-blox dynamic-model defaults in open flight stacks (recorded %s)" %
           time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), ""]
    for r in rows:
        out.append("## %s" % r["stack"])
        out.append("")
        if r["status"] != "ok":
            out.append("`%s` at `%s`: %s" % (r["path"], r["ref"], r["status"]))
            out.append("")
            continue
        out.append("[`%s`](%s) at %s (`%s`)" % (r["path"], r["url"], r["ref"], r["sha"][:12]))
        out.append("")
        if not r["matches"]:
            out.append("No line matches `%s`." % r["pattern"])
        else:
            out.append("```")
            for m in r["matches"]:
                out.append("%d: %s" % (m["line"], m["text"]))
                for k, a in enumerate(m["after"]):
                    out.append("%d: %s" % (m["line"] + k + 1, a))
            out.append("```")
        out.append("")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    rows = []
    for t in TARGETS:
        rows.append(record(t))
        time.sleep(1)
    with open(os.path.join(args.out_dir, "defaults.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    md = markdown(rows)
    with open(os.path.join(args.out_dir, "defaults.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md, flush=True)
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
