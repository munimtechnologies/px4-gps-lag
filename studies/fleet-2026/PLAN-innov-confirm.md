# fleet-2026, part 3: does the corrected innovation check hold on fresh logs?

Written 2026-10-30, after `GRADE-innov.md` and before any innovation of these logs was read. By MV2 of Munim, Inc.; the plan, code and analysis are made with AI agents. Text CC BY 4.0, code Apache-2.0. Data: PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0).

## Why

The pre-registered innovation check (`PLAN-innov.md`) assumed EKF2's innovation is measurement minus prediction. PX4 computes prediction minus measurement (`_state.vel - velocity`). Graded as written, the check decided C2. With PX4's sign, the same numbers would have decided C1: Spearman +0.757, 95.1% same sign, median ratio 0.48 (`GRADE-innov.md`). That correction was found after the result was seen, so it is tested here on logs whose innovations nobody has read.

## Logs

The 98 logs (98 vehicles) that passed `gps_lag.py` 0.1.0 in px4-log-health's `studies/fleet-health-2026` (seed 20261031, one log per vehicle, none from fleet-2026's 400 logs or 337 vehicles), read from that study's `logs.jsonl` on main. Their measured lags are already published. Their innovations have not been read. They are downloaded one at a time in file order, 6 s apart, and each is deleted once measured. The run stops on HTTP 403/444, and otherwise after 100 minutes.

## Method (`innov.py` 0.2.0)

`innov.py` 0.1.0 unchanged, with one exception: **implied excess = +k** (PX4's sign), where 0.1.0 used −k. Topics, fusion time, sample filters, the ±0.1 s acceleration window and the gates (≥ 100 kept samples, acceleration RMS ≥ 0.3 m/s²) are all the same. Unit tests fly synthetic vehicles whose innovations follow PX4's sign. As a mechanical check, the same job re-scores part 2's `innov.jsonl` with the sign flipped. It must reproduce +0.757, 0.951 and 0.483.

## Checks (same thresholds as part 2)

d = `lag_minus_param_ms` from fleet-health-2026; x = implied excess.

- **VE1** at least 60 logs validated (d known and the log passes the innovation gates). Otherwise this is a pilot and decides nothing.
- **V1** Spearman(d, x) ≥ 0.3.
- **V2** of validated logs with |d| > 50 ms, at least 70% have x of the same sign. Decided only with at least 10 such logs.
- **V3** for those logs, median x / d is between 0.2 and 1.2.
- **V4** median |x| of logs with |d| ≤ 20 ms is below that of logs with |d| > 50 ms (at least 10 in each group).

## Decision

- **C1** (VE1, V1, V2 hold): the README restores D1, the measured lag as a starting value for `EKF2_GPS_DELAY` to check with EKF2 replay, and cites this confirmation.
- **C2** (VE1 holds, V1 or V2 fails): D1 stays withdrawn.
- **pilot** (VE1 fails): nothing changes.

V3 and V4 are reported and decide nothing.

## Limits

- Fewer logs than part 2. About 31% of these logs are more than 50 ms off their setting (fleet-health-2026), so V2 should have about 25-30 logs.
- Part 2's limits apply: a first-order model, shared attitude, and innovations logged at 500 ms.
- The direction of the correction is known before this run. That is the point: the run tests whether it holds on fresh data, using thresholds that were fixed before part 2.

## Reproduce

```
pip install numpy pyulog ijson requests
python fetch_deps.py
python -m unittest -v test_gps_lag test_fleet test_innov
python innov.py --rescore-v010 v1-innov.jsonl --out-dir out/v1-flipped
python innov.py --rows health-logs.jsonl --out-dir out/confirm --budget-min 100
```
