# dynmodel-2026, paired check: grade

Graded on 2026-11-05 against [`PLAN-paired.md`](PLAN-paired.md), which was committed on 2026-11-04 as `4845191` before the logs were downloaded. The sealed job `px4-gps-lag-paired-v1` waited until the plan, `paired.py` 0.1.0 and `test_paired.py` were on `main` (540 s). It ran the tests (all passed) and then downloaded `logs_dynmodel.zip` from PX4 PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831) once (7,978,097 bytes, sha256 `aa6997a9…3b49`). It measured both logs with `main`'s `gps_lag.py`, unchanged. The sha256 of every file is in [`paired/job-fetched.json`](paired/job-fetched.json). Rows: [`paired/paired-rows.jsonl`](paired/paired-rows.jsonl). Scores: [`paired/paired-summary.json`](paired/paired-summary.json).

**Result: E0 and P1 held, so rule D1 applies.** The zip holds two logs from one vehicle, a Pixhawk FMU-v5X with a serial u-blox F9P. Its parameters differ in `GPS_UBX_DYNMODEL` and not in the delay or port settings. **The model-6 flight's GPS lagged 214.2 ms and the model-7 flight's 110.5 ms, a difference of +103.7 ms.** The plan's threshold was +30 ms. P2 was not scored, because the vehicle has one log of each model. This is one vehicle and one pair of flights, so it is a case, not a fleet figure. It agrees in direction with the pre-registered fleet result ([`GRADE.md`](GRADE.md): +46 ms, interval 33 to 55) and is about twice its size.

## The two logs

| | model 6 (airborne <1g) | model 7 (airborne <2g) |
|---|---|---|
| file in the zip | `log_8_2025-5-27-12-55-02.ulg` | `log_5_2025-5-27-11-50-34.ulg` |
| vehicle (sys_uuid hash) | `69b9cdfa06af` | `69b9cdfa06af` |
| hardware, build | PX4_FMU_V5X, v1.15.0 development build | same |
| GPS | serial u-blox F9P (device type 0xAA), 5 Hz logged | same |
| `EKF2_GPS_DELAY` | 160 ms | 160 ms |
| `GPS_UBX_MODE`, `GPS_1_CONFIG` | 0, 201 | 0, 201 |
| GPS pairs in flight | 254 | 275 |
| manoeuvring (RMS GPS acceleration) | 2.45 m/s² | 2.77 m/s² |
| fit R² | 0.993 | 0.992 |
| **GPS lag** | **214.2 ms** (± 2.1) | **110.5 ms** (± 1.0) |
| lag minus `EKF2_GPS_DELAY` | **+54.2 ms** | −49.5 ms |

## Checks

| | rule | result | |
|---|---|---|---|
| **E0** | at least one vehicle with a passing model-6 and a passing model-7 log | 1 vehicle (both logs passed) | **held** |
| **P1** | median within-vehicle (model 6 − model 7) ≥ +30 ms | **+103.7 ms** | **held** |
| **P2** | full separation where a vehicle has ≥ 2 logs of each model | not scored (1 and 1) | — |

We had given D1 and D2 about even odds.

## Exploratory: is the gap stable within each flight? (not pre-registered)

`gps_lag.py`'s standard error (± 2.1 and ± 1.0 ms) treats every GPS pair as independent, so it understates how much one flight's figure could move. A within-flight check is written and queued as a separate sealed job. It does not change the grade above. [`paired/segments/paired_segments.py`](paired/segments/paired_segments.py) 0.1.0 re-fits each log's lag with `gps_lag.py`'s own functions:

- on each third of the flight's GPS pairs;
- with a moving-block bootstrap (blocks of 25 consecutive pairs, 400 resamples, seed 20261105);
- on low- and high-acceleration pairs, split at one shared threshold so that both flights are compared over the same range;
- with the share of each flight's GPS intervals in which the IMU's horizontal acceleration exceeded 1 g, the limit model 6 is named for.

It must reproduce both published lags to 0.05 ms before it reports anything. Its results will be added here as they come, whatever they show.

## What D1 means, and what it does not

- **px4-gps-lag's README** now gives both results: the fleet figure (observational, pre-registered) and this within-vehicle case (pre-registered, one vehicle).
- **px4-log-health's checkup** (0.3.4, released once its sealed test run passes) adds one information line to the report of any log whose serial u-blox receiver runs `GPS_UBX_DYNMODEL` 6. It states both results and their limits and suggests trying 7, which PX4 has used for multicopters since v1.17, and then measuring again. It is a note, not a flag.
- It does **not** show that model 6 adds about 100 ms on every vehicle. The fleet figure is about half that. One pair of flights can differ in more than the model: wind, the manoeuvres, satellite geometry. The exploratory check above addresses only how stable each flight's own figure is.
- **Why this matters for EKF2.** EKF2 fuses each GPS sample as if it were measured `EKF2_GPS_DELAY` before it arrived. On this vehicle the delay was set to 160 ms, and the measured lag was 54 ms more than that at model 6 and 50 ms less at model 7. A setting tuned on one model is off by about 50 ms on the other. PR #24831 describes EKF2 being upset and resetting at model 6 in aggressive flight; the PR did not report a lag figure, and we did not check whether the lag explains those resets.

## Prior work

We searched on 2026-11-05 and found no published millisecond figure for the GPS lag of u-blox's dynamic models. In Betaflight PR [#3110](https://github.com/betaflight/betaflight/pull/3110) (2017), contributors said the dynamic model "changes the level of filtering (delay)" of the output, without a figure, and Betaflight now switches to airborne <4g after arming. ArduPilot's `GPS_NAVFILTER` defaults to airborne <4g. PX4 set <1g for multicopters until v1.17.

## Limits

- One vehicle, one pilot, one flight per model, flown on 2025-05-27 to test EKF2 resets, not lag.
- A development build (v1.15.0, PX4 main in May 2025), not a release.
- The lag is measured against `vehicle_gps_position.timestamp`, so it includes PX4's parsing and serial transfer. These are identical between the two logs.
- The logs are not republished here; they stay attached to PR #24831. Only per-log figures are published, with no positions.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
