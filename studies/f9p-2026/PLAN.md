# f9p-2026: the u-blox F9P at 5 Hz on PX4 v1.16 and v1.17 (pre-registration)

Written and committed on 2026-11-02, before the sample below is drawn. Nothing in this sample has been downloaded or looked at. Code: `f9p.py` 0.1.0 (scoring, standard library only), `fresh2.py` 0.1.0 (the draw), `f9p_extra.py` 0.1.0 (an exploratory pass), and `test_f9p.py`. All are committed with this plan.

## Why

PX4-GPSDrivers commit `bbdd576` ("ublox update F9P output rates"), shipped in PX4 v1.16 and v1.17, set the u-blox F9P L1L2 to measure every 200 ms (5 Hz). Before that, PX4 ran it at 10 Hz. The code comment gives the reason: on F9P firmware 1.50 and newer, with four constellations, 5 Hz is the most the receiver supports with RTK. PX4's GPS delay default stayed at 110 ms: `EKF2_GPS_DELAY` up to v1.17, and `SENS_GPSn_DELAY` from v1.18.

On fresh-2026's rows, after [`GRADE-rate2.md`](../receiver-2026/GRADE-rate2.md) was written (so this is **already-seen data**, and the reason for this plan), the qualifying F9P logs defined below show:

- **21 logs**, median lag **176.7 ms**, about 67 ms more than the 110 ms default;
- **11 of 21 (52%)** more than 50 ms later than their own `EKF2_GPS_DELAY`;
- **two groups**: 10 logs between 115 and 148 ms, 11 between 177 and 235 ms, and none between 150 and 175 ms.

[`GRADE-rate2.md`](../receiver-2026/GRADE-rate2.md) (pre-registered, G2 held) found the M9 at 10 Hz on the same releases about 110 ms less late than the F9P at 5 Hz.

We found no published measurement of the F9P's lag on PX4 after the rate change. ArduPilot gives the F9 120 ms and notes "F9 lag not verified yet from flight log" (`AP_GPS_UBLOX.cpp`). The code comments on PX4's rate change give the receiver's rate limits, not its lag. If the figure holds on a sample nobody has seen, the vehicles affected are every F9P L1L2 vehicle on PX4 v1.16 or v1.17, which run a delay setting that is about 70 ms short by default.

## Sample

- `fresh2.py` runs fresh-2026's pipeline unchanged (`fresh_nis.py` 0.1.0 → `fresh.py`, `fresh_mm.py`, `nis.py`, `gps_lag.py`, `receiver.py`, `rate.py`, all at the commits that pre-registered them). Only the draw's seed changes: **20261109** instead of 20261102. The draw stops before any download if it is not called with that seed.
- The draw uses PX4 Flight Review's public logs, as before, and leaves out every log and vehicle of fleet-2026, fleet-health-2026, receiver-2026 **and fresh-2026**.
- At most 1,000 download attempts in 215 minutes, 6 s apart, stopping at the first block (403/444).
- The sealed job first waits until this plan is on `main`.

## Which logs count

A **qualifying F9P log** passed `gps_lag.py`'s gates (a lag was measured), is not simulated, has exactly one GPS receiver, and comes from PX4 v1.16.x or v1.17.x of any build type (development, alpha, beta, rc or release). Its receiver is the u-blox F9P (as PX4 recorded it in the device_id), on a 200 ms grid (`rate.py`), and it is not in moving-base mode (`GPS_UBX_MODE` 0 or missing).

A **qualifying M9 log** meets the same rules with the u-blox M9 on a 100 ms grid.

v1.18 is left out: it moved the delay to `SENS_GPSn_DELAY`, and only 8 such logs turned up in fresh-2026.

## Checks

| | rule | on fresh-2026 (seen) |
|---|---|---|
| **E0** | at least **12** qualifying F9P logs | 21 |
| **P1** | median lag **≥ 150 ms**, and its seeded bootstrap 95% interval lies **above 110 ms** | 176.7 ms |
| **P2** | at least **35%** of qualifying F9P logs are more than 50 ms later than their own setting (`lag_minus_param_ms` > 50; logs without a setting are left out of this share) | 52% |
| **P3** | two groups: at least **25%** of logs at ≤ 150 ms, at least **25%** at ≥ 175 ms, and at most **15%** strictly between | 48% / 0% / 52% |
| **P4** | median(M9) − median(F9P) **≤ −50 ms**, with the 95% interval below 0; scored only with at least **8** qualifying M9 logs | −110 ms (rate2, 12 M9 logs) |

If E0 fails, P1-P4 are not scored. Intervals use a percentile bootstrap with 2,000 resamples and seed 20261109 (`f9p.py`).

**Predictions:** E0, P1 and P4 hold. P2 is less certain, because 52% on 21 logs could easily be 35% on another sample. P3 is the least certain: a gap seen once in 21 logs may be chance.

**Replications** (copied from the pinned code's own output, not new rules): **R1** is mismatch-2026's check M2, re-scored on this sample by `fresh_mm.py`; **R2** is nis-2026's check N1, re-scored by `nis.py`. fresh-2026's own checks (E1, F1-F6) are also recomputed on the new rows and reported as a replication.

## Decisions

- **D1.** If E0, P1 and P2 hold, the result goes out in three places:
  - px4-gps-lag's README states the F9P-at-5-Hz figure from both samples.
  - px4-log-health's checkup adds one information line to qualifying F9P logs. It gives the figure and the parameter to measure, and is not a flag. It ships only after a sealed test.
  - MV2 opens one issue on PX4-Autopilot with the figure, if no existing issue or pull request already covers it.
- **D2.** If P3 holds, the two groups count as replicated. Any field that separates them cleanly in both samples (from the exploratory pass below) becomes the next pre-registered question. If P3 fails, the README says the gap seen in fresh-2026 did not replicate.
- **D3.** If P1 fails, the README says the 178 ms F9P figure came from one sample and did not replicate, and nothing is added to the checkup.

## Exploratory, not predicted

`f9p_extra.py` downloads every passing F9P log of the new sample again (any release, 6 s apart, 45 minutes at most). From each it keeps only the GPS-related parameters (`GPS_*`, `SER_GPS*`, `SENS_GPS*`, `EKF2_GPS_*`), the median satellites used with a 3D fix or better, and the firmware's console messages that mention the GPS. No position is kept. `f9p.py` lists every qualifying F9P log with its group, release, maximum fix type, GPS bus, flight controller, device id and those fields, and counts the groups by each field. Candidate separators we will look at: constellation settings (`GPS_1_GNSS`), RTK fixes, baud rate, and the flight controller. Nothing here is scored.

## Limits

- Flight Review uploads are self-selected and often follow a problem.
- The lag is measured against `vehicle_gps_position.timestamp`, the time PX4 received and parsed the solution. It therefore includes PX4's own configuration and serial transfer, not only the receiver's processing time.
- The grid is read from solutions that reach PX4, so dropped epochs could make 10 Hz look like 5 Hz.
- The release is read from the version string, not from each build's driver code. Forks that keep PX4's version numbers count as PX4.
- Flight Review deletes uploads after 12 months. The per-log rows are published, but the raw logs behind them disappear over time.

## Outputs

`logs.jsonl` (one line per attempt; vehicle ids hashed, no positions), `summary.json`, `mismatch-summary.json`, `nis-summary.json`, `f9p-extra.jsonl`, `f9p-summary.json` and `job-fetched.json`. They will be published in this folder with `GRADE.md`, whatever the outcome.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
