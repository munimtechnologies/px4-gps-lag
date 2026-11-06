# upgrade-2026, extension: more tries per vehicle, scored only on new pairs (plan)

Pre-registered on 2026-11-06, after upgrade-2026's first run was graded ([`GRADE.md`](GRADE.md): E0 failed, D3) and before any log for this extension is downloaded. Code: [`extend.py`](extend.py) 0.1.0 (it imports `upgrade.py` 0.1.0 unchanged), tests [`test_extend.py`](test_extend.py). The sealed job waits until this plan and both files are on `main` and checks that its own copies are identical. It also checks that `upgrade.py` and `gps_lag.py` are the copies the first run used (`e6b3dcac…`, `3338d743…`). Only then does it read Flight Review's public list.

## Why

The first run visited all 139 multicopters with eligible logs on both PX4 v1.16 and v1.17. With at most 3 tries a side, it found 10 pairs, against the 12 its plan needed. Most attempts failed for reasons that belong to one flight rather than to the vehicle: the IMU explained too little of the GPS velocity change (103), too few in-flight GPS pairs (32), too little manoeuvring (27). Another flight of the same vehicle often passes, so more tries per vehicle should find more pairs.

## What we have already seen

- The first run's 357 rows (`v1/rows.jsonl`), including the 10 pairs and their differences (median +84.6 ms; 9 of 10 switched from model 6 to 7).
- The v1.16 lags of 17 vehicles whose v1.16 log counted but whose v1.17 logs did not within 3 tries. These v1.16 rows are reused here as they are.
- No v1.17 lag of any vehicle outside the 10 pairs, and no log beyond the first 3 tries of any side.

## Design

- **Vehicles.** Every vehicle with eligible logs on both releases in today's list (the same filters as `upgrade.py` 0.1.0), plus every vehicle the first run tried, **minus the 10 vehicles paired in the first run**. They are visited in a new seeded order (seed 20261115).
- **Logs, per side.** The first run's attempts come first, in their order. They are reused from `v1/rows.jsonl` without a download, and re-judged with the same `usable()` rule. Then come the vehicle's untried logs in a seeded order. Attempts continue until one counts, or until **10 attempts in all** have been made on that side (the first run's included). A log counts exactly as in the first plan, and the v1.17 log needs the same u-blox device type as the v1.16 log.
- **Limits.** 60 new pairs, 450 downloads or 200 minutes, whichever comes first. Downloads go one at a time, 6 s apart, and stop at once on HTTP 403 or 444. Logs over 80 MB are skipped. Each log is deleted once measured, no position is read, and vehicle ids are published only as `sha256(uuid)[:12]`.
- **Measure.** For each new pair, d = lag(v1.16) − lag(v1.17), with `gps_lag.py` `3338d743…`. Intervals are percentile bootstraps of the median over vehicles (2,000 resamples, seed 20261116; +1 for the switched, +2 for the unchanged).

## Predictions (new pairs only)

| | rule | our prior |
|---|---|---|
| **X0** | at least 8 new pairs | about even |
| **X1** | median d ≥ +20 ms, and the interval's lower end > 0 | likely, if X0 |
| **X2** | at least half of the new pairs switched (model 6 on v1.16, 7 on v1.17) | likely (9 of 10 in the first run) |
| **X3** | median d of the switched new pairs ≥ +30 ms (scored only with ≥ 6 switched) | likely |
| **X4** | median d of the unchanged new pairs within ±20 ms (scored only with ≥ 4 unchanged) | probably not scored |

X1-X4 are scored only if X0 holds. A rule that cannot be scored is reported as "not scored".

## What we will do with each result

- **DX1 (X0, X1 and X3 hold):** report the within-vehicle effect of the v1.16 → v1.17 upgrade as confirmed on new pairs. This goes in px4-gps-lag's README, in px4-log-health's dynamic-model note and in the discuss.px4.io thread. It is offered once in the PR #24831 thread, together with the offer of a one-sentence addition to `GPS_UBX_DYNMODEL`'s description in `src/drivers/gps/params.yaml`.
- **DX4 (X0 and X1 hold, X3 not scored):** report that the upgrade lowered the same vehicles' lag, but do not attribute it to the model.
- **DX2 (X0 holds, X1 or X3 fails):** report that the upgrade did not lower the same vehicles' lag as predicted. px4-log-health's note would then say that the between-vehicle figure was not confirmed within vehicles.
- **DX3 (X0 fails):** publish the new pairs as a second case series. No claim. No third extension of this design.
- If X4 fails, the release itself moved the lag. Then X1 is not attributed to the model alone.

## Also reported (not graded)

- The first plan's own checks (E0, U1-U4) on all pairs, the first run's 10 included, labelled as including pairs already seen.
- How many new pairs have their v1.17 log dated on or after their v1.16 log.
- Receivers, each side's model counts and the share of logs more than 50 ms past their setting.
- Every attempt, reused or downloaded, in `rows-ext.jsonl`.

## Limits, known in advance

- The new pairs come from vehicles that the first run tried and could not pair. They may differ from the 10 that paired easily, for example by flying less, with weaker manoeuvres or with more varied logging.
- Several pairs in the first run probably share an operator. The same will be true here, so pairs are not fully independent owners.
- All of the first plan's limits still apply: two flights on different days, other v1.17 changes, self-selected uploads, and lag measured against `vehicle_gps_position.timestamp`.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
