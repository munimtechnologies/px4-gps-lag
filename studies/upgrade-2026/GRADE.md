# upgrade-2026: grade

Graded on 2026-11-06 against [`PLAN.md`](PLAN.md), which was committed on 2026-11-05 before any log was listed. The sealed job `px4-gps-lag-upgrade-v1` found the plan on `main` (sha256 `ff32458d…`). It checked that its `upgrade.py` 0.1.0 and `test_upgrade.py` were `main`'s copies and that `gps_lag.py` was the pinned one (`3338d743…`), and it ran the unit tests (all passed). Only then did it read Flight Review's public list. File hashes are in [`v1/job-fetched.json`](v1/job-fetched.json). Every download attempt is in [`v1/rows.jsonl`](v1/rows.jsonl), the pairs are in [`v1/pairs.jsonl`](v1/pairs.jsonl), and the scores are in [`v1/summary.json`](v1/summary.json). Vehicle ids are `sha256(uuid)[:12]`, and no position was read.

## Result: E0 failed, so rule D3 applies. A case series, no claim

**10 vehicles gave a pair. The plan needed 12.** U1-U4 are therefore not scored, and nothing is concluded either way. Below is what was found, as the plan's D3 says.

| | |
|---|---|
| log entries in the public list | 486,672 |
| eligible (real multicopter, ≥ 120 s, vehicle id, v1.16/v1.17, not a development build) | 17,942 logs, 3,192 vehicles |
| vehicles with eligible logs on **both** releases | **139** (2,080 only on v1.16, 973 only on v1.17) |
| vehicles visited | all 139 (the job stopped at "list exhausted", not at a limit) |
| downloads | 357 in 49 minutes, one at a time, 6 s apart; never blocked |
| pairs | **10** |

Why the 347 other attempts did not count:

| reason | logs |
|---|---|
| counted | 37 (10 pairs; 17 vehicles had a counting v1.16 log but no counting v1.17 log within 3 tries) |
| `gps_lag.py`: the IMU explains too little of the GPS velocity change | 103 |
| no `vehicle_gps_position` in the log | 84 |
| larger than the 80 MB download limit | 35 |
| GPS not a serial u-blox receiver | 33 |
| too few in-flight GPS pairs | 32 |
| too little manoeuvring | 27 |
| the v1.17 log's receiver had a different device type | 4 |
| no `sensor_combined` / no `vehicle_attitude` | 1 / 1 |

Only 37 of the 357 attempts (10%) counted, and with at most 3 tries a side, few vehicles got a counting log on both sides. The plan's prior on E0 was "about even", which was too optimistic.

## The 10 pairs

d = lag on v1.16 − lag on v1.17. A positive d means the GPS was less late after the upgrade.

| vehicle | receiver | board | v1.16 log | model | lag | v1.17 log | model | lag | **d** |
|---|---|---|---|---|---|---|---|---|---|
| `2d366e54b1d5` | M8 | FMU-v6C | 2026-05-13, v1.16.2 | 6 | 68.8 | 2026-08-13, v1.17.0 | 7 | 95.6 | **−26.8** |
| `914cff99ec31` | M8 | FMU-v5 | 2026-05-18, v1.16.2 | 6 | 235.4 | 2026-08-13, v1.17.0 | 7 | 180.6 | **+54.8** |
| `6cdebe79d7d8` | M8 | FMU-v5 | 2026-05-18, v1.16.2 | 6 | 195.0 | 2026-08-13, v1.17.0 | 7 | 97.4 | **+97.6** |
| `3e0206eff5df` | M9 | FMU-v5 | 2025-12-19, v1.16.0 | 6 | 128.9 | 2026-06-04, v1.17.0 | 7 | 19.8 | **+109.1** |
| `0865d922e4e9` | F9P | CUAV X7 Pro (octo) | 2025-10-01, v1.16.0 | 6 | 201.6 | 2026-08-19, v1.17.0 alpha | **6** | 182.3 | **+19.3** |
| `182746427322` | M9 | FMU-v5 | 2026-04-28, v1.16.0 | 6 | 86.6 | 2026-05-16, v1.17.0 alpha | 7 | 79.4 | **+7.2** |
| `72094dd79c2e` | F9P | CUAV X7 Pro (octo) | 2025-12-09, v1.16.0 | 6 | 236.4 | 2025-11-27, v1.17.0 alpha | 7 | 98.5 | **+137.9** |
| `49a2804b6f62` | M8 | FMU-v6C | 2026-05-18, v1.16.2 | 6 | 194.4 | 2026-08-13, v1.17.0 | 7 | −0.5 | **+194.9** |
| `81df89e1cc22` | M8 | FMU-v5 | 2026-05-13, v1.16.2 | 6 | 189.7 | 2026-08-07, v1.17.0 | 7 | 115.3 | **+74.4** |
| `07f813c57117` | M8 | NXP MR-Tropic | 2025-05-20, v1.16.0 rc | 6 | 194.7 | 2025-11-18, v1.17.0 alpha | 7 | 99.8 | **+94.9** |

