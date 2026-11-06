# dynmodel-2026, fleet mechanism check: plan (pre-registered)

Written on 2026-11-06, before any log for this check has been downloaded. The sealed job that runs it (`px4-gps-lag-tau-fleet-v1`) waits until this file, [`tau-fleet/tau_fleet.py`](tau-fleet/tau_fleet.py) 0.1.0 and [`tau-fleet/test_tau_fleet.py`](tau-fleet/test_tau_fleet.py) are on `main`. It checks that its copies match `main`'s and runs the tests before it downloads a log. It will not run at the same time as census-2026's job, so that only one job reads Flight Review at a time.

## Why

On the one vehicle flown at both models (the two logs on PX4 PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831)), most of model 6's extra lag behaved like heavier smoothing, not later delivery ([`GRADE-mechanism.md`](GRADE-mechanism.md)). Fitted as a first-order low-pass (τ) followed by a delay (D), τ was 110 ms at model 6 and 20 ms at model 7, while D differed by only 15 ms. That matters for tuning: a filter's delay depends on how fast the vehicle manoeuvres, so no single `EKF2_GPS_DELAY` fully cancels it.

That is one vehicle. Across 244 public vehicles, model-6 logs lagged a median 46 ms more than model-7 logs of the same receiver class ([`GRADE.md`](GRADE.md), K1). This plan asks whether that fleet gap also sits in τ.

## Units

dynmodel-2026's graded logs (one per vehicle, chosen by `dynmodel.graded()` from the published [`dynmodel-rows.jsonl`](dynmodel-rows.jsonl)) at `GPS_UBX_DYNMODEL` 6 or 7: 106 and 60 logs (`dynmodel-summary.json`, `graded_dyn6` and `graded_dyn7`). Their lags were published before either mechanism question existed. Model 8 is left out.

What has been seen: each unit's delay-only lag, receiver class and model (all published). Not seen: any unit's τ or D.

## Method

- **Order.** Units sorted by log id and shuffled with seed 20261119. Each is downloaded from Flight Review once, one at a time and 6 s apart, at most 80 MB, and deleted after it is measured. The run stops after 200 minutes or on a block (HTTP 403, 429 or 444). Units not reached are recorded as such.
- **Counted.** A unit counts if it downloads, `gps_lag.py` (the pinned copy at commit `967b5ad`, the one mechanism-v1 ran) reads it and passes it, and it has at least 100 GPS pairs.
- **Fit.** The same (τ, D) grid fit as `mechanism.py` 0.1.0 on the same GPS pairs: τ 0 to 250 ms in 10 ms steps, D −200 to +600 ms in 5 ms steps, one acceleration bias per axis. `tau_fleet.fit_lite` computes it one τ at a time to save memory. A test checks that it gives the same answer as `mechanism.fit_grid` on a synthetic vehicle. Each log also gets mechanism-v1's moving-block bootstrap (blocks of 25 pairs, 200 resamples, seed 20261107), which is reported but not scored.
- **Fleet statistic.** This is dynmodel-2026's K1 statistic applied to τ: for each model-6 log, its τ minus the median τ of the same receiver class's model-7 logs, pooled over classes with at least 5 counted model-7 logs. The median of these residuals has a seeded percentile bootstrap 95% interval (2,000 resamples, seed 20261120, both groups resampled within each class). The same statistic is computed for D, and for τ + D.

## Checks and rules

| | rule |
|---|---|
| **E0** (enough data) | At least 30 counted model-6 logs and 25 counted model-7 logs in reference classes. If not, H0: nothing is graded. |
| **T1** (main) | The pooled τ residual of model-6 logs is at least **+20 ms**, and its interval's lower end is above 0. |
| **T2** | The pooled τ residual is larger than the pooled D residual. That means more of the fleet gap sits in the filter than in the delay after it. |

- **H1** (E0, T1, T2): the fleet gap behaves like smoothing too.
- **H2** (E0, T1, not T2): model 6 has more smoothing across the fleet, but its delay after the filter also grows at least as much. Mixed.
- **H3** (E0, not T1): the fleet does not show the smoothing seen on the one vehicle. GRADE-mechanism.md stays a single-vehicle case.
- **H0**: E0 failed.

**Our odds:** T1 50%, T2 60% given T1, so H1 about 30%, H2 about 20%, H3 about 45%, H0 about 5%. Per-log τ will be noisier than on the PR logs, which were flown to test the setting: many fleet flights have little manoeuvring, and some older logs record GPS only every 500 ms. The fleet's whole lag gap (+46 ms) is less than half the PR vehicle's (+104 ms). Both of these make a τ gap of 20 ms or more harder to see.

## What each outcome leads to

- **H1**: px4-log-health's model-6 note says that across public logs too, model 6's extra lag behaves like filtering, which a delay setting alone can't cancel. MV2 offers PX4 a one-sentence addition to the `GPS_UBX_DYNMODEL` parameter description, once, on the PX4 forum thread where this work is discussed.
- **H2 / H3**: reported as they are. The note says the smoothing was seen on one vehicle only (H3), or that both parts grow (H2).
- **H0**: reported, with how many units were lost and why.
- Whatever the outcome, every row (`tau-rows.jsonl`), the summary and the job's file hashes are published in `tau-fleet/`.

## Reported, not scored

The fit by receiver class and model (median τ, D and τ + D, how many fits are identified by mechanism-v1's rule, how many have τ at the top of the grid). How much the low-pass cuts the unexplained variance, median by model. The τ residual restricted to logs whose new lag is within 2 ms of the published one, to logs whose GPS is logged at least every 150 ms, to identified fits, and to the F9P alone. Why each uncounted unit didn't count.

## Limits

- Observational. Model 6 was PX4's multicopter default up to v1.16, so the vehicles at 6 and 7 also differ in release and often in airframe. Within-class matching on receiver is the only control.
- A first-order low-pass is a stand-in for u-blox's unpublished navigation filter. τ summarises how smoothing-like the lag is.
- Flight Review removes uploads after 12 months. Some units from late 2025 may be gone, and the rows say which.
- The download limit of 80 MB leaves out the longest or most heavily logged flights.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
