# rate2-2026: grade

Graded 2026-11-02 against [`PLAN-rate2.md`](PLAN-rate2.md), which was committed (fd33d25) before any fresh-2026 log was downloaded. `rate2.py` 0.1.0, unchanged, scored fresh-2026's published rows ([`fresh/logs.jsonl`](fresh/logs.jsonl)) in a sealed run (`px4-gps-lag-rate2-v1`: `test_rate2` passed, then `rate2.py --logs logs.jsonl`). It read no flight log. Its output is [`rate2/summary.json`](rate2/summary.json).

## Checks

| check | rule | result | |
|---|---|---|---|
| G0 | M8, M9 and F9P each ≥ 8 gridded passing logs with a scored release | M8 **5**, M9 16, F9P 21 | **failed** (M8) |
| G1 | in each class ≥ 80% on the interval its release asks for | not scored (G0 failed) | — |
| G2 | new driver (v1.16/v1.17): median lag of M9 at 100 ms − F9P at 200 ms ≤ −20 ms, 95% interval below 0, ≥ 8 logs each | **−110.4 ms** (−132.2 to −60.1), 12 M9 and 18 F9P logs | **held** |

The plan expected about 12 M8, 25 M9 and 9 F9P logs. The sample held fewer M8 and M9 logs and more F9P logs than that. M8 receivers were 4% of passing fresh-2026 logs, so the M8 gate failed for the same reason fresh-2026's E1 did.

Reported but not scored, because G0 failed: all 42 gridded, era-known M8, M9 and F9P logs ran at the interval their release's driver asks for (M8 5 of 5, M9 16 of 16, F9P 21 of 21; old driver 8, new driver 34). This matches the after-the-fact re-score in [`GRADE-rate.md`](GRADE-rate.md) (M8 11/11, M9 33/34, F9P 13/14) on new logs, but it is not a pre-registered result.

## Decisions

- **D1 (rate line in px4-log-health's checkup): does not fire**, because G0 failed. The checkup gets no measurement-rate line.
- **D2: G2 held.** On PX4 v1.16 and v1.17, the M9 measures twice as often as the F9P (10 Hz against 5 Hz) and is still about 110 ms less late. On v1.12-v1.15 the M9 measured *less* often than the F9P (8 Hz against 10 Hz) and was also less late ([`GRADE-rate.md`](GRADE-rate.md), Q2). So which receiver measures faster does not explain why the M9 is less late.

## Reported, not predicted

| | logs | median lag |
|---|---|---|
| M9, old driver (125 ms) | 4 | 89.5 ms |
| M9, new driver (100 ms) | 12 | 67.7 ms |
| F9P, old driver (100 ms) | 3 | 119.1 ms |
| F9P, new driver (200 ms) | 18 | **178.1 ms** |

- No M10 log was scored (0 of 0).
- Logs by driver era: old 112, new 94, not scored 92 (v1.18 pre-releases, v1.15 development builds, forks and missing versions).
- `rate2.py` counted 0 new-driver F9P logs with no grid and a 140-150 ms step (the F9P L1L5 case). Two passing v1.16 F9P rows do have a logged interval of 143 ms (`logged_dt_ms`) and no grid. The plan's count uses a different field, and this was not looked into further.

**Exploratory.** Both receivers were later when they measured less often: M9 at 8 Hz 89.5 ms against 67.7 ms at 10 Hz, F9P at 10 Hz 119.1 ms against 178.1 ms at 5 Hz. The old-driver groups hold only 3 and 4 logs, so this is no more than a pointer. The figure that matters in practice is the F9P at 5 Hz. On PX4 v1.16 and v1.17 its median lag of 178 ms is about 70 ms more than PX4's 110 ms default. Looking at fresh-2026's single-receiver F9P rows at 5 Hz after this grade, the lags also look like two groups: 10 logs between 115 and 148 ms, 11 between 177 and 235 ms, and none between 150 and 175 ms. Both observations come from data already seen, so they are tested on a new sample in [`studies/f9p-2026/PLAN.md`](../f9p-2026/PLAN.md), written before that sample is drawn.

## Limits

The plan's own limits apply. The grid is read from solutions that reach PX4, so dropped epochs could make 10 Hz look like 5 Hz. The era is read from the version string, not from each build's driver code. Forks and custom builds can set other rates. Lags are PX4 measurements against `vehicle_gps_position.timestamp` (`gps_lag.py`), so they include how PX4 configures and reads each receiver, not only the chip.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
