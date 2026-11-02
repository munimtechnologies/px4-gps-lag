# floor-2026: does EKF2's GPS position noise floor explain its tiny NIS on real flights? (pre-registration)

Written and committed on 2026-11-02, before the sample below is drawn. It is scored on the same new sample as [`f9p-2026`](../f9p-2026/PLAN.md) (seed 20261109), whose logs nobody has downloaded or looked at yet: the sealed job waits until this plan and `floor.py` 0.1.0 are on `main` before it draws a single log. Code: `floor.py` 0.1.0 (standard library only; it reads the per-log rows and downloads nothing) and `test_floor.py`.

## Why

[nis-2026](../nis-2026/GRADE.md) found that on 285 real PX4 flights EKF2's GNSS position innovations are far smaller than EKF2's own innovation variance says: a median normalised innovation squared (NIS) of **0.0079**, where a consistent filter gives 0.693. PX4 RFC [#28837](https://github.com/PX4/PX4-Autopilot/issues/28837) explains this from simulation by correlated GNSS errors that EKF2 treats as independent.

There is a second, simpler cause that nobody has measured on real logs, as far as we found: the **noise floor**. EKF2 fuses each GNSS position with the noise

    pos_noise = max(hacc, EKF2_GPS_P_NOISE)

(PX4 v1.15.4, `src/modules/ekf2/EKF/gps_control.cpp`, `Ekf::updateGnssPos()`; `hacc` is `vehicle_gps_position.eph`, set in `src/modules/ekf2/EKF2.cpp`, `UpdateGpsSample()`). `EKF2_GPS_P_NOISE` defaults to 0.5 m. A receiver that reports 0.3 m (or 0.014 m with RTK) is still fused as if it were 0.5 m, so its innovations look small against the variance EKF2 assumes. The noise is also capped at `EKF2_NOAID_NOISE` (default 10 m) when GPS is the only horizontal aid; logs at or above 10 m are left out.

Per log, with `eph` the in-flight median of `vehicle_gps_position.eph`:

    q = eph / max(eph, EKF2_GPS_P_NOISE)      (q = 1 at or above the floor, q < 1 under it)

If the real innovations scale with the receiver's eph, NIS ≈ c · q² under the floor and stays flat (≈ c) above it.

Prior art: the floor exists so that a receiver that is too optimistic about its accuracy can't make EKF2 over-trust it, and users with RTK are told to lower it (PX4 docs, "Using PX4's Navigation Filter (EKF2)"; discuss.px4.io topic 19746). PX4-ECL issue [#197](https://github.com/PX4/PX4-ECL/issues/197) plotted innovations against reported accuracy on one RTK flight. RFC #28837 keeps the floor in its proposed noise model. We found no measurement, across many real flights, of how much the floor lowers EKF2's position NIS.

## Sample and rows

Every row of f9p-2026's `logs.jsonl` with `nis_ok` true, not simulated, a positive `nis_pos_median` and a `q` (`eph` positive, noise below 10 m). Unlike f9p-2026, a log need not pass `gps_lag.py`'s lag gates: NIS does not depend on them. The fields come from `nis.py` 0.1.0, unchanged, as in nis-2026. A missing `EKF2_GPS_P_NOISE` counts as the default 0.5 m.

## Checks

| | rule |
|---|---|
| **E0** | at least **150** usable logs, at least **40** with q = 1 and at least **60** with q < 1 |
| **F1** | Spearman ρ(q, position NIS) over all usable logs **≥ 0.20**, with its 95% interval above 0 |
| **F2** | under the floor (q < 1), the least-squares slope of ln NIS on ln q has its 95% interval **above 0**, and the slope is **≤ 3** (the floor alone predicts 2) |
| **F3** | median NIS of q = 1 logs is **at least 2 times** the median NIS of logs with q ≤ 0.5, with its interval above 1; scored only with at least **30** logs at q ≤ 0.5 |
| **F4** | among q = 1 logs, Spearman ρ(eph, position NIS) is between **−0.25 and 0.25** (above the floor EKF2 already scales its noise with eph) |

If E0 fails, F1-F4 are not scored. Intervals are percentile bootstraps over logs, 2,000 resamples, seed 20261110 (F3 resamples the two groups separately).

**What we expect, and what we have already seen.** The floor arithmetic alone predicts that all four hold, with F2's slope near 2. But the published nis-2026 summary, broken down by fix type (seen before this plan), points the other way for the size of the effect: RTK-fixed logs (median eph 0.014 m, so q about 0.03) had a median NIS of 0.0044, against 0.0076 for plain 3D fixes (eph 0.68 m, q = 1). With the default floor, the floor alone would make the RTK figure about 1,000 times smaller, not 2 times (unless those logs lowered `EKF2_GPS_P_NOISE`, which q accounts for). While writing this plan we also counted two fields in fresh-2026's rows (seen): 251 of the 588 logs with an eph had it at 0.5 m or more (43%), and in the first 400 rows that carry the parameter about 15% had changed `EKF2_GPS_P_NOISE` from 0.5 (values from 0.01 to 10 m). No per-log q-against-NIS pair was computed on any sample. **Our prediction:** E0, F1 and F4 hold; F2 holds with a slope well under 2; F3 is uncertain and may fail. That would mean the floor explains only part of the low NIS, and the rest is what RFC #28837 describes.

**Replication** (reported, not graded): the same checks on fresh-2026's rows ([`receiver-2026/fresh/logs.jsonl`](../receiver-2026/fresh/logs.jsonl)), an independent earlier sample.

## Decisions

- **D1.** If E0, F1 and F2 hold: px4-gps-lag's README states how much of the low NIS the floor explains (the slope against 2), and MV2 adds the figures to his comment thread on RFC #28837, once, since they bear on how the RFC's noise scaling should treat `EKF2_GPS_P_NOISE`.
- **D2.** If F1 fails: the README says that on real flights the position NIS does not follow the floor, so the low NIS is not a side effect of `EKF2_GPS_P_NOISE` and the RFC's explanation stands without it.
- F3 and F4 are reported either way; neither changes px4-log-health's checkup.

## Exploratory, not predicted

`floor.py` also lists, for each fix type and for default vs changed `EKF2_GPS_P_NOISE`: the number of logs, median q, median eph, median position NIS and the share under the floor, plus Spearman ρ(q, velocity NIS). Velocity uses its own floor (`EKF2_GPS_V_NOISE` against the receiver's speed accuracy, which the rows do not carry), so that last figure is only descriptive.

## Limits

- One in-flight median of eph per log; eph moves within a flight, so the floor may bind for part of it only.
- eph is the receiver's own estimate, not its true error, and receivers differ in how honest it is.
- The innovation variance also contains EKF2's own state uncertainty, not only the observation noise, so q² is an upper bound on how much the floor can lower NIS.
- Flight Review uploads are self-selected; the rows are those of f9p-2026's draw.

## Outputs

`floor-summary.json` (graded checks, exploratory breakdowns, and the fresh-2026 replication), published in this folder with `GRADE.md`, whatever the outcome.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
