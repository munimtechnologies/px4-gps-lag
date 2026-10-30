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

**Using the number (rule D1 of the study):** if a passing log's `lag_minus_param_ms` is more than about 50 ms either way, the measured `lag_ms` is a reasonable **starting value** for `EKF2_GPS_DELAY`. Measure two or three flights first, since a vehicle's flights should agree within a few ms. Check any change with EKF2 replay of your own logs (PX4 docs: "EKF2 log replay") before flying it. A small difference is not worth changing. This is not a setting the tool can verify for you: there is no ground truth for any one vehicle. A pre-registered cross-check against EKF2's own GPS innovations is running (`studies/fleet-2026/PLAN-innov.md`). If it disagrees, this suggestion is withdrawn.

## Studies

- `studies/fleet-2026/`: GPS lag across a random sample of PX4 Flight Review public logs (CC BY 4.0) from 2025-10 on, compared with each vehicle's `EKF2_GPS_DELAY`. Plan, grade (E1 passed, 5 of 6 predictions held), and one line per log in `v1/logs.jsonl`.
- `studies/fleet-2026/PLAN-innov.md`: does EKF2's GPS velocity innovation, plotted against acceleration, lean the way the measured lag says it should? `innov.py`, pre-registered before any innovation was read.

## Tests

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet test_innov
```

The tests fly synthetic vehicles with known GPS delays and check that they are recovered within 3 ms. They also check that the innovation slope recovers a known excess delay.
