# px4-gps-lag

How far behind the IMU is your PX4 vehicle's GPS? `gps_lag.py` measures it from a flight log (`.ulg`). It measures against the same timestamp from which PX4's EKF2 subtracts `EKF2_GPS_DELAY` (default 110 ms).

By MV2 of Munim, Inc. The code and studies are made with AI agents. Apache-2.0.

## Use

```
pip install numpy pyulog
python gps_lag.py flight.ulg
```

It prints one JSON line per log with:

- `lag_ms` and its nominal standard error `se_ms`;
- the log's own `param_gps_delay_ms`, and `lag_minus_param_ms`;
- the GPS bus (`serial`, `uavcan`, ...);
- `passed` / `reason`.

A log passes only if the flight has enough manoeuvring for the lag to be measurable (see the gates in `gps_lag.py`). Hover-only flights usually don't pass.

How it works: for each pair of consecutive logged GPS samples in flight, the change in GPS north and east velocity is compared with the IMU's acceleration (`sensor_combined`, rotated by `vehicle_attitude`), integrated over the same interval shifted back by a candidate lag. The lag that fits best, allowing a constant accelerometer bias, is the measurement. No position is read.

[px4-log-health](https://github.com/munimtechnologies/px4-log-health)'s `checkup.py` gives a readable report per flight: health flags, a fleet comparison and this GPS delay verdict. It also comes as a GitHub Action. It runs in your browser too, with nothing uploaded: [munimv2.github.io/px4-log-check](https://munimv2.github.io/px4-log-check/).

**PX4 v1.18 and newer.** PX4 PR [#26660](https://github.com/PX4/PX4-Autopilot/pull/26660) replaced `EKF2_GPS_DELAY` with one delay per receiver (`SENS_GPS0_DELAY`, `SENS_GPS1_DELAY`), applied by moving each sample's `timestamp_sample` back. `gps_lag.py` still measures the lag on those logs, but `param_gps_delay_ms` is empty. px4-log-health's checkup (0.3.2 and newer) reads the delay EKF2 applied from the log's own sample times and names the parameter to change. On 8 public v1.18 pre-release logs, that applied delay was 110.0 ms every time ([`GRADE-fresh.md`](studies/receiver-2026/GRADE-fresh.md)). PX4 main has since renamed `vehicle_gps_position` to `vehicle_gnss` (PR [#24399](https://github.com/PX4/PX4-Autopilot/pull/24399)), which `gps_lag.py` does not read yet.

## What the fleet says

On 164 public Flight Review logs from 115 vehicles (`studies/fleet-2026/GRADE.md`, pre-registered), the median lag was 99.8 ms, close to the default 110 ms. But 29.6% of logs were more than 50 ms away from their own setting. Two logs of the same vehicle agreed to within a median 5.3 ms, and 98% of the logs ran the default.

**Replicated.** An independent sample of 98 logs from 98 other vehicles gave a median of 113.8 ms, with 31.2% of logs more than 50 ms off their setting. Both figures were inside the ranges set before that run (px4-log-health, [`studies/fleet-health-2026/GRADE.md`](https://github.com/munimtechnologies/px4-log-health/blob/main/studies/fleet-health-2026/GRADE.md), R1 and R2).

**EKF2's own residuals agree.** On those 98 fresh logs, EKF2's GPS velocity innovations were compared with acceleration. In 25 of the 27 logs more than 50 ms off their setting, they lean the way the measured mismatch says they should. The two methods also rank the logs alike (Spearman +0.86). The check was pre-registered and decided C1 ([`studies/fleet-2026/GRADE-innov-confirm.md`](studies/fleet-2026/GRADE-innov-confirm.md)).

**Does the mismatch matter? It shows in EKF2's own GPS check (mismatch-2026, pre-registered).** EKF2 accepts or rejects each GPS velocity sample with an innovation test (a ratio above 1 means rejected). On 256 fresh logs ([`studies/mismatch-2026/GRADE.md`](studies/mismatch-2026/GRADE.md)), the test ratio while accelerating rose to a median 2.7 times its steady-flight value on logs more than 50 ms off their setting, against 1.7 times on the others. The difference in log10 lift was +0.19 (interval 0.10 to 0.31). The larger the mismatch, the larger the rise (Spearman 0.26, interval 0.15 to 0.37).

On rejections, 20% of mismatched logs had at least one GPS velocity rejection in flight, against 16% of the others. That gap is within chance, but the data can't rule out a real one of up to 14 points, so the plan's "no extra rejections" check (M3) failed. As the plan's rule D1 says, px4-log-health's checkup says this on every mismatched log (since 0.3.3).

On a second fresh sample (f9p-2026, 266 logs), the dose-response held again (Spearman 0.17, 0.05 to 0.28). The mismatched-versus-matched difference was +0.06 (−0.06 to +0.26), so it did not replicate.

**How consistent are EKF2's GNSS innovations on real flights? (nis-2026, pre-registered).** PX4 RFC [#28837](https://github.com/PX4/PX4-Autopilot/issues/28837) argues from simulation that EKF2 treats GNSS samples as independent although real GNSS errors stay correlated. That leaves its normalised innovation squared (NIS) far below 1 and its gate far wider than the real innovations. On 285 real flights ([`studies/nis-2026/GRADE.md`](studies/nis-2026/GRADE.md)), all four checks held:

- the median position NIS was **0.0079** (consistent: 0.693), velocity **0.024**;
- measured in the innovations' real spread, EKF2's 5-SD gate is about **30 SDs** wide for position and **17** for velocity (the RFC's simulation: more than 11);
- position innovations 1 s apart correlate at **0.78** (1/e time about 3.7 s), velocity ones at **0.35** (about 1 s, the limit of 500 ms logging).

All four held again on a second fresh sample of 289 flights (f9p-2026): 0.0076, 0.023, 0.76 and 0.34. Figures by fix type (3D, SBAS, RTK fixed) and receiver are in the grade. Innovations are not raw GNSS errors, so these figures describe what EKF2 sees, not the receiver's own error correlation time.

**EKF2's noise floor explains only a small part of it (floor-2026, pre-registered).** EKF2 fuses each GNSS position with the noise `max(eph, EKF2_GPS_P_NOISE)` (default 0.5 m; `Ekf::updateGnssPos()`). A receiver reporting 0.3 m, or 1 cm with RTK, is still fused as 0.5 m. On 559 flights ([`studies/floor-2026/GRADE.md`](studies/floor-2026/GRADE.md)), all five checks held:

- **The floor matters.** NIS rises with q = eph / max(eph, floor) (Spearman 0.37, 0.29 to 0.44). Logs at or above the floor have 4.8 times the median NIS of logs at q ≤ 0.5.
- **Under the floor, it is much weaker than the floor alone predicts.** NIS falls as about q^0.42 (0.30 to 0.54), not q². For RTK at 1.4 cm against a 0.5 m floor, that is a factor of about 4-5, not about 1,000.
- **Most of the low NIS is there with the floor not binding.** At q = 1 the median position NIS was still **0.0081**, about 85 times below consistent, and it did not depend on eph (ρ −0.09).

On fresh-2026's rows the slope was 0.23 (interval −0.06 to 0.43), and the other checks held.

## The u-blox dynamic model: model 6 adds GPS lag (dynmodel-2026, pre-registered twice)

u-blox receivers tune their navigation filter to a "dynamic platform model" (`GPS_UBX_DYNMODEL`). PX4's `rc.mc_defaults` set 6 (airborne <1g) for every multicopter up to v1.16. PR [#24831](https://github.com/PX4/PX4-Autopilot/pull/24831) moved multicopters to 7 (<2g) from v1.17, because 6 "can upset the EKF" in aggressive flight. `rc.fw_defaults` sets 8 (<4g).

**Across public logs.** [`studies/dynmodel-2026/GRADE.md`](studies/dynmodel-2026/GRADE.md) read the GPS parameters of 244 public u-blox logs whose lags had been published before the question existed (only the start of each log, where the parameters are). **Every pre-registered check held:**

| receiver | `GPS_UBX_DYNMODEL` 6 (airborne <1g) | 7 (<2g, PX4's default) | 8 (<4g) |
|---|---|---|---|
| u-blox F9P | 15 logs, **180.7 ms** | 12, 137.3 ms | 6, 120.9 ms |
| u-blox M9 | 25, **108.7 ms** | 19, 62.0 ms | 34, 69.1 ms |
| u-blox M8 | 17, **186.1 ms** | 9, 114.1 ms | 7, 124.4 ms |
| u-blox, model not detected | 47, **144.4 ms** | 19, 116.2 ms | 31, 115.8 ms |

- Within receiver classes, model-6 logs were a median **+45.6 ms** later than model-7 logs (interval 33 to 55; K1). On the F9P, +43.4 ms (8 to 67; K2). On other receivers, +45.7 ms (31 to 58; K4).
- On fresh-2026's F9P at 5 Hz, the model sorted 14 of 16 logs into the right one of the two lag groups seen before (K3). All 7 model-6 logs were in the late group.
- Model 8 was no less late than 7 (+3.5 ms, −10 to 13).
- **41.5%** of model-6 logs were more than 50 ms later than their own delay setting, against 8.8% at model 7.

Because PX4's defaults give model 6 to multicopters on v1.16 or older, that comparison can't on its own separate the model from the vehicle type and release. An exploratory re-score of the same logs (`dynconf.py`, in the grade) kept the gap among multicopters only (+45 ms, 28 to 60) and matched on receiver and release as well (+52 ms, 31 to 82). Release alone (−7 ms) and vehicle type alone (−4 ms) showed no gap.

**Within one vehicle: +104 ms.** The pre-registered paired check ([`GRADE-paired.md`](studies/dynmodel-2026/GRADE-paired.md)) measured the two logs a PX4 maintainer attached to PR #24831. They come from one vehicle with a serial F9P, flown on the same day (2025-05-27) at model 6 and at model 7, with the same delay and port settings. **The GPS lagged 214.2 ms at model 6 and 110.5 ms at model 7 (+103.7 ms; the plan's threshold was +30 ms), so rule D1 applies.** One pair of flights is a case, not a fleet figure. Still, it points the same way as the fleet result, and on this vehicle the vehicle type and release can't explain it. An exploratory within-flight check found the gap in every third of both flights and at low and high acceleration alike (block-bootstrap interval of the difference 86.6 to 108.3 ms). The model-6 flight exceeded 1 g in only 0.39% of its GPS intervals.

**On that vehicle, the extra lag behaves like heavier smoothing, not later delivery (pre-registered, M1 = smoothing).** [`GRADE-mechanism.md`](studies/dynmodel-2026/GRADE-mechanism.md) fitted each flight's GPS velocity as the IMU velocity passed through a first-order low-pass (time constant τ) and then delayed by D. At model 6, τ = **110 ms** (bootstrap interval 90 to 140) and D = 110 ms. At model 7, τ = **20 ms** (0 to 60) and D = 95 ms. The difference is in τ (+90 ms, 59.8 to 130), not in D (+15 ms, −20 to +50). A filter's delay depends on how fast the vehicle manoeuvres, so no single `EKF2_GPS_DELAY` fully compensates model 6's extra lag: on the fitted filter, a 0.2 Hz manoeuvre is delayed about 109 ms and a 2 Hz one about 75 ms, and only 59% of a 2 Hz velocity swing gets through. EKF2's innovations agreed in sign with the measured mismatch on both flights (M2). Neither flight had an in-flight EKF2 reset or GPS rejection (descriptive only). This is still one vehicle and one flight per model, and a first-order low-pass is a stand-in for u-blox's unpublished filter. Whether the fleet's +46 ms gap also sits in τ is pre-registered in [`PLAN-tau-fleet.md`](studies/dynmodel-2026/PLAN-tau-fleet.md), on dynmodel-2026's own model-6 and model-7 logs.

**The same vehicles before and after the v1.17 upgrade (upgrade-2026, pre-registered twice): too few pairs, no claim.** `param set-default` stores nothing, so a multicopter that never set `GPS_UBX_DYNMODEL` by hand moves from model 6 to 7 when it is upgraded from v1.16 to v1.17. Flight Review's public list has 139 multicopters with eligible logs on both releases. The first run ([`GRADE.md`](studies/upgrade-2026/GRADE.md), up to 3 tries a side) found 10 pairs against the 12 needed. The pre-registered extension ([`GRADE-ext.md`](studies/upgrade-2026/GRADE-ext.md), up to 10 tries a side, scored on new pairs only) visited the other 129 and found **1** new pair against the 8 needed. Both are rule D3: a case series, no claim, and no third run of this design. The v1.17 side is the bottleneck: the vehicles ran out of usable v1.17 logs. Across all 11 pairs (described, not graded): the 9 vehicles that switched from model 6 to 7 dropped by a median **94.9 ms**, while the 2 that kept model 6 on v1.17 (both CUAV X7 Pro boards with F9P receivers) moved by +19.3 and −2.1 ms. Several pairs probably share an operator.

We found no earlier published millisecond figure for the lag of u-blox's dynamic models (search on 2026-11-05). Betaflight contributors noted in PR [#3110](https://github.com/betaflight/betaflight/pull/3110) that the model "changes the level of filtering (delay)", without a figure. ArduPilot's `GPS_NAVFILTER` defaults to <4g.

**What it means for you:** if your u-blox vehicle runs `GPS_UBX_DYNMODEL` 6 (any multicopter on v1.16 or older that kept the default), there is about a 4-in-10 chance that its GPS lag is more than 50 ms past its delay setting. Measure it, or set 7 (PX4's multicopter default since v1.17; it needs a reboot) and measure again. Changing the model is likely the better fix than raising the delay setting, because model 6's extra lag behaved like smoothing on the one vehicle flown at both. px4-log-health's checkup says this on every log with a serial u-blox at model 6, from [v0.3.4](https://github.com/munimtechnologies/px4-log-health/releases/tag/v0.3.4) on. Upgrading to v1.17 does not change a model 6 that was stored in the vehicle's parameters (by hand or from a saved parameter file).

## Does the receiver model matter? (exploratory, seen four times)

PX4 uses one GPS delay for every receiver up to v1.17. ArduPilot assigns a lag by u-blox generation: 120 ms for M8 "based on flight logs", and the same 120 ms for F9, M9 and M10, with the comment "F9 lag not verified yet from flight log" (`AP_GPS_UBLOX.cpp`, `get_lag`). PX4's GPS driver records the receiver model it detected in the device_id of every GPS message, and `receiver.py` reads it.

Four samples, with no vehicle in common between them:

| receiver (as PX4 detected it) | receiver-2026: vehicles, median lag | receiver-confirm | fresh-2026 | f9p-2026 (logs) |
|---|---|---|---|---|
| u-blox M9 | 25, **71.3 ms** | 32, **76.2 ms** | 29, **81.3 ms** | 41, **82.7 ms** |
| DroneCAN | 39, 104.4 ms | 49, 92.9 ms | 84, 105.9 ms | 82, 96.2 ms |
| u-blox, model not detected (includes M10 on v1.15) | 19, 127.8 ms | 27, 130.3 ms | 38, 140.9 ms | 41, 121.7 ms |
| u-blox F9P | 16, **142.6 ms** | 27, **143.5 ms** | 42, **143.1 ms** | 36, **131.4 ms** |
| u-blox M8 | 15, **146.6 ms** | 7, **150.9 ms** | 12, **145.3 ms** | 28, **173.4 ms** |
| NMEA | 13, 150.0 ms | 16, 230.9 ms | 24, 208.4 ms | 20, 145.5 ms |

- **receiver-2026** ([`GRADE.md`](studies/receiver-2026/GRADE.md)) was a fresh random sample of 163 passing logs. Its enough-data check (E1) failed, so it is exploratory.
- **receiver-confirm** ([`GRADE-confirm.md`](studies/receiver-2026/GRADE-confirm.md)) read the receiver model of the 213 vehicles in the two earlier samples, whose lags had been published before the M9 gap was seen. **M9 − F9P = −67.3 ms (interval −101 to −48)**. E1 failed (7 M8 vehicles).
- **fresh-2026** ([`GRADE-fresh.md`](studies/receiver-2026/GRADE-fresh.md)) was a new random sample of 298 passing logs, leaving out every earlier vehicle. **M9 − F9P = −61.8 ms (interval −88 to −42)**. E1 failed again: 12 M8 logs against the 15 needed. A per-receiver default would have brought only 2.3 points more vehicles within 50 ms of their lag (F5 failed).
- **f9p-2026** ([`studies/f9p-2026/GRADE.md`](studies/f9p-2026/GRADE.md)) recomputed fresh-2026's checks on its own new sample of 310 passing logs (reported, not graded). E1 held this time. **M9 − M8 = −90.7 ms (−111 to −64)**, M9 − F9P = −48.7 ms (−72 to −21), and a per-receiver default would bring 8.9 points more logs within 50 ms (F5 held). F3, F4 and F6 failed.

What this means: on PX4, the M9 was the least-late u-blox receiver in four independent samples, by about 50-90 ms. It is still exploratory by the plans' own rules: the M8 class reached its count only in the reported fourth sample. No per-receiver line has been added to px4-log-health's checkup. Knowing the model doesn't replace measuring your own vehicle. Since PX4 v1.18 the delay can be set per receiver (`SENS_GPSn_DELAY`), which is where such a measurement goes. These are PX4 measurements only and say nothing about ArduPilot's own lag. The dynamic model (above) does not explain the receiver gap: at each model, the M9 is still the least late (at model 7, M9 62 ms against F9P 137 and M8 114).

### The measurement rate does not explain the M9 gap (rate-2026 and rate2-2026, pre-registered)

[`GRADE-rate.md`](studies/receiver-2026/GRADE-rate.md) read each of the 376 earlier logs' measurement rate from the phase of the receiver's own UTC times (`rate.py` 0.1.0), and scored the lags already published. **On the same 125 ms grid, M9 logs were 53 ms less late than the other serial u-blox logs (interval −106 to −19 ms; check Q2 held).**

Its check that receivers run at the rate PX4's driver asks for (Q1) **failed**, because the plan took the rates from PX4 v1.15.4's driver. PX4-GPSDrivers changed them in January 2025 (`bbdd576`, "ublox update F9P output rates"), and PX4 v1.16 and v1.17 ship that change:

| receiver | PX4 v1.12-v1.15 asks for | PX4 v1.16-v1.17 asks for |
|---|---|---|
| u-blox M8 | 200 ms (5 Hz) | 200 ms (5 Hz) |
| u-blox M9 | 125 ms (8 Hz) | 100 ms (10 Hz) |
| u-blox F9P L1L2 | 100 ms (10 Hz) | 200 ms (5 Hz) |
| u-blox F9P L1L5 | 100 ms (10 Hz) | 143 ms (7 Hz) |

**rate2-2026** ([`GRADE-rate2.md`](studies/receiver-2026/GRADE-rate2.md)) pre-registered the release-aware rule before fresh-2026 was downloaded, then scored it on fresh-2026's rows. **On v1.16 and v1.17, the M9 at 10 Hz was 110 ms less late than the F9P at 5 Hz (−110.4 ms, interval −132 to −60; 12 and 18 logs; G2 held).** So the M9 is less late both when it measures less often than the F9P (v1.12-v1.15) and when it measures twice as often (v1.16-v1.17). The measurement rate does not explain the gap.

### The F9P at 5 Hz: no single figure, but two groups (f9p-2026, pre-registered)

On fresh-2026, the F9P at 5 Hz on v1.16/v1.17 had a median lag of 178 ms, and its lags looked like two groups. [`studies/f9p-2026/GRADE.md`](studies/f9p-2026/GRADE.md) tested both on a new sample under a plan committed before the draw:

- **The 178 ms figure did not replicate** (rule D3). The median was 122 ms (105.7 to 191.9) on 12 qualifying logs, and 4 of 12 were more than 50 ms past their setting. Nothing is added to the checkup.
- **The two groups did replicate** (P3). There were 8 logs at 82-144 ms, 4 at 185-239 ms, and none in between. The median depends on how many logs of each group a sample happens to have.
- The dynamic model lines up with the groups: see dynmodel-2026 above (K3 held, 14 of 16).

If you fly an F9P on PX4 v1.16 or v1.17, measure your own lag (`gps_lag.py`, or px4-log-health's checkup) rather than assume 110 ms.

## Suggested setting (rule D1)

If a passing log's `lag_minus_param_ms` is more than about 50 ms either way, the measured `lag_ms` is a reasonable **starting value** for `EKF2_GPS_DELAY` (on PX4 v1.18 and newer, for the receiver's `SENS_GPSn_DELAY`).

- Measure two or three flights first. Flights of one vehicle should agree within a few ms.
- Check the change with EKF2 log replay (PX4 docs: "EKF2 log replay") before flying it.
- Smaller differences aren't worth changing.
- If the receiver is a u-blox at `GPS_UBX_DYNMODEL` 6, changing the model to 7 may be the better fix (see above). Measure again after the change, because the lag moves with the model.
- This is not a calibration. The studies show that two independent methods agree on the direction and rank of the mismatch, and that the mismatch shows in EKF2's own test ratios. They don't show that the new setting improves any one vehicle's estimate. There is no ground truth for any one vehicle.

History: D1 was withdrawn after the first innovation check came back C2 as written, because that plan had EKF2's innovation sign backwards (PX4 computes prediction minus measurement; see `GRADE-innov.md`). The corrected check was pre-registered on fresh logs and held, so D1 is back.

## Studies

- `studies/fleet-2026/`: GPS lag across a random sample of PX4 Flight Review public logs (CC BY 4.0) from 2025-10 on, compared with each vehicle's `EKF2_GPS_DELAY`. Plan, grade (E1 passed, 5 of 6 predictions held), and one line per log in `v1/logs.jsonl`. `v1/summary.json` is the same rows re-scored, and it matches the grade.
- `studies/fleet-2026/PLAN-innov.md`, `GRADE-innov.md`, `innov/`: does EKF2's GPS velocity innovation, plotted against acceleration, lean the way the measured lag says it should? Graded C2 as written. The innovation sign was wrong in the plan; see the grade.
- `studies/fleet-2026/PLAN-innov-confirm.md`, `GRADE-innov-confirm.md`, `confirm/`: the corrected check (`innov.py` 0.2.0, PX4's sign) on the 98 fresh logs from px4-log-health, with the same thresholds. 89 logs validated; C1.
- `studies/receiver-2026/`: lag by GPS receiver model (`receiver.py` 0.1.0). Plan, grade (E1 failed, so exploratory; 5 of 6 predictions held as written), `logs.jsonl`, `summary.json` and `job-fetched.json`. The first run was stopped from outside the job after 88 logs (exit 143). Its rows were never scored; the complete second run is the one graded.
- `studies/receiver-2026/PLAN-confirm.md`, `GRADE-confirm.md`, `confirm/`: the M9 gap tested on the earlier samples' published lags (`confirm.py` 0.1.0).
- `studies/receiver-2026/PLAN-rate.md`, `GRADE-rate.md`, `rate/`: measurement rate from the receiver's UTC times (`rate.py` 0.1.0), scored on the published lags.
- `studies/receiver-2026/PLAN-fresh.md`, `GRADE-fresh.md`, `fresh/`: the receiver gap on a fresh sample (`fresh.py` 0.1.0). `fresh/logs.jsonl` also carries the mismatch-2026 (`mm_`) and nis-2026 (`nis_`) fields of every log.
- `studies/receiver-2026/PLAN-rate2.md`, `GRADE-rate2.md`, `rate2/summary.json`: the release-aware rate rule, scored from fresh-2026's rows (`rate2.py` 0.1.0). G2 held; G0 failed (M8 5); G1 not scored.
- `studies/mismatch-2026/`: does a GPS delay more than 50 ms off its setting raise EKF2's GPS velocity test ratios while accelerating? (`mismatch.py` 0.1.0). E0, S0, M1 and M2 held; M3 failed.
- `studies/nis-2026/`: NIS and autocorrelation of EKF2's horizontal GNSS innovations on real flights (`nis.py` 0.1.0). E0, N1, N2, W1 and W2 held.
- `studies/f9p-2026/PLAN.md`, `GRADE.md`, `logs.jsonl`, summaries, `f9p-extra.jsonl`, `job-fetched.json`: the F9P at 5 Hz on a new sample (seed 20261109; `fresh2.py`, `f9p.py`, `f9p_extra.py` 0.1.0). E0 and P3 held; P1, P2 and P4 failed (D3: the 178 ms figure is withdrawn). The first run was stopped from outside after 53 minutes and not scored.
- `studies/floor-2026/PLAN.md`, `GRADE.md`, `floor-summary.json`: does EKF2's GPS position noise floor explain the low position NIS? (`floor.py` 0.1.0). E0 and F1-F4 held; D1.
- `studies/dynmodel-2026/PLAN.md`, `GRADE.md`, `dynmodel-rows.jsonl`, `dynmodel-summary.json`, `job-fetched.json`: does the u-blox dynamic platform model add GPS lag? (`dynmodel.py` 0.1.0, standard library, reads only each log's parameters). E0 and K1-K4 held; D1. `dynconf/`: the exploratory re-score within matched vehicle type, release and receiver (`dynconf.py` 0.1.0, `test_dynconf.py`, `dynmap.txt`, `dynconf-summary.json`).
- `studies/dynmodel-2026/PLAN-paired.md`, `GRADE-paired.md`, `paired/`: the same question within one vehicle, on the logs attached to PX4 PR #24831 (`paired.py` 0.1.0). E0 and P1 held; D1. `paired/paired-rows.jsonl`, `paired-summary.json`, `job-fetched.json`; `paired/segments/`: the exploratory within-flight check (`paired_segments.py` 0.1.1, `test_paired_segments.py`, `segments-summary.json`, `job-fetched.json`). It reproduced both lags, and the gap held in every third of both flights and at both acceleration levels. Its first sealed run (0.1.0) stopped while writing its summary, because two yes/no fields were numpy booleans; 0.1.1 makes them plain booleans and computes nothing differently.
- `studies/dynmodel-2026/PLAN-mechanism.md`, `GRADE-mechanism.md`, `mechanism/`: on the same two logs, is model 6's extra lag heavier smoothing (a first-order low-pass) or later delivery (a pure delay)? Plus EKF2's innovation sign, test ratios, resets and rejection flags (`mechanism.py` 0.1.0, `test_mechanism.py`, `job_fetch.py`, `mechanism-summary.json`, `job-fetched.json`). E1 and M2 held; M1 = smoothing.
- `studies/dynmodel-2026/PLAN-tau-fleet.md`, `tau-fleet/`: the same (τ, D) fit on dynmodel-2026's graded logs at models 6 and 7, re-downloaded from Flight Review (`tau_fleet.py` 0.1.0, `test_tau_fleet.py`, `job_fetch.py`). Pre-registered; its sealed run starts after census-2026's.
- `studies/upgrade-2026/PLAN.md`, `GRADE.md`, `upgrade.py`, `test_upgrade.py`, `v1/` (`rows.jsonl`, `pairs.jsonl`, `summary.json`, `job-fetched.json`): the dynamic model within vehicles, before and after their v1.16 → v1.17 upgrade (`upgrade.py` 0.1.0, seed 20261113). E0 failed (10 pairs of 12), so D3: a case series, no claim. `PLAN-ext.md`, `GRADE-ext.md`, `extend.py`, `test_extend.py`, `ext/` (`rows-ext.jsonl`, `pairs-ext.jsonl`, `summary-ext.json`, `job-fetched.json`): the pre-registered extension (up to 10 tries a side, seed 20261115, scored on new pairs only). X0 failed (1 new pair of 8), so DX3: a case series, no claim, and no third run of this design.
- `studies/census-2026/PLAN.md`, `census.py`, `test_census.py`, `job_fetch.py`: how many multicopters ran `GPS_UBX_DYNMODEL` 6 on v1.16, and how many still run it on v1.17, after PX4 changed the default (`census.py` 0.1.0, standard library; reads only each log's parameters, one log per vehicle, seed 20261117). Pre-registered; its sealed run is queued.

**How long the raw logs stay.** Since October 2024, Flight Review keeps every upload, public ones included, for 12 months, then removes it automatically (announcement on discuss.px4.io, "PX4 Flight Review & Data Retention", topic 41906, 2024-10-14). These studies drew logs uploaded from October 2025 on, so the raw logs behind them start to disappear from October 2026.

- What stays: the per-log rows in each study's `logs.jsonl` (log id, hashed vehicle id, every measured figure, no positions). The scored checks can be recomputed from them.
- What goes: once a log is gone, it can't be measured again from the raw file. If you want to re-measure, download the logs you need while they are still listed.

## Tests

```
pip install numpy pyulog ijson requests
python -m unittest -v test_gps_lag test_fleet test_innov test_receiver test_confirm test_rate test_rate2 test_fresh test_mismatch test_nis test_f9p test_floor test_dynmodel test_paired
```

The tests fly synthetic vehicles with known GPS delays and check that they are recovered within 3 ms. Each study's test file also checks its own scoring on synthetic rows, including the cases a plan leaves unscored.

`test_dynmodel` and `test_paired` (standard library only) check:

- the ULog reader on a synthetic log fed whole, byte by byte and cut short: it keeps only initial parameters and stops at the data section;
- the log selection and the f9p-2026 rule;
- the download loop's handling of deleted logs, blocks, network errors and the time budget;
- every dynmodel-2026 check on synthetic rows, including the unscored cases and one log per vehicle;
- `paired.py`'s zip extraction (nested zips one level down; archive paths are never used as output paths) and every paired check, including E0 failing and P2 unscored.

`studies/dynmodel-2026/paired/segments/test_paired_segments.py` (numpy; run it with `gps_lag.py` on the path) flies two synthetic vehicles 100 ms apart and checks the thirds, the block bootstrap, the acceleration split and that the summary is plain JSON.

`studies/dynmodel-2026/mechanism/test_mechanism.py` (numpy only; no log is read) flies synthetic vehicles whose GPS velocity passes through an exact low-pass and delay. It checks that a pure delay is found as delay and smoothing as τ, plus the low-pass and block helpers, EKF2's counter and flag statistics, plain JSON output and every mechanism outcome (smoothing, delivery, mixed, not identified).

`studies/upgrade-2026/test_upgrade.py` (standard library only; run it from that folder) checks the list filters (multicopters, v1.16/v1.17 non-development builds, vehicles on both releases), the seeded order, the receiver and parameter reading, the draw (at most 3 tries a side, the same receiver after the upgrade, blocks, the download and time limits) and every upgrade-2026 check, including D2, D3 and the unscored cases.

`studies/upgrade-2026/test_extend.py` (standard library only; run it from that folder) checks the extension's order (paired vehicles left out, the first run's tries first and never twice), the draw (reused tries without a download, at most 10 tries a side, the same receiver after the upgrade, blocks and limits) and every extension check, including DX2, DX3 and DX4.
