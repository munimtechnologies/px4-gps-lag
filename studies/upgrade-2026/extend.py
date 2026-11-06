"""extend.py: upgrade-2026's extension. More tries per vehicle, scored only on new pairs.

px4-gps-lag study upgrade-2026, extension (pre-registered in studies/upgrade-2026/PLAN-ext.md).
upgrade-2026's first run (upgrade.py 0.1.0, D3) visited all 139 multicopters with eligible public
logs on both PX4 v1.16 and v1.17. With at most 3 tries a side it found 10 pairs, against the 12
its plan needed. This extension continues the same draw with up to 10 tries a side:

* the 10 vehicles paired in the first run are left out;
* every vehicle on both releases in today's list, and every vehicle the first run tried, is
  visited in a new seeded order (seed 20261115);
* on each side, the first run's attempts are reused first (no download; their rows are read from
  studies/upgrade-2026/v1/rows.jsonl), then untried logs in a seeded order, until one counts or
  10 attempts in all have been made on that side;
* a log counts exactly as in upgrade.py 0.1.0 (usable()), and the v1.17 log needs the same u-blox
  device type as the v1.16 log.

    python extend.py --out-dir out --v1-rows v1-rows.jsonl --v1-pairs v1-pairs.jsonl
                     [--budget-min 200] [--max-pairs 60] [--max-downloads 450]

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time

import upgrade as up

__version__ = "0.1.0"

SEED_X = 20261115          # vehicle order and log order of the extension
BOOT_SEED_X = 20261116     # bootstrap intervals of the new pairs (+1 switched, +2 unchanged)
TRIES_X = 10               # attempts per side, the first run's included
PRE, POST = up.PRE, up.POST


def d(p):
    return p["pre"]["lag_ms"] - p["post"]["lag_ms"]


# ---------------------------------------------------------------- the first run

def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def v1_attempts(rows):
    """{vehicle: {side: [rows in attempt order]}} of the first run."""
    by = {}
    for r in sorted(rows, key=lambda r: r["attempt"]):
        by.setdefault(r["vehicle"], {PRE: [], POST: []})[r["side"]].append(r)
    return by


# ---------------------------------------------------------------- the order

def plan_x(both, tried, paired, seed=SEED_X):
    """Vehicles not paired in the first run (on both releases now, or tried then), in a seeded
    order, and for each side the first run's attempts followed by the untried listed logs in a
    seeded order. Returns (order, cands); a candidate is ('v1', row) or ('new', listed entry)."""
    rng = random.Random(seed)
    order = sorted((set(both) | set(tried)) - set(paired))
    rng.shuffle(order)
    cands = {}
    for v in order:
        cands[v] = {}
        for side in (PRE, POST):
            old = (tried.get(v) or {}).get(side, [])
            done = {r["log_id"] for r in old}
            new = sorted((c for c in (both.get(v) or {}).get(side, []) if c["log_id"] not in done),
                         key=lambda c: c["log_id"])
            rng.shuffle(new)
            cands[v][side] = [("v1", r) for r in old] + [("new", c) for c in new]
    return order, cands


# ---------------------------------------------------------------- the draw

def draw_x(order, cands, fetch, write, max_pairs=60, max_downloads=450, out_of_time=lambda: False,
           sleep=lambda s: None, tries=TRIES_X):
    """Like upgrade.draw(), but a side may take up to `tries` attempts and the first run's
    attempts are reused without a download. fetch(entry) returns the measured row (may raise
    up.Blocked). write(row) records every attempt, reused ones included."""
    pairs, downloads, visited, stop, blocked = [], 0, 0, None, None
    for vi, v in enumerate(order):
        if len(pairs) >= max_pairs:
            stop = "max pairs"
            break
        visited = vi + 1
        got = {}
        for side in (PRE, POST):
            want = got[PRE]["devtype"] if side == POST else None
            for kind, c in cands[v][side][:tries]:
                if kind == "v1":
                    row = dict(c, source="v1", vehicle_rank_x=vi + 1)
                    if row.get("download") == "ok":
                        ok, why = up.usable(row, side, want)
                    else:
                        ok, why = False, "download %s" % row.get("download")
                else:
                    if downloads >= max_downloads:
                        stop = "max downloads"
                        break
                    if out_of_time():
                        stop = "budget"
                        break
                    if downloads:
                        sleep(up.DELAY_S)
                    downloads += 1
                    row = dict(c, source="ext", attempt_x=downloads, vehicle_rank_x=vi + 1, side=side)
                    try:
                        row.update(fetch(c))
                    except up.Blocked as exc:
                        blocked = stop = "blocked: %s" % exc
                        break
                    if row.get("download") == "ok":
                        ok, why = up.usable(row, side, want)
                    else:
                        ok, why = False, "download %s" % row.get("download")
                row["counts"], row["why"] = ok, why
                write(row)
                if ok:
                    got[side] = row
                    break
            if stop or side not in got:
                break
        if PRE in got and POST in got:
            pairs.append({"vehicle": v, "pre": got[PRE], "post": got[POST]})
        if stop:
            break
    else:
        stop = "list exhausted"
    return {"pairs": pairs, "downloads": downloads, "visited": visited, "stop": stop, "blocked": blocked}


# ---------------------------------------------------------------- scoring

def score_x(new_pairs):
    """The extension's pre-registered checks, on the new pairs only."""
    n = len(new_pairs)
    sw = [p for p in new_pairs if p["pre"]["dynmodel"] == 6 and p["post"]["dynmodel"] == 7]
    un = [p for p in new_pairs if p["pre"]["dynmodel"] == p["post"]["dynmodel"]]
    d_all, d_sw, d_un = [d(p) for p in new_pairs], [d(p) for p in sw], [d(p) for p in un]
    med_all, med_sw, med_un = up.median(d_all), up.median(d_sw), up.median(d_un)
    ci_all = up.boot_median(d_all, BOOT_SEED_X)
    x0 = n >= 8
    checks = {
        "X0": x0,
        "X1": bool(med_all >= 20 and ci_all is not None and ci_all[0] > 0) if x0 else None,
        "X2": bool(len(sw) / n >= 0.5) if x0 else None,
        "X3": bool(med_sw >= 30) if x0 and len(sw) >= 6 else None,
        "X4": bool(abs(med_un) <= 20) if x0 and len(un) >= 4 else None,
    }
    if not x0:
        decision = "DX3"
    elif checks["X1"] and checks["X3"]:
        decision = "DX1"
    elif checks["X1"] and checks["X3"] is None:
        decision = "DX4"
    else:
        decision = "DX2"
    return {
        "new_pairs": n,
        "diff_pre_minus_post_ms": {
            "all": {"n": n, "median": med_all, "ci95": ci_all},
            "switched_6_to_7": {"n": len(sw), "median": med_sw, "ci95": up.boot_median(d_sw, BOOT_SEED_X + 1)},
            "unchanged_model": {"n": len(un), "median": med_un, "ci95": up.boot_median(d_un, BOOT_SEED_X + 2)},
            "positive": sum(1 for x in d_all if x > 0),
        },
        "checks": checks,
        "decision": decision,
    }


