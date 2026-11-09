# dronecan-2026 extension: the same test on the vehicles the first pass did not reach (plan)

Pre-registered on 2026-11-09, after the first pass was graded ([GRADE.md](GRADE.md)) and before any log in this extension is read. A sealed job checks that this file on `main` matches its own copy before it reads Flight Review's list.

## Why

The first pass ([PLAN.md](PLAN.md)) stopped at its limit of 40 downloaded logs after 96 of 986 candidate vehicles. Only 4 had a DroneCAN GNSS receiver, and one self-stamped log passed gps_lag's gates (residual +72 ms), so D1 failed and D3/D4 could not be graded. The question is unchanged: since [PX4 PR #27427](https://github.com/PX4/PX4-Autopilot/pull/27427), does the delay a DroneCAN receiver reports for itself cover its measured GPS lag?

What has been seen before this plan: the first pass's 96 rows and its grade, and gnss-2026's 11 vehicles. Both sets of vehicles are left out here.

## What runs

`dronecan_ext.py` 0.1.0 runs in a sealed job after `test_gps_lag.py`, `test_gps_lag_gnss.py`, `test_dronecan_logs.py` and `test_dronecan_ext.py` pass. It uses the first pass's code unchanged (`dronecan_logs.py` 0.1.0, `gnss_logs.py` 0.1.0, px4-gps-lag 0.2.0, all fetched from `main`), with three changes:

1. **Vehicles.** Every vehicle the first pass requested (the `vehicle` field of all 96 rows in `dronecan-rows.jsonl` on `main`) is left out, as well as gnss-2026's 11. Everything else about the list and its order is as in PLAN.md: Flight Review's public list read once, real logs of at least 60 s dated 2026-06-30 or later, v1.18 or newer or with no readable release, newest first, then by log id, one log per vehicle.
2. **Downloads.** As before, only a log whose initial `UAVCAN_ENABLE` is 1 or more is downloaded, and now only if its release reads as PX4 v1.x (v1.18 or newer). Other release numbers and unreadable ones get their definitions read and are recorded as `uavcan on, not v1.x`. In the first pass the 19 downloaded logs on such releases gave no DroneCAN receiver (14 unknown buses, 3 serial, 2 without a GPS topic), so this saves downloads at little cost to D1-D4; it does leave fewer serial logs for D5.
3. **Limits.** At most 900 requests and 300 downloaded logs, 300 minutes, 6 s between requests. The pass still stops at the first block (HTTP 403/429/444) or after five errors in a row.

For every downloaded log the job also records the device id of each logged `sensor_gps` instance (the per-receiver topic). This is descriptive only: the classes below still come from gps_lag's `gps_bus`, as in the first pass.

## Predictions

The same five predictions with the same thresholds, graded on **this extension's logs only**:

| | prediction | our prior |
|---|---|---|
| **D1** | at least 8 DroneCAN logs (from 8 vehicles) are read | 70% |
| **D2** | in at least half of the DroneCAN logs read that are not unknown, the receiver is self-stamped | 60% |
| **D3** | if at least 5 self-stamped DroneCAN logs pass gps_lag's gates: their median residual is more than 20 ms | 65% |
| **D4** | if at least 5 pass: in at least two thirds of them, the measured lag is closer to 110 ms than to the applied delay | 55% |
| **D5** | control: if at least 5 serial-receiver logs are read that are not unknown, at least 90% of them have the applied delay within 1 ms of a delay parameter or 110 ms | 85% |

The same scores on the first pass and the extension pooled are reported beside them, marked as pooled; they are not the grade. Logs whose GPS sample has no device id but whose `sensor_gps` receivers are all DroneCAN are listed separately and not graded.

## What follows

- **D3 holds:** report it on PR #27427 with the rows and code, and have px4-log-health's checkup warn when a self-stamped receiver's measured lag is more than 50 ms past its applied delay, without suggesting a setting (PX4 ignores the delay setting for these receivers).
- **D3 fails:** report that the self-reported delay held up on public logs, which is the validation the PR asked for, and the checkup compares against the applied delay with no extra warning.
- **D3 not graded again:** report how few DroneCAN logs public flights hold, and stop this line of study until more v1.18 logs are public.

Everything is reported, whichever way it goes: rows in `dronecan-ext-rows.jsonl`, scores in `dronecan-ext-summary.json`, and a grade in `GRADE-ext.md`.

## Limits known in advance

The first pass's limits all apply. In addition, the extension's vehicles come later in the newest-first order, so they are older flights on average (still 2026-06-30 or later).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
