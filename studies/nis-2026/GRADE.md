# nis-2026 graded against PLAN.md

Plan: [`PLAN.md`](PLAN.md), committed before any log for this study was downloaded. The logs are fresh-2026's ([`../receiver-2026/GRADE-fresh.md`](../receiver-2026/GRADE-fresh.md)): job `px4-gps-lag-fresh-v1`, 2026-11-01 16:14-19:17 UTC, a seeded random sample of public Flight Review logs from 2025-10 on, one per vehicle, 298 passing `gps_lag.py`'s gates. `nis.py` 0.1.0 read its fields from the same downloads (the `nis_` fields of [`../receiver-2026/fresh/logs.jsonl`](../receiver-2026/fresh/logs.jsonl)). Scores: [`summary.json`](summary.json).

## The question

PX4 RFC [#28837](https://github.com/PX4/PX4-Autopilot/issues/28837) argues from a 1-D simulation that EKF2 treats every GNSS sample as independent while real GNSS errors stay correlated for seconds to minutes. In its simulation the mean NIS is only 0.18 and the gate is more than 11 times wider than the real innovations. Is that what EKF2's horizontal GNSS innovations look like on real flights?

## Checks

285 logs were usable (11 had no `estimator_innovations`, 2 too few samples). For 168 of them, `estimator_status_flags` was used to keep only samples while GPS was being fused.

If EKF2's variances were right and its innovations Gaussian, the per-sample NIS would have a median of ln 2 = 0.693 and a mean of 1, and the innovations would be white.

| Check | Rule | Result | |
|---|---|---|---|
| E0 | ≥ 60 usable logs | 285 | **holds** |
| N1 | median position NIS < 0.347, interval too | **0.0079** (0.0065 to 0.0093) | **holds** |
| N2 | median velocity NIS < 0.347, interval too | **0.0243** (0.0200 to 0.0297) | **holds** |
| W1 | median 1 s position autocorrelation > 0.2, interval too | **0.78** (0.74 to 0.81) | **holds** |
| W2 | median 1 s velocity autocorrelation > 0.2, interval too | **0.35** (0.32 to 0.40) | **holds** |

Medians across logs of each log's median. All four held, as the plan expected. W2 was the one we were least sure of.

## What it means

- **On real flights, EKF2's GNSS innovations are far smaller than its own variances say.** The typical log's position NIS is about 1/88 of the consistent value, velocity about 1/29. The median of the per-log mean NIS is 0.027 for position and 0.087 for velocity, against 1 for a consistent filter and 0.18 in the RFC's simulation.
- **The gate is even wider than the RFC's simulation suggests.** Measured in the innovations' actual spread (gate / √mean NIS), the 5-SD gate is a median **30 SDs** wide for position and **17 SDs** for velocity. The RFC's figure from simulation was "more than 11 times".
- **Position innovations are strongly correlated; velocity ones much less.**

| lag | 1 s | 2 s | 5 s | 10 s | 20 s | 1/e time τ (median) |
|---|---|---|---|---|---|---|
| position | 0.78 | 0.60 | 0.23 | 0.08 | 0.00 | **3.7 s** (14 logs above 20 s) |
| velocity | 0.35 | 0.15 | 0.01 | −0.01 | 0.00 | **1.0 s** (none above 20 s) |

The velocity τ of about 1 s is at the limit of what 500 ms logging can resolve, so velocity innovations are close to white beyond 2 s.

## D1 fires

E0 holds, so MV2 posts **one** comment on RFC #28837 with these figures by fix type, linking here and to the per-log rows, and stating the limits below.

## Exploratory (not predicted): by fix type, receiver and rate

| modal fix type | logs | position NIS | position τ | position r(1 s) | velocity NIS | velocity τ | median eph |
|---|---|---|---|---|---|---|---|
| 3D | 117 | 0.0076 | 3.7 s | 0.81 | 0.024 | 0.9 s | 0.68 m |
| DGPS / SBAS | 110 | 0.0103 | 3.9 s | 0.79 | 0.034 | 1.1 s | 0.40 m |
| RTK fixed | 55 | 0.0044 | 2.9 s | 0.66 | 0.017 | 1.1 s | 0.01 m |
| RTK float | 2 | 0.041 | 1.0 s | 0.35 | 0.131 | 1.1 s | 0.11 m |

| receiver | logs | position NIS | position τ | velocity NIS |
|---|---|---|---|---|
| u-blox M8 | 11 | 0.0161 | 4.6 s | 0.036 |
| u-blox M9 | 29 | 0.0103 | 3.9 s | 0.041 |
| u-blox F9P | 41 | 0.0044 | 3.3 s | 0.019 |
| all others | 204 | 0.0078 | 3.7 s | 0.022 |

By measurement grid (from `rate.py`): 100 ms, 40 logs, position NIS 0.0164; 125 ms, 25 logs, 0.0053; 200 ms, 103 logs, 0.0044. Grid, receiver and fix type go together here (on PX4 v1.16+ an F9P runs at 200 ms and many F9P logs are RTK), so these splits can't separate them.

**One likely contributor, not tested here.** EKF2 floors the position observation noise at `EKF2_GPS_P_NOISE` (0.5 m by default) and velocity at `EKF2_GPS_V_NOISE` (0.3 m/s). The median reported eph was 0.38 m overall and 0.01 m on RTK-fixed logs. Wherever the receiver's own accuracy is better than the floor, the variance EKF2 uses is larger than the receiver's noise, and the NIS falls. The RFC's mechanism (correlated error that the filter partly absorbs) points the same way. This study does not separate the two.

## Limits

- **Innovations are not raw GNSS errors.** EKF2 absorbs slowly varying error into its states, so the innovations' correlation time is not the receiver's error correlation time, and is expected to be shorter. This measures what EKF2 itself sees, not the τ the RFC would put in `EKF2_GPS_P_TAU` / `EKF2_GPS_V_TAU`.
- Innovations and variances are logged every 500 ms while EKF2 fuses GPS at 5-10 Hz, so nothing faster than about 1 s is resolved.
- EKF2's own state errors, the GPS delay mismatch (see [`../mismatch-2026/GRADE.md`](../mismatch-2026/GRADE.md)), wind and vibration all add structure to the innovations. None of it is separated here.
- The first EKF2 instance only, which in multi-EKF setups is not always the selected one.
- Flight Review uploads are self-selected, often after a problem. One log per vehicle. Nothing here is about ArduPilot.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