def report_extra(new_pairs, v1_pairs, seen=frozenset()):
    """Reported, not graded: the first plan's own checks on all pairs (the 10 seen ones included),
    and simple descriptions of the new pairs."""
    pooled = up.summarise(list(v1_pairs) + list(new_pairs), seen)
    later = sum(1 for p in new_pairs if p["post"].get("log_date", "") >= p["pre"].get("log_date", ""))
    return {"pooled_first_plan": pooled,
            "new_post_log_not_before_pre_log": later,
            "new_receivers": up.summarise(new_pairs, seen)["receivers"] if new_pairs else {},
            "new_pre": up.summarise(new_pairs, seen)["pre"] if new_pairs else None,
            "new_post": up.summarise(new_pairs, seen)["post"] if new_pairs else None}


# ---------------------------------------------------------------- main

def main(argv=None):
    import ijson
    import requests
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--v1-rows", required=True)
    ap.add_argument("--v1-pairs", required=True)
    ap.add_argument("--budget-min", type=float, default=200)
    ap.add_argument("--max-pairs", type=int, default=60)
    ap.add_argument("--max-downloads", type=int, default=450)
    ap.add_argument("--seen", default="dynmodel-rows.jsonl")
    ap.add_argument("--tmp", default="/tmp/px4-upgrade-x")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.tmp, exist_ok=True)
    started = time.time()

    v1_rows, v1_pairs = read_jsonl(args.v1_rows), read_jsonl(args.v1_pairs)
    tried = v1_attempts(v1_rows)
    paired = {p["vehicle"] for p in v1_pairs}

    session = requests.Session()
    session.headers["User-Agent"] = up.USER_AGENT.replace("upgrade/", "upgrade-ext/")
    with session.get(up.DBINFO, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        resp.raw.decode_content = True
        both, counts = up.group(ijson.items(resp.raw, "item"))
    order, cands = plan_x(both, tried, paired)
    counts.update({"v1_rows": len(v1_rows), "v1_vehicles_tried": len(tried), "v1_paired": len(paired),
                   "vehicles_x": len(order),
                   "vehicles_x_not_on_both_now": sum(1 for v in order if v not in both)})
    print(json.dumps(counts), flush=True)

    path = os.path.join(args.tmp, "log.ulg")

    def fetch(c):
        row = {"download": up.download(session, c["log_id"], path)}     # raises Blocked
        if row["download"] == "ok":
            row.update(up.measure(path))
            os.remove(path)
        return row

    deadline = started + args.budget_min * 60
    with open(os.path.join(args.out_dir, "rows-ext.jsonl"), "w", encoding="utf-8") as out:
        def write(row):
            out.write(json.dumps(row, default=up.plain) + "\n")
            out.flush()
            print("%s %s %s %s %s lag %s model %s (%s)" % (row.get("source"), row["vehicle"], row["side"],
                  row["log_id"], row["counts"], row.get("lag_ms"), row.get("dynmodel"), row["why"]),
                  flush=True)
        res = draw_x(order, cands, fetch, write, max_pairs=args.max_pairs,
                     max_downloads=args.max_downloads, out_of_time=lambda: time.time() > deadline,
                     sleep=time.sleep)

    new_pairs = res["pairs"]
    seen = up.load_seen(args.seen)
    summary = score_x(new_pairs)
    summary.update({"extend": __version__, "upgrade": up.__version__, "seed": SEED_X,
                    "boot_seed": BOOT_SEED_X, "tries_per_side": TRIES_X, "list": counts,
                    "downloads": res["downloads"], "vehicles_visited": res["visited"],
                    "stopped": res["stop"], "blocked": res["blocked"],
                    "reported_not_graded": report_extra(new_pairs, v1_pairs, seen),
                    "wall_s": round(time.time() - started, 1)})
    with open(os.path.join(args.out_dir, "pairs-ext.jsonl"), "w", encoding="utf-8") as f:
        for p in new_pairs:
            f.write(json.dumps(p, default=up.plain) + "\n")
    text = json.dumps(summary, indent=1, default=up.plain)
    with open(os.path.join(args.out_dir, "summary-ext.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
