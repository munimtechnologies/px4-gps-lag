# mismatch-2026: does a wrong GPS delay show in EKF2's own GPS checks? (pre-registration)

Written and committed before any log for this study was downloaded. `mismatch.py` (0.1.0), `fresh_mm.py` (0.1.0) and `test_mismatch.py` are committed with this plan. The logs are the ones fresh-2026 downloads ([`../receiver-2026/PLAN-fresh.md`](../receiver-2026/PLAN-fresh.md), seed 20261102), and that job has not been filed yet.

## Why

On public PX4 logs, about 30% of vehicles have a GPS that is more than 50 ms later or earlier than their own `EKF2_GPS_DELAY` says (fleet-2026: 29.6%; fleet-health-2026: 31.2%). EKF2's GPS velocity innovations lean the way that mismatch predicts (innov-confirm: 25 of 27, Spearman +0.86). The question a pilot asks next is **"does it matter?"** EKF2 decides whether to use each GPS velocity sample with its innovation test. Nobody we found has measured whether a delay mismatch moves that test on real flights. This study measures it on fresh logs, before any of them is read.

## What PX4 computes (sources, v1.15.4 unless noted)

- `src/modules/ekf2/EKF/ekf.h`, `setEstimatorAidStatusTestRatio`: `test_ratio[i] = sq(innovation[i]) / (sq(innovation_gate) * innovation_variance[i])`, and the sample is rejected when a ratio is above 1.
- `src/modules/ekf2/EKF/gps_control.cpp`, `updateGnssVel`: observation variance `sq(max(sacc, gps_vel_noise))`, gate `max(gps_vel_innov_gate, 1)`. `module.yaml`: `EKF2_GPS_V_NOISE` defaults to 0.3 m/s and `EKF2_GPS_V_GATE` to 5.0 SD.
- `src/modules/ekf2/EKF2.cpp`, `PublishInnovationTestRatios`: `gps_hvel[0]` and `[1]` are the north and east test ratios. In v1.12.3, `getGpsVelPosInnovRatio` fills only `gps_hvel[0]` with one horizontal ratio, as `msg/EstimatorInnovations.msg` says ("the test ratio will be put in the first component"). The study uses the larger of `[0]` and `[1]`, which reads the same in both layouts.
- `src/modules/logger/logged_topics.cpp`: `estimator_innovation_test_ratios` and `estimator_innovations` are logged at 500 ms and `vehicle_local_position` at 100 ms, in v1.12.3 and v1.15.4 alike. The first estimator instance is used.
- Innovation = prediction − measurement in PX4 (see `studies/fleet-2026/GRADE-innov.md`). A GPS that is later than the setting by Δ leaves an innovation of about +0.6 · a · Δ.

**The arithmetic, written before any data.** With the defaults, the innovation variance is at least 0.3² = 0.09 (m/s)², so rejection needs |innovation| > 5 · 0.3 = 1.5 m/s. A GPS 100 ms later than its setting, at 3 m/s², leans about 0.6 · 3 · 0.1 = 0.18 m/s, a test ratio of at most 0.18² / (25 · 0.09) ≈ 0.014. Steady flight sits around the same order of magnitude. So we expect the mismatch to **show** in the ratio during manoeuvres, but not to cause rejections on its own. For that, 0.6 · a · Δ would have to reach 1.5 m/s, i.e. 25 m/s² at Δ = 100 ms.

## Per log (`mismatch.read_mismatch`)

