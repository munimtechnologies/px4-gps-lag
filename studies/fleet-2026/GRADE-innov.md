# fleet-2026, part 2: graded

Graded 2026-10-30 against `PLAN-innov.md`, which was committed before any innovation was read. By MV2 of Munim, Inc.; the plan, code, analysis and this text were made with AI agents. Text CC BY 4.0. Data: PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0). Run: job `px4-gps-lag-innov-v1` (sealed container, `innov.py` 0.1.0, `gps_lag.py` 0.1.0 from main; tests passed; no 403/444; 23 minutes).

## As pre-registered: C2

| Check | Rule | Result | Holds |
|---|---|---|---|
| VE1 | at least 60 logs validated | 152 of 164 | yes |
| V1 | Spearman(d, x) ≥ 0.3 | **−0.757** | no |
| V2 | ≥ 70% of logs with \|d\| > 50 ms have x of the same sign | **4.9%** (2 of 41) | no |
| V3 | median x / d in 0.2-1.2 | **−0.483** | no |
| V4 | median \|x\| smaller where \|d\| ≤ 20 ms than where \|d\| > 50 ms | 7.8 ms (47 logs) vs 38.0 ms (41 logs) | yes |

d is fleet-2026's measured lag minus the log's own `EKF2_GPS_DELAY`; x is the implied excess from EKF2's GPS velocity innovations. Fusion time came from `timestamp_sample` in 137 validated logs and from `timestamp − EKF2_GPS_DELAY` in 15. Not validated: 5 logs with no GPS velocity innovation, 2 with too few in-flight innovations, plus 5 whose innovations passed but whose fleet-2026 row had no `EKF2_GPS_DELAY`. Median x was 5.5 ms; median standard error 1.6 ms.

**The written decision is C2, and it is applied:** rule D1 (offering the measured lag as a starting value for `EKF2_GPS_DELAY`) is withdrawn from the README. The README says "diagnostic only, no suggested setting" until a further check says otherwise.

## What went wrong: the plan had EKF2's innovation sign backwards

The result is not "no agreement". It is a strong agreement with the opposite sign, and only one wrong assumption is needed to explain it.

`PLAN-innov.md` assumed EKF2's innovation is **measurement minus prediction** (the usual textbook sign). PX4 uses **prediction minus measurement**:

- PX4 v1.14.0, `src/modules/ekf2/EKF/vel_pos_fusion.cpp`, `updateVelocityAidSrcStatus`: `aid_src.innovation[i] = _state.vel(i) - aid_src.observation[i];`
- PX4 main, `src/modules/ekf2/EKF/aid_sources/gnss/gps_control.cpp`, `updateGnssVel`: `_state.vel - velocity, // innovation`
- The older `ekf2_innovations` topic (5 logs here, PX4 v1.3-v1.10) shows the same reversed relation as the newer `estimator_innovations` logs.

We found this only after reading the result, by going to the source the plan should have cited. With PX4's sign, the innovation of a GPS that is L late, fused as if P late, is v(t − P) − v(t − L) ≈ +a·(L − P). The implied excess is then **+k**, not −k. Flipping that one sign changes the checks with no other change:

| Check | With PX4's sign | Would hold |
|---|---|---|
| V1 | Spearman **+0.757** (Spearman's ρ changes sign exactly) | yes |
| V2 | **95.1%** same sign (39 of 41; no log had x exactly 0) | yes |
| V3 | median ratio **+0.483** | yes |
| V4 | unchanged (absolute values) | yes |

That would be C1. Taken at face value, EKF2's own residuals on 152 public logs lean the way `gps_lag.py`'s measured mismatch says they should, in 39 of the 41 logs where the mismatch is large, and they show about half its size, as a filter that partly follows the late GPS should.

**Why we don't simply switch to C1.** The flip is a fact about PX4's code, not a choice fitted to the data, but it was found after the data were seen. A grade that is changed after seeing the result is no longer pre-registered. So the written rule stands, and the corrected reading is tested on logs whose innovations have not been read: `PLAN-innov-confirm.md` (committed with this file). It runs `innov.py` 0.2.0, which uses PX4's sign, on the 98 independent logs that passed `gps_lag.py` in px4-log-health's fleet-health-2026 replication. Its thresholds and decision rules are the same as this plan's. If it decides C1, D1 returns to the README with the confirmation cited. If not, D1 stays withdrawn.

## Limits

- The plan's limits still apply. It is a first-order model. The same attitude estimate feeds both methods, so they are not fully independent. The innovation is logged at 500 ms and is the last fusion's.
- An agreement in sign and rank is not a calibration. Under either reading, the innovation shows about half the measured mismatch. That fits a filter that partly follows the GPS, but this study does not measure the filter's gain.
- 15 validated logs had no `timestamp_sample`; their fusion time is assumed.

## Files

- `innov/summary.json`, `innov/innov.jsonl`: the run's output, unchanged (`implied_excess_ms` is in 0.1.0's sign; negate it for PX4's).
- `v1/summary.json`: fleet-2026 re-scored from `v1/logs.jsonl` by `fleet.py --rescore` in the same job. It matches `GRADE.md` (E1, P1, P2, P3, P5, P6 hold, P4 does not; median lag 99.8 ms; 29.6% over 50 ms off; serial 108.7 ms). The one difference is the DroneCAN median, 90.3 ms here against 90.4 ms in `GRADE.md`. That is most likely the per-log lags being stored rounded to 0.1 ms; no check changes. Its `exploratory` block is not pre-registered.
- `innov/fetched.json`: hashes showing the job ran main's `gps_lag.py`, `fleet.py` and `innov.py`.
