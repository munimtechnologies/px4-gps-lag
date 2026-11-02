# px4-gps-lag

How far behind the IMU is your PX4 vehicle's GPS? `gps_lag.py` measures it from a flight log (`.ulg`), against the same timestamp PX4's EKF2 subtracts `EKF2_GPS_DELAY` (default 110 ms) from.

By MV2 of Munim, Inc. The code and studies are made with AI agents. Apache-2.0.

## Use

```
pip install numpy pyulog
python gps_lag.py flight.ulg
```

It prints one JSON line per log, with `lag_ms`, its nominal standard error `se_ms`, the log's own `param_gps_delay_ms`, `lag_minus_param_ms`, the GPS bus (`serial`, `uavcan`, ...), and `passed` / `reason`. A log passes only if the flight has enough manoeuvring for the lag to be measurable (see the gates in `gps_lag.py`). Hover-only flights usually don't pass.

How it works: for each pair of consecutive logged GPS samples in flight, the change in GPS north and east velocity is compared with the IMU's acceleration (`sensor_combined`, rotated by `vehicle_attitude`) integrated over the same interval shifted back by a candidate lag. The lag that fits best, allowing a constant accelerometer bias, is the measurement. No position is read.

For a readable report per flight (health flags, fleet comparison and this GPS delay verdict), and a GitHub Action, see [px4-log-health](https://github.com/munimtechnologies/px4-log-health)'s `checkup.py`. It also runs in your browser, with nothing uploaded: [munimv2.github.io/px4-log-check](https://munimv2.github.io/px4-log-check/).

**PX4 v1.18 and newer.** PX4 PR [#26660](https://github.com/PX4/PX4-Autopilot/pull/26660) replaced `EKF2_GPS_DELAY` with a delay per receiver (`SENS_GPS0_DELAY`, `SENS_GPS1_DELAY`), applied by moving each sample's `timestamp_sample` back. `gps_lag.py` still measures the lag on those logs, but `param_gps_delay_ms` is empty. px4-log-health's checkup (0.3.2 and newer) reads the delay EKF2 applied from the log's own sample times and names the parameter to change. On 8 public v1.18 pre-release logs, that applied delay was 110.0 ms every time ([`GRADE-fresh.md`](studies/receiver-2026/GRADE-fresh.md)). PX4 main has since renamed `vehicle_gps_position` to `vehicle_gnss` (PR [#24399](https://github.com/PX4/PX4-Autopilot/pull/24399)), which `gps_lag.py` does not read yet.

## What the fleet says

On 164 public Flight Review logs from 115 vehicles (`studies/fleet-2026/GRADE.md`, pre-registered), the median lag was 99.8 ms, close to the default 110 ms. But 29.6% of logs were more than 50 ms away from their own setting, and two logs of the same vehicle agreed to a median 5.3 ms. 98% of them ran the default.

**Replicated.** On an independent sample, 98 logs from 98 other vehicles, the median was 113.8 ms and 31.2% were more than 50 ms off their setting. Both figures were inside the ranges set before that run (px4-log-health, [`studies/fleet-health-2026/GRADE.md`](https://github.com/munimtechnologies/px4-log-health/blob/main/studies/fleet-health-2026/GRADE.md), R1 and R2).

**EKF2's own residuals agree.** On those 98 fresh logs, EKF2's GPS velocity innovations, compared with acceleration, lean the way the measured mismatch says they should in 25 of 27 logs that are more than 50 ms off their setting, and the two methods rank the logs alike (Spearman +0.86). The check was pre-registered and decided C1 ([`studies/fleet-2026/GRADE-innov-confirm.md`](studies/fleet-2026/GRADE-innov-confirm.md)).

**Does the mismatch matter? It shows in EKF2's own GPS check (mismatch-2026, pre-registered).** EKF2 accepts or rejects each GPS velocity sample with an innovation test (ratio above 1 = rejected). On 256 fresh logs ([`studies/mismatch-2026/GRADE.md`](studies/mismatch-2026/GRADE.md)), the test ratio while accelerating was a median 2.7 times its steady-flight value on logs more than 50 ms off their setting, against 1.7 times on the others (difference in log10 lift +0.19, interval 0.10 to 0.31). The larger the mismatch, the larger the rise (Spearman 0.26, interval 0.15 to 0.37). 20% of mismatched logs had at least one GPS velocity rejection in flight, against 16% of the others. That gap is within chance, but the data can't rule out a real one of up to 14 points, so the plan's "no extra rejections" check (M3) failed. As the plan's rule D1 says, px4-log-health's checkup says this on every mismatched log (since 0.3.3).

**How consistent are EKF2's GNSS innovations on real flights? (nis-2026, pre-registered).** PX4 RFC [#28837](https://github.com/PX4/PX4-Autopilot/issues/28837) argues from simulation that EKF2 treats GNSS samples as independent although real GNSS errors stay correlated, which leaves its normalised innovation squared (NIS) far below 1 and its gate far wider than the real innovations. On 285 real flights ([`studies/nis-2026/GRADE.md`](studies/nis-2026/GRADE.md)), all four checks held:

- the median position NIS was **0.0079** (consistent: 0.693), velocity **0.024**;
- measured in the innovations' real spread, EKF2's 5-SD gate is about **30 SDs** wide for position and **17** for velocity (the RFC's simulation: more than 11);
- position innovations 1 s apart correlate at **0.78** (1/e time about 3.7 s), velocity ones at **0.35** (about 1 s, the limit of 500 ms logging).

Figures by fix type (3D, SBAS, RTK fixed) and receiver are in the grade. Innovations are not raw GNSS errors, so these are what EKF2 sees, not the receiver's own error correlation time.

**Is part of it just EKF2's noise floor? (floor-2026, pre-registered, running).** EKF2 fuses each GNSS position with the noise `max(eph, EKF2_GPS_P_NOISE)` (default 0.5 m; `Ekf::updateGnssPos()`), so a receiver reporting 0.3 m, or 1 cm with RTK, is still fused as 0.5 m. If that floor were the main cause, a log's NIS would scale with (eph / floor)² under it. [`studies/floor-2026/PLAN.md`](studies/floor-2026/PLAN.md) tests this on f9p-2026's new sample, drawn after the plan was committed. From the summary already seen (RTK fixed 0.0044 against 3D 0.0076), we expect the floor to explain only part of it.

## Does the receiver model matter? (exploratory, seen three times)

PX4 uses one GPS delay for every receiver up to v1.17. ArduPilot assigns a lag by u-blox generation: 120 ms for M8 "based on flight logs", and the same 120 ms for F9, M9 and M10, with the comment "F9 lag not verified yet from flight log" (`AP_GPS_UBLOX.cpp`, `get_lag`). PX4's GPS driver records the receiver model it detected in the device_id of every GPS message, and `receiver.py` reads it.

Three samples with no vehicle in common, one log per vehicle:

| receiver (as PX4 detected it) | receiver-2026: vehicles, median lag | receiver-confirm | fresh-2026 |
|---|---|---|---|
| u-blox M9 | 25, **71.3 ms** | 32, **76.2 ms** | 29, **81.3 ms** |
| DroneCAN | 39, 104.4 ms | 49, 92.9 ms | 84, 105.9 ms |
| u-blox, model not detected (includes M10 on v1.15) | 19, 127.8 ms | 27, 130.3 ms | 38, 140.9 ms |
| u-blox F9P | 16, **142.6 ms** | 27, **143.5 ms** | 42, **143.1 ms** |
| u-blox M8 | 15, **146.6 ms** | 7, **150.9 ms** | 12, **145.3 ms** |
| NMEA | 13, 150.0 ms | 16, 230.9 ms | 24, 208.4 ms |

- **receiver-2026** ([`GRADE.md`](studies/receiver-2026/GRADE.md)) was a fresh random sample of 163 passing logs. Its enough-data check (E1) failed, so it is exploratory.
- **receiver-confirm** ([`GRADE-confirm.md`](studies/receiver-2026/GRADE-confirm.md)) read the receiver model of the 213 vehicles in the two earlier samples, whose lags had been published before the M9 gap was seen. **M9 − F9P = −67.3 ms (interval −101 to −48)**. E1 failed (7 M8 vehicles).
- **fresh-2026** ([`GRADE-fresh.md`](studies/receiver-2026/GRADE-fresh.md)) was a new random sample of 298 passing logs, leaving out every earlier vehicle. **M9 − F9P = −61.8 ms (interval −88 to −42)**. E1 failed again: 12 M8 logs against the 15 needed (M8 receivers were 4% of passing logs, not the 9% the plan assumed). A per-receiver default would have brought only 2.3 points more vehicles within 50 ms of their lag (F5 failed), because the spread within each class is wide. The NMEA check (F4) failed. NMEA receivers on a 200 ms grid had a median lag of 102 ms, and those at 1 Hz 256 ms.

What this means: on PX4, the M9 was 60-75 ms less late than the F9P and the M8 in three independent samples, and the F9P and M8 were within 8 ms of each other each time. By the plans' own rules it is still exploratory, because the M8 class never reached its count, and no per-receiver line was added to px4-log-health's checkup. Knowing the model doesn't replace measuring your own vehicle. Since PX4 v1.18 the delay can be set per receiver (`SENS_GPSn_DELAY`), which is where such a measurement goes. These are PX4 measurements only and say nothing about ArduPilot's own lag.

### The measurement rate does not explain the M9 gap (rate-2026 and rate2-2026, pre-registered)

[`GRADE-rate.md`](studies/receiver-2026/GRADE-rate.md) read each of the 376 earlier logs' measurement rate from the phase of the receiver's own UTC times (`rate.py` 0.1.0), and scored the lags already published. **On the same 125 ms grid, M9 logs were 53 ms less late than the other serial u-blox logs (interval −106 to −19 ms; check Q2 held).**

Its check that receivers run at the rate PX4's driver asks for (Q1) **failed**, because the plan took the rates from PX4 v1.15.4's driver. PX4-GPSDrivers changed them in January 2025 (`bbdd576`, "ublox update F9P output rates"), and PX4 v1.16 and v1.17 ship that change:

| receiver | PX4 v1.12-v1.15 asks for | PX4 v1.16-v1.17 asks for |
|---|---|---|
| u-blox M8 | 200 ms (5 Hz) | 200 ms (5 Hz) |
| u-blox M9 | 125 ms (8 Hz) | 100 ms (10 Hz) |
| u-blox F9P L1L2 | 100 ms (10 Hz) | 200 ms (5 Hz) |
| u-blox F9P L1L5 | 100 ms (10 Hz) | 143 ms (7 Hz) |

**rate2-2026** ([`GRADE-rate2.md`](studies/receiver-2026/GRADE-rate2.md)) pre-registered the release-aware rule before fresh-2026 was downloaded and scored it on fresh-2026's rows. **On v1.16 and v1.17, the M9 at 10 Hz was 110 ms less late than the F9P at 5 Hz (−110.4 ms, interval −132 to −60; 12 and 18 logs; G2 held).** So the M9 is less late whether it measures less often than the F9P (v1.12-v1.15) or twice as often (v1.16-v1.17), and the measurement rate does not explain the gap. The plan's enough-data check G0 failed (5 M8 logs, 8 needed), so its rate check G1 was not scored. Reported only: all 42 gridded M8, M9 and F9P logs ran at the rate their release asks for. No rate line was added to the checkup.

### The F9P at 5 Hz (exploratory; f9p-2026, pre-registered, running)

On fresh-2026, the F9P at 5 Hz on v1.16/v1.17 had a median lag of **178 ms** (rate2's 18 logs), about 70 ms more than the 110 ms default. Its lags also looked like two groups, 115-148 ms and 177-235 ms. Both observations come from data already seen. They are being tested on a new sample, leaving out every earlier log and vehicle, under a plan committed before that sample was drawn: [`studies/f9p-2026/PLAN.md`](studies/f9p-2026/PLAN.md). The first run of that sample was stopped from outside the job after 53 minutes (exit 143, not an error in the code); as with receiver-2026, its partial rows are not scored or looked at, and the same seeded draw runs again in full. If you fly an F9P on PX4 v1.16 or v1.17, measure your own lag (`gps_lag.py`, or px4-log-health's checkup) rather than assume 110 ms.

## Suggested setting (rule D1)

If a passing log's `lag_minus_param_ms` is more than about 50 ms either way, the measured `lag_ms` is a reasonable **starting value** for `EKF2_GPS_DELAY` (on PX4 v1.18 and newer, for the receiver's `SENS_GPSn_DELAY`).

- Measure two or three flights first. Flights of one vehicle should agree within a few ms.
- Check the change with EKF2 log replay (PX4 docs: "EKF2 log replay") before flying it.
- Smaller differences aren't worth changing.
- This is not a calibration. The studies show that two independent methods agree on the direction and rank of the mismatch, and that the mismatch shows in EKF2's own test ratios, not that the new setting improves any one vehicle's estimate. There is no ground truth for any one vehicle.

History: D1 was withdrawn after the first innovation check came back C2 as written, because that plan had EKF2's innovation sign backwards (PX4 computes prediction minus measurement; see `GRADE-innov.md`). The corrected check was pre-registered on fresh logs and held, so D1 is back.

## Studies

- `studies/fleet-2026/`: GPS lag across a random sample of PX4 Flight Review public logs (CC BY 4.0) from 2025-10 on, compared with each vehicle's `EKF2_GPS_DELAY`. Plan, grade (E1 passed, 5 of 6 predictions held), and one line per log in `v1/logs.jsonl`. `v1/summary.json` is the same rows re-scored, and it matches the grade.
- `studies/fleet-2026/PLAN-innov.md`, `GRADE-innov.md`, `innov/`: does EKF2's GPS velocity innovation, plotted against acceleration, lean the way the measured lag says it should? Graded C2 as written. The innovation sign was wrong in the plan; see the grade.
- `studies/fleet-2026/PLAN-innov-confirm.md`, `GRADE-innov-confirm.md`, `confirm/`: the corrected check (`innov.py` 0.2.0, PX4's sign) on the 98 fresh logs from px4-log-health, with the same thresholds. 89 logs validated; C1.
- `studies/receiver-2026/`: lag by GPS receiver model (`receiver.py` 0.1.0). Plan, grade (E1 failed, so exploratory; 5 of 6 predictions held as written), `logs.jsonl`, `summary.json` and `job-fetched.json`. The first run was stopped from outside the job after 88 logs (exit 143). Its rows were never scored, and the complete second run is the one graded.
- `studies/receiver-2026/PLAN-confirm.md`, `GRADE-confirm.md`, `confirm/`: the M9 gap tested on the earlier samples' published lags (`confirm.py` 0.1.0). All 213 logs re-read; E0 held (213 of 213 re-measured within 1 ms); E1 failed (M8 7); C2 and C4 held as written; C1, C3 and C5 not scored.
- `studies/receiver-2026/PLAN-rate.md`, `GRADE-rate.md`, `rate/`: measurement rate from the receiver's UTC times (`rate.py` 0.1.0), scored on the published lags. All 376 logs re-read; E0, E1 and Q2 held; Q1 failed (the driver's rates changed in v1.16); Q4 failed; Q3 not scored.
- `studies/receiver-2026/PLAN-fresh.md`, `GRADE-fresh.md`, `fresh/`: the receiver gap on a fresh sample (`fresh.py` 0.1.0, which reuses `gps_lag.py`, `receiver.py` and `rate.py` unchanged). 1,000 attempts, 298 passing logs. E1 failed (M8 12), so exploratory; F2 met its rule; F4 and F5 failed; F1, F3 and F6 not scored. `fresh/logs.jsonl` also carries the mismatch-2026 (`mm_`) and nis-2026 (`nis_`) fields of every log.
- `studies/receiver-2026/PLAN-rate2.md`, `GRADE-rate2.md`, `rate2/summary.json`: the release-aware rate rule and the M9 gap on PX4 v1.16+, scored from fresh-2026's rows (`rate2.py` 0.1.0, which reads no log). G2 held; G0 failed (M8 5); G1 not scored.
- `studies/mismatch-2026/PLAN.md`, `GRADE.md`, `summary.json`: does a GPS delay more than 50 ms off its setting raise EKF2's GPS velocity test ratios while accelerating, or add rejections? (`mismatch.py` 0.1.0). E0, S0, M1 and M2 held; M3 failed.
- `studies/nis-2026/PLAN.md`, `GRADE.md`, `summary.json`: NIS and autocorrelation of EKF2's horizontal GNSS position and velocity innovations on real flights, the open questions of PX4 RFC #28837 (`nis.py` 0.1.0). E0, N1, N2, W1 and W2 held.
- `studies/f9p-2026/PLAN.md`: the F9P at 5 Hz on PX4 v1.16/v1.17, on a new sample (seed 20261109) that leaves out every earlier log and vehicle (`fresh2.py`, `f9p.py`, `f9p_extra.py` 0.1.0). Also re-scores mismatch-2026's M2 and nis-2026's N1. Pre-registered; no results yet (the first run was stopped from outside after 53 minutes and is being run again in full).
- `studies/floor-2026/PLAN.md`: does EKF2's GPS position noise floor (`max(eph, EKF2_GPS_P_NOISE)`) explain the low position NIS? Scored on f9p-2026's rows with fresh-2026 as a replication (`floor.py` 0.1.0, standard library, reads no log). Pre-registered; no results yet.

**How long the raw logs stay.** Since October 2024, Flight Review keeps every upload, public ones included, for 12 months, then removes it automatically (announcement on discuss.px4.io, "PX4 Flight Review & Data Retention", topic 41906, 2024-10-14). These studies drew logs uploaded from October 2025 on, so the raw logs behind them start to disappear from October 2026. The per-log rows in each study's `logs.jsonl` (log id, hashed vehicle id, every measured figure, no positions) stay here, and the scored checks can be recomputed from them, but once a log is gone it can't be measured again from the raw file. If you want to re-measure, download the logs you need while they are still listed.

## Tests

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet test_innov test_receiver test_confirm test_rate test_rate2 test_fresh test_mismatch test_nis test_f9p test_floor
```

The tests fly synthetic vehicles with known GPS delays and check that they are recovered within 3 ms. They also check that the innovation slope, in PX4's sign, recovers a known excess delay, and that re-scoring 0.1.0's rows flips every signed check. `test_receiver` checks the device_id decoding against PX4's bit layout, the choice of receiver, the exclusion of earlier vehicles and every scored check on synthetic rows. `test_confirm` checks that one published lag per vehicle is taken from both earlier formats, and checks every scored check on synthetic rows. `test_rate` checks that synthetic receivers at 100, 125 and 200 ms get their grid, and that 1-2 Hz receivers, logs throttled to 500 ms and times off any grid get none. It also checks every scored check on synthetic rows. `test_rate2` checks the release parsing (old driver, new driver, development builds, forks), the expected interval per class and release, and every scored check on synthetic rows, including the unscored cases. `test_fresh` checks every scored check of the fresh study on synthetic rows, including the ones it leaves unscored when a class is too small, and that the draw uses its own seed and leaves out earlier vehicles. `test_mismatch` flies a synthetic 200 s flight with known test ratios and a known innovation lean, and checks the acceleration bins, the lift, rejections, the in-flight mask and the slope. It also checks every scored check on synthetic rows, and that `fresh_mm.py` returns exactly `rate.read_rate`'s fields (or `fresh.py`'s own error fields) plus the mismatch fields. `test_nis` checks NIS on known innovations and variances, the in-flight and GPS-fused masks, the autocorrelation on a hand-worked case, on white noise and on a known AR(1) series (its 1/e time recovered), every scored check on synthetic rows, and that `fresh_nis.py` adds the NIS fields to exactly what `fresh_mm.py` returns. `test_f9p` (standard library only) checks the release and log selection, every f9p-2026 check on synthetic rows (including the unscored cases and the 150/175 ms boundaries), the seeded bootstrap, that `fresh2.py` draws with seed 20261109 and refuses any other, and the parameter and message filters of `f9p_extra.py`. `test_floor` (standard library only) checks the floor ratio q (default, lowered floor, the 10 m cap), tied ranks, Spearman, the slope, the seeded bootstrap, the row filters, and every floor-2026 check on synthetic rows: all holding, a flat NIS failing F1, too few logs leaving everything unscored, and F3 unscored without logs at q ≤ 0.5.
