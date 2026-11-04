# dynmodel-2026, paired check: one vehicle flown with u-blox dynamic model 6 and 7 (pre-registration)

Written and committed on 2026-11-04, before the logs below were downloaded or opened. Code: `paired.py` 0.1.0 and `test_paired.py`, committed with this plan. The sealed job waits until all three are on `main` before it downloads the logs.

## Why

[dynmodel-2026](GRADE.md) found that across public PX4 logs, u-blox logs with `GPS_UBX_DYNMODEL` = 6 were a median 46 ms later than logs with 7 from the same receiver class. Every pre-registered check held. But the comparison is between different vehicles, and PX4's own defaults tie the model to the vehicle:

- `rc.mc_defaults` set `GPS_UBX_DYNMODEL 6` for every multicopter up to v1.16. PX4 PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831) removed that line (merged 2025-05-27, first released in v1.17), so multicopters now get the parameter default 7.
- `rc.fw_defaults` sets 8 for fixed wings ("FW takeoff acceleration can easily exceed ublox GPS 2G default").
- VTOLs and everything else get 7.

So model-6 logs are mostly multicopters on v1.16 or older, and model-7 logs are a mix of newer multicopters, VTOLs and vehicles set by hand. The fleet difference could come from the vehicle type or the release rather than the model. An exploratory re-score within matched strata is running separately; it uses data already seen.

That same PR gives a cleaner test. To support the change, a PX4 maintainer flew "similar aggressive flights" with model 6 and model 7 and attached the logs to the PR as [`logs_dynmodel.zip`](https://github.com/user-attachments/files/20456409/logs_dynmodel.zip) (2025-05-27). Within one vehicle, the vehicle type, airframe, receiver and release are the same, and only the model (and the flight) changes. The PR discussion compared EKF2 resets, not GPS lag, and gives no lag figure. We have not opened the zip.

## Method

The sealed job downloads the zip once and records its sha256 and size. `paired.py run` extracts every `.ulg` (also from zips inside it, one level down). For each log it reads the initial parameters (`GPS_UBX_DYNMODEL`, `EKF2_GPS_DELAY`, `SENS_GPS0_DELAY`, `GPS_UBX_MODE`, `GPS_1_CONFIG`), the release, the GPS device type and a 12-character hash of `sys_uuid`. It then measures the GPS lag with px4-gps-lag's `gps_lag.py` (`read_log`, `measure`) from `main`, unchanged, with its usual pass gates. No position is kept.

A **passing log** passes `gps_lag.py` and has `GPS_UBX_DYNMODEL` in its parameters. A **qualifying vehicle** (same `sys_uuid` hash) has at least one passing log with model 6 and one with model 7.

## Checks

| | rule |
|---|---|
| **E0** | at least one qualifying vehicle |
| **P1** | the median over qualifying vehicles of (median lag of its model-6 logs − median lag of its model-7 logs) is **≥ +30 ms** (dynmodel-2026's K1 threshold) |
| **P2** | in every qualifying vehicle with at least 2 logs of each model, every model-6 log is later than every model-7 log. Not scored if no vehicle has 2 of each |

If E0 fails, nothing is scored and the zip's contents are reported.

**What we expect.** We are unsure. If the model itself adds the lag that the fleet showed, P1 should hold, since the fleet effect was +46 ms (interval 33 to 55). If the fleet figure comes from vehicle type or release, the within-vehicle difference should be near 0. We give the two outcomes about even odds. With a handful of logs, one vehicle and one pilot, the result is a case, not a fleet figure. Flights differ in how hard they manoeuvre, and `gps_lag.py` reports a standard error per log.

## Decisions

- **D1 (E0 and P1 hold):** the within-vehicle evidence agrees with the fleet figure. px4-gps-lag's README says so. px4-log-health's checkup may add its information line for model 6 (dynmodel-2026's D1), worded with both results and their limits.
- **D2 (E0 holds, difference below +10 ms):** the README says the fleet difference is not seen within this vehicle and is probably due to what comes with model 6, not the model itself. The checkup does not add the line, and MV2 files no PX4 issue about the model's lag.
- **D3 (E0 holds, difference from +10 to +30 ms):** inconclusive. The README reports the figure, and nothing is added to the checkup.

## Reported, not predicted

Every log's file name, vehicle hash, release, GPS device type, model, pass/fail reason, lag, standard error, lag minus the delay setting and excitation. Model 8 logs, if any. The zip's sha256 and size.

## Limits

- One maintainer's vehicle, flown to test EKF2 resets, not lag. The flights may differ in more than the model.
- The lag is measured against `vehicle_gps_position.timestamp`, so it includes PX4's parsing and serial transfer.
- The logs come from a pull request's test build (PX4 main in May 2025), not a release.

## Outputs

`paired-rows.jsonl`, `paired-summary.json` and `job-fetched.json`, published in `studies/dynmodel-2026/paired/` with `GRADE-paired.md`, whatever the outcome. The logs themselves are not republished; they stay attached to PR #24831.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
