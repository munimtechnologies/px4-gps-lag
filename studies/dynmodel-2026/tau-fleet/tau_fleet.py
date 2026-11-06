"""tau_fleet: across the fleet, does u-blox dynamic model 6's extra GPS lag look like smoothing? (pre-registered)

px4-gps-lag study dynmodel-2026, fleet mechanism check. Plan: studies/dynmodel-2026/PLAN-tau-fleet.md,
committed before this code reads any log.

On the one vehicle flown at both models (the logs on PX4 PR #24831), mechanism.py found that model 6's
extra ~100 ms of GPS lag sits in a first-order low-pass time constant tau (110 ms against 20 ms), not
in the delay D after it (GRADE-mechanism.md). This script asks the same question of the fleet: it
takes dynmodel-2026's graded logs at GPS_UBX_DYNMODEL 6 and 7 (one per vehicle, lags published
before the question existed), downloads each one again from PX4 Flight Review in a seeded order, and
fits (tau, D) exactly as mechanism.py does (same grid, same GPS pairs as gps_lag.py, same per-log
moving-block bootstrap). Logs are downloaded one at a time, 6 s apart, and deleted once measured.
No position is read. Vehicle ids stay the hashes dynmodel-2026 published.

    python tau_fleet.py --rows dynmodel-rows.jsonl --out-dir out [--budget-min 200]

By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import argparse
import json
import os
import random
import statistics
import sys
import time

import numpy as np

__version__ = "0.1.0"

DOWNLOAD = "https://review.px4.io/download"
USER_AGENT = ("px4-gps-lag-tau-fleet/%s (MV2 of Munim, Inc.; mv2@munimtech.com; "
              "research on public logs)" % __version__)
ORDER_SEED = 20261119        # download order
BOOT_SEED = 20261120         # fleet bootstrap intervals
LOG_SEED = 20261107          # per-log moving-block bootstrap (mechanism-v1's seed)
LOG_RESAMPLES = 200
BLOCK = 25
BOOT = 2000
DELAY_S = 6.0
MAX_BYTES = 80 * 1000 * 1000
LOW, DEFAULT = 6, 7
MIN_REF = 5                  # a receiver class needs this many fitted model-7 logs to be a reference
MIN_LOW = 30                 # E0: fitted model-6 logs in reference classes
MIN_DEFAULT = 25             # E0: fitted model-7 logs in reference classes
T1_MIN_MS = 20.0
REPRO_MS = 2.0               # reported: the new lag within 2 ms of the published one
MIN_FIT_PAIRS = 100          # gps_lag.MIN_PAIRS


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- which logs

def units(rows):
    """dynmodel-2026's graded logs at model 6 or 7, in a seeded random order."""
    import dynmodel as dm
    out = []
    for r in dm.graded(rows):
        m = dm.dyn(r)
        if m not in (LOW, DEFAULT):
            continue
        out.append({"log_id": r["log_id"], "vehicle": r.get("vehicle"), "receiver": r["receiver"],
                    "dynmodel": m, "published_lag_ms": float(r["lag_ms"]),
                    "ver_sw_release": r.get("ver_sw_release"), "sample": r.get("sample")})
    out.sort(key=lambda u: u["log_id"])
    random.Random(ORDER_SEED).shuffle(out)
    return out


# ---------------------------------------------------------------- one log

def boot_weights(n, resamples=LOG_RESAMPLES, seed=LOG_SEED, block=BLOCK):
    """Row 0: all ones (the fit itself). Rows 1..: one moving-block resample each, drawn in the same
    order as mechanism.fit_grid draws them."""
    import mechanism as mc
    rng = np.random.default_rng(seed)
    W = np.ones((resamples + 1, n))
    for b in range(resamples):
        W[b + 1] = np.bincount(mc.block_indices(n, rng, block), minlength=n)
    return W


