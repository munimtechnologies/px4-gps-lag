# dynmodel-2026, fleet mechanism check: is model 6's extra lag smoothing across public logs too? (grade)

Graded on 2026-11-08 against [`PLAN-tau-fleet.md`](PLAN-tau-fleet.md) (pre-registered 2026-11-06, before any of these logs was downloaded again). **Result: E0, T1 and T2 all held, so the outcome is H1: across the fleet, model 6's extra GPS lag behaves like smoothing too.** The plan's stated odds for H1 were about 30%.

## What ran

- **The sealed job** was `px4-gps-lag-tau-fleet-v1`, run on 2026-11-07 from 19:43 to 21:07 UTC.
  - A boot step downloaded `job_fetch.py`, `tau_fleet.py` and `test_tau_fleet.py` from commit `f2eb66b7` (the commit that pre-registered them) and checked each against its git blob sha ([`tau-fleet/boot-fetched.json`](tau-fleet/boot-fetched.json)). All three matched.
  - `job_fetch.py` then checked them against `main` ([`tau-fleet/job-fetched.json`](tau-fleet/job-fetched.json)): `PLAN-tau-fleet.md` was on `main` (sha256 `50914be6…`, line endings normalised); `tau_fleet.py` (`d2752e44…`) and `test_tau_fleet.py` (`d8c68c5c…`) were `main`'s copies; `mechanism.py` was the copy the single-vehicle check used (`2c545775…`); `gps_lag.py` was the pinned `967b5ad` (`3338d743…`); and dynmodel-2026's rows were the published copy (`96bc66f6…`, 261 lines).
  - All 14 synthetic tests passed. Only then did it download any log.
- **The pass.** It downloaded the 166 graded dynmodel-2026 logs at models 6 and 7 (106 and 60) one at a time, 6 s apart, in the seeded order (seed 20261119). It was never blocked and stopped because the list was exhausted, after 82 minutes of its 200-minute budget.
  - All 166 downloads passed pinned `gps_lag.py` with at least 100 GPS pairs, so every unit was fitted.
  - Every log reproduced its published dynmodel-2026 lag within 2 ms (166 of 166), so these are the same flights, measured the same way.
- **The fit** is `mechanism.py`'s, unchanged: the IMU velocity is passed through a first-order low-pass with time constant τ (0 to 250 ms in 10 ms steps) and then delayed by D (−200 to +600 ms in 5 ms steps), and the (τ, D) that best explains each GPS velocity change, allowing a constant accelerometer bias, is the fit. Each log also gets a bootstrap interval.
- **The files.** Every row is in [`tau-fleet/tau-rows.jsonl`](tau-fleet/tau-rows.jsonl): log id, hashed vehicle id, receiver class, model, published and re-measured lag, τ, D, τ + D, fit quality and the bootstrap interval, with no positions. The scored figures are in [`tau-fleet/tau-summary.json`](tau-fleet/tau-summary.json).

## The checks

The fleet statistic is dynmodel-2026's K1 applied to τ: for each model-6 log, its τ minus the median τ of the same receiver class's model-7 logs, pooled over classes with at least 5 model-7 logs, with a seeded bootstrap interval (2,000 resamples, seed 20261120, both groups resampled within each class). The same is done for D and for τ + D. The u-blox M10 class (1 model-7 log) is not a reference class, so 104 model-6 and 59 model-7 logs are scored.

| | rule | result | |
|---|---|---|---|
| **E0** | at least 30 model-6 and 25 model-7 logs in reference classes | 104 and 59 | **held** |
| **T1** | τ residual ≥ +20 ms, interval above 0 | **+110 ms** (50 to 145) | **held** |
| **T2** | τ residual larger than the D residual | +110 ms against **−45 ms** (−75 to 0) | **held** |
| | τ + D residual (reported with the checks) | +53.8 ms (40 to 80) | |

**Decision: H1.** Model 6's extra lag sits in the fitted smoothing, not in a later delivery, on the fleet as on the one vehicle of [`GRADE-mechanism.md`](GRADE-mechanism.md) (τ 110 against 20 ms there). The τ + D residual, +53.8 ms, is close to the +45.6 ms lag gap dynmodel-2026 graded on the same logs (K1), so the fit accounts for the known gap rather than finding a new one.

## By receiver (descriptive, not pre-registered as checks)

Medians per class. "Identified" means τ's own bootstrap interval is at most 100 ms wide and neither the fit nor more than 5% of the draws sit at the top of the τ grid.

