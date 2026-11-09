# xcorr-2026: gnss_latency.py against px4-gps-lag, graded

`tools/gnss_latency.py` is a draft tool in the style of PX4's `Tools/dronecan_calibration/`
latency scripts. It measures how far GNSS velocity lags the IMU by cross-correlating the two
after an identical zero-phase band-pass (0.1-2 Hz). px4-gps-lag measures the same lag by a
different method (a least-squares fit per GPS sample pair). The checks V0-V4 were fixed in
`CRITERIA.md` before the sealed job `gnss-latency-validate-v1` ran (2026-11-09 10:25 UTC).
This is a **method-agreement check on logs px4-gps-lag had already measured, not a new result**.

**All five checks held.**

| check | criterion | result |
|---|---|---|
| V0 | synthetic tests recover known delays (0, 40, 150, 210 ms) within 3 ms | held: 19 tests OK |
| V1 | interior correlation peak with r >= 0.5 on each of the 5 logs | held: r = 0.979 to 0.999 |
| V2 | within 20 ms of px4-gps-lag on at least 4 of 5 logs | held: 5 of 5, largest gap 6.4 ms |
| V3 | on the 3 PX4 main logs, residual from timestamp_sample agrees with total - applied within 10 ms | held: gaps 1.5, 2.5 and 0.0 ms |
| V4 | a PDF report for every log that passes V1 | held: 5 PDFs |

| log | bus | px4-gps-lag (ms) | xcorr (ms) | diff | r | applied by PX4 (ms) | residual (ms) |
|---|---|---|---|---|---|---|---|
| log_5 (PR #24831, model 7) | serial | 110.5 | 104.2 | -6.3 | 0.998 | 160.0 (EKF2_GPS_DELAY) | -55.8 |
| log_8 (PR #24831, model 6) | serial | 214.2 | 217.0 | +2.8 | 0.993 | 160.0 (EKF2_GPS_DELAY) | +57.0 |
| 5f1584c9 (PX4 main) | DroneCAN | 166.3 | 166.1 | -0.2 | 0.999 | 85.7 (sample stamps) | +80.5 |
| 5548f136 (PX4 main) | DroneCAN | 110.3 | 103.9 | -6.4 | 0.979 | 98.0 (sample stamps) | +5.9 |
| 53a8335a (PX4 main) | serial u-blox | 189.5 | 183.8 | -5.7 | 0.995 | 110.0 (sample stamps) | +73.8 |

Full rows: `validation.json`; the job's own table: `validation.md`.

## What this shows, and its limits

- Two independent methods give the same GNSS lag on real logs to within 6.4 ms. Cross-correlation
  read lower on 4 of the 5 logs (mean -3.2 ms), so any systematic gap between them is small but
  may not be zero.
- Both methods measure total lag from receiver measurement to arrival at the flight controller,
  including any smoothing inside the receiver. Neither can tell a pure delay from a filter.
- Five logs, all already used to build px4-gps-lag; this checks the new tool, not the fleet.
- **Correction to CRITERIA.md:** its table lists 110 ms "applied" for the two PR #24831 logs.
  Those logs set `EKF2_GPS_DELAY` = 160 ms, as px4-log-health's own report on them says
  (`studies/dynmodel/report-0.3.6.md`: "this vehicle's EKF2_GPS_DELAY is 160 ms"). The tool read
  160 from the log. No check used that column (V3 covers only the PX4 main logs), so the grade
  does not change.

## Next

The tool may be offered to PX4 (`Tools/`) only after MV2's docs pull request
(PX4/PX4-Autopilot#29671) is reviewed, and following PX4's CONTRIBUTING rules on tests and AI
disclosure.

By MV2 of Munim, Inc.; made with AI agents (graded 2026-11-09). Text CC BY 4.0, code Apache-2.0.