def fit_lite(imu_t, a_ne, t1, t2, dv, resamples=LOG_RESAMPLES, seed=LOG_SEED, block=BLOCK):
    """mechanism.fit_grid's (tau, D) fit and bootstrap, one tau at a time so that memory stays small.
    Returns (fit, taus_ms, lags_ms) like mechanism.fit_grid, without the profile."""
    import mechanism as mc
    imu_t = np.asarray(imu_t, dtype=float)
    t1 = np.asarray(t1, dtype=float)
    t2 = np.asarray(t2, dtype=float)
    dv = np.asarray(dv, dtype=float)
    V = mc.cumulative(imu_t, a_ne)
    d = t2 - t1
    n = len(t1)
    W = boot_weights(n, resamples, seed, block)
    sdd = W @ (d * d)                                            # (B+1,)
    sse = np.empty((resamples + 1, len(mc.TAUS), len(mc.LAGS)))
    X = np.empty((len(mc.LAGS), n, V.shape[1]))
    for i, tau in enumerate(mc.TAUS):
        F = mc.lowpass(imu_t, V, tau)
        for j, lag in enumerate(mc.LAGS):
            for k in range(V.shape[1]):
                X[j, :, k] = np.interp(t2 - lag, imu_t, F[:, k]) - np.interp(t1 - lag, imu_t, F[:, k])
        r = dv[None, :, :] - X                                   # (lags, n, axes)
        s2 = np.tensordot(W, r * r, axes=([1], [1]))             # (B+1, lags, axes)
        sd = np.tensordot(W, r * d[None, :, None], axes=([1], [1]))
        sse[:, i, :] = np.sum(s2 - sd * sd / sdd[:, None, None], axis=2)
    sst = float(np.sum((dv - dv.mean(axis=0)) ** 2))
    s0 = sse[0]
    i, j = mc.argbest(s0)
    j0 = int(np.argmin(s0[0]))
    fit = {"pairs": n, "tau_ms": mc.ms(mc.TAUS[i]), "lag_ms": mc.ms(mc.LAGS[j]),
           "sum_ms": mc.ms(mc.TAUS[i] + mc.LAGS[j]),
           "r2": round(1.0 - float(s0[i, j]) / sst, 5),
           "lag_tau0_ms": mc.ms(mc.LAGS[j0]), "r2_tau0": round(1.0 - float(s0[0, j0]) / sst, 5),
           "tau_edge": i == len(mc.TAUS) - 1, "lag_edge": j in (0, len(mc.LAGS) - 1)}
    taus, lags = [], []
    for b in range(1, resamples + 1):
        bi, bj = mc.argbest(sse[b])
        taus.append(mc.ms(mc.TAUS[bi]))
        lags.append(mc.ms(mc.LAGS[bj]))
    taus, lags = np.asarray(taus), np.asarray(lags)
    if resamples:
        fit["boot"] = {"tau_ms": mc.pct3(taus), "lag_ms": mc.pct3(lags), "sum_ms": mc.pct3(taus + lags),
                       "tau_at_edge_share": round(float(np.mean(taus >= mc.ms(mc.TAUS[-1]))), 3)}
        fit["identified"] = bool(mc.identified(fit))
    return fit, taus, lags


