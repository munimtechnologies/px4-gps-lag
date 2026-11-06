# dynmodel-2026, mechanism check: grade

Graded on 2026-11-06 against [`PLAN-mechanism.md`](PLAN-mechanism.md), which was committed before any figure below was computed. The sealed job `px4-gps-lag-mechanism-v1` (2026-11-06, 16:17-16:24 UTC) found the plan on `main` (sha256 `0a8071fc…`). It checked that its `mechanism.py` 0.1.0 (`2c545775…`) and `test_mechanism.py` (`52b93517…`) were `main`'s copies, that `gps_lag.py` was the copy pinned at commit `967b5ad` (`3338d743…`), and that the log archive attached to PX4 PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831) (`logs_dynmodel.zip`, `aa6997a9…`, 7,978,097 bytes) was the one the paired check used. It ran the 14 unit tests (all passed), and only then opened a log. Hashes are in [`mechanism/job-fetched.json`](mechanism/job-fetched.json); every figure is in [`mechanism/mechanism-summary.json`](mechanism/mechanism-summary.json).

## Result: E1 held, M1 = **smoothing**, M2 held

Most of model 6's extra lag on this vehicle behaves like heavier filtering of the velocity, not like a later delivery of the same velocity. The plan gave smoothing 50%.

## E1 (validity): held

| | model 6 (`log_8_2025-5-27-12-55-02.ulg`) | model 7 (`log_5_2025-5-27-11-50-34.ulg`) |
|---|---|---|
| published lag ([`GRADE-paired.md`](GRADE-paired.md)) | 214.2 ms | 110.5 ms |
| `gps_lag.fit_lag` now | 214.2 ms | 110.5 ms |
| grid fit with τ = 0 | 215 ms | 110 ms |

Both lags were reproduced, and the delay-only grid fit is within 5 ms of each (0.8 and 0.5 ms).

## M1 (main): smoothing

Each flight's GPS velocity change was fitted as the IMU velocity passed through a first-order low-pass (time constant τ) and then delayed by D.

| | model 6 | model 7 | 6 − 7 |
|---|---|---|---|
| GPS pairs | 254 | 275 | |
| best τ (bootstrap 95% interval) | **110 ms** (90 to 140) | **20 ms** (0 to 60) | **+90 ms** (59.8 to 130.0) |
| best D (interval) | 110 ms (80 to 125) | 95 ms (50 to 110) | +15 ms (−20.0 to +50.1) |
| τ + D (interval) | 220 ms (205 to 225) | 115 ms (110 to 115) | +105 ms |
| R² at best (τ, D) | 0.99479 | 0.99243 | |
| R² with τ = 0 | 0.99284 | 0.99240 | |
| τ at the top of the grid (250 ms) | no; 0% of draws | no; 0% of draws | |

- **Both τ are identified** by the plan's rule: intervals 50 and 60 ms wide (at most 100 allowed), neither best τ at the grid's top, no draw at the top.
- **Δτ = +90 ms ≥ +50, and its bootstrap 2.5th percentile (+59.8 ms) is above 0**, so the outcome is smoothing. The delivery rule (|Δτ| ≤ 20 and ΔD ≥ +70) is far from holding: the delay after the filter differs by only +15 ms, with an interval that includes 0.
- τ + D is the low-frequency delay of the fitted model. It matches the delay-only lag (220 against 215, 115 against 110), as it should.

How strong is the evidence? At model 6, adding the low-pass cut the unexplained variance from 0.716% to 0.521%, a 27% reduction. At model 7 it cut it from 0.760% to 0.757%: the model-7 profile is almost flat from τ = 0 to 30 ms, so that flight is close to a pure delay. τ and D trade off against each other along a ridge (the interval of τ + D is much narrower than those of τ and D alone). So the separation rests on the model-6 flight preferring a smoothed fit, and the bootstrap says that preference is stable.

What the fitted filters imply (illustration, computed from the fitted τ, not measured): a first-order low-pass with τ = 110 ms delays a 0.2 Hz manoeuvre by about 109 ms, a 1 Hz one by about 96 ms and a 2 Hz one by about 75 ms, and passes 82% of a 1 Hz velocity swing and 59% of a 2 Hz one. With τ = 20 ms the delay is about 20 ms at all of these, and at least 97% passes. EKF2 models GPS lag as one fixed delay (`EKF2_GPS_DELAY`), so on the model-6 flight the right setting would depend on how quickly the vehicle manoeuvres, and quick velocity changes reach EKF2 damped as well as late.

## M2 (consistency): held

| | model 6 | model 7 |
|---|---|---|
| `EKF2_GPS_DELAY` in the log | 160 ms | 160 ms |
| measured lag − setting | +54.2 ms | −49.5 ms |
| EKF2 innovation-implied excess (`innov.measure_innov`) | **+29.2 ms** (± 2.6) | **−37.8 ms** (± 2.2) |
| innovation samples, correlation r | 104, +0.61 | 111, −0.75 |

`measure_innov` passed on both logs, with the GPS seen as late at model 6 and early at model 7, as the plan required. The innovation-implied figures are smaller than the measured mismatches, and they were already public in px4-log-health's [report on these logs](https://github.com/munimtechnologies/px4-log-health/blob/main/studies/dynmodel/report.md), so this is a consistency check, not a prediction.

## D (descriptive): no resets or rejections in flight on either flight

| EKF2, instance 0, in flight | model 6 | model 7 |
|---|---|---|
| GPS horizontal velocity test ratio: median, 95th percentile, share > 1 | 0.028, 0.277, 0% (104) | 0.038, 0.345, 0% (112) |
| GPS horizontal position test ratio: median, 95th percentile, share > 1 | 0.0063, 0.089, 0% (104) | 0.0003, 0.0023, 0% (112) |
| resets in flight (vel NE, pos NE, vel D, quaternion) | 0, 0, 0, 0 | 0, 0, 0, 0 |
| resets over the whole log | 2, 3, 1, 1 | 2, 3, 1, 2 |
| share of status samples with `reject_hor_vel` / `reject_hor_pos` | 0% / 0% (60) | 0% / 0% (74) |
| share with `cs_gps` (GPS fused) | 100% | 100% |

Neither flight shows the EKF upset that PR #24831 describes for model 6 in aggressive flight: no in-flight reset, no rejection, every test ratio far below 1. The position test ratio was about 20 times higher at model 6 (median), but this is one flight per model, so it says nothing about cause. The plan made no prediction here.

## What this means (the plan's rule for smoothing)

- On this vehicle, **most of model 6's extra ~100 ms behaves like filtering**. A filter's delay depends on how fast the vehicle manoeuvres, so no single `EKF2_GPS_DELAY` value fully compensates it. That supports PX4's v1.17 move of multicopters to model 7 more than it supports retuning the delay.
- px4-log-health's model-6 note already suggests trying model 7 and measuring again. Its next release will add one sentence: on the one vehicle flown at both models, the extra lag behaved like heavier smoothing, which a delay setting alone can't fully cancel.
- About 100 ms of delay after the filter is there at both models (D = 110 and 95 ms). It includes serial transfer and parsing, because the lag is measured against PX4's receive timestamp.

## Limits

- One vehicle, one flight per model, on one day. This is about these two flights, not a fleet.
- A first-order low-pass is a stand-in for u-blox's navigation engine, whose real filter is not published. τ summarises how smoothing-like the lag is; it is not the engine's constant.
- The separation of τ and D rests on a 27% smaller residual on the model-6 flight. Other shapes (for example a filter whose time constant varies with the manoeuvre) could fit as well.
- The low-pass uses one step size (the median IMU interval).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
