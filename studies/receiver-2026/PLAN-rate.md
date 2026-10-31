# rate-2026: does the GPS measurement rate explain the receiver gap? (pre-registration)

Written and committed before any log for this check was downloaded. `rate.py` (0.1.0) and `test_rate.py` are committed with this plan, and the job that runs them waits until this file is on main.

## Why

On PX4 public logs, u-blox M9 receivers showed about half the GPS lag of F9P receivers. That held on two samples with no vehicle in common: receiver-2026 (71 ms vs 143 ms) and receiver-confirm (76 ms vs 144 ms, interval −101 to −48 ms). The M8 sat with the F9P (147 ms, n 15; 151 ms, n 7). Both are exploratory, because each study's enough-data check failed ([`GRADE.md`](GRADE.md), [`GRADE-confirm.md`](GRADE-confirm.md)).

The obvious explanation is the measurement rate. PX4's u-blox driver sets a different measurement interval for each model:

- PX4-GPSDrivers `src/ubx.cpp`, `configureDevice()` (protocol 27 and newer). At ad769ff (PX4 v1.15.4): `rate_meas = (_board == Board::u_blox9_F9P) ? 100 : 125;` in normal mode, and `rate_meas = 125; //8Hz for heading.` otherwise. At f512678 (PX4 v1.12.3): `const int rate_meas = (_board == Board::u_blox9_F9P) ? 100 : 125;`.
- `configureDevicePreV27()`, the CFG-RATE path older receivers such as the M8 take: `measRate = UBX_TX_CFG_RATE_MEASINTERVAL`, which `src/ubx.h` defines as `200 /**< 200ms for 5Hz (F9* boards use 10Hz) */`.
- Both paths use time reference 0 (UTC), so measurement epochs sit on a UTC grid.

So the M8 should run at 200 ms, the M9 (and M10) at 125 ms, and the F9P at 100 ms, or 125 ms in moving-base mode on v1.15+. The rate alone does not order the lags: the fastest-configured receiver (F9P) and the slowest (M8) lag alike. But nobody has read the actual rate from flight logs, and a receiver may not run at the rate PX4 asks for.

## What is new: reading the rate from the log

`vehicle_gps_position.time_utc_usec` is the receiver's own UTC time of each solution. If epochs are aligned to UTC, the fraction of the second in those times sits on the measurement grid: 0, 125, 250, … ms for an 8 Hz receiver. `rate.py` takes the distinct non-zero times and tries 250, 200, 125, 100 and 50 ms grids, coarsest first. It accepts a grid when:

- at least 90% of the times are within 5 ms of a grid point,
- at least half the grid's slots in a second are seen, and
- at least 50% of consecutive times are exactly one step apart.

The last rule matters because PX4 v1.12-v1.14 log `vehicle_gps_position` every 500 ms (`logged_topics.cpp`, `add_topic("vehicle_gps_position", 500)`). In such a log an 8 or 10 Hz receiver shows only every 4th to 6th epoch, which could pass for a slower grid. Those logs get no grid. A log with fewer than 50 distinct times also gets none. The unit tests check this on synthetic receivers at 100, 125, 200, 500 and 1000 ms, on throttled logs and on times off any grid.

## Sample: lags that are already published

Every log that already has a published lag and a receiver class: receiver-2026's passed logs (`logs.jsonl`, sha256 `12202a3e…`, the file receiver-confirm read) and receiver-confirm's re-read logs (`confirm/logs.jsonl`). That is about 376 logs, one per vehicle. Simulated GPS is left out. Each log is downloaded again, `vehicle_gps_position` and `GPS_UBX_MODE` are read, and the log is deleted.

**The lags scored are the published ones.** Only the measurement grid is new, so no lag can be tuned to this plan. Downloads follow the same rules as before: 6 s apart, stop at once on HTTP 403/444, a 150-minute budget, no position read, vehicle ids only as a hash. Flight Review deletes uploads after 12 months, and the oldest of these logs date from October 2025. Logs already deleted count as "missing" and are reported.

## Checks

