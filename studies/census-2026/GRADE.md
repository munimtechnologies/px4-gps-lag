# census-2026: how many PX4 multicopters still run u-blox model 6? (grade)

Graded on 2026-11-07 against [`PLAN.md`](PLAN.md) (pre-registered 2026-11-06) and [`AMENDMENT-1.md`](AMENDMENT-1.md) (a code-only fix published before any log was read). **Result: E0, C1, C2 and C3 all held, so the outcome is H1.** PX4's change to the default reached most v1.17 multicopters.

## What ran

- **The sealed job** was `px4-gps-lag-census-v2`, run on 2026-11-07 from 09:19 to 10:46 UTC. It first checked its inputs against `main` ([`job-fetched.json`](job-fetched.json)):
  - `AMENDMENT-1.md` was on `main`;
  - `PLAN.md` was the file the 0.1.0 job saw (sha256 `5da57c61…`, line endings normalised);
  - its `census.py` 0.1.1 and `test_census.py` were `main`'s copies (`cf7c5c05…`, `65658146…`);
  - dynmodel-2026's rows were the published copy (`96bc66f6…`, 261 lines).

  All 32 synthetic tests passed. Only then did it read the list.
- **The list.** Flight Review's public list had 487,576 entries. 18,037 logs passed the filters: real multicopter logs of at least 120 s, with a vehicle id, on a v1.16 or v1.17 build that is not a development build.
  - Eligible vehicles: 2,225 on v1.16 and 1,126 on v1.17, of which 139 are on both.
  - After leaving out the vehicles on both releases and dynmodel-2026's 257 vehicles, the graded draw had 2,048 vehicles on v1.16 and 964 on v1.17.
- **The pass.** It made 660 requests, one at a time and 6 s apart, and was never blocked. Every read was status `ok`.
  - v1.16 reached 250 vehicles with a model read after 253 reads, and v1.17 after 268 reads. The graded draw then stopped as planned.
  - Last, it read one v1.17 log from each of the 139 vehicles on both releases. 124 of those logs had the parameter.
  - 36 reads had no `GPS_UBX_DYNMODEL` in the log. PX4's logger writes only parameters that are in use, so these are most likely vehicles where no serial GPS driver ran. They count toward the read limit, not the share, exactly as the plan says.
- **The files.** Every read is in [`census-rows.jsonl`](census-rows.jsonl): log id, hashed vehicle id, board, release, build kind, GPS-related parameters and logged defaults, with no flight data. The scored figures are in [`census-summary.json`](census-summary.json).

## The checks

| | rule | result | |
|---|---|---|---|
| **E0** | at least 200 graded vehicles with a model read on each release | 250 and 250 | **held** |
| **C1** | v1.16: share at model 6 ≥ 75% | **81.6%** (204 of 250; 95% Wilson 76.3 to 85.9) | **held** |
| **C2** | v1.17: share at model 6 between 2% and 20% | **5.6%** (14 of 250; 3.4 to 9.2) | **held** |
| **C3** | v1.16 share minus v1.17 share ≥ 50 points | **76.0 points** | **held** |

**Decision: H1.** As the plan says, the README and the discuss.px4.io thread report both shares and how many v1.17 multicopters still run model 6. H2 (a v1.17 share above 20%) did not happen, so the plan does not call for a documentation sentence. Our prior for C1 was about 85%, and the result was 81.6%.

Every model value read:

| release | model 6 (<1g) | 7 (<2g) | 8 (<4g) | vehicles |
|---|---|---|---|---|
| v1.16 | **204** (81.6%) | 41 | 5 | 250 |
| v1.17 | **14** (5.6%) | 234 | 2 | 250 |
| v1.17, vehicles also on v1.16 (reported only) | 11 (8.9%; 5.0 to 15.2) | 113 | 0 | 124 |

Applied to the 964 v1.17-only multicopters in the draw, 5.6% is about 54 vehicles (32 to 88). The vehicles also seen on v1.16 are the visible upgraders, and more of them still run model 6 (8.9%). That fits a stored model 6 carrying over the upgrade. The two intervals overlap, so this is not a finding.

## Also reported (not pre-registered as checks; descriptive)

