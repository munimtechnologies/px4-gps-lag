# receiver-confirm: grade

Graded against [`PLAN-confirm.md`](PLAN-confirm.md), committed in fc29b29 before any log for this check was downloaded. The job fetched the plan, `confirm.py` 0.1.0 and `test_confirm.py` from main and recorded their sha256 in `confirm/job-fetched.json`. It used `receiver.py` 0.1.0 from f654f61 (sha256 `8077de08…`, the file receiver-2026 ran), with `gps_lag.py` 0.1.0 and `fleet.py` 0.1.1 from 62a205e. The published lags it scored came from px4-gps-lag `studies/fleet-2026/v1/logs.jsonl` at 62a205e and px4-log-health `studies/fleet-health-2026/logs.jsonl` at 07c8e1f. The verdicts below are the mechanical `checks` in `confirm/summary.json`. Every per-log row is in `confirm/logs.jsonl`.

The run went from 2026-10-31 08:32 to 09:08 UTC. The unit tests passed first (test_confirm, test_receiver, test_gps_lag, test_fleet). Flight Review never blocked the run, and the whole sample fitted in the budget.

## Sample

- 213 vehicles: one passed log each, 115 from fleet-2026 and 98 from fleet-health-2026. **All 213 logs could still be downloaded.** None had been removed under Flight Review's 12-month retention yet.
- 168 logs got a receiver class from the log itself (vehicle_gps_position or the only sensor_gps). 22 were blended from several receivers ("multiple"), and 23 named no receiver ("unknown"). 14 of the 23 unknowns are PX4 v1.11 logs.

| class (PX4 devtype) | vehicles | median lag (published) | p25-p75 |
|---|---:|---:|---:|
| u-blox M9 (0xA9) | 32 | **76.2 ms** | 63.3-94.5 |
| DroneCAN / UAVCAN | 49 | 92.9 ms | 73.1-105.5 |
| multiple receivers, blended | 22 | 109.4 ms | 80.2-126.8 |
| unknown | 23 | 105.7 ms | 49.5-140.8 |
| u-blox, model not detected (0xA5) | 27 | 130.3 ms | 110.5-154.9 |
| u-blox F9P (0xAA) | 27 | **143.5 ms** | 121.7-177.9 |
| u-blox M8 (0xA8) | 7 | **150.9 ms** | 102.0-222.1 |
| NMEA (0xAB) | 16 | 230.9 ms | 136.6-254.4 |
| MAVLink sim (0xAF), other I2C, M10, Septentrio, Femtomes | 4, 3, 1, 1, 1 | | |

## E1 failed again, so every result below is exploratory

| check | as written | result |
|---|---|---|
| E0: ≥ 90% of re-read logs re-measure within 1 ms of the published lag | **held** | 213 of 213 (100%) |
| E1: M8, M9 and F9P each have ≥ 10 re-read logs | **failed** | M9 32, F9P 27, **M8 7** |
| C1: M9 − M8 ≤ −20 ms, interval below 0 | not scored | M8 has fewer than 10 logs |
| C2: M9 − F9P ≤ −20 ms, interval below 0 | held as written | **−67.3 ms**, 95% interval −101.0 to −48.4 |
| C3: F9P − M8 ≥ −20 ms | not scored | M8 has fewer than 10 logs |
| C4: per-class delay puts ≥ 5 points more vehicles within 50 ms than 110 ms | held as written | 74.2% → 82.8% of 151 vehicles in 5 classes (+8.6 points, leave-one-out) |
| C5: median(M9) < 110 ms < median(M8), median(F9P) | not scored | needs E1 |

**Decision D1 does not fire.** It needed E1, C1 and C2. px4-log-health's checkup gets no per-receiver line. Per-vehicle measurement stays the advice.

**Why E1 failed.** The plan expected M8 at about receiver-2026's share (9% of passed logs). M8 turned out to be 3% here (7 of 213). fleet-2026 holds many PX4 v1.11-v1.12 logs, and those name a receiver less often (the plan's second limit). The lesson from receiver-2026 applied again: we sized a class check from a share that didn't hold. The M8 comparison has to wait for more M8 logs.

