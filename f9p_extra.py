"""f9p-2026, exploratory pass: what might separate the F9P logs' two lag groups?

For every passing u-blox F9P log in a sample's logs.jsonl, downloads the log again from
PX4 Flight Review (6 s apart; stops at the first 403 or 444) and keeps only:
the GPS-related parameters (GPS_*, SER_GPS*, SENS_GPS*, EKF2_GPS_*), the median number of
satellites used while the fix is 3D or better, and the firmware's own console messages that
mention the GPS (u-blox, UBX, GNSS, RTK, baud). No position, time of day or other message is
kept, and each log is deleted after reading. Nothing here is a scored check of the plan.

    python f9p_extra.py --logs logs.jsonl --out f9p-extra.jsonl [--budget-min 45]

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import re
import statistics
import time

__version__ = "0.1.0"

URL = "https://review.px4.io/download?log=%s"
PARAM_PREFIXES = ("GPS_", "SER_GPS", "SENS_GPS", "EKF2_GPS_")
MSG = re.compile(r"(?i)u-?blox|\bubx\b|gnss|\bgps\b|\brtk\b|baud|f9p|\bfw\b|firmware ver")
MAX_MESSAGES = 40
MAX_CHARS = 200
SPACING_S = 6.0


def pick_params(params):
    """The GPS-related parameters, sorted by name."""
    return {k: params[k] for k in sorted(params) if k.startswith(PARAM_PREFIXES)}


def pick_messages(texts):
    """GPS-related console messages, first occurrence only, at most 40, each cut to 200 characters."""
    out = []
    for t in texts:
        t = (t or "").strip()[:MAX_CHARS]
        if t and MSG.search(t) and t not in out:
            out.append(t)
            if len(out) == MAX_MESSAGES:
                break
    return out


def sats_median(sats, fix_types):
    """Median satellites used over samples with fix_type >= 3 (3D or better), or None."""
    used = [s for s, f in zip(sats, fix_types) if f >= 3]
    return float(statistics.median(used)) if used else None


def wanted(rows):
    return [r["log_id"] for r in rows if r.get("passed") is True and r.get("receiver") == "ubx_f9p"
            and r.get("lag_ms") is not None]


def read_log(path):
    from pyulog import ULog
    ulog = ULog(path, message_name_filter_list=["vehicle_gps_position", "sensor_gps"])
    out = {"params": pick_params(ulog.initial_parameters),
           "messages": pick_messages(m.message for m in ulog.logged_messages)}
    gps = [d for d in ulog.data_list if d.name in ("vehicle_gps_position", "sensor_gps") and d.multi_id == 0]
    gps.sort(key=lambda d: d.name != "vehicle_gps_position")
    if gps and "satellites_used" in gps[0].data and "fix_type" in gps[0].data:
        out["sats_median"] = sats_median([int(x) for x in gps[0].data["satellites_used"]],
                                         [int(x) for x in gps[0].data["fix_type"]])
    else:
        out["sats_median"] = None
    return out


def main(argv=None):
    import requests
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget-min", type=float, default=45)
    ap.add_argument("--tmp", default="/tmp/px4-gps-lag-f9p")
    args = ap.parse_args(argv)
    try:
        import fleet
        agent = fleet.USER_AGENT
    except Exception:
        agent = "px4-gps-lag f9p_extra (MV2 of Munim, Inc.; mv2@munimtech.com)"
    with open(args.logs, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    ids = wanted(rows)
    os.makedirs(args.tmp, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = agent
    t0, done = time.time(), 0
    with open(args.out, "w", encoding="utf-8") as out:
        for i, log_id in enumerate(ids):
            if time.time() - t0 > args.budget_min * 60:
                print("f9p_extra: time budget reached after %d of %d" % (i, len(ids)), flush=True)
                break
            if i:
                time.sleep(SPACING_S)
            path = os.path.join(args.tmp, "%s.ulg" % log_id)
            rec = {"log_id": log_id, "f9p_extra": __version__}
            try:
                resp = session.get(URL % log_id, timeout=180, stream=True)
                if resp.status_code in (403, 444):
                    print("f9p_extra: server answered %d; stopping" % resp.status_code, flush=True)
                    break
                if resp.status_code != 200:
                    rec["error"] = "http %d" % resp.status_code
                else:
                    with open(path, "wb") as f:
                        for chunk in resp.iter_content(1 << 20):
                            f.write(chunk)
                    rec.update(read_log(path))
                    done += 1
            except Exception as exc:   # one bad log must not stop the pass
                rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            finally:
                if os.path.exists(path):
                    os.remove(path)
            out.write(json.dumps(rec) + "\n")
            out.flush()
    print("f9p_extra: read %d of %d F9P logs" % (done, len(ids)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
