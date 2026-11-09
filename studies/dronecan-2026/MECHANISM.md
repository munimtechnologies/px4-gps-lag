# dronecan-2026: what a DroneCAN GNSS node's self-reported delay can and cannot cover (code reading)

Written 2026-11-09, **before** the extension pass (PLAN-ext.md, job `px4-gps-lag-dronecan-ext-v1`) read any log. It explains, from the source code alone, why the delay PX4 applies to a DroneCAN GNSS receiver since PR #27427 can fall short of the GPS lag measured against the IMU. The add-on test of this reading is pre-registered in PLAN-nodefw.md. Nothing here has been checked on hardware.

By MV2 of Munim, Inc. (mv2@munimtech.com). Written with AI agents. Text CC BY 4.0. The code quoted is PX4's (BSD-3-Clause) and ArduPilot's (GPL-3.0), cited by file. Only short lines are quoted.

## 1. What PX4 does with a Fix2 message (PX4 main, `src/drivers/uavcan/sensors/gnss.cpp`, `process_fixx`)

The bridge's own comment states the design:

> // Recover the navigation epoch in HRT: map msg.timestamp (node send UTC)
> // into HRT, then subtract (msg.timestamp - msg.gnss_timestamp), which is
> // the node-measured receiver processing delay.

In code:

- `const hrt_abstime send_hrt = estimator->toLocal(msg_ts_usec, sensor_gnss.timestamp);`
- `const int64_t processing_us = static_cast<int64_t>(msg_ts_usec - gnss_ts_usec);`
- `const int64_t pvt_hrt = static_cast<int64_t>(send_hrt) - processing_us;`
- `sensor_gnss.timestamp_sample = static_cast<hrt_abstime>(pvt_hrt);`

The guard only accepts `msg_ts_usec > gnss_ts_usec`, a non-zero `gnss_ts_usec` and a difference under `kMaxProcessingDelayUs = 500'000`. Otherwise the sample falls through to the `SENS_GNSS*_DELAY` path.

The clock mapping (`ClockOffsetEstimator`, added in commit b320731) "tracks the minimum of (local - remote)". Its commit message says the "residual bias is the minimum observed transport latency". On CAN that is about a millisecond, far too small to explain the 12 to 83 ms shortfalls in gnss-2026 and the first dronecan pass.

So the delay PX4 applies is the CAN transport time plus **whatever the node says passed between `gnss_timestamp` and `timestamp`**. Any time that the node's two stamps do not span is not covered.

## 2. What the two common node firmwares put in those two stamps

**ArduPilot AP_Periph** (`Tools/AP_Periph/gps.cpp`), once it has a fix:

- `pkt.gnss_timestamp.usec = gps.last_message_epoch_usec();` is the navigation epoch (GPS week and iTOW).
- `pkt.timestamp.usec = gps.time_epoch_usec();`

In `libraries/AP_GPS/AP_GPS.cpp`, `time_epoch_usec()` returns the epoch of the last iTOW **plus** `AP_HAL::micros64() - istate.last_corrected_gps_time_us`. So `timestamp - gnss_timestamp` equals the time **since `last_corrected_gps_time_us`**, not the time since the epoch.

`last_corrected_gps_time_us` is set in `AP_GPS_Backend::check_new_itow` (`GPS_Backend.cpp`):

- With a PPS edge and a 2D fix or better: `uart_us = _last_pps_time_us;` is close to the epoch itself.
- Otherwise: `uart_us = port->receive_time_constraint_us(msg_length);` is when the message **started arriving on the UART**. It is then jitter-corrected (`jitter_correction.correct_offboard_timestamp_usec(_pseudo_itow, uart_us)`).

**Reading:** an AP_Periph node without PPS reports only the time from the UART arrival of the fix to the CAN send. The receiver's own time from the navigation epoch to its serial output is not in the report, and neither is the serial transfer itself, apart from the start-of-message correction. ArduPilot's own EKF does not rely on this: `AP_GPS_UBLOX::get_lag` budgets 120 ms for u-blox 7, M8, M9, M10 and F9 ("based on flight logs the 7 and 8 series seem to produce about 120ms lag"). With PPS wired to the node's MCU, the report starts at the PPS edge and should span the receiver's latency.

