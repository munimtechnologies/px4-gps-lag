# fleet-2026, part 2: does EKF2's own GPS innovation agree with the measured lag?

Written 2026-10-30, after fleet-2026 was graded (`GRADE.md`) and before any innovation was read from any log. By MV2 of Munim, Inc.; the plan, code and analysis are made with AI agents. Text CC BY 4.0, code Apache-2.0. Data: PX4 Flight Review public logs (Dronecode / PX4, CC BY 4.0).

## Why

fleet-2026 measured each log's GPS lag L with `gps_lag.py`. Its median was 99.8 ms, close to the default `EKF2_GPS_DELAY` P of 110 ms, but 29.6% of logs differed from their own P by more than 50 ms. Two logs of the same vehicle agreed to a median 5.3 ms. Repeatability says the measurement is stable. It doesn't say the measurement is right: a bias in the method that repeats on every log of a vehicle would look the same.

EKF2 gives an independent check. It fuses a GPS velocity measured L before its timestamp as if it had been measured P before. While the vehicle accelerates at a, its GPS velocity innovation (`estimator_innovations.gps_hvel`, GPS minus prediction) is then about v(t − L) − v(t − P) ≈ −a·(L − P). So the slope k of the innovation against acceleration should have the opposite sign to L − P. Its size should be smaller, because the filter's state partly follows the late GPS. This uses a signal `gps_lag.py` never reads: the estimator's own residual. We found no published check of a fleet's GPS delay against EKF2 innovations.

## Method (`innov.py` 0.1.0)

- **Logs:** the 164 logs that passed in fleet-2026 (`v1/logs.jsonl`, `passed: true`), downloaded again one at a time in file order, 6 s apart. The run stops on 403/444, and otherwise after 100 minutes. Each log is deleted once measured.
- **Innovations:** `estimator_innovations.gps_hvel[0..1]` (north, east), or `ekf2_innovations.vel_pos_innov[0..1]` in older logs, instance 0. These are logged every 500 ms by default.
- **Fusion time:** `timestamp_sample` (EKF2's delayed horizon) if the log has it, else `timestamp` − P.
- **Samples kept:** in flight (`vehicle_land_detected`), finite, not both zero, and different from the sample before (a repeat means no new fusion). The ±0.1 s IMU window must be inside the record with no gap over 0.1 s.
- **Acceleration:** north-east acceleration from `sensor_combined` and `vehicle_attitude` exactly as in `gps_lag.py` 0.1.0 (imported from main unchanged), averaged over ±0.1 s around the fusion time.
- **Fit:** the slope k of the innovation against that acceleration, with one constant per axis and both axes pooled. The **implied excess** is −k, in ms.
- **Gates:** a log is *validated* if it has at least 100 kept samples and an acceleration RMS of at least 0.3 m/s².
- **Unit tests:** synthetic flights recover an excess of +90 ms (L = 200, P = 110) and −60 ms (L = 50) within 12 ms. They also check that a filter that half-follows the GPS halves the slope.

## Checks (`innov/summary.json` → `checks`)

Here d = `lag_minus_param_ms` from fleet-2026, and x = implied excess.

- **VE1 (enough data):** at least 60 logs validated. If VE1 fails, this is a pilot and decides nothing.
- **V1** Spearman's rank correlation between d and x over validated logs is at least 0.3.
- **V2** Of validated logs with |d| > 50 ms, at least 70% have x of the same sign as d. Decided only with at least 10 such logs.
- **V3** For those logs, the median of x / d is between 0.2 and 1.2 (the innovation shows part of the mismatch, not more than all of it).
- **V4** The median |x| of validated logs with |d| ≤ 20 ms is smaller than that of logs with |d| > 50 ms. Decided only with at least 10 in each group.

## What it decides (`decision`)

- **C1:** VE1, V1 and V2 hold. The README says that EKF2's own innovations agree with the direction of the measured mismatch on public logs, and keeps fleet-2026's D1 (the measured lag as a starting value for `EKF2_GPS_DELAY`, to be checked with EKF2 replay).
- **C2:** VE1 holds but V1 or V2 fails. D1 is withdrawn: the README goes back to "diagnostic only, no suggested setting" until a replay study says otherwise.
- **pilot:** VE1 fails. Nothing changes; the numbers are reported.

V3 and V4 are reported either way and decide nothing.

## Limits

- **Not blind to the lags.** The lags are already graded and public. The innovations have not been read. All code and thresholds are fixed here before they are.
- **A first-order model.** Second-order terms and EKF2's other aiding (for example a second GPS, optical flow or vision) also move the innovation. Attitude errors put gravity into the "acceleration", and the same attitude feeds both methods, so they are not fully independent.
- **Fusion time.** EKF2 fuses GPS at the receiver's rate, while innovations are logged every 500 ms. The logged innovation is from the last fusion, up to one GPS interval before `timestamp_sample`, which blurs the acceleration it is paired with. Where `timestamp_sample` is missing, the fusion time is assumed, not read.
- **Agreement in sign, not a calibration.** Even under C1, the measured lag is a starting value to check with replay, not a setting.

## Reproduce

```
pip install numpy pyulog ijson requests
python fetch_deps.py
python -m unittest -v test_gps_lag test_fleet test_innov
python innov.py --rows v1-logs.jsonl --out-dir out/innov --budget-min 100
```
