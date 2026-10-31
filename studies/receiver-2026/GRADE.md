# receiver-2026: grade

Graded against [`PLAN.md`](PLAN.md), committed in f654f61 before any log was downloaded. The run used `receiver.py` 0.1.0 fetched from that same commit (sha256 `8077de08…`, see `job-fetched.json`), with `gps_lag.py` 0.1.0 and `fleet.py` 0.1.1 from 62a205e. The checks below are the mechanical verdicts in `summary.json` (`checks`). Every per-log row is in `logs.jsonl`.

The first run on 2026-10-30 was stopped from outside the job after 88 logs. Its rows were never scored. This grade is the complete second run (2026-10-30 21:51 to 2026-10-31 00:05 UTC, 130-minute budget, no block from Flight Review).

## Sample

- Flight Review listed 483,966 logs, and 36,269 were eligible (real, at least 240 s long, from 2025-10-01 on). The 700 logs and 634 vehicles of the two earlier studies were left out.
- 537 logs were attempted (one per vehicle) and 441 downloaded. 96 were over 80 MB. **163 passed** the lag gates.
- Most of the logs that failed the gates did so because the IMU explained too little of the GPS velocity change (97), had no `vehicle_gps_position` (74), had too few in-flight GPS pairs (55) or had too little manoeuvring (44).
- 136 of the 163 (83.4%) got a known receiver class. In 103 it came from `vehicle_gps_position` and in 33 from the only `sensor_gps`. 11 were blended from several receivers ("multiple") and 16 named none ("unknown").

| class (PX4 devtype) | passed logs | median lag | p25-p75 |
|---|---:|---:|---:|
| u-blox M9 (0xA9) | 25 | **71.3 ms** | 47.8-87.9 |
| DroneCAN / UAVCAN | 39 | 104.4 ms | 70.4-114.5 |
| u-blox, model not detected (0xA5; includes M10 on v1.15) | 19 | 127.8 ms | 113.9-136.5 |
| u-blox F9P (0xAA) | 16 | **142.6 ms** | 133.9-176.6 |
| u-blox M8 (0xA8) | 15 | **146.6 ms** | 124.8-169.7 |
| NMEA (0xAB) | 13 | 150.0 ms | 96.1-212.5 |
| multiple receivers, blended | 11 | 126.6 ms | 110.8-157.7 |
| unknown | 16 | 87.7 ms | 43.1-135.7 |
| u-blox M10, detected (0xAC) | 4 | 100.0 ms | |
| Ashtech, MAVLink sim, other I2C | 2, 2, 1 | | |

## E1 failed, so every result below is exploratory

**E1 (enough data): FAILED.** It needed at least two serial u-blox classes with at least 25 passed logs. Only M9 had 25. M8 had 15, F9P 16 and the undetected u-blox class 19. As the plan says, nothing below is a confirmed result, even where a check holds as written. The plan assumed bigger u-blox classes than the public logs hold, and that was our mistake.

| check | as written | result |
|---|---|---|
| P1: M8 median between 80 and 160 ms | held | 146.6 ms (n 15). That is inside the range, but above ArduPilot's 120 ms and PX4's default 110 ms. |
| P2: F9P median at most M8's | held, **not clear** | F9P − M8 = −4.0 ms, 95% interval −28.0 to +29.3. The interval contains 0, so F9P and M8 can't be told apart here. |
| P3: largest gap between detected models is at least 20 ms, interval excludes 0 | held | M8 − M9 = 75.3 ms, interval 52.9 to 106.5 |
| P4: a per-class delay puts at least 5 points more vehicles within 50 ms than 110 does | held | 77.2% → 88.6% of 114 vehicles (+11.4 points, leave-one-out) |
| P5: DroneCAN lag below serial receivers with a known type | held | 104.4 vs 124.8 ms, −20.4 ms, interval −42.8 to −1.6 |
| P6: at least 70% of passed logs get a known class | held | 83.4% |

