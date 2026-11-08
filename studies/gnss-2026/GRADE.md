# gnss-2026: grade

Graded on 2026-11-08 against [PLAN.md](PLAN.md), which was published on `main` before any log was read. The sealed job (`px4-gps-lag-gnss-v1`, 2026-11-08 15:21-15:50 UTC) first built gps_lag.py 0.2.0 from main's 0.1.0 with the five planned edits (`job-diff.txt`). It then passed `test_gps_lag`, `test_gps_lag_gnss` and `test_gnss_logs`, checked PLAN.md on `main`, and read Flight Review's public list once. Rows are in `gnss-rows.jsonl` and scores in `gnss-summary.json`. Neither file holds any position.

## The pass

- Flight Review listed 487,780 logs. 733 were candidates (not simulation or CI, dated 2026-09-29 or later, at least 60 s long, v1.18 or newer or unreadable), from 236 vehicles.
- All 236 vehicles were requested, one log each. The list ran out before any limit was reached, and nothing was blocked.
- **11 were PX4 main logs** (their formats include `vehicle_gnss`), from 11 vehicles. All 11 are quadrotors: 10 run v1.18.0 beta builds and 1 a development build. None also logs `vehicle_gps_position`. The other 225 still log `vehicle_gps_position`.
- 3 of the 11 define `vehicle_gnss` but never wrote a sample of it, so 8 were read.

## Predictions

| | prediction | prior | result |
|---|---|---|---|
| **P1** | at least 5 main logs, from at least 3 vehicles | 55% | **held**: 11 logs, 11 vehicles |
| **P2** | all seven columns come from their first-choice `vehicle_gnss` field in every main log read | 80% | **held**: 8 of 8 |
| **P3** | in at least 90% of main logs read, the applied delay is within 1 ms of `SENS_GNSS0_DELAY` or `SENS_GNSS1_DELAY` | 70% | **failed**: 4 of 8 (50%) |
| **P4** | gps_lag.py 0.2.0 passes its quality gates on at least 3 main logs | 45% | **held**: 5 |
| **P5** | if at least 5 pass: median (measured lag − applied delay) within ±50 ms | 65% | **failed**: median +79.5 ms (5 logs) |

So gps_lag.py 0.2.0 reads what PX4 main writes (P2), and its gates work on those logs (P4). As the plan says for P2, **px4-gps-lag 0.2.0 is released**. P3 and P5 failed for a reason found in PX4's code (below), not in the reader.

## The eight logs read

"Applied" is the median of `receiver.timestamp − timestamp_sample`, the delay PX4 applied to the sample. "Lag" is gps_lag's measured lag of the GPS velocity behind the IMU, against `receiver.timestamp`. Every log has `SENS_GNSS0_DELAY` = `SENS_GNSS1_DELAY` = 110 ms (the default).

| order | hardware | receiver (bus, device type) | applied (ms) | lag ± se (ms) | lag − applied (ms) | gates |
|---|---|---|---|---|---|---|
| 70 | ZEROONE_X6 | DroneCAN, 0x85 | 85.65 | 166.3 ± 0.8 | +80.6 | pass |
| 75 | SKYSAKURA_H743 | simulated receiver on real hardware, 0xAF | 0.58 | −15.9 ± 7.2 | −16.5 | pass |
| 91 | PX4_FMU_V6C | serial, 0xA5 | 110.00 | 189.5 ± 2.4 | +79.5 | pass |
| 99 | CUBEPILOT_CUBEORANGE | DroneCAN, 0x85 | 98.03 | 110.3 ± 1.0 | +12.3 | pass |
| 104 | CUBEPILOT_CUBEORANGEPLUS | serial, 0xA2 | 110.00 | (112.2) | | IMU explains too little |
| 138 | PX4_FMU_V6X | serial, 0xA5 | 110.00 | | | no in-flight GPS samples |
| 176 | CUAV_7_NANO | DroneCAN, 0x85 | 10.18 | 92.8 ± 0.7 | +82.6 | pass |
| 198 | PX4_FMU_V6C | serial, 0xA5 | 110.00 | (141.7) | | IMU explains too little |

All four serial receivers had exactly 110.00 ms applied. None of the three DroneCAN receivers did, and neither did the simulated one.

