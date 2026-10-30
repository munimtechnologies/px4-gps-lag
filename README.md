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

**Status: diagnostic only.** Whether the measured lag is repeatable enough to suggest a value for `EKF2_GPS_DELAY` is being tested on public Flight Review logs (`studies/fleet-2026/PLAN.md`, pre-registered before any log was downloaded). Until that is graded, treat the number as a diagnostic, and check any change with EKF2 replay.

## Studies

- `studies/fleet-2026/`: GPS lag across a random sample of PX4 Flight Review public logs (CC BY 4.0) from 2025-10 on, compared with each vehicle's `EKF2_GPS_DELAY`. Plan written first; results pending.

## Tests

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet
```

The tests fly synthetic vehicles with known GPS delays and check that they are recovered within 3 ms.