**PX4 cannode** (`src/drivers/uavcannode/Publishers/GnssFix2.hpp`):

- `fix2.gnss_time_standard = fix2.GNSS_TIME_STANDARD_UTC;`
- `fix2.gnss_timestamp.usec = sensor_gnss.time_utc_usec;`
- `fix2.timestamp` is set to `now + _pps_offset_us` **only** if PPS data is fresh. Otherwise it stays 0, which fails PX4's guard, so a PX4-cannode node without PPS uses `SENS_GNSS*_DELAY` (110 ms by default) and is not self-stamped at all.

## 3. Two separate reasons a self-stamped delay can be short

1. **Stamping starts at UART arrival, not at the epoch** (AP_Periph without PPS, or any firmware that does the same). Expected signature: a **small applied delay** (CAN plus node time, roughly 5 to 30 ms) and a large residual (the receiver's epoch-to-output time).
   - In the logs already read, the two self-stamped logs with an applied delay of about 10 ms were both on CUAV flight controllers: CUAV_7_NANO in gnss-2026 (applied 10.18 ms, lag 92.8 ms, residual +82.6 ms) and CUAV_X7PRO in the first dronecan pass (applied 10.2 ms, lag 55.2 ms, R² gate missed by 0.001).
2. **Receiver smoothing that no time stamp sees.** The measured lag is the delay at which the GPS velocity best matches the IMU-integrated velocity. It includes any low-pass behaviour inside the receiver's navigation filter: px4-gps-lag's dynmodel-2026 study found u-blox dynamic model 6 behaving like about 110 ms more smoothing than model 7. A node's stamps cannot report this even with PPS.
   - The serial path's fixed 110 ms default was tuned empirically against both causes together. Expected signature: a normal applied delay (60 to 100 ms) and a residual that varies by vehicle. In the logs already read, applied delays of 85.65, 98.03 and 83.3 ms on CubePilot and ZeroOne boards had residuals of +80.6, +12.3 and +72.0 ms.

Both are hypotheses fitted to 5 logs that were read before this note was written, so those logs are **not** evidence for them. PLAN-nodefw.md tests them on the extension's logs, which no one has seen yet. PX4 logs carry the DroneCAN node name in `device_information` (logged every 900 ms by default on v1.18 and main; the GNSS bridge registers each receiver's `device_id` with it), so each self-stamped receiver can be tied to its node firmware.

## 4. A separate small bug found while reading (not part of the study)

In the same function, for nodes that send GPS or TAI time with a known leap-second count:

- `sensor_gnss.time_utc_usec = gnss_ts_usec - msg.num_leap_seconds + 9;` (GPS)
- `sensor_gnss.time_utc_usec = gnss_ts_usec - msg.num_leap_seconds - 10;` (TAI)

The constants match the DroneCAN DSDL (`uavcan.equipment.gnss.Fix2`: UTC = TAI - leap seconds - 10, GPS = TAI - 19), but they are **seconds** subtracted from a value in **microseconds**. With today's 27 leap seconds, a GPS-time node's UTC comes out 18 s ahead, and a TAI-time node's 37 s ahead. `release/1.18` has the same lines. Neither AP_Periph nor PX4 cannode is affected, because both send `GNSS_TIME_STANDARD_UTC`. A one-line fix per case multiplies by 1,000,000.

## Limits

- This is code reading only. Whether a given CAN GPS module wires PPS to its node MCU is not visible in a PX4 log.
- Vendors can rename AP_Periph nodes. PLAN-nodefw.md classifies a name as AP_Periph if it starts with `org.ardupilot.` or appears as a `CAN_APP_NODE_NAME` in ArduPilot's hwdef files.
- Code was read at PX4 main and ArduPilot master on 2026-11-09. The logs come from v1.18 builds and older main builds, whose bridge has the same structure (checked on `release/1.18`).
