# fleet-2026: grade

Graded 2026-10-30 against `PLAN.md` (committed before any log was downloaded). By MV2 of Munim, Inc.; the grading and write-up are made with AI agents. Text CC BY 4.0. Data: PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0).

**Result: check E1 passed and 5 of 6 predictions held.** On 164 public PX4 logs from 115 vehicles, GPS velocity lagged the IMU by a median **99.8 ms** against the timestamp EKF2 corrects. That is close to the default `EKF2_GPS_DELAY` of 110 ms. The spread was wide: half the logs fell between 71 and 133 ms, and a tenth below 48 or above 179. 98% of these logs ran the default 110 ms, but **29.6% differed from their own setting by more than 50 ms**. Two logs of the same vehicle agreed to a median **5.3 ms** (49 vehicles), so the lag behaves like a property of the vehicle, not of the flight. The miss was P4: DroneCAN GPS lagged *less* than serial GPS, not more (90.4 against 108.7 ms). **Decision D1 holds:** the README offers the measured lag as a starting value for `EKF2_GPS_DELAY`, to be checked with EKF2 replay. A pre-registered cross-check against EKF2's own innovations (`PLAN-innov.md`) can still withdraw that.

## The run

- Job `px4-gps-lag-fleet-v1`, sealed container, 2026-10-30 02:08-03:06 UTC (the measuring step took 56 min; peak memory 0.12 GB). `wait_for_plan.py` found `PLAN.md` on main (sha256 58b19963...) and confirmed that `gps_lag.py` and `fleet.py` were byte for byte main's 0.1.0 (3338d743... and 4ffa4619...). The 21 unit tests passed.
- The public log list had 483,966 logs. 36,269 were eligible (from 2025-10-01, at least 240 s, not simulated), from 8,310 vehicles. The run stopped at its cap of 400 logs, well inside the 120-minute budget. The server never refused a download.
- **A bug at the very end.** `fleet.py` 0.1.0 measured all 400 logs and wrote every row to `logs.jsonl`. Then it crashed while writing `summary.json`, at the first check. `gps_lag.py`'s refined lag is a numpy float, so the check `40 <= median <= 160` produced a numpy boolean, which Python's `json` cannot write. Every figure above the checks had already been written. The checks below apply the plan's thresholds to those figures by hand. `fleet.py` 0.1.1 fixes the bug and adds `--rescore`. The next job re-scores the published `v1/logs.jsonl` with no download, and its `summary.json` must reproduce every number here.

## Check E1: passed

| Stated before the run | Result | |
|---|---|---|
| at least 80 logs pass | 164 | yes |
| from at least 50 vehicles | 115 | yes |

## Predictions

| | Prediction | Result | |
|---|---|---|---|
| P1 | median lag of passing logs between 40 and 160 ms | 99.8 ms (IQR 71.3-133.0; 10-90%: 47.6-178.9; range −9.4 to 355.5) | held |
| P2 | at least 20% of passing logs differ from their own `EKF2_GPS_DELAY` by over 50 ms | 29.6% (47 of 159 logs with the parameter) | held |
| P3 | at least 70% run the default 110 ms | 98.1% (values seen: 100, 110, 160 ms) | held |
| P4 | DroneCAN GPS median lag > serial GPS median (each group ≥ 15) | 90.4 ms (34 logs) against 108.7 ms (65 logs) | **missed** |
| P5 | same-vehicle median \|difference\| ≤ 25 ms (≥ 15 vehicles) | 5.3 ms over 49 vehicles | held |
| P6 | median standard error ≤ 10 ms | 1.2 ms | held |

The median of lag minus each log's own setting was −10.3 ms.

GPS bus of passing logs: serial 65 (median 108.7 ms), DroneCAN 34 (90.4), not recorded 60 (103.2), I²C 3 (152.1), MAVLink 2 (−9.4). The MAVLink pair is too few to read anything into. A GPS that reaches the flight controller over MAVLink is timestamped on arrival at a different point in the chain.

## Why logs did not pass (236 of 400)

| Reason | Logs |
|---|---|
| download over the 80 MB cap | 68 |
| IMU explains too little of the GPS velocity change (R² < 0.6) | 51 |
| no `vehicle_gps_position` in the log | 44 |
| too few in-flight GPS pairs (< 100) | 33 |
| too little manoeuvring (< 0.3 m/s²) | 31 |
| best lag at the edge of the search | 4 |
| no `vehicle_attitude` | 3 |
| no `sensor_combined` | 2 |

## Decision

**D1 holds** (E1 and P5 held). The README now offers the measured lag as a starting value for `EKF2_GPS_DELAY` when it differs from the setting by more than about 50 ms. Any change is to be checked with EKF2 replay of the vehicle's own logs. `PLAN-innov.md` (committed beside this grade, before any innovation was read) tests the measured mismatch against EKF2's own GPS velocity innovations. Its rule C2 withdraws D1 if they disagree.

## What it says

- **The default is about right on average, and wrong for many vehicles.** Nearly a third of the measured logs (29.6%) sit more than 50 ms from their own setting. Repeat flights of a vehicle agree to about 5 ms, so a per-vehicle value is measurable. Almost nobody changes the default (98%).
- **DroneCAN was not slower.** We expected CAN transport to add delay. It didn't: DroneCAN receivers came out about 18 ms *earlier* than serial ones. The receiver models differ between the groups, so this compares installed setups, not buses.
- **What "lag" means here.** It is measured against `vehicle_gps_position.timestamp`, the time EKF2 subtracts its delay from. It is the total of receiver filtering, transport and driver time, which is what the setting has to match.

## Honest limits

- **Repeatable is not the same as correct.** The method recovered known delays within 3 ms on synthetic flights, but there is no ground truth for these vehicles. `PLAN-innov.md` is an independent check of direction, using a signal this method never reads. EKF2 replay remains the real test for any one vehicle.
- **Not a random sample of PX4 vehicles.** People upload logs for many reasons, often after a problem. The gates keep only flights with enough manoeuvring, and the 80 MB cap drops long high-rate logs (68 of 400).
- **The nominal standard error is optimistic.** The median 1.2 ms assumes independent residuals. The 5.3 ms same-vehicle spread is a more honest guide to precision.
- **P4's groups are not matched.** Receiver models, firmware versions and logging rates all differ between them.

## Files

`v1/logs.jsonl` holds one line per log attempted, by its public Flight Review id, with vehicle ids hashed and no position. The re-scored `summary.json` (fleet.py 0.1.1 `--rescore`) will be added beside it.

## Reproduce

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet
python fleet.py --out-dir out --budget-min 120 --max-logs 400       # draws again from today's list
python fleet.py --out-dir out --rescore studies/fleet-2026/v1/logs.jsonl   # re-scores this run
```