def measure(path, published_ms):
    """gps_lag.py's verdict and the (tau, D) fit on the same GPS pairs."""
    import gps_lag as gl
    log = gl.read_log(path)
    row = {}
    v = gl.measure(log)
    row["gps_lag_passed"] = bool(v.get("passed"))
    row["gps_lag_reason"] = v.get("reason")
    row["gps_lag_ms"] = v.get("lag_ms")
    row["reproduced"] = (v.get("lag_ms") is not None and abs(float(v["lag_ms"]) - published_ms) <= REPRO_MS)
    facts = log.get("facts") or {}
    row["param_gps_delay_ms"] = facts.get("param_gps_delay_ms")
    row["gps_logged_dt_ms"] = (None if facts.get("gps_logged_dt_s") is None
                               else round(float(facts["gps_logged_dt_s"]) * 1e3, 1))
    row["log_release"] = facts.get("ver_sw_release")
    flying = gl.flying_at(log["gps_t"], log["land_t"], log["landed"])
    usable = np.asarray(log["usable"], dtype=bool) & np.asarray(flying, dtype=bool)
    idx = gl.gps_pairs(log["gps_t"], usable, log["imu_t"])
    if len(idx) < MIN_FIT_PAIRS:
        row["fit"] = None
        return row
    gps_t = np.asarray(log["gps_t"], dtype=float)
    vel = np.asarray(log["vel_ne"], dtype=float)
    imu_t = np.asarray(log["imu_t"], dtype=float)
    a_ne = gl.ne_accel(imu_t, log["f_body"], log["att_t"], log["q"])
    fit, _, _ = fit_lite(imu_t, a_ne, gps_t[idx], gps_t[idx + 1], vel[idx + 1] - vel[idx])
    row["fit"] = fit
    return row


def counts(row):
    """(True, 'ok') when a measured row is fitted and graded, else (False, why)."""
    if row.get("download") != "ok":
        return False, "download %s" % row.get("download")
    if row.get("error"):
        return False, "error"
    if not row.get("gps_lag_passed"):
        return False, "gps_lag: %s" % row.get("gps_lag_reason")
    if not row.get("fit"):
        return False, "too few GPS pairs"
    return True, "ok"


# ---------------------------------------------------------------- scoring

def _pct(sorted_xs, q):
    return sorted_xs[int(round(q * (len(sorted_xs) - 1)))]


def classes_of(rows, key):
    """{receiver: {dynmodel: [value, ...]}} for counted rows; key picks the value from the fit."""
    c = {}
    for r in rows:
        c.setdefault(r["receiver"], {}).setdefault(r["dynmodel"], []).append(float(key(r)))
    return c


def _residuals(classes, low, pick=None):
    res = []
    for name in sorted(classes):
        g = classes[name]
        ref, lows = g.get(DEFAULT, []), g.get(low, [])
        if len(ref) >= MIN_REF and lows:
            m = statistics.median(pick(ref) if pick else ref)
            res.extend(x - m for x in (pick(lows) if pick else lows))
    return res


def resid(classes, low=LOW, seed=BOOT_SEED, only=None):
    """dynmodel.resid's statistic: median over model-6 logs of (value - median value of the same
    receiver class's model-7 logs), classes with at least MIN_REF model-7 logs, with a seeded
    percentile bootstrap 95% interval (both groups resampled within each class)."""
    cl = {c: g for c, g in classes.items() if only is None or c in only}
    res = _residuals(cl, low)
    if not res:
        return None
    rng = random.Random(seed)
    stats = sorted(statistics.median(_residuals(cl, low, lambda xs: rng.choices(xs, k=len(xs))))
                   for _ in range(BOOT))
    return {"n_low": len(res), "median_ms": round(statistics.median(res), 1),
            "ci95_ms": [round(_pct(stats, 0.025), 1), round(_pct(stats, 0.975), 1)]}


def ref_counts(classes):
    """(model-6 logs, model-7 logs) in reference classes."""
    n6 = n7 = 0
    for g in classes.values():
        if len(g.get(DEFAULT, [])) >= MIN_REF:
            n6 += len(g.get(LOW, []))
            n7 += len(g.get(DEFAULT, []))
    return n6, n7