## Why P3 failed: PX4 main ignores the delay setting when the driver stamps its own sample time

In PX4 main, `src/modules/sensors/vehicle_gps_position/VehicleGPSPosition.cpp` resolves each receiver's sample time like this (BSD-3-Clause, PX4 Development Team):

```cpp
	// A driver that doesn't know the receiver latency leaves timestamp_sample at 0 (or at the publish time); the
	// configured receiver delay applies then.
	if ((driver_timestamp_sample != 0) && (driver_timestamp_sample < driver_timestamp)) {
		return driver_timestamp_sample;
	}

	return (delay_us > 0 && driver_timestamp > delay_us) ? driver_timestamp - delay_us : driver_timestamp;
```

The parameter's own description says the same: SENS_GNSS${i}_DELAY is "Only applied when the GPS driver does not provide its own timestamp_sample correction."

The DroneCAN GNSS bridge (`src/drivers/uavcan/sensors/gnss.cpp`) supplies one. It maps the node's `Fix2.timestamp` (its send time, in UTC) into the flight controller's clock with a per-node clock-offset estimator, then subtracts the node's reported processing time (`Fix2.timestamp − Fix2.gnss_timestamp`). This came with [PX4 PR #27427](https://github.com/PX4/PX4-Autopilot/pull/27427) ("anchor DroneCAN GNSS timestamp_sample to receiver PPS", merged 2026-06-29, also on release/1.18). The PR says that "only the minimum CAN transport latency (a few ms) remains as bias". Its description also says: "Still a draft: needs flight-log validation on hardware before un-drafting." No flight log is posted on it.

So on PX4 main and v1.18, a DroneCAN receiver that fills `Fix2.timestamp` gets whatever delay its node reports, and SENS_GNSSn_DELAY no longer applies. The simulated receiver also stamps its own sample time.

## Why P5 failed, and what the three DroneCAN logs show (exploratory)

P5 compared the measured lag with the applied delay. On the four serial receivers the applied delay is the 110 ms setting. Only one of them passed the gates, and its lag is 79.5 ms more than that. That is not unusual: in px4-gps-lag's pre-registered fleet study of older firmware, 29.6% of logs were more than 50 ms away from their own setting.

On the three DroneCAN receivers, the delay the node reported was 12 to 83 ms short of the measured lag (+80.6, +12.3, +82.6 ms). The 110 ms setting, the delay these receivers got before PR #27427, would have been closer on all three (56.3, 0.3 and 17.2 ms away). In px4-gps-lag's earlier fleet studies of older firmware, DroneCAN receivers had median lags of 92.9 to 105.9 ms in four independent samples, close to 110 ms.

This was not predicted, and it rests on three logs from three vehicles. We don't know which node firmware they run or whether a PPS signal anchored their clocks. Also, gps_lag measures how late the velocity is, and that includes any smoothing inside the receiver, while PR #27427 targets the time of the navigation epoch. It is therefore a hypothesis, not a result. A separate pre-registered study, [dronecan-2026](../dronecan-2026/PLAN.md), tests it on DroneCAN logs from other vehicles.

## What follows

- **px4-gps-lag 0.2.0 is released** (P2 held): `gps_lag.py` reads `vehicle_gnss` when a log has no `vehicle_gps_position`. Logs with `vehicle_gps_position` are read exactly as before.
- **For PX4 main and v1.18 logs, compare the measured lag with the delay PX4 actually applied** (`stamp_minus_sample_ms` in gps_lag's output), not with SENS_GNSSn_DELAY. They differ whenever the driver stamps its own sample time. px4-log-health's checkup will make this change in its next version (0.3.7).
- The simulated-receiver log (order 75) passed the gates and counted toward P5 as the plan specified. Leaving it out would leave four logs, too few for P5 under the plan's own rule.

## Limits

- Public PX4 main logs are developers' test flights: 11 of the 236 vehicles flying v1.18 or newer since 2026-09-29.
- One log per vehicle, chosen by the plan's fixed order. No position was read or written.
- Field names can change again before PX4's next release.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0. The PX4 excerpt above is BSD-3-Clause, © PX4 Development Team.