**Why the v1.17 vehicles at model 6 run it.** PX4's logger writes a parameter's default ('Q' message) only when the default differs from the logged value ([`logger.cpp`, `write_parameter_defaults`, v1.17.0](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/src/modules/logger/logger.cpp)). The configuration default (the airframe's) is written only if it differs from the value. So a log with no configuration default for `GPS_UBX_DYNMODEL` ran its configuration default.

| release and model | vehicles | logged configuration default | what that means |
|---|---|---|---|
| v1.16, model 6 | 200 | none | the default (6) gave it |
| v1.16, model 6 | 4 | 7 | 6 set against a default of 7 |
| v1.16, model 7 | 18 | 6 | set away from the default 6 |
| v1.16, model 7 | 23 | none | the configuration default was 7 |
| v1.16, model 8 | 4 | 6 | set away from the default 6 |
| v1.16, model 8 | 1 | none | the configuration default was 8 |
| v1.17, model 6 | **13** | **7** | **6 set against the default 7** |
| v1.17, model 6 | 1 | none | the configuration default was 6 |
| v1.17, model 7 | 234 | none | the default (7) gave it |
| v1.17, model 8 | 2 | 7 | set away from the default 7 |

- On v1.16, 200 of the 204 model-6 vehicles had it because the multicopter default gave it to them.
- On v1.17, 13 of the 14 model-6 vehicles have 6 set against a default of 7. It was stored in their parameters (by hand or from a saved parameter file) or set by a startup script. One vehicle's own configuration default is 6.
- On v1.16, 22 of 250 vehicles (8.8%) had moved off 6 by hand (18 to 7, 4 to 8).

**The receiver protocol.** `GPS_1_PROTOCOL` 6 is "NMEA (generic)" ([`params.c`, v1.17.0](https://github.com/PX4/PX4-Autopilot/blob/v1.17.0/src/drivers/gps/params.c)).
- 4 of the 14 v1.17 model-6 vehicles have their main GPS set to NMEA, so no u-blox is configured there at model 6. 10 have it set to u-blox (1).
- Among v1.17 vehicles whose main GPS is set to u-blox, 10 of 219 (4.6%) run model 6.
- On v1.16 the figure is 175 of 217 (80.6%). Of the 204 model-6 vehicles there, 175 were set to u-blox, 3 to auto-detect, 11 to NMEA, and 15 logs had no `GPS_1_PROTOCOL`.
- Overall, NMEA was set on 12 v1.16 and 24 v1.17 vehicles.

**Build kind (v1.17).** Model 6 was on 6 of 84 pre-release vehicles (7.1%) and 8 of 166 release vehicles (4.8%).

**Boards of the 14 v1.17 vehicles at model 6.** PX4 FMU-v6X 4, CUAV X7 Pro 2, CubePilot Cube Orange+ 2, PX4 FMU-v4 2, and one each of CUAV X25 EVO, PX4 FMU-v5, PX4 FMU-v6C and X-MAV AP-H743v2. The two upgrade-2026 vehicles that kept model 6 were also CUAV X7 Pro boards. They are not in this graded draw, because vehicles on both releases are left out.

## Other open flight stacks (descriptive)

To put PX4's old multicopter default in context, a separate sealed job (`autopilot-dynmodel-defaults-v1`, GitHub only) recorded each stack's default u-blox dynamic model at a pinned commit on 2026-11-07: [`autopilot-defaults.md`](autopilot-defaults.md), [`autopilot-defaults.json`](autopilot-defaults.json), code [`defaults.py`](defaults.py).

| stack (commit) | default for multicopters |
|---|---|
| PX4 v1.16.0 (`6ea3539`) | `rc.mc_defaults`: `param set-default GPS_UBX_DYNMODEL 6` (<1g) |
| PX4 v1.17.0 (`d6f12ad`) | no override in `rc.mc_defaults`, so the parameter default **7** (<2g); fixed-wing `rc.fw_defaults` sets 8 |
| ArduPilot master (`b7c08d4`) | `GPS_NAVFILTER` default `GPS_ENGINE_AIRBORNE_4G` (8, <4g) |
| Betaflight master (`bfb608d`) | flight model `UBLOX_MODEL_AIRBORNE_4G` (acquire model `STATIONARY`) |
| INAV master (`940b928`) | `gps_dyn_model` default `AIR_2G` |

PX4 up to v1.16 was the only one of these open stacks whose multicopters ran <1g. Since v1.17 none does.

## What it means

- **The default change worked for most vehicles.** About 4 in 5 public v1.16 multicopters ran model 6, and about 1 in 18 v1.17 multicopters still do. On public logs, model 6 went with a median 46 ms more GPS lag, and with 104 ms more on PR #24831's test vehicle ([`../dynmodel-2026/GRADE.md`](../dynmodel-2026/GRADE.md), [`GRADE-paired.md`](../dynmodel-2026/GRADE-paired.md)). So far fewer flights carry that lag on v1.17.
- **The ones left behind set it themselves.** Almost every v1.17 vehicle still at 6 has it set against the default, so if your parameter file came from a v1.16 or older vehicle, check `GPS_UBX_DYNMODEL`. Measure again after changing it. px4-log-health's checkup adds a note on every log with a serial u-blox at model 6.
- **These are uploaded logs.** The shares describe vehicles whose owners upload to Flight Review, not every PX4 multicopter.

## Limits

- A log's parameters don't show whether a u-blox receiver is attached. The shares count what a serial u-blox on the vehicle would run, and the protocol figures narrow that only for the main GPS port.
- Flight Review uploads are self-selected. Vehicles that upload often, or that keep stored parameter files, may differ from the fleet.
- One log per vehicle. A vehicle that changed the model between flights is counted at the value in the drawn log.
- Vehicles with logs on both releases were left out of the graded draw, and they are the clearest upgraders (reported separately above). The v1.17-only vehicles may have upgraded from v1.15 or older, or from logs that aren't public.
- The vehicle id is the autopilot's, so a board moved between airframes counts as one vehicle.
- The reading of 'Q' messages relies on `write_parameter_defaults` as written at v1.17.0. Its v1.16 behaviour was not checked separately.

## Files

- `census-rows.jsonl`: every read (660 lines), with its status. Vehicle ids are `sha256(uuid)[:12]`.
- `census-summary.json`: the shares, the checks, the decisions, the reported breakdowns, the list counts and the pass record.
- `job-fetched.json`: what the sealed job checked on `main` before reading the list.
- `autopilot-defaults.md`, `autopilot-defaults.json`, `defaults.py`, `test_defaults.py`: the cross-stack defaults.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text and data CC BY 4.0, code Apache-2.0. Log data derived from PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0).
