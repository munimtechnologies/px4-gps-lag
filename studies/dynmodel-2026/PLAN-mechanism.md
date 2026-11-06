# dynmodel-2026, mechanism check: plan (pre-registered)

Written on 2026-11-06, before any of the figures below have been computed. The sealed job that computes them (`px4-gps-lag-mechanism-v1`) waits until this file, [`mechanism/mechanism.py`](mechanism/mechanism.py) 0.1.0 and [`mechanism/test_mechanism.py`](mechanism/test_mechanism.py) are on `main`, checks that its copies match `main`'s, and runs the tests before it opens a log.

## Why

On the two logs attached to PX4 PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831) (one vehicle, serial u-blox F9P, same delay and port settings), the GPS lagged the IMU by **214.2 ms at `GPS_UBX_DYNMODEL` 6 and 110.5 ms at 7** ([`GRADE-paired.md`](GRADE-paired.md)). The gap held in every third of both flights, at low and high acceleration, and under a block bootstrap (+103.7 ms, 86.6 to 108.3).

On the PX4 forum ([topic 49705](https://discuss.px4.io/t/49705)), Yiğitcan Öztürk asked whether that extra delay comes from the receiver's navigation filter or from measurement and delivery timing, and whether EKF2's GPS velocity test ratios and resets differ between the two flights. This plan answers what two logs can answer.

The question matters for tuning. A pure delivery delay is a constant time shift, and one `EKF2_GPS_DELAY` value can cancel it. Smoothing by the receiver's filter also damps quick velocity changes. No single delay setting fully cancels that: the right value would be larger for slow manoeuvres than for quick ones.

## What has been seen, and what has not

Seen: each flight's lag, thirds, block bootstrap, low/high-acceleration split and 1 g share (all in `GRADE-paired.md`). px4-log-health's checkup report on the same two logs ([`studies/dynmodel/report.md`](https://github.com/munimtechnologies/px4-log-health/blob/main/studies/dynmodel/report.md)) is public and includes EKF2's innovation-implied excess for both logs, so M2 below is a consistency check, not a blind prediction. We did not re-read it while writing this plan.

Not computed before this plan: any fit with a smoothing term, EKF2's test ratios, its reset counters and its rejection flags on these logs.

## Method

`mechanism.py` takes each log's GPS pairs exactly as `gps_lag.py` selects them (the copy at commit `967b5ad`, the one px4-log-health's checkup pins), with the IMU's north-east acceleration from `gps_lag.ne_accel` and its running integral.

- **Smoothing plus delay.** The IMU velocity goes through a first-order low-pass filter with time constant τ and is then delayed by D. For each grid point (τ from 0 to 250 ms in 10 ms steps; D from −200 to +600 ms in 5 ms steps), the change over each GPS interval is compared with the change in GPS velocity, with one constant acceleration bias per axis, as in `gps_lag.fit_lag`. The best (τ, D) is the one with the smallest squared error. τ = 0 is `gps_lag.py`'s delay-only model.
- **Intervals.** A moving-block bootstrap (blocks of 25 consecutive GPS pairs, 200 resamples, seed 20261107 for both logs) refits (τ, D) on each resample. The model-6 minus model-7 differences are taken draw by draw.
- **Identified.** A flight's τ counts as identified when its bootstrap 95% interval is at most 100 ms wide, the best τ is not at the top of the grid (250 ms), and at most 5% of the draws are.
- **EKF2.** `innov.measure_innov` (unchanged, same commit) for the GPS velocity innovation against acceleration. From `estimator_innovation_test_ratios`: the GPS horizontal velocity and position test ratios (larger of the two axes, fresh in-flight samples). From `estimator_status`: how often each reset counter stepped while flying. From `estimator_status_flags`: the in-flight share of `reject_hor_vel`, `reject_hor_pos` and `cs_gps`. Instance 0 only.

The synthetic tests check that a pure delay of 150 ms comes back as τ ≤ 10 ms with τ + D within 10 ms of 150, and that a 100 ms low-pass followed by a 50 ms delay comes back as τ within 20 ms of 100 and D within 15 ms of 50.

## Checks and rules

| | rule |
|---|---|
| **E1** (validity) | `gps_lag.fit_lag` reproduces both published lags to 0.05 ms, and the τ = 0 grid fit lands within 5 ms of them. If not, nothing below is graded. |
| **M1** (main) | With Δτ = τ(6) − τ(7) and ΔD = D(6) − D(7): **smoothing** if both flights' τ is identified, Δτ ≥ +50 ms and the bootstrap 2.5th percentile of Δτ is above 0; **delivery** if both are identified, \|Δτ\| ≤ 20 ms and ΔD ≥ +70 ms; **mixed** if both are identified and neither rule holds; **not identified** otherwise. |
| **M2** (consistency) | `measure_innov` passes on both logs, with implied excess above 0 at model 6 and below 0 at model 7. Both logs have `EKF2_GPS_DELAY` = 160 ms, between the two measured lags, so EKF2 should see the GPS as late at model 6 and early at model 7. |
| **D** (descriptive) | Test ratios, reset counts and rejection shares for both flights, side by side. No prediction: one flight per model cannot show whether model 6 causes resets. |

**Our odds for M1:** smoothing 50%, mixed 20%, not identified 20%, delivery 10%. We expect smoothing because u-blox describes the dynamic platform models as tuning its navigation engine to the expected dynamics. But a first-order filter is only a stand-in for that engine, and two flights with about a minute of usable GPS pairs each may not separate τ from D.

## What each outcome leads to

- **smoothing**: GRADE-mechanism.md says that most of model 6's extra lag behaves like filtering, so no single `EKF2_GPS_DELAY` fully compensates it. That supports PX4's v1.17 move to model 7 more than retuning the delay would. px4-log-health's dynamic-model note can say so in a later release.
- **delivery**: the extra lag behaves like a constant shift, so retuning the delay would compensate it. The note keeps its wording.
- **mixed / not identified**: reported as it is; no change to any tool.
- Whatever the outcome, every figure is published (`mechanism/mechanism-summary.json`) and the result is posted once in the forum thread.

## Limits

- One vehicle and one flight per model, so this is about these two flights, not a fleet.
- A first-order low-pass is a simplification. The receiver's real filter is unknown, so τ is a summary of how smoothing-like the lag is, not the filter's actual constant.
- The low-pass uses one step size (the median IMU interval).
- The lag is measured against PX4's receive timestamp, so serial transfer and parsing are in D. The two flights share port, baud rate and configuration.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
