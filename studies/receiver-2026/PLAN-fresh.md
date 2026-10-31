# fresh-2026: the receiver gap on a fresh sample (pre-registration)

Written and committed before any log for this study was downloaded. `fresh.py` (0.1.0) and `test_fresh.py` are committed with this plan. The job that runs them waits until this file is on main, and it will be filed only after the rate-2026 job has finished, so that two studies never download from Flight Review at the same time.

## Why

Two samples with no vehicle in common saw the same thing on PX4. Vehicles whose GPS PX4 detected as a u-blox M9 were about 70 ms less late than those with an F9P or an M8:

- receiver-2026: M9 71.3 ms (25 vehicles), F9P 142.6 (16), M8 146.6 (15). See [`GRADE.md`](GRADE.md).
- receiver-confirm: M9 76.2 (32), F9P 143.5 (27), M8 150.9 (7); M9 − F9P −67.3 ms, interval −101.0 to −48.4. See [`GRADE-confirm.md`](GRADE-confirm.md).

Both failed their own enough-data check (E1), each time because too few M8 logs turned up, so by their plans the gap is still exploratory, and M9 vs M8 has never been tested as planned. ArduPilot's u-blox driver gives the M8, M9 and F9 the same 120 ms lag, noting that the F9 value is "not verified yet from flight log" (`libraries/AP_GPS/AP_GPS_UBLOX.cpp`, `get_lag`). PX4 uses one `EKF2_GPS_DELAY`, 110 ms by default.

This study draws a new sample big enough for the M8. It also tests the NMEA hint (pooled 206.5 ms over 29 vehicles, never predicted) on logs that did not suggest it.

## Data

- PX4 Flight Review public logs (CC BY 4.0), with fleet.py 0.1.1's rules: real (non-simulated) logs of at least 240 s, from 2025-10-01 on, at most 80 MB.
- New seed **20261102**. One log per vehicle, vehicles in seeded random order. **Every log and every vehicle drawn by fleet-2026 (`studies/fleet-2026/v1/logs.jsonl`), px4-log-health's fleet-health-2026 (`studies/fleet-health-2026/logs.jsonl`) or receiver-2026 (`studies/receiver-2026/logs.jsonl`, all 537 attempts) is left out.** receiver-confirm and rate-2026 only re-read those same vehicles, so nothing here has been seen before.
- Up to 1,000 attempts in a 215-minute budget, 6 s between downloads, stop at once on HTTP 403/444. Each log is deleted once read. No position is read. Vehicle ids are published only as a hash.
- Per log, all unchanged: lag from `gps_lag.py` 0.1.0 with its gates (only logs that pass count), the receiver class from `receiver.py` 0.1.0, and the measurement grid from `rate.py` 0.1.0.

**Sizing E1 from the right sample.** receiver-2026 drew from the same population (logs from 2025-10 on) and got 163 passing logs from 537 attempts in 130 minutes: M8 9.2%, M9 15.3%, F9P 9.8% and NMEA 8.0% of passing logs. At that pace, 215 minutes gives about 890 attempts and about 270 passing logs: about 25 M8, 41 M9, 26 F9P and 22 NMEA. If only 700 attempts are made, the expected M8 count is about 20. Flight Review removes uploads after 12 months, so the oldest logs are disappearing; missing logs fail fast and cost little time.

## Checks

Intervals are seeded bootstrap 95% intervals of the difference of medians (2,000 resamples, `receiver.py`'s `boot_diff`). A comparison is made only when each side has at least 15 passing logs (NMEA: 12).

- **E1 (enough data):** ubx_m8, ubx_m9 and ubx_f9p each have at least 15 passing logs. If E1 fails, every result below is reported as exploratory only.
- **F1 (M9 vs M8):** median(M9) − median(M8) ≤ −20 ms, and the interval lies below 0.
- **F2 (M9 vs F9P):** median(M9) − median(F9P) ≤ −20 ms, and the interval lies below 0.
- **F3 (ArduPilot's F9 = M8 assumption):** the F9P and M8 medians are within 30 ms of each other. The interval is reported.
- **F4 (NMEA):** median(NMEA) − median(all serial u-blox: ubx_m8, ubx_m9, ubx_f9p, ubx_10, ubx_generic) ≥ +20 ms, and the interval lies above 0.
- **F5 (a per-receiver default would help, replication):** `receiver.py`'s P4 rule. On classes with at least 15 passing logs (uavcan included), each vehicle's leave-one-out class median puts at least 5 percentage points more vehicles within 50 ms of their lag than 110 ms does.
- **F6 (receivers run at the driver's rate, fresh sample):** `rate.py`'s Q1 rule on passing logs. In each of M8, M9 and F9P (each with at least 10 gridded logs), at least 70% of gridded logs sit on the interval PX4's driver asks for (M8 200 ms, M9 125 ms, F9P 100 ms, or 125 ms when `GPS_UBX_MODE` is not 0).
- **R2 (reported, not predicted):** `rate.py`'s Q2 on passing logs, i.e. whether M9 logs are still at least 20 ms less late than other serial u-blox logs on the same 125 ms grid. rate-2026 asks this on the earlier logs and its answer was not known when this plan was written. Here it is reported either way.

## Decisions written in advance

- **D1:** if E1, F1 and F2 hold, the M9 gap counts as confirmed. The px4-gps-lag README drops "exploratory" for M9 vs M8 and F9P, and px4-log-health's checkup gets a line in its GPS delay section: "receivers of this class on public logs: median X ms (n vehicles)", with X and n from this study. Measuring your own vehicle stays the advice.
- **D2:** if E1 holds and F1 or F2 fails, the write-up says plainly that the gap did not hold on fresh data. The README's receiver table gets this sample as a third column and stays exploratory.
- **D3:** if F4 holds, the README notes that NMEA receivers ran later than serial u-blox ones on public PX4 logs. Nothing changes in the checkup.
- Every check is PX4-only. The measured lag runs from the measurement to the flight controller's timestamp, so it includes PX4's configuration of each model (rate, baud, messages), not only the chip. None of this says what ArduPilot's lag is on ArduPilot vehicles.
- Whatever the outcome, `fresh/logs.jsonl`, `fresh/summary.json`, `fresh/job-fetched.json` and a `GRADE-fresh.md` are published, including every check that fails. If the job is stopped from outside (exit 143 or similar), its partial rows are not scored: it is re-run unchanged from the start.

## Exploratory (not predicted)

`receiver.py`'s and `rate.py`'s own breakdowns: lag by class × PX4 release, class × fix type, class × grid, `GPS_UBX_MODE` by class, `EKF2_GPS_DELAY` by class, and the rank correlation of grid and lag.

## Limits

- Flight Review uploads are self-selected, often after a problem.
- ubx_generic mixes M10 receivers with undetected u-blox units, and uavcan modules are not identified.
- One log per vehicle. Vehicles of one class may share other traits, such as the frame, the flight controller or the PX4 release.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
