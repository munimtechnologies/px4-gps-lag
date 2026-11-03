# dynmodel-2026: does the u-blox dynamic platform model change the GPS lag PX4 sees? (pre-registration)

Written and committed on 2026-11-03, before any of the parameters below are read. Code: `dynmodel.py` 0.1.0 (standard library only) and `test_dynmodel.py`, committed with this plan. The sealed job waits until all three are on `main` before it reads a single log.

## Why

[f9p-2026](../f9p-2026/GRADE.md) found the u-blox F9P's lags on PX4 v1.16/v1.17 split into two groups again: 8 logs at 82-144 ms and 4 at 185-239 ms, none in between (check P3 held; it was first seen in fresh-2026). Its exploratory pass then read each log's GPS parameters. **One setting separated the 12 logs exactly: all 4 high logs had `GPS_UBX_DYNMODEL` = 6 ("airborne with <1g acceleration"), and all 8 low logs had 7 (PX4's default, "airborne with <2g") or 8 ("<4g").** That is already-seen data from 12 logs, and the reason for this plan. Under f9p-2026's rule D2, a field that separates the groups cleanly in both samples becomes the next pre-registered question. fresh-2026's F9P logs, where the two groups were first seen, have never had their parameters read.

The mechanism is plausible. `GPS_UBX_DYNMODEL` sets the receiver's dynamic platform model (PX4 `src/drivers/gps/params.c`; u-blox `CFG-NAVSPG-DYNMODEL`), which tells the receiver's navigation filter how hard the vehicle can accelerate. A model that expects gentler motion could smooth velocity more, and smoothed velocity reaches PX4 later relative to the IMU. `gps_lag.py` measures the lag from the GPS velocity change against integrated IMU acceleration, so extra smoothing would show up as extra lag.

Prior art. u-blox's integration manuals give each model's limits (altitude, velocity, the sanity check), but no latency figures. Betaflight's GPS guide says the 1G/2G/4G airborne models set how much filtering the module applies, and in Betaflight PR [#3110](https://github.com/betaflight/betaflight/pull/3110) a contributor wrote that the dynamic model also changes the filtering, and with it the delay, of an M8N's output. Neither gives a measured figure, and the two sources don't agree on which model filters more. PX4's parameter description says nothing about lag. We found no measurement, on real flights, of how much lag a u-blox dynamic model adds.

## Logs

The published per-log rows of three earlier samples, read in this order: receiver-2026 ([`studies/receiver-2026/logs.jsonl`](../receiver-2026/logs.jsonl)), fresh-2026 ([`studies/receiver-2026/fresh/logs.jsonl`](../receiver-2026/fresh/logs.jsonl)) and f9p-2026 ([`studies/f9p-2026/logs.jsonl`](../f9p-2026/logs.jsonl)). Their lags were measured and published before this question existed, and nothing in them changes.

A **usable** log passed `gps_lag.py` (a lag was measured), is not simulated, has exactly one GPS receiver, and is a u-blox receiver PX4 identified (M8, M9, F9P, M10, or "model not detected") on a serial bus.

For each usable log, `dynmodel.py collect` reads **only the start of the log** from PX4 Flight Review: the ULog definitions section, where the initial parameters are. It stops at the first data-section message and closes the connection, keeping only the GPS parameters (`GPS_*`, `SER_GPS*`, `SENS_GPS*`, `EKF2_GPS_*`). Logs are read 6 s apart in a seeded random order (seed 20261111). The pass stops at the first block (403/429/444) or after five network errors in a row, with a 150-minute budget. Logs that Flight Review has already deleted (it keeps uploads for 12 months) are counted, not replaced.

**Left out as seen:** every f9p-2026 F9P log whose parameters are in f9p-2026's `f9p-extra.jsonl`. That includes the 12 above. They are listed separately and never scored.

**Graded set:** usable logs whose `GPS_UBX_DYNMODEL` was read, with one log per vehicle (the first in the sample order above, then row order).

## Checks

The 6-logs have `GPS_UBX_DYNMODEL` = 6, and the 7-logs have 7. A log's **residual** is its lag minus the median lag of the 7-logs with the same receiver class. Only classes with at least 5 7-logs count.

| | rule |
|---|---|
| **E0** | at least **12** graded 6-logs and at least **60** graded 7-logs |
| **K1** | over all u-blox classes, the median residual of 6-logs is **≥ +30 ms**, and its 95% interval lies above 0 |
| **K2** | F9P only: median lag of 6-logs minus median lag of 7-logs is **≥ +40 ms**, with its interval above 0. Scored only with at least 5 6-logs and 10 7-logs |
| **K3** | fresh-2026's qualifying F9P logs (f9p-2026's rule: v1.16/v1.17, 200 ms grid, not a moving base), in its low (≤ 150 ms) or high (≥ 175 ms) group, with a model read: at least **80%** have 6 in the high group and any other model in the low group. Scored only with at least 10 such logs, at least 3 of them 6-logs |
| **K4** | receivers other than the F9P: the median residual of 6-logs is **≥ +20 ms**, with its interval above 0. Scored only with at least 8 such 6-logs |

If E0 fails, K1-K4 are not scored. Intervals are seeded percentile bootstraps with 2,000 resamples (seed 20261112), resampling both groups within each class.

**What we expect.** We don't know how many PX4 users set 6: in the 12 seen F9P logs it was 4. E0 could fail. If it holds, we expect K1, K2 and K3 to hold, because the seen gap was about +90 ms on the F9P. K4 is uncertain: the M8 and M9 run different firmware, and their filters may react differently to the model.

## Decisions

- **D1.** If E0, K1 and K2 hold:
  - px4-gps-lag's README states the figure.
  - px4-log-health's checkup adds one information line for u-blox serial logs with `GPS_UBX_DYNMODEL` 6. The line gives the figure and suggests measuring the lag or trying 7. It ships only after a sealed test.
  - MV2 opens one PX4-Autopilot issue suggesting that the parameter's description mention the lag, if no issue or pull request already covers it.
- **D2.** If E0 holds and K1 fails, the README says the dynamic model does not explain the F9P's two groups, and they stay unexplained.
- K3 and K4 are reported either way. K3 says whether the model separates the groups in both samples (f9p-2026's D2).

## Reported, not predicted

Status counts, including deleted logs. The model values by receiver class and by sample. The median lag by receiver and model. Model 8 against 7, using the same residual. The share of logs more than 50 ms off their own delay setting, for models 6, 7 and 8. The seen f9p-2026 logs, by model.

## Limits

- This is observational. Whoever sets 6 may also differ in other ways, such as the vehicle, the integrator's parameter file or the flight style. The plan cannot tell the model's own effect from what comes with it.
- The parameter is read at boot. PX4 applies `GPS_UBX_DYNMODEL` when it configures the receiver, and a change needs a reboot. It does not apply when PX4 is not configuring the receiver (`GPS_UBX_CFG_INTF` and similar setups are not checked).
- The lag is measured against `vehicle_gps_position.timestamp`, so it includes PX4's own parsing and serial transfer.
- Flight Review uploads are self-selected, and logs older than 12 months may already be gone.

## Outputs

`dynmodel-rows.jsonl` has one line per usable log: sample, hashed vehicle, receiver, lag, release, status and the GPS parameters, with no position. It is published in this folder with `dynmodel-summary.json`, `job-fetched.json` and `GRADE.md`, whatever the outcome.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
