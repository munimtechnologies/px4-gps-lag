# fleet-2026: how far behind the IMU is GPS on real PX4 vehicles, and does EKF2_GPS_DELAY match?

Written 2026-10-30, before any log was downloaded. By MV2 of Munim, Inc.; the plan, code and analysis are made with AI agents. Text CC BY 4.0, code Apache-2.0. Data: PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0).

## Why

PX4's EKF2 fuses each GPS sample as if it had been measured `EKF2_GPS_DELAY` before its `vehicle_gps_position.timestamp`. The default is 110 ms (checked in the v1.14 and v1.15 sources). If the setting is wrong, velocity innovations grow while the vehicle accelerates. PX4's documented remedy is to replay one's own log with different delays. ArduPilot's developers have said that the right delay is hard for users to find. Nobody has published the delay as measured across many real vehicles. We searched for a fleet-wide measurement on Flight Review, papers on PX4/ArduPilot logs, and Roboto's analysis of 123,227 public 2024 logs (which counts uploads, hardware, failsafes and console messages, not timing). We found only single-vehicle forum reports and single-vehicle methods (for example arXiv 2008.10469, which cross-correlates differenced GPS velocity with IMU acceleration).

This is the same kind of question MV2's earth-rover-pilot answered for sidewalk robots on FrodoBots-2K ("GPS 1.5 s behind the wheels"), asked of a flying fleet.

## Method (`gps_lag.py` 0.1.0)

For each log: take consecutive logged `vehicle_gps_position` samples (3D fix or better, NED velocity valid) while `vehicle_land_detected` says the vehicle is not landed, 0.05-1.2 s apart (the default logger profile keeps one every 0.5 s). Compare each pair's change in north and east GPS velocity with `sensor_combined`'s specific force, rotated to north-east by `vehicle_attitude` and integrated over the same interval shifted back by a candidate lag L (-200 to +800 ms, 5 ms steps, then a parabola through the best three). Fit one constant acceleration bias per axis at each L. The lag is the L with the smallest squared error. A nominal standard error comes from the curvature there. Pairs whose IMU window has a gap over 0.1 s are dropped. No position is read.

A log **passes** only if it has at least 100 pairs, the GPS velocity changes have an RMS of at least 0.3 m/s² about their mean, the best lag is not at either end of the search, the fit explains at least 60% of the velocity changes (R² ≥ 0.6) and the standard error is at most 20 ms. A log whose GPS device is on the simulation bus does not count. The unit tests recover known delays of 62.5, 110, 150 and 420 ms within 3 ms on synthetic flights, including with an accelerometer bias, quaternion sign flips, an IMU gap and 10 Hz GPS logging.

## Sample (`fleet.py` 0.1.0)

- The public log list from `review.px4.io/dbinfo`, read once. Eligible logs are dated 2025-10-01 or later, at least 240 s long, not SITL and not simulated.
- Vehicles (by Flight Review's `vehicle_uuid`; a log without one is its own vehicle) are put in a random order with seed 20261030. One log per vehicle is attempted. When a vehicle's first log passes, a second of its logs is attempted, for up to 60 vehicles (for P5).
- Downloads are one at a time, 6 s apart (the default of Flight Review's own `download_logs.py`). Logs over 80 MB are skipped. The run stops if the server answers 403/444, and otherwise after 120 minutes or 400 logs. Each log is deleted once measured. Vehicle ids are published only as a 12-character hash.

## Checks (computed in `summary.json` → `checks`)

- **E1 (enough data):** at least 80 logs pass, from at least 50 vehicles. If E1 fails, no prediction decides anything; the numbers are reported as a pilot.
- **P1** The median measured lag of passing logs is between 40 and 160 ms.
- **P2** At least 20% of passing logs differ from their own `EKF2_GPS_DELAY` by more than 50 ms.
- **P3** At least 70% of passing logs run the default `EKF2_GPS_DELAY` of 110 ms.
- **P4** DroneCAN GPS logs have a higher median lag than serial GPS logs (decided only if each group has at least 15 passing logs).
- **P5** Repeatability: for vehicles with two passing logs, the median absolute difference between their two lags is at most 25 ms (decided only with at least 15 such vehicles).
- **P6** The median standard error of passing logs is at most 10 ms.

## What it decides

- **D1:** if E1 holds and P5 holds, `gps_lag.py`'s README offers the measured lag as a starting value for `EKF2_GPS_DELAY`, to be checked with EKF2 replay. Otherwise it is documented as a diagnostic only, with no suggested setting.
- Whatever happens, the fleet distribution, the share of logs far from their setting, and the reasons logs failed the gates are published in `studies/fleet-2026/GRADE.md` with `summary.json` and `logs.jsonl`.

## Limits

- **Timing as logged.** The lag is measured against the timestamps the flight controller logged. That is exactly what EKF2 subtracts its delay from, but it mixes receiver latency, transport (serial or CAN) and driver time, and it cannot separate them.
- **The receiver's own velocity filter** adds lag that depends on its dynamic model. This measures the total, which is what the setting should match.
- **Attitude comes from EKF2**, which itself fuses GPS. Small attitude errors become small acceleration errors. The bias term absorbs constant ones, not changing ones.
- **The public logs are not a random sample of PX4 vehicles.** People upload logs for many reasons, often after a problem. The gates keep only flights with enough manoeuvring, so hovering-only and short flights are under-represented.
- **One code path.** `vehicle_gps_position` is the blended output when a vehicle has two receivers. `device_id` gives the bus of the receiver it reports.

## Reproduce

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet
python fleet.py --out-dir out --budget-min 120 --max-logs 400
```

The draw depends on the public log list on the day it is read; `summary.json` records how many logs were listed and eligible, and `logs.jsonl` lists every log attempted by its public Flight Review id.
