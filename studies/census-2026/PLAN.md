# census-2026: how many PX4 multicopters still run u-blox model 6? (plan)

Pre-registered on 2026-11-06, before any log for this census is read. Code: [`census.py`](census.py) 0.1.0, tests [`test_census.py`](test_census.py) (standard library only). The sealed job waits until this plan and both files are on `main` and checks that its own copies are identical. Only then does it read Flight Review's public list. It also checks that `dynmodel-2026`'s rows are the published copy (`96bc66f6…`).

## Why

dynmodel-2026 found that u-blox logs at `GPS_UBX_DYNMODEL` 6 (airborne <1g) had GPS data a median 46 ms later than logs at 7 (<2g), and the PR #24831 vehicle lagged 104 ms more at 6 than at 7 ([`../dynmodel-2026/GRADE.md`](../dynmodel-2026/GRADE.md), [`GRADE-paired.md`](../dynmodel-2026/GRADE-paired.md)). Up to v1.16, PX4's `rc.mc_defaults` gave every multicopter model 6. PR #24831 removed that line for v1.17, so a multicopter now gets 7 unless 6 is stored in its parameters (set by hand, or loaded from a saved parameter file).

How far did that change reach? Nobody has counted how many multicopters ran model 6 on v1.16, or how many still run it on v1.17. The answer sizes the problem: how many flights the extra lag affects, and whether a default change is enough or users who upgrade also need to be told.

## What we have already seen

- dynmodel-2026 read the model of 244 logs from earlier samples (all releases). Their vehicles are left out of this census's graded draw.
- upgrade-2026 and its extension read the model of logs from the 139 multicopters with logs on both v1.16 and v1.17. In the 11 pairs, all 11 ran 6 on v1.16 and 2 kept 6 on v1.17. These vehicles are left out of the graded draw. Their v1.17 logs are read last and only reported.
- No other v1.16 or v1.17 log's `GPS_UBX_DYNMODEL` has been read.

## Design

- **The list.** Flight Review's public list, read once. Kept: real multicopter logs (`mav_type` contains "rotor" or "copter", not VTOL, helicopter or fixed-wing) of at least 120 s, with a vehicle id, on a v1.16 or v1.17 build that is not a development build. These are upgrade.py 0.1.0's filters.
- **Graded draw.** For each release, every vehicle with eligible logs on that release only, minus dynmodel-2026's vehicles. They are visited in a seeded order (seed 20261117), and each gets one seeded-random log. The two releases are taken in turn, so a cut-off hits both alike. A release stops when it has **250** vehicles with a model read, after 400 reads, or when it runs out of vehicles.
- **Reported, not graded.** After the graded draw, one seeded-random v1.17 log of each vehicle on both releases.
- **What is read.** Only the start of each log: the ULog definitions section, which holds the initial parameters ('P') and the logged parameter defaults ('Q'). Reading stops at the first data-section message, or at 16 MB. Only GPS-related parameters are kept (`GPS_*`, `SER_GPS*`, `SENS_GPS*`, `EKF2_GPS_*`). No flight data, position or console message is read. Requests go one at a time, 6 s apart, and the pass stops at the first HTTP 403, 429 or 444, or after five network errors in a row. Limit: 170 minutes. Vehicle ids are published only as `sha256(uuid)[:12]`.
- **Measure.** For each release, the share of graded vehicles whose log has `GPS_UBX_DYNMODEL` = 6, with a 95% Wilson interval.

## Predictions

| | rule | our prior |
|---|---|---|
| **E0** | at least 200 graded vehicles with a model read on each release | likely |
| **C1** | v1.16: share at model 6 ≥ 75% | likely (PX4's default; we expect about 85%) |
| **C2** | v1.17: share at model 6 between 2% and 20% | likely (2 of 11 upgraded vehicles kept 6) |
| **C3** | share at 6 on v1.16 minus share on v1.17 ≥ 50 points | likely |

C1-C3 are scored only if E0 holds.

## What we will do with each result

- **H1 (E0, C1, C2 and C3 hold):** the default change reached most v1.17 multicopters. px4-gps-lag's README and the discuss.px4.io thread report both shares, and how many v1.17 multicopters still run 6.
- **H2 (E0, and the v1.17 share at 6 is above 20%):** a stored model 6 is common after the upgrade, so the default change alone does not reach many vehicles. MV2 offers one sentence for PX4's documentation in the discuss.px4.io thread: check `GPS_UBX_DYNMODEL` after upgrading a multicopter from v1.16 or older.
- **H3 (E0, and C1 fails):** fewer v1.16 multicopters ran model 6 than PX4's defaults imply, so the extra lag reached fewer flights than the defaults suggest. The README says so.
- **H0 (E0 fails):** the counts are published with no claim.

## Also reported (not graded)

- Each release's count of every model value (6, 7, 8 and others).
- v1.17 by build kind (release or pre-release), and the boards (`sys_hw`) of v1.17 vehicles at 6.
- The model against the logged configuration default ('Q' messages), where the log has one.
- `GPS_1_PROTOCOL` values.
- The vehicles on both releases: the share of their v1.17 logs at 6.
- Every read in `census-rows.jsonl`, with its status.

## Limits, known in advance

- A log's parameters don't say whether a u-blox receiver is attached. The census counts what any serial u-blox on the vehicle would run. DroneCAN GPS modules and other receivers don't use this parameter.
- Flight Review uploads are self-selected, and vehicles that upload often or keep stored parameter files may differ from the fleet.
- One log per vehicle. A vehicle that changed the model between flights is counted at the value in the drawn log.
- Vehicles with eligible logs on both releases are left out of the graded draw, and they are the clearest upgraders. Vehicles counted as v1.17 only may still have upgraded from v1.15 or older, or from logs that aren't public.
- The vehicle id is the autopilot's, so a board moved between airframes counts as one vehicle.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
