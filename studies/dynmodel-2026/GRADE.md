# dynmodel-2026: grade

Graded on 2026-11-04 against [`PLAN.md`](PLAN.md) (committed 2026-11-03 as `4dcf76b`, before any parameter was read). The sealed job `px4-gps-lag-dynmodel-v1` waited until the plan, `dynmodel.py` 0.1.0 and `test_dynmodel.py` were on `main` (270 s). It ran the 23 tests (all passed), then read the parameters from 15:24 to 15:51 UTC on 2026-11-03. The sha256 of every file it used is in [`job-fetched.json`](job-fetched.json). Rows: [`dynmodel-rows.jsonl`](dynmodel-rows.jsonl). Scores: [`dynmodel-summary.json`](dynmodel-summary.json).

**Result: every check held (E0, K1, K2, K3, K4), so rule D1 fires.** On public PX4 logs, u-blox logs with `GPS_UBX_DYNMODEL` = 6 were a median **46 ms later** than logs with 7 from the same receiver class. **But read the section "What we learned after the plan"**: PX4's own defaults give model 6 to multicopters up to v1.16, so this comparison is also partly multicopters against other vehicles and older against newer releases. An exploratory re-score among multicopters only, matched on receiver and release, kept the gap (+52 ms, interval 31 to 82). Before acting on D1 we pre-registered a within-vehicle check.

## What was read

| | logs |
|---|---|
| usable u-blox serial logs in receiver-2026, fresh-2026 and f9p-2026 | 261 |
| left out as seen (f9p-2026's `f9p-extra.jsonl`) | 17 |
| read: parameters found, data section reached | 244 |
| deleted from Flight Review, blocked, errors | 0 |
| read but no `GPS_UBX_DYNMODEL` | 0 |
| **graded** (one log per vehicle) | **244** |

Models in the graded set: 6 = 106, 7 = 60, 8 = 78. By sample: receiver-2026 26 / 14 / 18, fresh-2026 39 / 23 / 28, f9p-2026 41 / 23 / 32 (6 / 7 / 8).

## Checks

| | rule | result | |
|---|---|---|---|
| **E0** | ≥ 12 graded 6-logs and ≥ 60 graded 7-logs | 106 and **60** (exactly the threshold) | **held** |
| **K1** | all u-blox classes: median residual of 6-logs ≥ +30 ms, interval above 0 | **+45.6 ms** (33.2 to 55.0), 104 logs in 4 classes | **held** |
| **K2** | F9P: median(6) − median(7) ≥ +40 ms, interval above 0 (≥ 5 and ≥ 10 logs) | **+43.4 ms** (8.4 to 67.2); 180.7 vs 137.3 ms, 15 and 12 logs | **held** |
| **K3** | fresh-2026's two F9P groups: ≥ 80% have 6 in the high group and other models in the low group (≥ 10 logs, ≥ 3 at 6) | **14 of 16 (87.5%)** | **held** |
| **K4** | receivers other than the F9P: median residual of 6-logs ≥ +20 ms, interval above 0 (≥ 8 logs) | **+45.7 ms** (31.4 to 57.5), 89 logs | **held** |

The residual is a log's lag minus the median lag of the 7-logs with the same receiver class (classes with at least 5 7-logs: F9P, M9, M8 and "model not detected"; the u-blox M10 class had 1). The intervals are seeded percentile bootstraps (2,000 resamples). The plan named seed 20261112; `dynmodel.py` uses it for K1 and 20261113, 20261114 and 20261115 for K2, K4 and the reported 8-against-7 figure, as committed with the plan.

K3 in full (fresh-2026, F9P at 5 Hz on v1.16/v1.17, low ≤ 150 ms, high ≥ 175 ms):

| model | low group | high group |
|---|---|---|
| 6 | 0 | **7** |
| 7 | 4 | 2 |
| 8 | 3 | 0 |

All 7 model-6 logs are in the high group. Two model-7 logs are high too, so the model does not explain every high log.

We expected E0 to be uncertain, K1-K3 to hold and K4 to be uncertain. All five held.

## Reported, not predicted

Median lag by receiver and model (graded logs):

| receiver | model 6 | model 7 | model 8 |
|---|---|---|---|
| u-blox F9P | 15 logs, **180.7 ms** | 12, 137.3 ms | 6, 120.9 ms |
| u-blox M9 | 25, **108.7 ms** | 19, 62.0 ms | 34, 69.1 ms |
| u-blox M8 | 17, **186.1 ms** | 9, 114.1 ms | 7, 124.4 ms |
| u-blox, model not detected | 47, **144.4 ms** | 19, 116.2 ms | 31, 115.8 ms |
| u-blox M10 | 2, 51.9 ms | 1, 156.6 ms | none |

- **Model 8 against 7:** median residual +3.5 ms (−9.6 to 13.0), 78 logs. The <4g model is no less late than <2g, so the lag does not simply shrink as the model allows more acceleration. Model 6 is the odd one out.
- **Off the delay setting:** 41.5% of model-6 logs were more than 50 ms later than their own `EKF2_GPS_DELAY`, against 8.8% at 7 and 11.7% at 8. Median lag minus setting: +40.6 ms at 6, −15.0 at 7, −23.4 at 8.
- **The 17 seen f9p-2026 logs** (not graded): model 6, 6 logs, median 191.9 ms; 7, 10 logs, 108.3 ms; 8, 1 log, 131.9 ms.

## What we learned after the plan

The plan did not check where users' values of `GPS_UBX_DYNMODEL` come from. PX4 sets them per vehicle type:

- `ROMFS/px4fmu_common/init.d/rc.mc_defaults` has `param set-default GPS_UBX_DYNMODEL 6` up to v1.16 (checked at the v1.15.4 and v1.16.0 tags). PX4 PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831), "Use PX4 default <2g ublox GNSS dynamic model also for multirotors" (merged 2025-05-27), removed it. The line is gone at v1.17.0, so multicopters get 7 from v1.17 on. The PR's reason: during long high-acceleration flight, the <1g model "can upset the EKF", with repeated estimator resets on an 850 mm vehicle with an F9P. It gives no lag figure.
- `rc.fw_defaults` sets 8 for fixed wings. `rc.vtol_defaults` does not set it, so VTOLs get 7.

