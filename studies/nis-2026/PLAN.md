# nis-2026: are EKF2's GNSS innovations as small and as independent as EKF2 assumes? (pre-registration)

Written and committed before any log for this study was downloaded. `nis.py` (0.1.0), `fresh_nis.py` (0.1.0) and `test_nis.py` are committed with this plan. The logs are the ones fresh-2026 downloads ([`../receiver-2026/PLAN-fresh.md`](../receiver-2026/PLAN-fresh.md), seed 20261102), read in the same pass as mismatch-2026 ([`../mismatch-2026/PLAN.md`](../mismatch-2026/PLAN.md)). That job has not been filed yet.

## Why

PX4 RFC [#28837](https://github.com/PX4/PX4-Autopilot/issues/28837) ("Scale EKF2 GNSS measurement noise by the error correlation time", opened 2026-09-24) argues that EKF2 treats every GNSS sample as independent, while real GNSS errors stay correlated for seconds to minutes. In its 1-D simulation this leaves the filter overconfident, gives a mean normalised innovation squared (NIS) of only 0.18 and a gate more than 11 times wider than the real innovations. Its open questions include "how correlated real GNSS velocity error is" and τ per fix type, and its rollout step 2 is to measure τ from logs. The RFC's figures come from simulation, and its rollout plans measurements on logs from specific receivers (u-blox F9P, X20, Septentrio mosaic). In a search on 2026-10-31 we found no measurement of EKF2's GNSS innovation consistency (NIS) or whiteness across many real flights. PX4's EKF2 documentation mentions batch scripts (`batch_process_logdata_ekf.py`) for checking many logs, but we found no published fleet NIS or autocorrelation results from them. Flight Review's public logs carry what is needed: `estimator_innovations` and `estimator_innovation_variances`.

## What PX4 computes and logs (sources, v1.15.4 unless noted)

- `msg/EstimatorInnovations.msg` (v1.12.3 and v1.15.4): one layout for `estimator_innovations`, `estimator_innovation_variances` and `estimator_innovation_test_ratios`; `gps_hpos[2]` (m, m²) and `gps_hvel[2]` (m/s, (m/s)²), north and east.
- `src/modules/ekf2/EKF/gps_control.cpp`: position observation variance `sq(max(hacc, EKF2_GPS_P_NOISE))` (capped at `EKF2_NOAID_NOISE` when GNSS is the only horizontal aiding source), velocity `sq(max(sacc, EKF2_GPS_V_NOISE))`, gates `max(EKF2_GPS_P_GATE, 1)` and `max(EKF2_GPS_V_GATE, 1)`. `module.yaml` defaults: P_NOISE 0.5 m, V_NOISE 0.3 m/s, both gates 5.0 SD. `control_status.flags.gps` is set when GPS fusion starts and cleared when it stops.
- `src/modules/logger/logged_topics.cpp`: `estimator_innovations` and `estimator_innovation_variances` at 500 ms, `estimator_status_flags` on every change, `vehicle_gps_position` at 100 ms, `vehicle_land_detected` on every change. `estimator_aid_src_gnss_*` is not logged on real hardware by default, so the logged innovations are used.

## Per log (`nis.read_nis`)

- Time base: `timestamp_sample` where the topic has it, else `timestamp`. The first instance (multi_id 0) of each topic.
- Each innovation sample is paired with the variance sample nearest in time (within 0.3 s).
- **Usable sample:** in flight (the last `vehicle_land_detected.landed` at or before it is 0), GPS fused (the last `estimator_status_flags.cs_gps` at or before it is 1, where the log has that topic), north and east innovation and variance finite, variances above 0, and not both innovations exactly 0.
- **NIS** per sample = (innov_N² / var_N + innov_E² / var_E) / 2. If EKF2's variances were right and its innovations Gaussian, this would be chi-square(2)/2: **median ln 2 = 0.693**, mean 1. A log's NIS is the **median** over its usable samples (robust to resets); the mean is also kept.
- **Autocorrelation** of the normalised innovations z = innov / √var at 1, 2, 5, 10 and 20 s: each usable sample is paired with the usable sample nearest t + lag (within 0.25 s); per axis r = mean(d_i·d_j) / mean(d²) with d = z − its log mean; the two axes are averaged. At least 30 pairs. A consistent filter's innovations are white, so r ≈ 0 at every lag.
- **τ:** the first lag where r falls below 1/e, linear between the lags above (lag 0 counts as 1); "above 20 s" if it never does.
- Usable log: at least 60 usable position samples (about 30 s of flight). Done separately for position and velocity.
- A log counts if fresh-2026 passed it (`gps_lag.py` 0.1.0's gates; not simulated) and it is usable here.

## Checks

Intervals are seeded bootstrap 95% intervals of the median across logs (seed 20261104, 2,000 resamples). Each fleet figure needs at least 30 logs.

- **E0 (enough data):** at least 60 usable logs. If E0 fails, everything below is exploratory only.
- **N1 (position innovations are smaller than EKF2's variances say):** the median across logs of the per-log median position NIS is below half the consistent value (0.347), and so is the upper end of its interval.
- **N2 (the same for velocity):** the same rule on velocity NIS.
- **W1 (position innovations are not white):** the median across logs of the 1 s position autocorrelation is above 0.2, and so is the lower end of its interval.
- **W2 (velocity innovations are not white):** the same rule on velocity.

**What we expect, before any data.** N1, N2 and W1 should all hold. The position variance floors the receiver's own hacc at 0.5 m, and the RFC's mechanism (correlated error that the filter partly follows) keeps innovations small and slow. N2 should hold for the same reason, and because the 0.3 m/s floor on velocity noise is at or above the speed accuracy u-blox receivers often report in open sky. W2 is the least certain: velocity error is expected to be less correlated (Groves, cited in the RFC, gives up to 20 s for velocity against 100 s for position), and EKF2's own state errors and the GPS delay add structure of their own.

## Decisions written in advance

- **D1:** if E0 holds, MV2 posts **one** comment on RFC #28837 with the fleet figures (median NIS, autocorrelation at each lag and τ for position and velocity, by fix type), whatever N1-W2 say, linking to the GRADE and the per-log data, and stating the limits below. If E0 fails, there is no comment, and the results are published as exploratory.
- `nis/summary.json`, the per-log rows (the `nis_` fields of fresh-2026's `logs.jsonl`) and a `GRADE.md` are published whatever the outcome. If the job is stopped from outside, its partial rows are not scored.

## How it runs, and what it costs fresh-2026

`fresh_nis.py` runs `fresh.py` 0.1.0 unchanged. It wraps `rate.read_rate` with `fresh_mm.combine` (mismatch-2026, unchanged) and adds `nis.read_nis`'s fields. `fresh.py`'s checks never read `mm_` or `nis_` fields, so its `summary.json` is the one `fresh.py` alone would write, and `mismatch.py` scores the same rows as before. Flight Review still sees one download per log. Reading five more small topics adds roughly one more second per log, inside fresh-2026's fixed 215-minute budget, so a few percent fewer logs may be attempted (fresh-2026's sizing, about 890 attempts against about 25 M8 expected and 15 needed, leaves room).

## Exploratory (not predicted)

Everything above by modal fix type in flight (3D, DGPS/SBAS, RTK float, RTK fixed), by receiver (M8, M9, F9P, other) and by GPS rate grid (100, 125, 200 ms, from `rate.py`); mean NIS; the gate in units of the actual innovation spread (gate / √mean NIS, the RFC's "more than 11 times"); median reported eph; how many logs never drop below 1/e by 20 s.

## Limits

- Innovations are not raw GNSS errors. EKF2 absorbs slowly varying error into its states, so the innovations' correlation time is not the receiver's error correlation time, and is expected to be shorter. The study measures what EKF2 itself sees.
- Innovations and variances are logged every 500 ms from a filter fusing GPS at 5-10 Hz: the study sees one in every 2.5-5 fused samples, so nothing faster than about 1 s is resolved.
- EKF2's own state errors, the GPS delay mismatch (mismatch-2026), wind and vibration all add structure to the innovations; none of it is separated here.
- The first EKF2 instance only, which in multi-EKF setups is not always the one selected.
- Flight Review uploads are self-selected, often after a problem. One log per vehicle. Nothing here is about ArduPilot.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
