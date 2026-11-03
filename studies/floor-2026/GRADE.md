# floor-2026: grade

Plan: [`PLAN.md`](PLAN.md), committed 2026-11-02 before f9p-2026's sample was drawn. Graded 2026-11-03 from `floor-summary.json` in this folder, written by `floor.py` 0.1.0 inside the sealed f9p-2026 job. That job's `test_floor` ran first and passed. The job fetched the plan and code from `main` without waiting, and their sha256 are in [`../f9p-2026/job-fetched.json`](../f9p-2026/job-fetched.json). The rows are f9p-2026's [`logs.jsonl`](../f9p-2026/logs.jsonl): 1,000 attempts and 835 downloads, drawn with seed 20261109.

**Question.** EKF2 fuses each GNSS position with the noise `max(eph, EKF2_GPS_P_NOISE)` (default 0.5 m). Does that floor explain why EKF2's GNSS position NIS on real flights is about 90 times below what a consistent filter gives (nis-2026)? For each log, q = eph / max(eph, floor), so q = 1 at or above the floor and q < 1 under it.

## Checks

| | rule | result | |
|---|---|---|---|
| **E0** | ≥ 150 usable, ≥ 40 at q = 1, ≥ 60 under | 559 usable: 259 at q = 1, 300 under, 180 at q ≤ 0.5 | held |
| **F1** | Spearman ρ(q, position NIS) ≥ 0.20, interval above 0 | **ρ = 0.37** (0.29 to 0.44) | held |
| **F2** | under the floor, slope of ln NIS on ln q: interval above 0, slope ≤ 3 (floor alone: 2) | **0.42** (0.30 to 0.54) | held |
| **F3** | median NIS at q = 1 ≥ 2 × median at q ≤ 0.5, interval above 1 | **4.8×**: 0.0081 against 0.0017 (3.7 to 7.0) | held |
| **F4** | at q = 1, \|ρ(eph, NIS)\| < 0.25 | **ρ = −0.09** | held |

Our prediction was that E0, F1 and F4 would hold, that F2 would hold with a slope well under 2, and that F3 was uncertain. All five held, and the slope was 0.42.

**Replication** on fresh-2026's rows (an independent earlier sample, 538 usable logs; reported, not graded): F1 ρ = 0.29 (0.21 to 0.37), F3 3.5× (2.1 to 5.3) and F4 ρ = −0.03 all held again. F2's slope was 0.23, with an interval from −0.06 to 0.43 that touches 0, so F2 did not hold there.

## Decision, as the plan wrote it

**D1 fires** (E0, F1 and F2 held). The README states how much the floor explains, and MV2 adds the figures to his comment thread on PX4 RFC [#28837](https://github.com/PX4/PX4-Autopilot/issues/28837), once.

## What it means

- **The floor is real, but it explains only a small part.** If the floor were the whole story, NIS would fall as q² under it (slope 2). It falls far more slowly, as about q^0.4 (0.2 to 0.5 across the two samples). For an RTK-fixed receiver reporting 1.4 cm against the 0.5 m floor (q ≈ 0.03), that is a factor of about 4-5 (about 2 with the replication's slope), not about 1,000. The fix-type breakdown agrees: the median NIS was 0.0015 for RTK fixed against 0.0054 for plain 3D fixes.
- **Most of the gap remains at or above the floor.** For logs at q = 1, where EKF2 already uses the receiver's own eph, the median position NIS was still **0.0081**, about 85 times below the consistent 0.693. In other words, the innovations are roughly 9 times smaller than EKF2's own innovation standard deviation. Above the floor, NIS did not depend on eph (F4).
- **For the RFC.** The floor accounts for a factor of about 2-5 on logs well under it, which is mostly RTK and lowered `EKF2_GPS_P_NOISE` (90 of the 559 logs changed it, median q 0.07). The rest of the low NIS happens with the floor not binding. So it has to come from elsewhere, for example correlated errors or the state-uncertainty part of the innovation variance. These logs can't tell those two apart.

## Exploratory, not predicted (from `floor-summary.json`)

| | logs | median q | median eph (m) | median position NIS | share under the floor |
|---|---|---|---|---|---|
| 3D | 216 | 1.0 | 0.77 | 0.0054 | 31% |
| DGPS/SBAS | 191 | 1.0 | 0.54 | 0.0071 | 47% |
| RTK fixed | 145 | 0.034 | 0.014 | 0.0015 | 99% |
| default `EKF2_GPS_P_NOISE` | 469 | 1.0 | 0.53 | 0.0056 | 48% |
| changed `EKF2_GPS_P_NOISE` | 90 | 0.065 | 0.014 | 0.0016 | 86% |

ρ(q, velocity NIS) = 0.39. Velocity has its own floor (`EKF2_GPS_V_NOISE` against the receiver's speed accuracy), which the rows do not carry, so this figure is descriptive only.

## Limits

- There is one in-flight median of eph per log, and the floor may bind for only part of a flight.
- eph is the receiver's own estimate of its accuracy, not its true error.
- The innovation variance also contains EKF2's own state uncertainty, so q² is an upper bound on what the floor alone can do. A slope under 2 is partly expected for that reason.
- Flight Review uploads are self-selected.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0.