So a model-6 log is usually a multicopter on v1.16 or older, left at its default. Model-7 logs mix multicopters on v1.17 or newer, VTOLs and values set by hand. The plan's limits named this kind of problem ("whoever sets 6 may also differ in other ways"), but not this specific, built-in link. The +46 ms is real in the data. Whether the model causes it, or the vehicle type or release that comes with it, the plan cannot say.

## Exploratory: does the gap survive matching on vehicle type and release? (not pre-registered)

After seeing the results above, we re-scored the same 244 graded logs within matched strata (`dynconf.py` 0.1.0, standard library; job `px4-gps-lag-dynconf-v1`; [`dynconf/dynconf-summary.json`](dynconf/dynconf-summary.json)). The script rebuilt the graded set from `dynmodel.py` and the model values in [`dynconf/dynmap.txt`](dynconf/dynmap.txt), and it reproduced the published summary exactly (244 / 106 / 60, K1 +45.6, K2 +43.4) before it scored anything. The vehicle type and release come from each log's published row. Differences are weighted means of within-stratum median differences, with seeded bootstrap intervals (seed 20261114).

First, the link is as strong as the defaults suggest. All 106 model-6 logs are multicopters. Of the 239 logs whose default is known, 91% run their vehicle type's default. Fixed wings are 74 of the 78 model-8 logs.

| model 6 minus model 7, matched on | strata | logs (6 / 7) | difference |
|---|---|---|---|
| receiver | 5 | 106 / 60 | +40.7 ms (26.6 to 52.6) |
| receiver, multicopters only | 4 | 104 / 32 | **+45.1 ms (27.8 to 59.7)** |
| receiver and release, multicopters only | 7 | 35 / 27 | **+51.8 ms (30.5 to 81.7)** |
| model 6 set by hand (not the default) vs model 7 as default | 2 | 5 / 25 | +62.3 ms (16.8 to 87.1) |
| model 6 as default vs model 7 set by hand | 4 | 96 / 12 | +47.6 ms (28.4 to 64.3) |

The two candidate confounders, taken on their own:

- **Release, holding the model:** v1.16 minus v1.17, matched on receiver, vehicle type and model: −7.1 ms (−34.1 to 5.0), 45 / 36 logs.
- **Vehicle type, holding the model at 7:** multicopters minus fixed wings, VTOLs and others, matched on receiver: −4.4 ms (−23.5 to 13.8), 32 / 27 logs.
- **Least squares** (lag on receiver, vehicle type, release group, model 6 and model 8): model 6 **+48.2 ms** (bootstrap 28.6 to 68.2). 600 of 1,000 resamples were solvable, because some levels are rare (one ground rover).

So in these logs, the gap does not come from being a multicopter or from the release. It shows among multicopters, within a release and receiver, and among people who chose 6 by hand on a release where it wasn't the default. That makes the model itself a stronger candidate. It is still not proof: whoever keeps or changes a default may differ in other ways, and the matched strata are small (35 and 27 logs). The paired check below is the test.

Model 8 is less clear. Matched on receiver and vehicle type it was −19.1 ms (−28.9 to −11.8), but most of those strata have a single model-7 log. The least-squares figure was −19.4 ms (−57.7 to 15.0).

## What happens with D1

D1 says: (1) the README states the figure, (2) px4-log-health's checkup adds an information line for model-6 u-blox logs, and (3) MV2 opens one PX4 issue asking that the parameter's description mention the lag.

- (1) is done. The README states the figure together with the default link above.
- (2) and (3) are **held** until a within-vehicle check is graded. A user who switches from 6 to 7 should only expect less lag if the model causes it. And PX4 already changed the multicopter default in v1.17 for its own reasons, so an issue would only be useful with a causal figure. We pre-registered that check today ([`PLAN-paired.md`](PLAN-paired.md)). It uses the logs a PX4 maintainer attached to PR #24831: similar aggressive flights of one vehicle with model 6 and with model 7. The exploratory re-score above makes a real effect more likely, but it does not replace the paired check.

For PX4 users today, the practical point does not depend on the cause: **if your u-blox vehicle runs `GPS_UBX_DYNMODEL` 6 (any multicopter on v1.16 or older that kept the default), there is about a 4-in-10 chance its GPS lag is more than 50 ms past its delay setting.** Measure it (`gps_lag.py`, or px4-log-health's checkup) before you trust the 110 ms default.

## Limits

- Observational, as above. The pre-registered checks cannot separate the model from the vehicle type and release that come with it. The exploratory matching does, partly, after the fact and on small strata.
- E0 held at exactly 60 model-7 logs.
- One log per vehicle. Flight Review uploads are self-selected.
- The parameter is read at boot. PX4 applies it when it configures the receiver (`GPS_UBX_CFG_INTF` setups are not checked).
- The lag is measured against `vehicle_gps_position.timestamp`, so it includes PX4's own parsing and serial transfer.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