- Time base: `timestamp_sample` where the topic has it, else `timestamp`. In flight means the last `vehicle_land_detected.landed` sample at or before that time is 0.
- Horizontal acceleration at each logged test ratio: the mean of `vehicle_local_position` `ax`, `ay` over the 0.4 s up to that sample, as a vector, then its length.
- Test ratio samples in flight that are finite and above 0 (resets give infinity, and no fusion gives 0). **Accelerating**: 1.5 ≤ |a| < 5 m/s². **Steady**: |a| < 0.5 m/s².
- Usable log: at least 8 accelerating and 20 steady samples. **Lift** = log10((median accelerating ratio + 10⁻⁴) / (median steady ratio + 10⁻⁴)).
- **Rejected**: any in-flight test ratio sample above 1.
- **Slope** (positive control): Σ(innovation · a) / Σ|a|² over in-flight `estimator_innovations` samples, north and east together, in seconds. It needs at least 8 samples at ≥ 1.5 m/s².
- A log counts if fresh-2026 passed it (`gps_lag.py` 0.1.0's gates; not simulated) and it is usable here. The mismatch is that log's `lag_minus_param_ms`. **Mismatched** means |mismatch| > 50 ms, the rule px4-log-health's checkup uses.

## Checks

Intervals are seeded bootstrap 95% intervals (seed 20261103, 2,000 resamples).

- **E0 (enough data):** at least 60 usable logs. If E0 fails, everything below is reported as exploratory only.
- **S0 (positive control):** Spearman ρ(slope, signed mismatch) ≥ 0.5, on logs with a slope (at least 30). If S0 fails, this way of reading the logs does not see the mismatch, and M1-M3 are reported but decide nothing.
- **M1 (it shows):** Spearman ρ(|mismatch|, lift) > 0, with the interval above 0 (at least 30 logs).
- **M2 (it shows, by the checkup's rule):** median lift of mismatched logs − median lift of the others > 0, with the interval above 0 (at least 15 logs each side).
- **M3 (it does not add rejections):** the share of mismatched logs with any rejection, minus that share among the others: the interval's upper end is below +10 percentage points (at least 15 each side).

Our expectation from the arithmetic above is that S0, M1, M2 and M3 all hold. M1 or M2 could still fail, because the acceleration bins mix other causes (vibration, attitude error, wind) into the ratio.

## Decisions written in advance

- **D1:** if E0, S0 and M1 hold, px4-log-health's checkup, in its GPS delay section for a mismatched log, adds: "On public PX4 logs, a delay this far off went with higher EKF2 GPS velocity test ratios while accelerating (median lift X vs Y)", with X and Y from this study.
- **D2:** if D1 fires and M3 holds, the line adds: "but not with more GPS velocity rejections." If M3 fails, it says instead that mismatched logs saw more rejections, with the two shares.
- If S0 or M1 fails, the checkup does not change, and the write-up says the mismatch was not visible in EKF2's test ratios on these logs.
- `mismatch/logs.jsonl` is fresh-2026's `logs.jsonl` (the `mm_` fields ride on the same rows). `mismatch/summary.json` and a `GRADE.md` are published whatever the outcome. If the job is stopped from outside, its partial rows are not scored.

## How it runs, and what it costs fresh-2026

`fresh_mm.py` runs `fresh.py` 0.1.0 unchanged. It only wraps `rate.read_rate`: the wrapper returns exactly what `rate.read_rate` returns (or, if that raises, exactly the fields `fresh.py` would set), plus the `mm_` fields. `fresh.py`'s checks never read `mm_` fields, so its `summary.json` is the one `fresh.py` alone would write. Flight Review still sees one download per log. Reading four more topics adds roughly one to two seconds per log, inside fresh-2026's fixed 215-minute budget, so a few percent fewer logs may be attempted. fresh-2026's sizing (about 890 attempts, about 25 M8 expected against 15 needed) leaves room for that.

## Exploratory (not predicted)

Lift, accelerating ratio and 95th-percentile ratio by |mismatch| band (≤25, 25-50, 50-100, >100 ms); GPS later vs earlier than its setting; slope ÷ mismatch (the share of the mismatch the filter shows).

## Limits

- Flight Review uploads are self-selected, often after a problem.
- The acceleration bins are within each log, but logs that manoeuvre harder may still differ in other ways (frame, vibration, wind) that also raise the ratio while accelerating.
- `vehicle_local_position` acceleration is EKF2's own estimate. The test ratio is logged every 500 ms, so short manoeuvres are under-sampled.
- One log per vehicle. Nothing here measures position accuracy, and nothing here is about ArduPilot.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