**Decisions.**
- **D1 does not fire.** It needs both E1 and P3. px4-log-health's checkup gets no per-receiver line from this study. Per-vehicle measurement (`gps_lag.py`) stays the advice.
- **D2 applies.** These are measurements on PX4 vehicles only. PX4 timestamps GPS data on a different path from ArduPilot, so this says nothing about ArduPilot's lag on ArduPilot vehicles.

## What it suggests (exploratory)

1. **M9 receivers came out about half as late as M8 and F9P: 71 ms against 147 and 143 ms.** The gap is large next to its interval (53-107 ms for M9 against M8). The default of 110 ms sits between two clusters. It is about 40 ms too long for a typical M9 vehicle and about 35 ms too short for a typical M8 or F9P one.
2. **We found no sign that F9P is faster than M8.** ArduPilot gives F9, M9 and M10 the same 120 ms as M8, with the comment "F9 lag not verified yet from flight log, but likely to be at least as good as M8". On these PX4 logs the F9P looks about the same as the M8, and the M9 looks much faster.
3. **DroneCAN GPS is again lower than serial**, by about 20 ms. That is now the third sample to point this way (fleet-2026 90 vs 109 ms; fleet-health-2026, exploratory, 108 vs 129 ms).

**Update rate does not simply explain the order.** These are hypotheses, not results. In PX4 v1.15.4 the GPS driver (PX4-GPSDrivers at ad769ff, `ubx.cpp`, `configureDevice`) sets `rate_meas = (_board == Board::u_blox9_F9P) ? 100 : 125` in normal mode. That means 10 Hz for F9P and 8 Hz for M9 and M10. M8 receivers take the older CFG-RATE path (`configureDevicePreV27`) with `UBX_TX_CFG_RATE_MEASINTERVAL`, which is 200 ms (5 Hz) in the current `ubx.h`. So the slowest-configured receiver (M8, 5 Hz) and the fastest-configured one (F9P, 10 Hz) have similar lags, and the 8 Hz M9 is far lower.

The current driver's comments say an F9P can do at most 7-9 Hz with four constellations. PX4-GPSDrivers #199 (Feb 2026) moved the F9P default to 5 Hz. One possibility is that asking an F9P for 10 Hz costs latency. RTK and its extra messages are another possibility: F9P logs with RTK fixed had a median of 156 ms against 136 ms without, but the groups are tiny. Both ideas are untested.

Other breakdowns, all small and descriptive, are in `summary.json` under `exploratory`. They split the lag by release, by fix type, by number of receivers, by logged GPS interval and by `EKF2_GPS_DELAY` value. Almost every vehicle in every class ran the default 110 ms.

## Next

The M9 gap was found here, not predicted, so it has to be checked on vehicles this study never saw. [`PLAN-confirm.md`](PLAN-confirm.md) pre-registers that check. It reads the receiver model of the vehicles in the two earlier samples, whose lags were measured and published before this study existed, and tests the M9 gap against those already-published lags.

## Limits

- E1 failed, so the classes are small (15-25). The intervals above are wide, and only the M9 gap is far from 0.
- Flight Review uploads are self-selected, often after a problem. Logs over 80 MB (96 of 537 attempts, 18%) were skipped.
- The lag runs from the measurement to the flight controller's timestamp. It mixes the receiver's own latency with the baud rate, the message load and the driver. A class difference can come from how PX4 configures each model, not from the chip alone.
- "u-blox, model not detected" mixes M10 receivers (on v1.15) with undetected units. DroneCAN modules are not identified. One log per vehicle. Vehicles in one class may share other traits, such as the frame or the flight controller.
- The two "MAVLink sim" logs (device type 0xAF on the MAVLink bus) passed the gates with lags near −13 ms. They are in no comparison.

## Files

- `logs.jsonl`: one row per attempted log. It has the log id, a hashed vehicle id, every measured figure, the receiver class with its source and device_id, and the best fix type. No positions are included.
- `summary.json`: the scored checks and the exploratory tables, exactly as the job wrote them.
- `job-fetched.json`: sha256 of every file the job fetched, including `receiver.py` at f654f61 and the plan on main (identical to f654f61's).

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Data from PX4 Flight Review public logs (CC BY 4.0). Text CC BY 4.0, code Apache-2.0.
