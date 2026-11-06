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

## Exploratory: the gap is stable within each flight (not pre-registered)

`gps_lag.py`'s standard error (± 2.1 and ± 1.0 ms) treats every GPS pair as independent, so it understates how much one flight's figure could move. A separate sealed job (`px4-gps-lag-paired-seg-v2`, [`paired/segments/paired_segments.py`](paired/segments/paired_segments.py) 0.1.1) re-fitted each log's lag with `gps_lag.py`'s own functions. Before reporting anything, the code requires both published lags to be reproduced to within 0.05 ms, and they were (110.5 and 214.2 ms). The results are in [`paired/segments/segments-summary.json`](paired/segments/segments-summary.json), and the file hashes in [`paired/segments/job-fetched.json`](paired/segments/job-fetched.json). The grade above is unchanged.

| | model 6 (214.2 ms) | model 7 (110.5 ms) | difference |
|---|---|---|---|
| first, middle, last third of the flight's GPS pairs | 195.6, 217.7, 216.1 | 108.9, 111.5, 123.2 | every model-6 third is later than every model-7 third |
| moving-block bootstrap, 95% (blocks of 25 pairs, 400 resamples) | 196.9 to 218.6 | 108.5 to 113.8 | **+103.7 (86.6 to 108.3)** |
| low-acceleration pairs (below 2.69 m/s², one threshold for both) | 213.4 | 110.5 | +102.9 |
| high-acceleration pairs | 218.7 | 110.5 | +108.2 |
| GPS intervals in which the IMU's horizontal acceleration exceeded 1 g | 0.39% | 1.45% | |

What this adds:

- **The gap is there in every third of both flights and at both acceleration levels.** It does not come from one part of a flight.
- **It is not caused by the model-6 flight exceeding 1 g.** The model-6 flight passed 1 g in only 0.39% of its GPS intervals, and its lag was the same at low acceleration (213.4 ms) as overall. The model-7 flight was slightly more aggressive (1.45%).
- The block bootstrap is the more honest interval for one flight. Even its lower end (+86.6 ms) is well above the plan's +30 ms threshold.

It is still one vehicle and one pair of flights. The within-flight check addresses only how stable each flight's own figure is, not whether another vehicle would show the same gap.

## What D1 means, and what it does not

- **px4-gps-lag's README** gives both results: the fleet figure (observational, pre-registered) and this within-vehicle case (pre-registered, one vehicle).
- **px4-log-health's checkup** ([v0.3.4](https://github.com/munimtechnologies/px4-log-health/releases/tag/v0.3.4)) adds one information line to the report of any log whose serial u-blox receiver runs `GPS_UBX_DYNMODEL` 6. It states both results and their limits and suggests trying 7, which PX4 has used for multicopters since v1.17, and then measuring again. It is a note, not a flag.
- It does **not** show that model 6 adds about 100 ms on every vehicle. The fleet figure is about half that. One pair of flights can differ in more than the model: wind, the manoeuvres, satellite geometry.
- **Why this matters for EKF2.** EKF2 fuses each GPS sample as if it were measured `EKF2_GPS_DELAY` before it arrived. On this vehicle the delay was set to 160 ms, and the measured lag was 54 ms more than that at model 6 and 50 ms less at model 7. A setting tuned on one model is off by about 50 ms on the other. PR #24831 describes EKF2 being upset and resetting at model 6 in aggressive flight; the PR did not report a lag figure, and we did not check whether the lag explains those resets.
- **Many vehicles, before and after the v1.17 upgrade:** [`../upgrade-2026/GRADE.md`](../upgrade-2026/GRADE.md). Its first run found too few pairs to score (10 of 12; D3, no claim), and an extension is pre-registered.

## Prior work

We searched on 2026-11-05 and found no published millisecond figure for the GPS lag of u-blox's dynamic models. In Betaflight PR [#3110](https://github.com/betaflight/betaflight/pull/3110) (2017), contributors said the dynamic model "changes the level of filtering (delay)" of the output, without a figure, and Betaflight now switches to airborne <4g after arming. ArduPilot's `GPS_NAVFILTER` defaults to airborne <4g. PX4 set <1g for multicopters until v1.17.

## Limits

- One vehicle, one pilot, one flight per model, flown on 2025-05-27 to test EKF2 resets, not lag.
- A development build (v1.15.0, PX4 main in May 2025), not a release.
- The lag is measured against `vehicle_gps_position.timestamp`, so it includes PX4's parsing and serial transfer. These are identical between the two logs.
- The 1 g share uses horizontal acceleration only.
- The logs are not republished here; they stay attached to PR #24831. Only per-log figures are published, with no positions.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
