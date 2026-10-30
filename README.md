# px4-gps-lag

How far behind the IMU is your PX4 vehicle's GPS? `gps_lag.py` measures it from a flight log (`.ulg`), against the same timestamp PX4's EKF2 subtracts `EKF2_GPS_DELAY` (default 110 ms) from.

By MV2 of Munim, Inc. The code and studies are made with AI agents. Apache-2.0.

## Use

```
pip install numpy pyulog
python gps_lag.py flight.ulg
```

It prints one JSON line per log, with `lag_ms`, its nominal standard error `se_ms`, the log's own `param_gps_delay_ms`, `lag_minus_param_ms`, the GPS bus (`serial`, `uavcan`, ...), and `passed` / `reason`. A log passes only if the flight has enough manoeuvring for the lag to be measurable (see the gates in `gps_lag.py`). Hover-only flights usually don't pass.

How it works: for each pair of consecutive logged GPS samples in flight, the change in GPS north and east velocity is compared with the IMU's acceleration (`sensor_combined`, rotated by `vehicle_attitude`) integrated over the same interval shifted back by a candidate lag. The lag that fits best, allowing a constant accelerometer bias, is the measurement. No position is read.

For a readable report per flight (health flags, fleet comparison and this GPS delay verdict), and a GitHub Action, see [px4-log-health](https://github.com/munimtechnologies/px4-log-health)'s `checkup.py`.

## What the fleet says

On 164 public Flight Review logs from 115 vehicles (`studies/fleet-2026/GRADE.md`, pre-registered), the median lag was 99.8 ms, close to the default 110 ms. But 29.6% of logs were more than 50 ms away from their own setting, and two logs of the same vehicle agreed to a median 5.3 ms. 98% of them ran the default.

**Replicated.** On an independent sample, 98 logs from 98 other vehicles, the median was 113.8 ms and 31.2% were more than 50 ms off their setting. Both figures were inside the ranges set before that run (px4-log-health, [`studies/fleet-health-2026/GRADE.md`](https://github.com/munimtechnologies/px4-log-health/blob/main/studies/fleet-health-2026/GRADE.md), R1 and R2).

**EKF2's own residuals agree.** On those 98 fresh logs, EKF2's GPS velocity innovations, compared with acceleration, lean the way the measured mismatch says they should in 25 of 27 logs that are more than 50 ms off their setting, and the two methods rank the logs alike (Spearman +0.86). The check was pre-registered and decided C1 ([`studies/fleet-2026/GRADE-innov-confirm.md`](studies/fleet-2026/GRADE-innov-confirm.md)). The innovation shows about 0.6 of the measured mismatch, as a filter that partly follows a late GPS should.

## Does the receiver model matter? (pre-registered, running)

PX4 uses one `EKF2_GPS_DELAY` for every receiver. ArduPilot assigns a lag by u-blox generation: 120 ms for M8 "based on flight logs", and the same 120 ms for F9, M9 and M10, with the comment "F9 lag not verified yet from flight log" (`AP_GPS_UBLOX.cpp`, `get_lag`). PX4's GPS driver records the receiver model it detected in the device_id of every GPS message. `receiver.py` reads that model and measures the lag on a fresh random sample of public logs, leaving out every vehicle the earlier studies saw. It then compares M8, M9, F9P, M10/generic u-blox and DroneCAN receivers. The six predictions and the decision rules are in [`studies/receiver-2026/PLAN.md`](studies/receiver-2026/PLAN.md), committed before any log was downloaded. The grade will be published whatever it says.

The first run, on 2026-10-30, was stopped from outside the job (the container got a stop signal, exit 143) after 88 of its logs, before it wrote a summary. Those partial rows were not scored. The same code, at the commit that published the plan, runs again from the start with the same seed, on Flight Review's list as it stands then (logs added or removed since the first run can change the draw).

## Suggested setting (rule D1)

If a passing log's `lag_minus_param_ms` is more than about 50 ms either way, the measured `lag_ms` is a reasonable **starting value** for `EKF2_GPS_DELAY`.

- Measure two or three flights first. Flights of one vehicle should agree within a few ms.
- Check the change with EKF2 log replay (PX4 docs: "EKF2 log replay") before flying it.
- Smaller differences aren't worth changing.
- This is not a calibration. The studies show that two independent methods agree on the direction and rank of the mismatch, not that the new setting improves any one vehicle's estimate. There is no ground truth for any one vehicle.

History: D1 was withdrawn after the first innovation check came back C2 as written, because that plan had EKF2's innovation sign backwards (PX4 computes prediction minus measurement; see `GRADE-innov.md`). The corrected check was pre-registered on fresh logs and held, so D1 is back.

## Studies

- `studies/fleet-2026/`: GPS lag across a random sample of PX4 Flight Review public logs (CC BY 4.0) from 2025-10 on, compared with each vehicle's `EKF2_GPS_DELAY`. Plan, grade (E1 passed, 5 of 6 predictions held), and one line per log in `v1/logs.jsonl`. `v1/summary.json` is the same rows re-scored, and it matches the grade.
- `studies/fleet-2026/PLAN-innov.md`, `GRADE-innov.md`, `innov/`: does EKF2's GPS velocity innovation, plotted against acceleration, lean the way the measured lag says it should? Graded C2 as written. The innovation sign was wrong in the plan; see the grade.
- `studies/fleet-2026/PLAN-innov-confirm.md`, `GRADE-innov-confirm.md`, `confirm/`: the corrected check (`innov.py` 0.2.0, PX4's sign) on the 98 fresh logs from px4-log-health, with the same thresholds. 89 logs validated; C1.
- `studies/receiver-2026/PLAN.md`: lag by GPS receiver model (`receiver.py` 0.1.0), pre-registered. Running.

**How long the raw logs stay.** Since October 2024, Flight Review keeps every upload, public ones included, for 12 months, then removes it automatically (announcement on discuss.px4.io, "PX4 Flight Review & Data Retention", topic 41906, 2024-10-14). These studies drew logs uploaded from October 2025 on, so the raw logs behind them start to disappear from October 2026. The per-log rows in each study's `logs.jsonl` (log id, hashed vehicle id, every measured figure, no positions) stay here, and the scored checks can be recomputed from them, but once a log is gone it can't be measured again from the raw file. If you want to re-measure, download the logs you need while they are still listed.

## Tests

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet test_innov test_receiver
```

The tests fly synthetic vehicles with known GPS delays and check that they are recovered within 3 ms. They also check that the innovation slope, in PX4's sign, recovers a known excess delay, and that re-scoring 0.1.0's rows flips every signed check. `test_receiver` checks the device_id decoding against PX4's bit layout, the choice of receiver, the exclusion of earlier vehicles and every scored check on synthetic rows.