## What it shows (exploratory)

1. **On 59 vehicles receiver-2026 never saw, the M9 again came out far less late than the F9P: 76 ms against 144 ms.** That is −67 ms, interval −101 to −48. receiver-2026 had −71 ms on 25 and 16 other vehicles. The gap shows up in each earlier sample on its own: in fleet-2026, M9 74.5 ms (n 19) against F9P 135.6 ms (n 16); in fleet-health-2026, M9 86.6 ms (n 13) against F9P 179.0 ms (n 11). It also holds within releases. The M9's median by PX4 release runs from 59 to 102 ms (v1.12-v1.18), and the F9P's from 125 to 186 ms (v1.12-v1.16). No release group of M9 logs sits as high as any release group of F9P logs.
2. **The M8 can't be judged from this check.** Its 7 logs have a median of 151 ms, close to receiver-2026's 147 ms, but 7 is too few to score.
3. **DroneCAN GPS sat below the serial u-blox classes here too** (93 ms). These are the same vehicles behind the bus-level comparisons in the two earlier studies, so this adds no new evidence. It was not a scored check.
4. **NMEA receivers lagged the most: a median of 231 ms (n 16), 10 of them on v1.15 at 245 ms.** That is about twice PX4's default 110 ms. The finding wasn't predicted, and the class is small and mixed (any receiver PX4 reads as NMEA), so it needs its own check before anyone relies on it.

**Pooled over receiver-2026 and this check** (descriptive only; one log per vehicle; the two sets share no vehicle):

| class | vehicles | median lag |
|---|---:|---:|
| u-blox M9 | 57 | 73.6 ms |
| DroneCAN | 88 | 97.9 ms |
| u-blox, model not detected | 46 | 128.1 ms |
| u-blox F9P | 43 | 143.5 ms |
| u-blox M8 | 22 | 148.8 ms |
| NMEA | 29 | 206.5 ms |

Plainly: the M9 being much less late than the F9P is no longer a one-sample finding. It has now appeared, with an interval far from 0, on two sets of vehicles that share none. But the plan said a failed E1 makes everything exploratory, so we don't call it confirmed. The M9-vs-M8 gap still rests on receiver-2026 alone.

## Next

Why would the M9 be less late? PX4's GPS driver gives each model a different measurement rate: M8 200 ms (5 Hz), M9 125 ms (8 Hz) and F9P 100 ms (10 Hz). So the configured rate doesn't simply order the lags. A pre-registered follow-up reads each log's real measurement rate from the phase of the receiver's own UTC time stamps. It then tests whether the rate explains the lag, using the lags already published here and in receiver-2026.

## Limits

- E1 failed, so the M8 class is tiny (7) and every comparison is exploratory.
- The lags were measured and published before the receiver was read, so they couldn't be tuned to the finding. But the receiver classes come from the same kind of public, self-selected uploads as receiver-2026's, and the two share its biases.
- The lag runs from the measurement to PX4's timestamp. It mixes the receiver's own latency with the baud rate, the message load and how PX4 configures each model. A class difference may come from that configuration, not from the chip.
- One log per vehicle. Vehicles in a class may share other traits (frame, flight controller, integrator's GPS module).
- These are PX4 measurements only. They say nothing about ArduPilot's lag on ArduPilot vehicles (D2).

## Files (`confirm/`)

- `logs.jsonl`: one row per vehicle. It has the log id, a hashed vehicle id, the sample it came from, the published lag, the re-measured lag, the receiver class with its source and device_id, and the best fix type. No positions are included.
- `summary.json`: the scored checks and the exploratory tables, exactly as the job wrote them.
- `job-fetched.json`: sha256 of every file the job fetched.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Data from PX4 Flight Review public logs (CC BY 4.0). Text CC BY 4.0, code Apache-2.0.
