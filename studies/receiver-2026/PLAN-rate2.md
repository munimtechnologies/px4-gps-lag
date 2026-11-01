# rate2-2026: do receivers run at the rate their PX4 release asks for? (pre-registration)

Written and committed after rate-2026 was graded ([`GRADE-rate.md`](GRADE-rate.md)) and before any log of the fresh-2026 sample was downloaded. `rate2.py` (0.1.0) and `test_rate2.py` are committed with this plan. The fresh-2026 job waits until this file and `rate2.py` are on main before it downloads anything.

## Why

rate-2026's Q1 failed: only 46% of M9 logs and 30% of F9P logs sat on the interval PX4 v1.15.4's u-blox driver asks for. Its per-log rows show why. On PX4 v1.16 and v1.17 the M9 logs sit on a 100 ms grid and the F9P logs on a 200 ms grid, the reverse of what the plan expected. The plan read the driver at v1.15.4 only. PX4-GPSDrivers commit `bbdd576` (2025-01-05, "ublox update F9P output rates") changed `configureDevice()`:

- before (`f512678` at PX4 v1.12.3, `ad769ff` at v1.15.4): F9P 100 ms, everything else on protocol 27+ 125 ms (F9P 125 ms in moving-base mode at v1.15.4);
- after (`4cea5de`, the submodule of PX4 v1.16.0 and v1.16.1; `0b96958`, PX4 v1.17.0): `int rate_meas = 100; // 10Hz` by default, `u_blox9_F9P_L1L2` 200 ms (5 Hz), `u_blox9_F9P_L1L5` 143 ms (7 Hz). The M9 now gets the 100 ms default.
- The M8 takes the older CFG-RATE path (`UBX_TX_CFG_RATE_MEASINTERVAL`, 200 ms) in both.

Re-scored by release on rate-2026's own logs, receivers nearly always ran at the rate their release asks for (M8 11/11, M9 33/34, F9P 13/14). That re-score was made after seeing the data, so it is exploratory. This plan tests the corrected rule on logs nobody has read yet.

## Data

fresh-2026's `logs.jsonl` (see [`PLAN-fresh.md`](PLAN-fresh.md)): a new seeded sample of public Flight Review logs from 2025-10 on, leaving out every log and vehicle of the earlier studies. Each row already carries `rate.py` 0.1.0's grid, `GPS_UBX_MODE`, the lag from `gps_lag.py` 0.1.0 and the receiver class from `receiver.py` 0.1.0. rate2.py reads no log. Only passing logs (`passed` true, with a lag, not simulated) count.

**The PX4 release** comes from the log's `ver_sw_release`:

- **old driver:** v1.12 to v1.14 (any build), and v1.15 builds that are not development builds;
- **new driver:** v1.16 and v1.17 (any build);
- **not scored:** v1.15 development builds (`-0`: they may come from main after the change or from the release branch before it), anything before v1.12 or from v1.18 on (not read), other major numbers (forks), and missing versions.

**Expected interval:** M8 200 ms in both. M9 (and M10): old 125 ms, new 100 ms. F9P: old 100 ms (or 125 ms when `GPS_UBX_MODE` is not 0), new 200 ms. An F9P L1L5 on the new driver runs at 143 ms, which is not one of `rate.py`'s grids, so it gets no grid and is not scored. The number of new-driver F9P logs with no grid and a typical step of 140-150 ms is reported.

**Sizing.** In rate-2026's sample, 11 of 22 M8 logs (50%), 34 of 57 M9 (60%) and 14 of 43 F9P (33%) had a grid and a scored release. With fresh-2026's expected ~25 M8, ~41 M9 and ~26 F9P passing logs, that is about 12, 25 and 9, so G0's 8 should be met, narrowly for the F9P. If G0 or G2 fall short, they are reported unscored.

## Checks

- **G0 (enough data):** M8, M9 and F9P each have at least 8 gridded passing logs with a scored release. If G0 fails, G1 is not scored.
- **G1 (receivers run at their release's rate):** in each of M8, M9 and F9P, at least 80% of those logs sit on the expected interval.
- **G2 (the rate is not the M9 story, on the new driver):** among new-driver logs, median lag(M9 on 100 ms) − median lag(F9P on 200 ms) ≤ −20 ms, with `receiver.py`'s seeded bootstrap 95% interval below 0. Scored if each side has at least 8 logs. On the old driver the M9 measured more slowly than the F9P (8 vs 10 Hz) and was less late. If it is still less late now that it measures faster (10 vs 5 Hz), the measurement rate cannot be what makes the gap.

Our expectations, written before any fresh log is read: G0 and G1 hold, G2 holds if it is scored. G2 is the least sure, because of the few new-driver F9P logs on 200 ms.

## Decisions written in advance

- **D1:** if G0 and G1 hold, px4-log-health's checkup gets an information line in its GPS section, "GPS measurement rate: N Hz (read from the receiver's time stamps)". It is not a flag, and it goes out only after a sealed test on real logs. This replaces rate-2026's D1, which did not fire.
- **D2:** if G2 holds, the px4-gps-lag README says that on PX4 v1.16+ the M9 is still less late than the F9P while measuring twice as often, so the rate does not explain the gap. If G2 fails, it says the gap shrank or vanished when the rates swapped. If G2 is unscored, it says so.
- PX4 only. Nothing here is about ArduPilot, which configures u-blox receivers itself.
- Whatever the outcome, `rate2-summary.json` and `GRADE-rate2.md` are published, including any check that fails.

## Reported, not predicted

Median lags of M9 old-driver on 125 ms, M9 new-driver on 100 ms, F9P old-driver on 100 ms and F9P new-driver on 200 ms; M10 on its expected interval; counts by driver era.

## Limits

- The grid shows the rate of solutions that reach PX4. A 10 Hz receiver logged at PX4's 100 ms limit may lose epochs, and some may read as 5 Hz.
- `GPS_UBX_RATE`-style user overrides are not in v1.16/v1.17 (`_output_rate` is not in those drivers), but forks and custom builds may set other rates. Those logs count against G1.
- The era comes from the version string, not from the driver code in each build.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
