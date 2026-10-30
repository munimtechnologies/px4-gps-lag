# fleet-2026, part 3: graded

Graded 2026-10-30 against `PLAN-innov-confirm.md`, which was committed (967b5ad) before any innovation of these logs was read. By MV2 of Munim, Inc.; the plan, code, analysis and this text were made with AI agents. Text CC BY 4.0. Data: PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0). Run: job `px4-gps-lag-innov-confirm-v1` (sealed container; `innov.py` 0.2.0 and `test_innov.py` byte-identical to main, `gps_lag.py` 0.1.0 and `fleet.py` from main, see `confirm/fetched.json`; 38 tests passed; no 403/444; 13 minutes).

## Mechanical check: passed

Re-scoring part 2's `innov/innov.jsonl` with PX4's sign gave Spearman **+0.757**, **0.951** same sign (41 logs) and median ratio **+0.483**, exactly the figures `GRADE-innov.md` predicted. So 0.2.0 differs from 0.1.0 only in the sign.

## As pre-registered: C1

| Check | Rule | Result | Holds |
|---|---|---|---|
| VE1 | at least 60 logs validated | **89** of 98 | yes |
| V1 | Spearman(d, x) ≥ 0.3 | **+0.861** | yes |
| V2 | ≥ 70% of logs with \|d\| > 50 ms have x of the same sign (≥ 10 logs) | **92.6%** (25 of 27) | yes |
| V3 | median x / d in 0.2-1.2 (reported, decides nothing) | **0.622** | yes |
| V4 | median \|x\| smaller where \|d\| ≤ 20 ms than where \|d\| > 50 ms (≥ 10 each; reported) | 7.6 ms (30 logs) vs 53.9 ms (27 logs) | yes |

d is the lag measured by `gps_lag.py` in px4-log-health's fleet-health-2026 minus the log's own `EKF2_GPS_DELAY`; x is the implied excess from EKF2's GPS velocity innovations, in PX4's sign. Of 98 logs, 94 passed the innovation gates (3 had too few in-flight innovations, 1 too little manoeuvring) and 5 of those had no `EKF2_GPS_DELAY` in the log, leaving 89. Fusion time came from `timestamp_sample` in 79 and from `timestamp − EKF2_GPS_DELAY` in 10. Median x was 3.7 ms; median standard error 1.5 ms.

**The written decision is C1, and it is applied:** rule D1 returns to the README. Where `gps_lag.py` finds the lag more than 50 ms off `EKF2_GPS_DELAY`, the measured lag is offered as a starting value for that parameter, to be checked with EKF2 log replay before flying it.

## What it means

Two independent methods, on two independent sets of public logs, now agree. `gps_lag.py` measures the GPS delay from the IMU and GPS velocities alone. EKF2's own GPS velocity innovations, compared with acceleration, lean the same way in 25 of 27 logs that are more than 50 ms off their setting (and in 39 of 41 in part 2), and the two rank the logs alike (ρ +0.86 here, +0.76 there). The innovation shows about half to two thirds of the measured mismatch (median ratio 0.62 here, 0.48 there), as a filter that partly follows a late GPS should.

The sign correction was found after part 2's data were seen. It was then tested here on 98 vehicles whose innovations nobody had read, with thresholds fixed before part 2. It held with more margin than part 2's flipped figures.

## Limits

- An agreement in sign and rank is not a calibration. This study does not show that setting `EKF2_GPS_DELAY` to the measured lag improves a vehicle's estimate. That is what EKF2 replay is for, and why D1 says "starting value, check with replay".
- First-order model; the same attitude estimate feeds both methods, so they are not fully independent; innovations are logged at 500 ms and are the last fusion's.
- 10 validated logs had no `timestamp_sample`; their fusion time is assumed.
- Uploaded logs are not a random sample of flights. They are often uploaded because something went wrong.

## Files

- `confirm/summary.json`, `confirm/innov.jsonl`: this run's output, unchanged (PX4's sign).
- `confirm/v1-flipped-summary.json`: part 2's rows re-scored with PX4's sign.
- `confirm/fetched.json`: hashes showing which files the job ran.
