# gnss-2026: can px4-gps-lag read real PX4 main logs? (plan)

Pre-registered on 2026-11-08, before any log was read. A sealed job checks that this file on `main` matches its own copy before it reads Flight Review's list.

## Why

[PX4 PR #24399](https://github.com/PX4/PX4-Autopilot/pull/24399) (on PX4 main since 2026-09-29) renamed the GPS topics and messages to GNSS. Logs from PX4 main have no `vehicle_gps_position`. They log `vehicle_gnss` (every 100 ms by default, `src/modules/logger/logged_topics.cpp`), which carries:

- a top-level `timestamp_sample`, "measurement time, delay corrected" (`msg/VehicleGnss.msg`);
- the selected receiver's `sensor_gnss` sample nested as `receiver`, which pyulog names `receiver.<field>`;
- new field names in that sample (`msg/SensorGnss.msg`): the velocity is `vel_north` / `vel_east` / `vel_down`, no longer `vel_n_m_s` / `vel_e_m_s` / `vel_d_m_s`. `fix_type`, `vel_ned_valid` and `device_id` keep their names.

`gps_lag.py` 0.1.0 reads only `vehicle_gps_position`, so it can't measure any PX4 main log. px4-log-health's checkup says so on those logs instead of giving a verdict.

**0.2.0** adds `gnss_as_gps()`. When a log has no `vehicle_gps_position` but has `vehicle_gnss`, it takes the columns `read_log` needs from `vehicle_gnss`: `receiver.timestamp` (the receiver's own stamp, as `vehicle_gps_position.timestamp` was), `receiver.vel_north`, `receiver.vel_east`, `receiver.fix_type`, `receiver.vel_ned_valid`, `timestamp_sample` and `receiver.device_id`. Each has a fallback name (see `GNSS_COLUMNS`). Logs with `vehicle_gps_position` are read exactly as before. The fit, the gates and the output are unchanged. `test_gps_lag_gnss.py` checks this on the synthetic flights of `test_gps_lag.py`, written out as the topics pyulog would return. The same flight gives identical arrays and an identical lag from either topic.

Every field name above comes from PX4's message files. None has been seen in a real public log yet. This study reads real ones.

## What runs

`gnss_logs.py` 0.1.0, in a sealed job, after `test_gps_lag.py` (unchanged) and the new `test_gps_lag_gnss.py` and `test_gnss_logs.py` pass on gps_lag.py 0.2.0. The job builds 0.2.0 from `main`'s 0.1.0 with five exact text edits (`patch_gps_lag.py`).

1. **List.** Flight Review's public list, read once. A log is a candidate if it is not simulation or CI, has a log id, is dated 2026-09-29 or later, is at least 60 s long, and its release is v1.18 or newer or can't be read.
2. **Order.** Development builds first, then pre-releases, unknown releases and releases. Within each, newest first, then by log id. One log per vehicle (the first in that order).
3. **Head.** For each candidate, stream the log and read only its definitions section (message formats and initial parameters). A **main log** is one whose formats include `vehicle_gnss`. For any other log, close the connection.
4. **Read.** For a main log, download the rest (at most 150 MB) to a temporary file and record:
   - the `vehicle_gnss` field names (names only), the column `gnss_as_gps` takes for each of the seven, and the number of instances;
   - median `receiver.timestamp − timestamp_sample` (the delay PX4 applied), median `timestamp − receiver.timestamp` (when the sensors module republished the sample), the share of samples marked `usable`, and the receiver's device type;
   - the GNSS-related initial parameters (`SENS_GNSS*`, `GPS_*`, `EKF2_GPS*`/`EKF2_GNSS*`);
   - `gps_lag.measure(gps_lag.read_log(log))`: lag, standard error, pairs, gates.

   No position is written out, and the file is deleted after it is read.
5. **Limits.** At most 300 requests and 30 main logs, 120 minutes, 6 s between requests. The pass stops at the first block (HTTP 403/429/444) or after five errors in a row.

## Predictions

| | prediction | our prior |
|---|---|---|
| **P1** | at least 5 main logs, from at least 3 vehicles, are found | 55% |
| **P2** | in every main log read, all seven columns come from their first-choice `vehicle_gnss` field (`receiver.timestamp`, `receiver.vel_north`, `receiver.vel_east`, `receiver.fix_type`, `receiver.vel_ned_valid`, `timestamp_sample`, `receiver.device_id`) | 80% |
| **P3** | in at least 90% of main logs read that have a `SENS_GNSS0_DELAY` or `SENS_GNSS1_DELAY`, the applied delay (median `receiver.timestamp − timestamp_sample`) is within 1 ms of one of them | 70% |
| **P4** | gps_lag.py 0.2.0 passes its quality gates on at least 3 main logs | 45% |
| **P5** | if at least 5 main logs pass: the median of (measured lag − applied delay) is within ±50 ms | 65% |

P2 and P3 test whether 0.2.0 reads what PX4 main writes. P4 and P5 test whether the measurement carries over. P5 isn't graded if fewer than 5 logs pass.

## What follows

- **P2 holds:** release px4-gps-lag 0.2.0, then px4-log-health checkup 0.3.7 pinned to it, so the checkup gives a GPS delay verdict on PX4 main logs.
- **P2 fails:** fix the column map from the field names recorded, re-test, then release. No release reads a name that no real log has.
- **P3 fails:** report how PX4 main's applied delay differs from its parameters. The checkup's v1.18+ path (`applied_delay`) reads the same difference, so it would need the same look.
- **P1 fails** (too few public main logs): release 0.2.0 on P2's evidence if any main log was read, and say how few there were.

Everything is reported, whichever way it goes: rows in `gnss-rows.jsonl`, scores in `gnss-summary.json`, and a grade in `GRADE.md`.

## Limits known in advance

- Public PX4 main logs are mostly developers' test flights and bench runs. They aren't the fleet that will run the next release.
- Field names can change again before PX4's next release. 0.2.0 reads the names PX4 main had on 2026-11-08.
- Flight Review keeps uploads for 12 months.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