All 20 logs had `EKF2_GPS_DELAY` 110 ms. Lags are in ms.

**Descriptive figures (not graded, because E0 failed):**

- All 10 vehicles ran model 6 on v1.16. On v1.17, 9 ran model 7 (switched) and 1 kept 6.
- Median d over all 10 pairs: **+84.6 ms** (bootstrap 19.3 to 116.4). Over the 9 switched pairs: **+94.9 ms** (7.2 to 137.9). The one unchanged pair: +19.3 ms.
- 9 of the 10 differences were positive.
- Median lag: **194.6 ms on v1.16 and 98.0 ms on v1.17**. Logs more than 50 ms past their 110 ms setting: 7 of 10 on v1.16, 2 of 10 on v1.17.
- The 6 pairs from vehicles that dynmodel-2026 never saw: +86.0 ms (13.2 to 123.5).

These point the same way as the fleet figure (+46 ms) and the PR #24831 vehicle (+104 ms). By the plan's own rule, 10 pairs are not enough to claim it.

## Notes on single pairs

- **`49a2804b6f62`'s v1.17 lag is −0.5 ms** (fit R² 0.65). A GPS fix can't lead the IMU, so this figure is probably a poor fit that `gps_lag.py`'s checks did not catch. It was scored as measured, as the plan says. Without this pair, the switched median is about +85 ms (8 pairs).
- **`72094dd79c2e`'s v1.17 log is dated 12 days before its v1.16 log**, so this owner went back from a v1.17 alpha to v1.16.0. The model follows the firmware either way. The plan did not require the v1.17 log to be the later one.
- **`0865d922e4e9` kept model 6 on a v1.17 alpha build.** Either it was set by hand or that build predates the change. Its v1.16 log also ran `GPS_UBX_MODE` 1, and its v1.17 log ran 0.
- **Shared operators are likely.** Five pairs (`2d366e54b1d5`, `914cff99ec31`, `6cdebe79d7d8`, `49a2804b6f62`, `81df89e1cc22`) have v1.16 logs from 13-18 May 2026 and v1.17 logs from 7-13 August 2026, on FMU-v5/v6C boards with M8 receivers. Two more (the CUAV X7 Pro octocopters) share a board and a v1.17 alpha build. So the 10 pairs are probably fewer than 10 independent owners.
- 5 of the 10 v1.16 lags lay between 189.7 and 201.6 ms. 4 of the 10 v1.17 lags lay between 95.6 and 99.8 ms.

## What D3 means

- **No claim either way.** The pre-registered fleet result ([`../dynmodel-2026/GRADE.md`](../dynmodel-2026/GRADE.md)) and the within-vehicle case ([`../dynmodel-2026/GRADE-paired.md`](../dynmodel-2026/GRADE-paired.md)) stand as they were. px4-log-health's dynamic-model note is not changed. No comment goes to PR #24831 on this result.
- **The next test is set before any new log is downloaded.** [`PLAN-ext.md`](PLAN-ext.md) continues this draw with up to 10 tries a side. It leaves out the 10 vehicles above and is scored only on new pairs.

## Limits

- Each pair is two flights on different days, which may differ in manoeuvres, wind and satellites. The pairing fixes the airframe and receiver, not the flight.
- v1.17 changed more than this default. With one unchanged pair, the plan's control (U4) had nothing to work with.
- Flight Review uploads are self-selected. The logs that counted are flights with enough manoeuvring and a serial u-blox receiver, not a sample of all vehicles.
- The lag is measured against `vehicle_gps_position.timestamp`, so it includes PX4's parsing and serial transfer.
- Flight Review removes uploads after 12 months (see the README), so the raw logs may not stay available. The rows do.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
