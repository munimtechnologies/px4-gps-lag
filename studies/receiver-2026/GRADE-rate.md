# rate-2026 graded against PLAN-rate.md

Plan: [`PLAN-rate.md`](PLAN-rate.md), committed in `5e4b8ac` before any log for this check was downloaded. Job `px4-gps-lag-rate-v1`, 2026-11-01 04:28-05:19 UTC: unit tests passed, then `rate.py` 0.1.0 re-downloaded every log of the two earlier samples that has a published lag. Data: [`rate/logs.jsonl`](rate/logs.jsonl), [`rate/summary.json`](rate/summary.json), [`rate/job-fetched.json`](rate/job-fetched.json).

All 376 logs downloaded, none missing, no block, all inside the budget. The lags scored are the ones published before this plan. Only the measurement grid is new.

## Checks

| Check | Rule | Result | |
|---|---|---|---|
| E0 | ≥50% of serial u-blox logs get a grid | 101 of 173 (58.4%) | **holds** |
| E1 | M8, M9, F9P each ≥10 gridded | 12, 41, 20 | **holds** |
| Q1 | each class ≥70% on the v1.15.4 driver interval | M8 12/12 (100%), M9 19/41 (46%), F9P 6/20 (30%) | **fails** |
| Q2 | M9 − other serial u-blox on 125 ms ≤ −20 ms, interval < 0 | −53.3 ms (−105.6 to −18.7), n 19 vs 10 | **holds** |
| Q3 | undetected u-blox, 200 ms − 125 ms ≥ +20 ms | 0 logs on 200 ms, 8 on 125 ms | not scored |
| Q4 | F9P, 100 ms − other grids ≥ +20 ms, interval > 0 | +5.3 ms (−59.3 to +47.2), n 5 vs 15 | **fails** |

Our expectations were E0, Q1 and Q2 holding. E0 and Q2 held. Q1 failed.

## Decisions, as written

- **D1 does not fire.** Q1 failed, so px4-log-health gets no rate line from this study. The receivers off the expected interval were M9 logs on a 100 ms grid (22 of 41) and F9P logs on a 200 ms grid (13 of 20) or a 125 ms grid (1 of 20 with `GPS_UBX_MODE` 0).
- **D2: the M9's lower lag is not explained by its measurement rate.** E1 and Q2 hold: on the same 125 ms grid, M9 logs were 53 ms less late than the other serial u-blox logs. The README says so.
- **D3:** PX4 only. Nothing here is about ArduPilot.

## Why Q1 failed: the plan read the wrong driver version

The plan took the expected intervals from PX4-GPSDrivers at PX4 v1.15.4 (`ad769ff`): F9P 100 ms, M9 125 ms. The per-log rows split cleanly by PX4 release, and the driver changed between v1.15 and v1.16:

- PX4-GPSDrivers `bbdd576` (2025-01-05, "ublox update F9P output rates") replaced `rate_meas = F9P ? 100 : 125` with `int rate_meas = 100; // 10Hz` plus `u_blox9_F9P_L1L2: 200 // 5Hz` and `u_blox9_F9P_L1L5: 143 // 7Hz`. Its comments explain the F9P change: with four constellations, an F9P L1L2 on firmware 1.50+ manages 7 Hz without RTK and 5 Hz with it.
- PX4 v1.16.0 and v1.16.1 ship that driver (`4cea5de`), and PX4 v1.17.0 ships `0b96958`, which has the same rates.

So since v1.16 PX4 asks an M9 for 10 Hz and an F9P L1L2 for 5 Hz. Before, it asked for 8 Hz and 10 Hz. The rule we wrote was right for v1.12-v1.15 and wrong for v1.16-v1.17.

**Exploratory re-score by release** (made after seeing the data, so it decides nothing; v1.15 development builds, versions before v1.12 or from v1.18 on, and forks are left out because their driver can't be told from the version):

| Class | Old driver (v1.12-v1.15) | New driver (v1.16-v1.17) | All scored |
|---|---|---|---|
| M8 (200 ms in both) | 3/3 | 8/8 | 11/11 |
| M9 (125 → 100 ms) | 11/11 on 125 ms | 22/23 on 100 ms | 33/34 |
| F9P (100 → 200 ms) | 4/5 on 100 ms | 9/9 on 200 ms | 13/14 |

Receivers nearly always ran at the rate their release asked for. Three F9P logs had no grid and were logged every 143 ms. Two are v1.17 builds, which fits an F9P L1L5 at 143 ms (7 Hz). The third is a v1.14.3 build, and the old driver never asks for 143 ms. `rate.py` doesn't try a 143 ms grid.

That corrected rule is now pre-registered on fresh logs: [`PLAN-rate2.md`](PLAN-rate2.md) (rate2-2026). It is scored on the fresh-2026 sample, which had not been downloaded when that plan was committed.

## What this says about the M9 gap (exploratory)

The swap is a natural experiment. On the old driver the M9 measured more slowly than the F9P (8 vs 10 Hz). On the new one it measures faster (10 vs 5 Hz). In both, it was much less late:

| | M9 | F9P | M9 − F9P |
|---|---|---|---|
| old driver: M9 on 125 ms, F9P on 100 ms | 74.5 ms (n 11) | 153.9 ms (n 4) | −79 ms |
| new driver: M9 on 100 ms, F9P on 200 ms | 64.5 ms (n 22) | 179.0 ms (n 9) | −115 ms |

These are medians of lags published before this study. The groups are small and no interval was computed, so they are descriptive only. Over all serial u-blox logs with a grid, Spearman's ρ between grid interval and lag was 0.39. That pools the classes, so it can't tell rate apart from receiver model. Within the M9, the 10 Hz logs had a median lag of 64.5 ms and the 8 Hz logs 77.3 ms, 13 ms apart. G2 of rate2-2026 tests the new-driver comparison on fresh logs.

## Other exploratory notes

- In 16 of the 23 F9P logs without a grid, consecutive receiver times were typically 500 ms apart. That fits PX4 v1.12-v1.14 logging GPS every 500 ms, which the plan expected to hide the grid.
- Of the 11 NMEA logs with no grid, 7 stepped 1000 ms (1 Hz). Those 7 had a median lag of 238.5 ms, the highest of any group here.
- Six MAVLink-fed GPS logs (`other:mavlink/0xAF`) had a median lag just below zero (−8.2 ms). The lag method probably measures something else for them. We have not looked into it.

## Limits

- The sample is the earlier studies' passed logs, so it shares their biases (self-selected uploads, ≤80 MB, one log per vehicle, mostly the default `EKF2_GPS_DELAY`).
- The grid shows the rate of the solutions that reach PX4, not the receiver's internal rate.
- Driver eras come from version strings. A custom build can carry any driver.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
