# upgrade-2026, extension: grade

Graded on 2026-11-06 against [`PLAN-ext.md`](PLAN-ext.md), which was committed before any log for this extension was downloaded. The sealed job `px4-gps-lag-upgrade-ext-v1` (2026-11-06, 08:40-09:46 UTC) found the plan on `main` (sha256 `70855651…`). It checked that its `extend.py` 0.1.0 and `test_extend.py` were `main`'s copies, and that `upgrade.py` (`e6b3dcac…`) and `gps_lag.py` (`3338d743…`) were the copies the first run used. It ran the 9 unit tests (all passed), and only then read Flight Review's public list. Hashes are in [`ext/job-fetched.json`](ext/job-fetched.json). Every attempt, reused or downloaded, is in [`ext/rows-ext.jsonl`](ext/rows-ext.jsonl), the new pairs are in [`ext/pairs-ext.jsonl`](ext/pairs-ext.jsonl), and the scores are in [`ext/summary-ext.json`](ext/summary-ext.json). Vehicle ids are `sha256(uuid)[:12]`, and no position was read.

## Result: X0 failed (1 new pair, 8 needed), so rule DX3 applies. A case series, no claim

X1-X4 are not scored. As the plan says, there will be no third extension of this design.

| | |
|---|---|
| log entries in the public list (today) | 487,180 |
| eligible logs / vehicles | 17,994 / 3,206 |
| vehicles with eligible logs on **both** releases | 139 (2,084 only on v1.16, 983 only on v1.17) |
| vehicles visited (all except the 10 paired in the first run) | 129; the job stopped at "list exhausted", not at a limit |
| first-run attempts reused without a download | 333 |
| new downloads | 282 (the whole run, list included, took 57 minutes), one at a time, 6 s apart; never blocked |
| **new pairs** | **1** |

### Why the new downloads did not count

| reason | new downloads |
|---|---|
| counted | 6 (5 on v1.16, 1 on v1.17) |
| `gps_lag.py`: the IMU explains too little of the GPS velocity change | 88 |
| not a serial u-blox receiver | 55 |
| no `vehicle_gps_position` in the log | 52 |
| larger than the 80 MB download limit | 45 |
| too little manoeuvring | 25 |
| too few in-flight GPS pairs | 7 |
| the v1.17 log's receiver had a different device type (here an M8 replaced by an M9) | 3 |
| no `vehicle_attitude` | 1 |
| **total** | **282** |

**The v1.17 side is the bottleneck.** With the reused tries, 22 vehicles had a counting v1.16 log (17 from the first run, 5 new). Their v1.17 sides got 78 attempts in all (32 reused, 46 new), about 3.5 per vehicle, well under the cap of 10, so most of them ran out of listed v1.17 logs. Only 1 of the 78 counted. Of the 46 new v1.17 downloads, 21 were out for reasons other than the fit (no GPS topic, not a serial u-blox, or too large), 21 failed `gps_lag.py`'s fit gates, 3 had a different receiver and 1 counted.

The plan's prior on X0 was "about even". That was wrong for the same reason as the first run's E0: we sized the gate on vehicles, not on how many counting logs each vehicle's v1.17 side could still give.

## The new pair

d = lag on v1.16 − lag on v1.17. A positive d means the GPS was less late after the upgrade.

| vehicle | receiver | board | v1.16 log | model | lag | v1.17 log | model | lag | **d** |
|---|---|---|---|---|---|---|---|---|---|
| `4356b0c5e400` | F9P | CUAV X7 Pro (quadrotor) | 2026-02-24, v1.16.1 rc | 6 | 223.4 | 2026-11-04, v1.17.0 | **6** | 225.5 | **−2.1** |

- Both logs had `EKF2_GPS_DELAY` 110 ms, so the GPS was about 113-116 ms past its setting on both releases. Fit R² 0.95 and 0.81; standard errors 1.5 and 2.1 ms.
- **This vehicle kept model 6 on the v1.17.0 release**, where the multicopter default is 7, so the value was stored outside PX4's defaults (by hand, from a saved parameter file, or by a custom airframe). It does not come from the board: CUAV X7 Pro's `rc.board_defaults` at v1.17.0 sets no GPS parameter. It is an unchanged-model pair, not a switch.
- The v1.17 log is dated after the v1.16 log. The vehicle was not in dynmodel-2026's sample.

## Also reported (not graded)

These pool the first run's 10 pairs with the new one, so **they include the pairs already seen** and test nothing.

| pooled pairs (first plan's checks) | n | median d | bootstrap interval |
|---|---|---|---|
| all | 11 | +74.4 ms | 7.2 to 109.1 |
| switched, model 6 → 7 | 9 | **+94.9 ms** | 7.2 to 137.9 |
| model unchanged (6 on both) | 2 | **+8.6 ms** | −2.1 to 19.3 |
| vehicles not in dynmodel-2026 | 7 | +74.4 ms | 7.2 to 109.1 |

- Median lag on v1.16: 194.7 ms (11 logs, all at model 6). On v1.17: 98.5 ms (9 at model 7, 2 at model 6). Logs more than 50 ms past their setting: 8 of 11 before the upgrade, 3 of 11 after.
- By the first plan's own rule, E0 (12 pairs) still fails at 11, so its D3 stands.
- **The two vehicles that kept model 6 through the upgrade barely moved (+19.3 and −2.1 ms); the nine that switched to 7 dropped by a median of 94.9 ms.** This is the comparison the first plan's control (U4) was meant to make. Here it rests on two vehicles, both CUAV X7 Pro boards with F9P receivers, so it is a description, not evidence. It points the same way as the fleet figure (+46 ms) and the within-flight case on PR #24831 (+104 ms): it is the model, not the release, that goes with the drop.

## What DX3 means

- **No claim.** The fleet result ([`../dynmodel-2026/GRADE.md`](../dynmodel-2026/GRADE.md)) and the within-vehicle case ([`../dynmodel-2026/GRADE-paired.md`](../dynmodel-2026/GRADE-paired.md)) stand as they were. px4-log-health's dynamic-model note does not change. Nothing is offered on PR #24831 because of this result.
- **No third extension.** Flight Review's public list, as of 2026-11-06, does not hold enough multicopters with usable logs on both v1.16 and v1.17 for this design to reach 8 or 12 pairs. A future test would need a different source of before-and-after logs: owners who fly the same vehicle at both models on purpose, or a later list when more vehicles have flown v1.17.

## Limits

- One new pair. Every limit of the first plan applies: two flights on different days, other v1.17 changes, self-selected uploads, lag measured against `vehicle_gps_position.timestamp`.
- Vehicles that kept model 6 on v1.17 had it stored outside PX4's defaults, and such vehicles may differ from those that kept the defaults.
- Shared operators are likely among the first run's pairs (see [`GRADE.md`](GRADE.md)). The two unchanged pairs share a board and receiver; their hashed vehicle ids differ, but they may share an owner.
- Flight Review removes uploads after 12 months, so the raw logs may not stay available. The rows do.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
