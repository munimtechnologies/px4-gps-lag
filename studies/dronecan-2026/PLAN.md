# dronecan-2026: does a DroneCAN receiver's self-reported delay cover its GPS lag? (plan)

Pre-registered on 2026-11-08, before any log in this study was read. A sealed job checks that this file on `main` matches its own copy before it reads Flight Review's list.

## Why

Since [PX4 PR #27427](https://github.com/PX4/PX4-Autopilot/pull/27427) (merged 2026-06-29; on PX4 main and release/1.18), PX4's DroneCAN GNSS bridge (`src/drivers/uavcan/sensors/gnss.cpp`) sets the sample time itself. It maps the node's `Fix2.timestamp` into the flight controller's clock and subtracts the node's processing time (`Fix2.timestamp − Fix2.gnss_timestamp`). When a driver sets the sample time, `VehicleGPSPosition::resolveSampleTimestamp` uses it, and the delay parameter (`SENS_GPSn_DELAY` on v1.18, `SENS_GNSSn_DELAY` on main, default 110 ms) is not applied. The PR expects "only the minimum CAN transport latency (a few ms)" to remain. Its description says it "needs flight-log validation on hardware", and no flight log is posted on it.

In [gnss-2026](../gnss-2026/GRADE.md), three DroneCAN receivers on PX4 main logs were 12, 81 and 83 ms later than the delay applied to them. The old 110 ms setting would have been closer on all three. That was found after the fact, on three vehicles. This study tests it on other vehicles.

## What runs

`dronecan_logs.py` 0.1.0 runs in a sealed job, after `test_gps_lag.py`, `test_gps_lag_gnss.py` (px4-gps-lag 0.2.0) and `test_dronecan_logs.py` pass. It reuses gnss-2026's `gnss_logs.py` 0.1.0 to read the list and log headers.

1. **List.** Flight Review's public list, read once. A log is a candidate if it is not simulation or CI, has a log id, is dated 2026-06-30 or later, is at least 60 s long, and its release is v1.18 or newer or can't be read. The 11 vehicles whose logs gnss-2026 read are excluded, which includes the three DroneCAN vehicles that suggested this test.
2. **Order.** Newest first, then by log id. One log per vehicle (the first in that order).
3. **Head.** For each candidate, stream the log and read only its definitions section. If the initial parameter `UAVCAN_ENABLE` is 1 or more, download the rest (at most 150 MB). Otherwise close the connection.
4. **Read.** `gps_lag.measure(gps_lag.read_log(log))` with px4-gps-lag 0.2.0. This gives the receiver's bus (`gps_bus`), the delay PX4 applied (`stamp_minus_sample_ms`, the median of the GPS sample's `timestamp − timestamp_sample`), the measured lag, its standard error and the quality gates. The job also records the receiver's device id and the delay parameters. No position is written out, and the file is deleted after it is read.
5. **Classes.** A **DroneCAN log** is one where `gps_bus` is `uavcan`. Its receiver is **self-stamped** if the applied delay is more than 1 ms from every logged delay parameter (`SENS_GNSS0/1_DELAY`, `SENS_GPS0/1_DELAY`) and from 110 ms. It is **unknown** if the log has no delay parameter or no applied delay.
6. **Limits.** At most 400 requests and 40 downloaded logs, 200 minutes, 6 s between requests. The pass stops at the first block (HTTP 403/429/444) or after five errors in a row.

## Predictions

"Residual" is the measured lag minus the applied delay. It is the part of the GPS lag that PX4 does not correct for.

| | prediction | our prior |
|---|---|---|
| **D1** | at least 8 DroneCAN logs (from 8 vehicles) are read | 50% |
| **D2** | in at least half of the DroneCAN logs read that are not unknown, the receiver is self-stamped | 60% |
| **D3** | if at least 5 self-stamped DroneCAN logs pass gps_lag's gates: their median residual is more than 20 ms | 65% |
| **D4** | if at least 5 pass: in at least two thirds of them, the measured lag is closer to 110 ms than to the applied delay | 55% |
| **D5** | control: if at least 5 serial-receiver logs are read that are not unknown, at least 90% of them have the applied delay within 1 ms of a delay parameter or 110 ms | 85% |

D1 and D2 ask whether there is enough to test. D3 is the main test: "a few ms" predicts that D3 fails, and the gnss-2026 hypothesis predicts that it holds. D4 asks whether the fixed default would have done better. D5 checks that the classification works on receivers whose drivers don't stamp their own time. D3 and D4 aren't graded with fewer than 5 passing logs, and D5 isn't graded with fewer than 5 serial logs.

## What follows

- **D3 holds:** report it on PR #27427's topic with the rows and code, and have px4-log-health's checkup (0.3.7) warn when a self-stamped receiver's measured lag is more than 50 ms past its applied delay. The checkup does not suggest a setting, because on these receivers PX4 ignores the delay setting.
- **D3 fails:** report that the self-reported delay held up on public logs, which is the validation the PR asked for, and the checkup compares against the applied delay with no extra warning.
- **D1 fails:** report how few DroneCAN logs there are. Nothing is claimed beyond gnss-2026's three.

Everything is reported, whichever way it goes: rows in `dronecan-rows.jsonl`, scores in `dronecan-summary.json`, and a grade in `GRADE.md`.

## Limits known in advance

- gps_lag measures how late the GPS velocity is behind the IMU. That includes any smoothing inside the receiver, while PR #27427 targets the time of the navigation epoch. A residual can come from either.
- The logs don't say which node firmware a receiver runs or whether a PPS signal anchored its clock. The device id is recorded.
- Public v1.18 and main logs are mostly developers' test flights. One log per vehicle.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
