# f9p-2026: grade

Plan: [`PLAN.md`](PLAN.md), committed 2026-11-02 before the sample was drawn. Graded 2026-11-03 from the sealed job's own output: `f9p-summary.json` (from `f9p.py` 0.1.0), `summary.json`, `mismatch-summary.json`, `nis-summary.json`, `f9p-extra.jsonl` and `logs.jsonl`, all in this folder. `job-fetched.json` records the sha256 of every file the job ran. The plan and the three scripts were the same files the first run fetched.

**Run.** The first run (`px4-gps-lag-f9p-v1`) was stopped from outside the job after 53 minutes (exit 143, a machine restart, not the code). Its partial rows were not scored or looked at. The second run drew the same seeded sample (seed 20261109) in full on 2026-11-02, 14:00-16:51 UTC: 1,000 download attempts, 835 logs downloaded, 310 passing `gps_lag.py`. The draw left out every log and vehicle of fleet-2026, fleet-health-2026, receiver-2026 and fresh-2026. Every test passed first, and the exploratory pass re-read every passing F9P log.

## Checks

| | rule | result | |
|---|---|---|---|
| **E0** | ≥ 12 qualifying F9P logs | **12** | held (just) |
| **P1** | median lag ≥ 150 ms, 95% interval above 110 ms | **122.2 ms** (105.7 to 191.9) | **failed** |
| **P2** | ≥ 35% more than 50 ms later than their own setting | **33.3%** (4 of 12) | **failed** |
| **P3** | ≥ 25% at ≤ 150 ms, ≥ 25% at ≥ 175 ms, ≤ 15% between | **66.7% / 0% / 33.3%** | held |
| **P4** | median(M9) − median(F9P) ≤ −50 ms, interval below 0 | **−46.5 ms** (−117.0 to −26.8); 20 M9 logs, median 75.7 ms | **failed** (narrowly) |
| R1 | mismatch-2026's M2, re-scored | difference in log10 lift +0.06 (−0.06 to +0.26) | did not replicate |
| R2 | nis-2026's N1, re-scored | median position NIS **0.0076** (0.0064 to 0.0094), 289 logs | replicated |

We predicted that E0, P1 and P4 would hold, that P2 was less certain and that P3 was the least certain. The result was close to the reverse: P3 held, while P1, P2 and P4 failed.

## Decisions, as the plan wrote them

- **D1 does not fire** (P1 and P2 failed). The checkup gets no F9P line, and no PX4 issue is opened.
- **D3 fires.** The 178 ms F9P-at-5-Hz figure came from one sample (fresh-2026) and **did not replicate**. On this sample the median is 122 ms, 12 ms over the 110 ms default. README updated.
- **D2: the two groups replicated.** Again there were no logs between 150 and 175 ms: 8 logs at 82-144 ms and 4 at 185-239 ms. The plan says a field that separates the groups cleanly in both samples becomes the next pre-registered question. See below.

What changed between the samples is the mix: fresh-2026 had 11 of 21 logs in the high group, this sample 4 of 12. So the median depends on how many high-group vehicles a sample happens to contain. A single "F9P at 5 Hz" figure is the wrong summary.

## Replications (copied from the pinned code's output)

- **mismatch-2026** (266 usable logs). S0 held: the innovation lean follows the measured mismatch, Spearman 0.64 (0.55 to 0.72). M1 held: the lift rises with the size of the mismatch, Spearman 0.17 (0.05 to 0.28). M2 did not replicate: mismatched logs' lift was not clearly above matched logs' (+0.06, interval −0.06 to +0.26). M3 failed again, as in the first sample: mismatched logs showed more velocity rejections, 18.4% against 11.9%, interval −2.6 to +15.3 points. So the dose-response (M1) held twice, while the mismatched-versus-matched split (M2) held once in two tries.
- **nis-2026** (289 usable logs). All four checks held again: position NIS median 0.0076, velocity 0.023, 1 s autocorrelation 0.76 for position and 0.34 for velocity. These are within 0.001, 0.001, 0.02 and 0.02 of the first sample.
- **fresh-2026's receiver checks**, recomputed on the new rows and reported only. E1 held this time (28 M8, 41 M9 and 36 F9P logs). The median lags were 82.7 ms (M9), 131.4 ms (F9P) and 173.4 ms (M8). F1 held, M9 − M8 = −90.7 ms (−111.1 to −63.9), and F2 held, M9 − F9P = −48.7 ms (−72.4 to −21.1). F5 held: a per-receiver default would bring 8.9 points more logs within 50 ms. F3, F4 and F6 failed. This is the **fourth sample** in which the u-blox M9 is the least-late u-blox receiver on PX4.

## Exploratory, not predicted: what separates the two groups?

`f9p_extra.py` re-read the GPS parameters of the 12 qualifying logs (`f9p-summary.json`, `explore.per_log`):

| group | lag (ms) | release | `GPS_UBX_DYNMODEL` |
|---|---|---|---|
| high | 239.1 | v1.16.2-0 | **6** |
| high | 202.4 | v1.16.0 | **6** |
| high | 198.8 | v1.16.1 | **6** |
| high | 185.0 | v1.16.0 | **6** |
| low | 144.2 | v1.17.0 | 7 |
| low | 131.9 | v1.16.1-0 | 8 |
| low | 112.4 | v1.17.0 | 7 |
| low | 111.5 | v1.17.0 | 7 |
| low | 106.2 | v1.16.1-0 | 7 |
| low | 105.1 | v1.17.0 | 7 |
| low | 95.0 | v1.17.0-64 | 7 |
| low | 81.7 | v1.17.0-64 | 7 |

- **`GPS_UBX_DYNMODEL` separates them exactly.** All four high logs use the u-blox dynamic model 6 ("airborne <1g"). All eight low logs use 7 (PX4's default, "airborne <2g") or 8 ("<4g").
- **The release does not.** Here every v1.17 log is in the low group. But in fresh-2026's published rows (looked at while grading, from `lag_minus_param_ms` and `ver_sw_release`), its six passing serial F9P logs on v1.17 split three and three: three were 70-104 ms later than their own delay setting, and three were 10-34 ms later.
- **Nothing else looked at separates them.** The constellation setting (`GPS_1_GNSS`) was 0 in 11 logs and 31 in one high log. `GPS_UBX_BAUD2` was 230400 in all 12, and the median satellite count was 28-32. The groups also mixed flight controllers (FMU v5/v6C/v6X, ARK, Cube Orange+, MicoAir) and RTK use (fix type 6 in 2 low and 3 high logs).

Twelve logs are too few to call this a finding. fresh-2026's F9P logs never had their parameters read. So, following D2, the next question is pre-registered before any of those parameters are read: [`../dynmodel-2026/PLAN.md`](../dynmodel-2026/PLAN.md). It reads the dynamic model of every u-blox log in the three earlier samples and leaves out these 12.

## Limits

- 12 qualifying F9P logs is the minimum the plan allowed. With so few logs, a sample's median depends on its group mix (see above).
- Flight Review uploads are self-selected and often follow a problem.
- The lag is measured against the time PX4 received the GPS solution.
- The exploratory table is descriptive. Out of the many parameters read, one was bound to line up with 12 logs by chance more often than one might think.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0.
