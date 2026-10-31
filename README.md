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

For a readable report per flight (health flags, fleet comparison and this GPS delay verdict), and a GitHub Action, see [px4-log-health](https://github.com/munimtechnologies/px4-log-health)'s `checkup.py`. It also runs in your browser, with nothing uploaded: [munimv2.github.io/px4-log-check](https://munimv2.github.io/px4-log-check/).

## What the fleet says

On 164 public Flight Review logs from 115 vehicles (`studies/fleet-2026/GRADE.md`, pre-registered), the median lag was 99.8 ms, close to the default 110 ms. But 29.6% of logs were more than 50 ms away from their own setting, and two logs of the same vehicle agreed to a median 5.3 ms. 98% of them ran the default.

**Replicated.** On an independent sample, 98 logs from 98 other vehicles, the median was 113.8 ms and 31.2% were more than 50 ms off their setting. Both figures were inside the ranges set before that run (px4-log-health, [`studies/fleet-health-2026/GRADE.md`](https://github.com/munimtechnologies/px4-log-health/blob/main/studies/fleet-health-2026/GRADE.md), R1 and R2).

**EKF2's own residuals agree.** On those 98 fresh logs, EKF2's GPS velocity innovations, compared with acceleration, lean the way the measured mismatch says they should in 25 of 27 logs that are more than 50 ms off their setting, and the two methods rank the logs alike (Spearman +0.86). The check was pre-registered and decided C1 ([`studies/fleet-2026/GRADE-innov-confirm.md`](studies/fleet-2026/GRADE-innov-confirm.md)). The innovation shows about 0.6 of the measured mismatch, as a filter that partly follows a late GPS should.

**Next, pre-registered: does the mismatch matter?** EKF2 accepts or rejects each GPS velocity sample with an innovation test (ratio above 1 = rejected). [`studies/mismatch-2026/PLAN.md`](studies/mismatch-2026/PLAN.md) asks whether logs whose GPS delay is off their setting show higher GPS velocity test ratios while the vehicle accelerates, and whether they see more rejections (`mismatch.py`). Arithmetic from PX4's defaults, written down first, says the mismatch should show but should not cause rejections by itself. It reads the same fresh logs as fresh-2026 (below), in the same download.

## Does the receiver model matter? (exploratory, seen twice)

PX4 uses one `EKF2_GPS_DELAY` for every receiver. ArduPilot assigns a lag by u-blox generation: 120 ms for M8 "based on flight logs", and the same 120 ms for F9, M9 and M10, with the comment "F9 lag not verified yet from flight log" (`AP_GPS_UBLOX.cpp`, `get_lag`). PX4's GPS driver records the receiver model it detected in the device_id of every GPS message, and `receiver.py` reads it.

Two samples with no vehicle in common, one log per vehicle:

| receiver (as PX4 detected it) | receiver-2026: vehicles, median lag | receiver-confirm: vehicles, median lag | pooled |
|---|---|---|---|
| u-blox M9 | 25, 71.3 ms | 32, 76.2 ms | 57, **73.6 ms** |
| DroneCAN | 39, 104.4 ms | 49, 92.9 ms | 88, 97.9 ms |
| u-blox, model not detected (includes M10 on v1.15) | 19, 127.8 ms | 27, 130.3 ms | 46, 128.1 ms |
| u-blox F9P | 16, 142.6 ms | 27, 143.5 ms | 43, **143.5 ms** |
| u-blox M8 | 15, 146.6 ms | 7, 150.9 ms | 22, **148.8 ms** |
| NMEA | 13, 150.0 ms | 16, 230.9 ms | 29, 206.5 ms |

- **receiver-2026** ([`GRADE.md`](studies/receiver-2026/GRADE.md)) was a fresh random sample of 163 passing logs. Its enough-data check (E1) failed, so it is exploratory. It found M9 about 75 ms less late than M8 (interval 53 to 107 ms), and F9P and M8 alike.
- **receiver-confirm** ([`GRADE-confirm.md`](studies/receiver-2026/GRADE-confirm.md)) read the receiver model of the 213 vehicles in the two earlier samples. Their lags had been published before the M9 gap was seen, and only the receiver class was new. **M9 − F9P = −67.3 ms (interval −101 to −48)**, as the plan predicted. Its E1 failed too: only 7 M8 vehicles turned up, against the 10 needed. So by the plan's own rule this is still exploratory, and the M9-vs-M8 gap could not be tested.

What this means: on PX4, the M9 being far less late than the F9P is now seen on two separate sets of vehicles, with an interval well away from 0 each time. The single 110 ms default sits between the M9 (about 74 ms) and the M8/F9P (about 145 ms). We still don't call it confirmed, and the decision to add a per-receiver line to px4-log-health's checkup did not fire. Measuring your own vehicle stays the advice. These are PX4 measurements only and say nothing about ArduPilot's own lag.

**Next, pre-registered: is it the measurement rate?** PX4's driver asks the M8 for 200 ms, the M9 for 125 ms and the F9P for 100 ms. [`studies/receiver-2026/PLAN-rate.md`](studies/receiver-2026/PLAN-rate.md) reads each log's actual rate from the phase of the receiver's own UTC times (`rate.py`). It then tests, on the lags already published, whether the M9 is still less late than other receivers measuring at the same 125 ms.

**Then, pre-registered: does the gap hold on fresh logs?** [`studies/receiver-2026/PLAN-fresh.md`](studies/receiver-2026/PLAN-fresh.md) draws a new random sample that leaves out every vehicle above, sized from receiver-2026's own class shares so that enough M8 logs turn up this time (`fresh.py`). It tests M9 against M8 and F9P, ArduPilot's assumption that the F9 is no later than the M8, and the NMEA hint in the table. It runs after the rate study, so that only one study downloads from Flight Review at a time.

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
- `studies/receiver-2026/`: lag by GPS receiver model (`receiver.py` 0.1.0). Plan, grade (E1 failed, so exploratory; 5 of 6 predictions held as written), `logs.jsonl`, `summary.json` and `job-fetched.json`. The first run was stopped from outside the job after 88 logs (exit 143). Its rows were never scored, and the complete second run is the one graded.
- `studies/receiver-2026/PLAN-confirm.md`, `GRADE-confirm.md`, `confirm/`: the M9 gap tested on the earlier samples' published lags (`confirm.py` 0.1.0). All 213 logs re-read; E0 held (213 of 213 re-measured within 1 ms); E1 failed (M8 7); C2 and C4 held as written; C1, C3 and C5 not scored.
- `studies/receiver-2026/PLAN-rate.md`: measurement rate from the receiver's UTC times (`rate.py` 0.1.0), scored on the published lags, pre-registered. Queued.
- `studies/receiver-2026/PLAN-fresh.md`: the receiver gap on a fresh sample of public logs (`fresh.py` 0.1.0, which reuses `gps_lag.py`, `receiver.py` and `rate.py` unchanged), pre-registered. Queued after the rate study.
- `studies/mismatch-2026/PLAN.md`: does a GPS delay more than 50 ms off its setting raise EKF2's GPS velocity test ratios while accelerating, or add rejections? (`mismatch.py` 0.1.0), pre-registered. `fresh_mm.py` runs `fresh.py` 0.1.0 unchanged and reads these figures from the same downloaded logs.

**How long the raw logs stay.** Since October 2024, Flight Review keeps every upload, public ones included, for 12 months, then removes it automatically (announcement on discuss.px4.io, "PX4 Flight Review & Data Retention", topic 41906, 2024-10-14). These studies drew logs uploaded from October 2025 on, so the raw logs behind them start to disappear from October 2026. The per-log rows in each study's `logs.jsonl` (log id, hashed vehicle id, every measured figure, no positions) stay here, and the scored checks can be recomputed from them, but once a log is gone it can't be measured again from the raw file. If you want to re-measure, download the logs you need while they are still listed.

## Tests

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet test_innov test_receiver test_confirm test_rate test_fresh test_mismatch
```

The tests fly synthetic vehicles with known GPS delays and check that they are recovered within 3 ms. They also check that the innovation slope, in PX4's sign, recovers a known excess delay, and that re-scoring 0.1.0's rows flips every signed check. `test_receiver` checks the device_id decoding against PX4's bit layout, the choice of receiver, the exclusion of earlier vehicles and every scored check on synthetic rows. `test_confirm` checks that one published lag per vehicle is taken from both earlier formats, and checks every scored check on synthetic rows. `test_rate` checks that synthetic receivers at 100, 125 and 200 ms get their grid, and that 1-2 Hz receivers, logs throttled to 500 ms and times off any grid get none. It also checks every scored check on synthetic rows. `test_fresh` checks every scored check of the fresh study on synthetic rows, including the ones it leaves unscored when a class is too small, and that the draw uses its own seed and leaves out earlier vehicles. `test_mismatch` flies a synthetic 200 s flight with known test ratios and a known innovation lean, and checks the acceleration bins, the lift, rejections, the in-flight mask and the slope. It also checks every scored check on synthetic rows, and that `fresh_mm.py` returns exactly `rate.read_rate`'s fields (or `fresh.py`'s own error fields) plus the mismatch fields.