def med(xs):
    xs = [float(x) for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def summarise(rows):
    """The plan's checks, from every attempted row."""
    ok = [r for r in rows if r.get("counts")]
    tau_c = classes_of(ok, lambda r: r["fit"]["tau_ms"])
    lag_c = classes_of(ok, lambda r: r["fit"]["lag_ms"])
    sum_c = classes_of(ok, lambda r: r["fit"]["sum_ms"])
    n6, n7 = ref_counts(tau_c)
    t1 = resid(tau_c, seed=BOOT_SEED)
    dres = resid(lag_c, seed=BOOT_SEED + 1)
    sres = resid(sum_c, seed=BOOT_SEED + 2)
    e0 = n6 >= MIN_LOW and n7 >= MIN_DEFAULT
    checks = {"E0": e0, "T1": None, "T2": None}
    if e0:
        checks["T1"] = bool(t1) and t1["median_ms"] >= T1_MIN_MS and t1["ci95_ms"][0] > 0
        checks["T2"] = bool(t1 and dres) and t1["median_ms"] > dres["median_ms"]
    if not e0:
        decision = "H0"
    elif checks["T1"] and checks["T2"]:
        decision = "H1"
    elif checks["T1"]:
        decision = "H2"
    else:
        decision = "H3"
    return {"tau_fleet": __version__, "order_seed": ORDER_SEED, "boot_seed": BOOT_SEED,
            "fitted": len(ok), "ref_dyn6": n6, "ref_dyn7": n7,
            "T1_tau_resid": t1, "T2_lag_resid": dres, "sum_resid": sres,
            "checks": checks, "decision": decision, "reported": report(rows, ok)}


def report(rows, ok):
    """Breakdowns the plan does not score."""
    why = {}
    for r in rows:
        why[r.get("why", "")] = why.get(r.get("why", ""), 0) + 1
    by = {}
    for r in ok:
        f = r["fit"]
        b = by.setdefault(r["receiver"], {}).setdefault(str(r["dynmodel"]), {"tau": [], "lag": [], "sum": [],
                                                                             "ident": 0, "edge": 0})
        b["tau"].append(f["tau_ms"])
        b["lag"].append(f["lag_ms"])
        b["sum"].append(f["sum_ms"])
        b["ident"] += 1 if f.get("identified") else 0
        b["edge"] += 1 if f.get("tau_edge") else 0
    table = {c: {m: {"n": len(v["tau"]), "median_tau_ms": med(v["tau"]), "median_lag_ms": med(v["lag"]),
                     "median_sum_ms": med(v["sum"]), "identified": v["ident"], "tau_at_grid_top": v["edge"]}
                 for m, v in sorted(g.items())} for c, g in sorted(by.items())}
    rep = [r for r in ok if r.get("reproduced")]
    fast = [r for r in ok if r.get("gps_logged_dt_ms") is not None and r["gps_logged_dt_ms"] <= 150.0]
    ident = [r for r in ok if r["fit"].get("identified")]
    gain = {}
    for m in (LOW, DEFAULT):
        xs = []
        for r in ok:
            f = r["fit"]
            if r["dynmodel"] == m and f["r2_tau0"] < 1.0:
                xs.append((f["r2"] - f["r2_tau0"]) / (1.0 - f["r2_tau0"]))
        gain[str(m)] = round(statistics.median(xs), 3) if xs else None
    return {
        "note": "not pre-registered; descriptive only",
        "why_counts": why,
        "by_receiver_and_model": table,
        "reproduced_within_2ms": {"n": len(rep), "of": len(ok)},
        "tau_resid_reproduced_only": resid(classes_of(rep, lambda r: r["fit"]["tau_ms"]), seed=BOOT_SEED + 3),
        "tau_resid_gps_logged_le_150ms": resid(classes_of(fast, lambda r: r["fit"]["tau_ms"]), seed=BOOT_SEED + 4),
        "tau_resid_identified_only": resid(classes_of(ident, lambda r: r["fit"]["tau_ms"]), seed=BOOT_SEED + 5),
        "tau_resid_f9p": resid(classes_of(ok, lambda r: r["fit"]["tau_ms"]), seed=BOOT_SEED + 6, only=("ubx_f9p",)),
        "median_residual_variance_cut_by_lowpass": gain,
    }


# ---------------------------------------------------------------- network and the loop

def download(session, log_id, path):
    """'ok', 'missing', 'too large' or 'failed'. Raises Blocked on 403/429/444."""
    import requests
    url = DOWNLOAD + "?log=" + log_id
    for attempt in range(5):
        try:
            with session.get(url, stream=True, timeout=600) as r:
                if r.status_code in (403, 429, 444):
                    raise Blocked("HTTP %d" % r.status_code)
                if r.status_code == 404:
                    return "missing"
                if r.status_code == 503:
                    try:
                        wait = float(r.headers.get("Retry-After"))
                    except (TypeError, ValueError):
                        wait = min(30 * 2 ** attempt, 300)
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    time.sleep(10)
                    continue
                if int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
                    return "too large"
                n = 0
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        n += len(chunk)
                        if n > MAX_BYTES:
                            break
                        f.write(chunk)
                if n > MAX_BYTES:
                    os.remove(path)
                    return "too large"
                return "ok"
        except requests.RequestException:
            time.sleep(10)
    return "failed"


def run(todo, fetch, write, out_of_time=lambda: False, sleep=lambda s: None):
    """Visit units in order; fetch(unit) returns the measured fields (may raise Blocked); write(row)
    records every attempt, and units never attempted. Returns {'attempted', 'stop'}."""
    attempted, stop = 0, None
    for u in todo:
        row = dict(u)
        if stop:
            row.update({"download": "not attempted", "counts": False, "why": "not attempted (%s)" % stop})
            write(row)
            continue
        if out_of_time():
            stop = "budget"
            row.update({"download": "not attempted", "counts": False, "why": "not attempted (budget)"})
            write(row)
            continue
        if attempted:
            sleep(DELAY_S)
        attempted += 1
        try:
            row.update(fetch(u))
        except Blocked as exc:
            stop = "blocked: %s" % exc
            row.update({"download": "blocked", "counts": False, "why": stop})
            write(row)
            continue
        ok, why = counts(row)
        row["counts"], row["why"] = ok, why
        write(row)
    return {"attempted": attempted, "stop": stop or "list exhausted"}


def main(argv=None):
    import requests
    import mechanism as mc
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--budget-min", type=float, default=200)
    ap.add_argument("--tmp", default="/tmp/px4-tau-fleet")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.tmp, exist_ok=True)
    started = time.time()
    with open(args.rows, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    todo = units(rows)
    print("tau_fleet: %d logs (%d at model 6, %d at model 7)" % (
        len(todo), sum(u["dynmodel"] == LOW for u in todo), sum(u["dynmodel"] == DEFAULT for u in todo)), flush=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    path = os.path.join(args.tmp, "log.ulg")

    def fetch(u):
        row = {"download": download(session, u["log_id"], path)}      # raises Blocked
        if row["download"] == "ok":
            try:
                row.update(measure(path, u["published_lag_ms"]))
            except Exception as exc:                                  # a log pyulog or gps_lag can't read
                row["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            finally:
                if os.path.exists(path):
                    os.remove(path)
        return row

    deadline = started + args.budget_min * 60
    out_rows = []
    with open(os.path.join(args.out_dir, "tau-rows.jsonl"), "w", encoding="utf-8") as out:
        def write(row):
            row = mc.plain(row)
            out_rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
            f = row.get("fit") or {}
            print("%s model %s %s: %s tau %s D %s" % (row["log_id"], row["dynmodel"], row["receiver"],
                  row["why"], f.get("tau_ms"), f.get("lag_ms")), flush=True)
        res = run(todo, fetch, write, out_of_time=lambda: time.time() > deadline, sleep=time.sleep)
    summary = summarise(out_rows)
    summary.update({"units": len(todo), "attempted": res["attempted"], "stopped": res["stop"],
                    "wall_s": round(time.time() - started, 1)})
    summary = mc.plain(summary)
    text = json.dumps(summary, indent=1)
    with open(os.path.join(args.out_dir, "tau-summary.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