Intervals are receiver.py's seeded bootstrap 95% intervals of the difference of medians (2,000 resamples, seed 20261101). "Serial u-blox" means the classes M8, M9, F9P, M10 (0xAC) and "u-blox, model not detected" (0xA5).

- **E0 (the method reads a rate):** at least 50% of the downloaded serial u-blox logs get a grid. Most v1.12-v1.14 logs can't, so this checks that enough logs are v1.15+ or log GPS at full rate.
- **E1 (enough data):** M8, M9 and F9P each have at least 10 logs with a grid. If E1 fails, Q1 and D2 are not scored, and everything else is exploratory.
- **Q1 (receivers run at the driver's rate):** in each of M8, M9 and F9P, at least 70% of logs with a grid sit on the driver's interval: M8 200 ms, M9 125 ms, F9P 100 ms (or 125 ms when `GPS_UBX_MODE` is not 0).
- **Q2 (the rate is not the M9 story):** among serial u-blox logs on a 125 ms grid, median(M9) − median(all others on 125 ms) ≤ −20 ms, with the interval below 0. Scored if both groups have at least 8 logs. If the M9 is still much less late than other receivers measuring at the same rate, the rate doesn't explain its lead.
- **Q3 (the undetected u-blox class splits by path):** among "model not detected" (0xA5) logs, median(200 ms grid) − median(125 ms grid) ≥ +20 ms, with the interval above 0. Scored if both groups have at least 8 logs. The 200 ms ones took the older CFG-RATE path, as the M8 does. This tests whether the old path goes with the higher lag.
- **Q4 (does 10 Hz cost an F9P latency?):** among F9P logs, median(100 ms grid) − median(any other grid) ≥ +20 ms, with the interval above 0. Scored if both groups have at least 5 logs. PX4-GPSDrivers #199 (merged 2026-02-09) moved some F9P configurations to 5 Hz (its commit "ubx: F9P L1/L5 5Hz output rate"), and the driver comments note that more satellites limit a receiver's rate. We expect too few F9P logs off 100 ms for this to be scored. We give it about even odds if it is.

Our expectations, written down before any data: E0 holds (60-70%), Q1 holds, and Q2 holds (the M9 stays lower at the same rate). For Q3 and Q4 we have no confident direction.

## Decisions written in advance

- **D1:** if E0 and Q1 hold, px4-log-health's checkup gets an information line in its GPS section: "GPS measurement rate: N Hz (read from the receiver's time stamps)". It is not a flag. It goes out only after a sealed test on real logs. If Q1 fails, the grade lists which receivers run off the driver's rate, and no line is added.
- **D2:** if E1 and Q2 hold, the px4-gps-lag README says the M9's lower lag is not explained by its measurement rate. If Q2 fails, it says the rate may explain it. If Q2 is unscored, it says so.
- **D3:** PX4 measurements only. They say nothing about ArduPilot.
- Whatever the outcome, `rate/logs.jsonl`, `rate/summary.json`, `rate/job-fetched.json` and `GRADE-rate.md` are published, including any check that fails.

## Exploratory (not predicted)

- Grids by receiver class (DroneCAN and NMEA included), and the lag by class and grid.
- The share of logs with a grid by PX4 release.
- The most common step between receiver times for logs with no grid. For example, 1000 ms would point to 1 Hz NMEA receivers.
- `GPS_UBX_MODE` by class, and Spearman's ρ between grid and lag over all serial u-blox logs with a grid.

## Limits

- The grid shows the rate of the solutions that reach PX4, not the receiver's internal rate.
- A log in which PX4 kept only every other epoch would look like a receiver at half the rate. With the v1.15+ default of one sample per 100 ms, that should be rare for receivers at 5-8 Hz. A 10 Hz receiver is right at the logging limit, so a few may read as 5 Hz.
- Receivers whose times are not aligned to UTC (some NMEA or DroneCAN modules) get no grid. That limits the class, not the method.
- The sample is the earlier studies' passed logs, so it shares their biases: self-selected uploads, no logs over 80 MB, one log per vehicle, mostly the default `EKF2_GPS_DELAY`.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
