# receiver-confirm: does the M9 gap hold on vehicles receiver-2026 never saw? (pre-registration)

Written and committed before any log for this check was downloaded. `confirm.py` (0.1.0) and `test_confirm.py` are committed with this plan, and the job that runs them waits until this file is on main.

## Why

receiver-2026 ([`GRADE.md`](GRADE.md)) failed its E1 (too few logs per u-blox class), so all of its results are exploratory. Its clearest one: on PX4, u-blox M9 receivers showed a median GPS lag of 71.3 ms (n 25), against 146.6 ms for M8 (n 15) and 142.6 ms for F9P (n 16). The M8 − M9 interval was 52.9 to 106.5 ms. This was found, not predicted, so it needs vehicles that study never saw.

## Sample: lags that were published before the finding

The two earlier samples left out of receiver-2026 are such vehicles. Their lags were measured with the same `gps_lag.py` 0.1.0 and published before receiver-2026 was planned:

- px4-gps-lag `studies/fleet-2026/v1/logs.jsonl` at 62a205e (graded in 1c5f672, 2026-10-30): 164 passed logs from 115 vehicles.
- px4-log-health `studies/fleet-health-2026/logs.jsonl` at 07c8e1f (graded in c3cc5af, 2026-10-30): 98 passed logs from 98 other vehicles.

Neither recorded the receiver model. `confirm.py` takes one passed log per vehicle (its earliest attempt; a vehicle in both files is taken once, from fleet-2026). It downloads each log again from Flight Review, reads the receiver class with receiver-2026's `read_receiver` (`receiver.py` 0.1.0 at f654f61, unchanged), and deletes the log.

**The lags scored are the published ones, not new measurements.** Only the receiver class is new, so the lags can't have been tuned after the finding. Each log's lag is also measured again with `gps_lag.py` 0.1.0, but only for the integrity check E0.

Downloads follow the same rules as before: 6 s apart, stop at once on HTTP 403/444, a 120-minute budget, no position read, vehicle ids only as a hash. Flight Review deletes uploads after 12 months, so some October-2025 logs may be gone. Those count as "missing" and are reported.

## Checks

Intervals are receiver.py's seeded bootstrap 95% intervals of the difference of medians (2,000 resamples, seed 20261101).

- **E0 (same lag again):** at least 90% of re-read logs get a re-measured lag within 1 ms of the published one. If E0 fails, the checks are still scored on the published lags, and the grade says so.
- **E1 (enough data):** ubx_m8, ubx_m9 and ubx_f9p each have at least 10 re-read logs. If E1 fails, everything below is exploratory only.
- **C1 (M9 below M8):** median(M9) − median(M8) ≤ −20 ms, and the interval lies below 0.
- **C2 (M9 below F9P):** median(M9) − median(F9P) ≤ −20 ms, and the interval lies below 0.
- **C3 (F9P no faster than M8):** median(F9P) − median(M8) ≥ −20 ms, which receiver-2026 suggested (−4 ms).
- **C4 (a per-class delay helps):** in classes with at least 10 re-read logs (DroneCAN included; "unknown", "multiple" and other types excluded), each vehicle's class median (leave-one-out) puts at least 5 points more vehicles within 50 ms than 110 ms does.
- **C5 (the default sits between):** median(M9) < 110 ms < both median(M8) and median(F9P).

## Decisions written in advance

- **D1:** if E1, C1 and C2 hold, px4-log-health's checkup gets a line in its GPS delay section for M8, M9 and F9P receivers: "PX4 vehicles with this receiver on public logs: median X ms (n vehicles; receiver-2026 + receiver-confirm)". The README of px4-gps-lag then states the M9 gap as a result. The line is a pointer, not a setting: per-vehicle measurement stays the advice. If C1 or C2 fails, the README says the M9 gap did not replicate, and no line is added.
- **D2:** PX4 measurements only. They say nothing about ArduPilot's lag on ArduPilot vehicles.
- Whatever the outcome, `logs.jsonl`, `summary.json` and a `GRADE-confirm.md` are published, including any check that fails.

## Exploratory (not predicted)

- Classes by sample (fleet-2026 vs fleet-health-2026) and by PX4 release.
- Pooled class medians over receiver-2026 and this check.
- Why the M9 might be faster. In PX4 v1.15.4's driver, M9 runs at 8 Hz, F9P at 10 Hz and M8 at 5 Hz, so the configured rate alone does not order them. This is described, not tested.

## Limits

- The earlier samples are random draws of Flight Review's public logs, like receiver-2026's, so they share its biases. Uploads are self-selected, and logs over 80 MB are skipped.
- fleet-2026 has more PX4 v1.11-v1.12 logs. If older releases record the receiver model less often, the classes shrink. E1 guards this.
- Logs deleted under the 12-month retention can't be re-read. If deletion depends on age, and age correlates with receiver, the sample tilts toward newer logs.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
