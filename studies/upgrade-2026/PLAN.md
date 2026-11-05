# upgrade-2026: does the same multicopter's GPS lag drop when it moves from PX4 v1.16 to v1.17? (plan)

Pre-registered on 2026-11-05, before any log for this study is listed or downloaded. Code: [`upgrade.py`](upgrade.py) 0.1.0, tests [`test_upgrade.py`](test_upgrade.py). The sealed job waits until this plan and both files are on `main`, checks that its own copies are identical, and only then reads Flight Review's public log list.

## Why

[dynmodel-2026](../dynmodel-2026/GRADE.md) found that public u-blox logs at `GPS_UBX_DYNMODEL` 6 (airborne <1g) lag a median **+46 ms** (33 to 55) more than model-7 logs of the same receiver class. That comparison is between vehicles and is observational. Its exploratory re-score showed that the model is tied to vehicle type and release, and its least-squares re-score was unstable. The [paired check](../dynmodel-2026/GRADE-paired.md) on the two logs a PX4 maintainer attached to PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831) found +104 ms inside one vehicle, but that is one vehicle and one pair of flights.

PX4 itself ran a larger experiment. Up to v1.16, `ROMFS/.../rc.mc_defaults` ran `param set-default GPS_UBX_DYNMODEL 6` for every multicopter. PR #24831 (merged into `main` on 2025-05-27, first released in v1.17) removed that line, so from v1.17 multicopters get the parameter's own default, 7 (<2g). (Checked on 2026-11-05: `rc.mc_defaults` at the `v1.16.0` tag has `param set-default GPS_UBX_DYNMODEL 6`; at `v1.17.0` it sets no `GPS_UBX_DYNMODEL`.) `param set-default` does not store a value, so **a multicopter that never set the parameter by hand changes from model 6 to model 7 when it is upgraded from v1.16 to v1.17**. Comparing the same vehicle's logs before and after the upgrade keeps the airframe, the receiver and usually the pilot fixed.

## Design

**Logs.** From Flight Review's public list (`/dbinfo`), read once: real logs (not SITL, not simulation, not CI) of at least 120 s, with a vehicle id (`vehicle_uuid`), a multicopter `mav_type` (contains "rotor" or "copter", and not VTOL, helicopter, fixed wing, rover, boat), and a v1.16.x or v1.17.x build that is not a development build. No date limit.

**Vehicles.** Only vehicles with eligible logs on both releases. They are visited in a random order (seed 20261113). For each vehicle:

1. its v1.16 logs in a seeded random order, at most 3 downloads, until one **counts**: `gps_lag.py`'s checks pass, the log's own release field is v1.16.x and not a development build, the receiver (most common `vehicle_gps_position.device_id`) is a u-blox on a serial port (device types 0xA5-0xA7, 0xA8 M8, 0xA9 M9, 0xAA F9P, 0xAC M10), and the log has `GPS_UBX_DYNMODEL`;
2. only then its v1.17 logs, the same way, and the receiver must have the **same device type** as the v1.16 log.

A vehicle with one counting log on each side is a **pair**. The job stops at 60 pairs, 400 downloads, 180 minutes, or the end of the list, whichever comes first. Downloads go one at a time, 6 s apart, and stop at once on HTTP 403 or 444. Each log is deleted once measured; no position is read; vehicle ids are published only as `sha256(uuid)[:12]`, the hash every px4-gps-lag study uses.

**Measure.** For each pair, d = lag(v1.16 log) − lag(v1.17 log), with `main`'s `gps_lag.py` (sha256 `3338d743…`, unchanged). **Switched** pairs have model 6 on v1.16 and 7 on v1.17. **Unchanged** pairs have the same model on both. Intervals are percentile bootstraps of the median over vehicles (2,000 resamples, seed 20261114; +1, +2, +3 for the switched, unchanged and not-seen groups).

## Predictions

| | rule | our prior |
|---|---|---|
| **E0** | at least 12 pairs | about even |
| **U1** | median d over all pairs ≥ +20 ms, and the interval's lower end > 0 | likely, if E0 |
| **U2** | at least half of the pairs switched (6 → 7) | likely: in dynmodel-2026, 91% of logs ran their release's default |
| **U3** | median d of switched pairs ≥ +30 ms (scored only with ≥ 8 switched pairs) | likely |
| **U4** | median d of unchanged pairs within ±20 ms (scored only with ≥ 6 unchanged pairs): the upgrade itself, without a model change, moves the lag little | about even |

U2-U4 are scored only if E0 holds. A rule that cannot be scored is reported as "not scored", not as held or failed.

## What we will do with each result

- **D1 (E0, U1 and U3 hold):** report it as the first within-vehicle fleet figure for the u-blox dynamic model, in px4-gps-lag's README and in px4-log-health's dynamic-model note. Offer it, once, in the PR #24831 thread with the offer of a one-sentence addition to `GPS_UBX_DYNMODEL`'s description in `src/drivers/gps/params.yaml`.
- **D2 (E0 holds, U1 or U3 fails):** report that the v1.16 → v1.17 upgrade did not lower the same vehicles' lag as predicted. px4-log-health's note would then be reworded to say the between-vehicle figure was not confirmed within vehicles.
- **D3 (E0 fails):** publish the counts and whatever pairs were found as a case series. No claim either way.
- If U4 fails, the release itself moved the lag. We then report the switched-minus-unchanged difference as exploratory and do not attribute U1 to the model alone.

## Also reported (not graded)

The same figures on the pairs from vehicles that dynmodel-2026 never saw (its `dynmodel-rows.jsonl`), each side's model counts and share of logs more than 50 ms past `EKF2_GPS_DELAY`, the receivers, every download attempt (`rows.jsonl`) and why a log did not count.

## Limits, known in advance

- Two logs per vehicle, flown on different days, maybe with different manoeuvres, wind and satellites. The pairing removes the airframe and receiver, not the flight.
- v1.17 changed more than this default. The GPS driver's measurement rates are the same in v1.16 and v1.17 (PX4 GPSDrivers), but other changes exist; U4 is the check for them.
- Vehicles that set the model by hand do not switch; vehicles whose owners changed the receiver between releases are dropped (or kept, if only the port changed and the device type did not).
- Flight Review uploads are self-selected, and a vehicle id can be shared by boards that were reflashed or cloned.
- The lag is measured against `vehicle_gps_position.timestamp`, so it includes PX4's parsing and serial transfer.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