| receiver | model | logs | τ | D | τ + D | identified | τ at 250 ms |
|---|---|---|---|---|---|---|---|
| u-blox F9P | 6 | 15 | **150 ms** | 80 | 225 | 10 | 3 |
| | 7 | 12 | **30 ms** | 110 | 137.5 | 8 | 1 |
| u-blox M9 | 6 | 25 | **140 ms** | −15 | 120 | 14 | 3 |
| | 7 | 19 | **20 ms** | 50 | 65 | 18 | 0 |
| u-blox M8 | 6 | 17 | **180 ms** | 45 | 200 | 9 | 3 |
| | 7 | 9 | **20 ms** | 75 | 115 | 8 | 1 |
| u-blox, model not detected | 6 | 47 | **160 ms** | 5 | 170 | 24 | 11 |
| | 7 | 19 | **60 ms** | 55 | 135 | 15 | 0 |
| u-blox M10 (not a reference class) | 6 | 2 | 65 ms | −7.5 | 57.5 | 2 | 0 |
| | 7 | 1 | 200 ms | −15 | 185 | 1 | 0 |

In every reference class, the median τ at model 6 is 100 to 160 ms above model 7, and the median D is lower.

**The same statistic on subsets** (reported only; each has its own bootstrap seed):

| subset | model-6 logs | τ residual |
|---|---|---|
| all logs that reproduced their published lag (all of them) | 104 | +110 ms (55 to 145) |
| τ identified | 57 | +90 ms (30 to 120) |
| GPS logged every 150 ms or faster | 36 | +85 ms (20 to 150) |
| u-blox F9P only | 15 | +120 ms (40 to 215) |

**How much the low-pass helps.** Against the best pure-delay fit (τ = 0), adding the low-pass removed a median 9.1% of the remaining residual variance on model-6 logs, against 1.1% on model-7 logs. Model-6 GPS velocity looks smoothed; model-7 GPS velocity mostly looks just delayed.

## What it means

- **A delay setting alone can't cancel it.** A low-pass delays slow manoeuvres by about its time constant and fast ones by less, and it also shrinks fast ones. One `EKF2_GPS_DELAY` (or `SENS_GPSn_DELAY` from v1.18) can match only one manoeuvre rate. On public logs, model 6's extra lag has that shape. For a u-blox vehicle at model 6, changing to 7 (PX4's multicopter default since v1.17; needs a reboot) and measuring again is the better first step than raising the delay.
- **This explains a known gap; it doesn't find a new one.** These are dynmodel-2026's own graded logs, so the result says what the +46 ms gap is made of, not that it replicates.

## Limits

- **τ and D trade off, and the split depends on the model.** 45 of 106 model-6 fits and 16 of 60 model-7 fits have D below zero, which a real delivery delay can't be. u-blox doesn't publish its filter, and a first-order low-pass is only a stand-in: a filter with prediction can smooth as much with less low-frequency delay, which a first-order fit would show as a shorter or negative D. The parts that don't rest on that split are the variance figures above (the low-pass helps model 6 about 8 times more) and τ + D (+53.8 ms).
- **τ is censored at 250 ms.** 20 of 106 model-6 fits sit at the top of the grid (2 of 60 at model 7), so the model-6 τ, and the residual, may be larger than shown. Only 57 of the 104 scored model-6 logs meet the "identified" rule; on those the residual is +90 ms (30 to 120).
- **Observational.** Receiver class is the only control. Model 6 runs mostly on v1.16-or-older multicopters, so vehicle type and release go with it. dynmodel-2026's exploratory re-score kept the lag gap within multicopters and within matched receiver and release, but that re-score was not repeated for τ.
- **Logs only.** No ground truth for any one vehicle's GPS; the fit describes what reaches PX4's log, at its logging rate.
- **Retention.** Flight Review deletes uploads after 12 months, so the raw logs behind these rows start to disappear from October 2026. The rows stay here.

## What follows (as the plan says for H1)

- px4-log-health's model-6 note will say that across public logs too, model 6's extra lag behaved like filtering (checkup 0.3.6, after its sealed tests pass).
- MV2 offers PX4, once, a one-sentence addition to the `GPS_UBX_DYNMODEL` parameter description, in the discuss.px4.io thread where this work is discussed.

## Files

- `tau-fleet/tau-rows.jsonl`: one row per log (166).
- `tau-fleet/tau-summary.json`: the checks, the decision and the reported breakdowns.
- `tau-fleet/job-fetched.json`, `tau-fleet/boot-fetched.json`: what the sealed job checked before downloading any log.
- `tau-fleet/boot.py`: the boot step that fetched the pre-registered code from `f2eb66b7`.
- `tau-fleet/tau_fleet.py`, `tau-fleet/test_tau_fleet.py`, `tau-fleet/job_fetch.py`: the pre-registered code (`tau_fleet.py` 0.1.0).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text and data CC BY 4.0, code Apache-2.0. Log data derived from PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0).
