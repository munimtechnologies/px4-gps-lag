# mismatch-2026 graded against PLAN.md

Plan: [`PLAN.md`](PLAN.md), committed before any log for this study was downloaded. The logs are fresh-2026's ([`../receiver-2026/GRADE-fresh.md`](../receiver-2026/GRADE-fresh.md)): job `px4-gps-lag-fresh-v1`, 2026-11-01 16:14-19:17 UTC, 1,000 attempts, 298 logs passing `gps_lag.py`'s gates. `mismatch.py` 0.1.0 read its fields from the same downloads (the `mm_` fields of [`../receiver-2026/fresh/logs.jsonl`](../receiver-2026/fresh/logs.jsonl)). Scores: [`summary.json`](summary.json).

## The question

About 30% of public PX4 vehicles have a GPS more than 50 ms later or earlier than their delay setting says. Does that show in EKF2's own GPS velocity test (the test ratio, above 1 = sample rejected), and does it add rejections?

## Checks

256 passing logs were usable (24 had too few samples in one of the acceleration bins, 11 had no `estimator_innovation_test_ratios`, 1 never left the ground). 93 were mismatched (more than 50 ms off their setting) and 163 were not.

| Check | Rule | Result | |
|---|---|---|---|
| E0 | ≥ 60 usable logs | 256 | **holds** |
| S0 | positive control: Spearman ρ(innovation slope, signed mismatch) ≥ 0.5 | **ρ = 0.64** (0.56 to 0.72), n 256 | **holds** |
| M1 | Spearman ρ(\|mismatch\|, lift) > 0, interval > 0 | **ρ = 0.26** (0.15 to 0.37) | **holds** |
| M2 | median lift, mismatched − others > 0, interval > 0 | **+0.19** (0.10 to 0.31), n 93 vs 163 | **holds** |
| M3 | share with any rejection, mismatched − others: interval's upper end < +10 points | +4.5 points (−5.3 to **+14.2**) | **fails** |

Lift is log10 of the median test ratio while accelerating (1.5 to 5 m/s²) over the median in steady flight (below 0.5 m/s²). Our expectation, written in the plan, was that all four would hold. M3 did not.

## What it means

- **A wrong GPS delay shows in EKF2's own GPS check.** On logs within 50 ms of their setting, the velocity test ratio while accelerating was a median 1.7 times its steady-flight value (lift 0.24). On mismatched logs it was 2.7 times (lift 0.43). The larger the mismatch, the larger the lift (M1).
- **We can't say it adds no rejections.** 20.4% of mismatched logs had at least one GPS velocity sample rejected in flight, against 16.0% of the others. The difference, +4.5 points, is within chance, but the interval reaches +14 points, above the plan's +10 limit. So M3 fails: the data don't rule out a real increase of that size.
- **The positive control held.** The innovation slope against acceleration follows the signed mismatch (ρ 0.64), as it did on earlier samples (innov-confirm: Spearman +0.86).

## Decisions, as written

- **D1 fires** (E0, S0 and M1 hold). px4-log-health's checkup, in the GPS delay section of a log more than 50 ms off, adds: "On public PX4 logs, a delay this far off went with higher EKF2 GPS velocity test ratios while accelerating (median lift 0.43 vs 0.24)".
- **D2, the M3-fails branch:** the line says that mismatched logs saw more rejections, with the two shares (20% vs 16%). The checkup also says that the difference is within chance, because the interval runs from −5 to +14 points.

## Exploratory (not predicted)

| \|mismatch\| | logs | median lift | ratio, accelerating vs steady |
|---|---|---|---|
| ≤ 25 ms | 87 | 0.24 | 1.7× |
| 25-50 ms | 76 | 0.26 | 1.8× |
| 50-100 ms | 57 | 0.48 | 3.0× |
| > 100 ms | 36 | 0.41 | 2.6× |

- The lift steps up past the 50 ms line rather than growing steadily. That is the line the checkup already uses.
- 59 mismatched logs had a GPS later than its setting, 34 earlier.
- The innovation slope was a median 0.18 of the mismatch. That is less than the 0.6 the plan's arithmetic assumed (from innov-confirm). Two things this study does differently may explain it. The acceleration here is EKF2's own `vehicle_local_position` estimate, averaged over 0.4 s. And the innovations are sampled every 500 ms. We have not tested which one it is.
- As the plan's arithmetic expected, the ratios stay small. In every band the median test ratio while accelerating was 0.002 to 0.005 and the median 95th percentile at most 0.035, far below the rejection line of 1. Rejections, where they happen, are rare spikes well above these levels.

## Limits

- Flight Review uploads are self-selected, often after a problem. One log per vehicle.
- Logs that manoeuvre harder may differ in other ways (frame, vibration, wind) that also raise the ratio while accelerating. The lift compares bins within each log, which removes some of that, not all.
- Test ratios are logged every 500 ms, so short manoeuvres are under-sampled. Nothing here measures position accuracy, and nothing is about ArduPilot.
- The mismatch is against `EKF2_GPS_DELAY`. The 3 passing logs from PX4 v1.18 have no such parameter and have no mismatch value here.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
