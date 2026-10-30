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

## What the fleet says

On 164 public Flight Review logs from 115 vehicles (`studies/fleet-2026/GRADE.md`, pre-registered), the median lag was 99.8 ms, close to the default 110 ms. But 29.6% of logs were more than 50 ms away from their own setting, and two logs of the same vehicle agreed to a median 5.3 ms. 98% of them ran the default.

**Replicated.** On an independent sample, 98 logs from 98 other vehicles, the median was 113.8 ms and 31.2% were more than 50 ms off their setting. Both figures were inside the ranges set before that run (px4-log-health, [`studies/fleet-health-2026/GRADE.md`](https://github.com/munimtechnologies/px4-log-health/blob/main/studies/fleet-health-2026/GRADE.md), R1 and R2).

**EKF2's own residuals agree.** On those 98 fresh logs, EKF2's GPS velocity innovations, compared with acceleration, lean the way the measured mismatch says they should in 25 of 27 logs that are more than 50 ms off their setting, and the two methods rank the logs alike (Spearman +0.86). The check was pre-registered and decided C1 ([`studies/fleet-2026/GRADE-innov-confirm.md`](studies/fleet-2026/GRADE-innov-confirm.md)). The innovation shows about 0.6 of the measured mismatch, as a filter that partly follows a late GPS should.

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

## Tests

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet test_innov
```

The tests fly synthetic vehicles with known GPS delays and check that they are recovered within 3 ms. They also check that the innovation slope, in PX4's sign, recovers a known excess delay, and that re-scoring 0.1.0's rows flips every signed check.
