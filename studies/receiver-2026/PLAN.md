# receiver-2026: does the GPS lag depend on the receiver model? (pre-registration)

Written and committed before any log for this study was downloaded. `receiver.py` (0.1.0) and `test_receiver.py` are committed with this plan, and the job that runs them waits until this file is on main.

## Question

PX4's EKF2 uses one setting, `EKF2_GPS_DELAY`, for the time between a GPS measurement and its arrival. The default is 110 ms, and 95-98% of public logs keep it. Our fleet studies found that about 30% of vehicles are more than 50 ms off their own setting (px4-gps-lag, `studies/fleet-2026/GRADE.md`, replicated in px4-log-health's fleet-health-2026, and confirmed by EKF2's own innovations in `GRADE-innov-confirm.md`). Do the receivers explain part of that?

ArduPilot assigns a lag by receiver generation. In `libraries/AP_GPS/AP_GPS_UBLOX.cpp`, `get_lag()`, the u-blox 7 and M8 get 0.12 s ("based on flight logs the 7 and 8 series seem to produce about 120ms lag"). F9, M9 and M10 get the same 0.12 s, with the comment "F9 lag not verified yet from flight log, but likely to be at least as good as M8". Unknown and older receivers get 0.22 s. We found no fleet measurement of lag by receiver model. A search turned up single-vehicle forum reports only, for example one ArduPilot F9P measured at 70-100 ms once its baud rate allowed 10 Hz (discuss.ardupilot.org/t/gps-data-lags-1s-behind-causes-gps-glitches/53760).

## How the receiver is read (PX4 source)

- `src/lib/drivers/device/Device.hpp` (v1.15.4): a device_id packs `bus_type : 3`, `bus : 5`, `address` (8 bits), `devtype` (8 bits). So devtype = (device_id >> 16) & 0xFF, and the bus type = device_id & 0x7 (1 i2c, 2 spi, 3 uavcan, 4 simulation, 5 serial, 6 mavlink).
- `src/drivers/drv_sensor.h`: 0xA5 UBX, 0xA6 UBX_6, 0xA7 UBX_7, 0xA8 UBX_8, 0xA9 UBX_9, 0xAA UBX_F9P, 0xAB NMEA, 0xAC UBX_10 and 0xAD UBX_20 (main only), 0xA0-0xA4 Ashtech, Emlid Reach, Femtomes, MTK, SBF, 0xAF SIM, 0x85 UAVCAN.
- `src/drivers/gps/gps.cpp`: the driver first sets DRV_GPS_DEVTYPE_UBX. After a successful configure, it sets the model from `driver_ubx->board()`: u_blox6 → UBX_6, u_blox7 → UBX_7, u_blox8 (M8N or M8P) → UBX_8, u_blox9 (M9N, or any F9 except F9P) → UBX_9, F9P → UBX_F9P. Anything else stays UBX (0xA5). In v1.15.4 that includes u_blox10 (M10). On main, only the L1/L5 M10 gets UBX_10 (PX4-GPSDrivers `ubx.h`, `enum class Board`). **So class "ubx_generic" (0xA5) mixes M10 receivers with undetected u-blox units.**
- `src/modules/sensors/vehicle_gps_position/VehicleGPSPosition.cpp` (v1.14+): vehicle_gps_position is the GPS blending module's output, and its device_id is set to 0 when blending ("clear device_id if blending").

receiver.py takes the most common non-zero device_id of `vehicle_gps_position`. If that is 0, it takes the only `sensor_gps` instance that has one. Several receivers with no selected id → "multiple". Nothing → "unknown". A uavcan bus id → "uavcan" (the module inside is not known). A serial id with a known devtype → its model ("ubx_m8", "ubx_m9", "ubx_f9p", "ubx_10", "ubx_generic", ...).

## Data

- PX4 Flight Review public logs (CC BY 4.0), with fleet.py 0.1.1's rules: real (non-simulated) logs of at least 240 s, from 2025-10-01 on, at most 80 MB.
- New seed 20261101. One log per vehicle, in seeded random order. **Every log and every vehicle drawn by fleet-2026 (`studies/fleet-2026/v1/logs.jsonl`) or by px4-log-health's fleet-health-2026 (`studies/fleet-health-2026/logs.jsonl`) is left out**, so this is a fresh sample.
- Up to 700 attempts in a 130-minute budget, 6 s between downloads, stop at once on HTTP 403/444. Each log is deleted once measured. No position is read; vehicle ids are published as a hash.
- Lag: gps_lag.py 0.1.0, unchanged, with its gates (≥100 in-flight GPS pairs, excitation ≥0.3 m/s², R² ≥0.6, SE ≤20 ms, best lag not at the search edge). Only logs that pass count.

## Checks

A class enters a comparison only with at least 15 passed logs. Intervals are seeded bootstrap 95% intervals of the difference of medians (2,000 resamples).

- **E1 (enough data):** at least two of the serial u-blox classes (ubx_m8, ubx_m9, ubx_f9p, ubx_10, ubx_generic) have at least 25 passed logs each. If E1 fails, every result below is reported as exploratory only.
- **P1 (ArduPilot's M8 figure):** the median lag of ubx_m8 is between 80 and 160 ms.
- **P2 (ArduPilot's untested F9 assumption):** the median lag of ubx_f9p is at most that of ubx_m8. The interval is reported, and P2 is called *clear* only if it lies below 0.
- **P3 (the model matters):** among serial classes whose model PX4 detected (uavcan excluded), the largest gap between two class medians is at least 20 ms, and its interval excludes 0.
- **P4 (a per-receiver default would help):** on vehicles in classes with at least 15 passed logs (uavcan included), using each vehicle's class median as the delay (leave-one-out: the median of the other vehicles in its class) puts at least 5 percentage points more vehicles within 50 ms than 110 ms does.
- **P5 (replication):** the median lag of uavcan receivers is lower than that of serial receivers with a known devtype. Both earlier samples point that way (90 vs 109 ms in fleet-2026; 108 vs 129 ms, exploratory, in fleet-health-2026).
- **P6 (the receiver can be read):** at least 70% of passed logs get a known class (not "unknown" or "multiple").

## Decisions written in advance

- **D1:** if E1 and P3 hold, px4-log-health's checkup gets a line in its GPS delay section: "receivers of this class on public logs: median X ms (n vehicles)". If P3 fails, the write-up says that the receiver model does not explain the mismatch on public logs, and per-vehicle measurement stays the advice.
- **D2:** P1 and P2 are reported as PX4 measurements only. The PX4 driver's timestamp path differs from ArduPilot's, so this says nothing about ArduPilot's lag on ArduPilot vehicles. It only tests whether the receivers' relative order matches ArduPilot's assumptions.
- Whatever the outcome, the per-log rows (`logs.jsonl`), `summary.json` and a GRADE.md are published, including any check that fails.

## Exploratory (not predicted)

Lag by class × PX4 release, class × best fix type (RTK fixed is 6), number of receivers, class × logged GPS interval, the `EKF2_GPS_DELAY` values used per class, and `timestamp - timestamp_sample` per class.

## Limits

- Flight Review uploads are self-selected, often after a problem.
- The measured lag runs from the measurement to the flight controller's timestamp. It mixes the receiver's own latency with the baud rate, message load and driver. A class difference can come from how PX4 configures each model (rate, baud), not from the chip alone.
- ubx_generic mixes M10 with undetected units, and uavcan modules are not identified.
- One log per vehicle. Vehicles of one class may share other traits, such as the frame or the flight controller.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
