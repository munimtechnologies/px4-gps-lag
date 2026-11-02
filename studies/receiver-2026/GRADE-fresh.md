# fresh-2026 graded against PLAN-fresh.md

Plan: [`PLAN-fresh.md`](PLAN-fresh.md), committed before any log for this study was downloaded. Job `px4-gps-lag-fresh-v1`, 2026-11-01 16:14-19:17 UTC: the unit tests of every module passed, then `fresh_nis.py` (which runs `fresh.py` 0.1.0 unchanged and adds the mismatch-2026 and nis-2026 fields to the same rows) drew the sample. Data: [`fresh/logs.jsonl`](fresh/logs.jsonl) (one line per attempt; vehicle ids hashed, no positions), [`fresh/summary.json`](fresh/summary.json), [`fresh/job-fetched.json`](fresh/job-fetched.json) (the sha256 of every file the job ran).

## The sample

- Flight Review listed 484,769 logs; 36,413 were eligible under fleet.py 0.1.1's rules (real, at least 240 s, from 2025-10-01 on). 1,237 logs and 1,164 vehicles of the earlier studies were left out.
- Seed 20261102, one log per vehicle. The job reached the cap of **1,000 attempts** after 179 minutes, inside the 215-minute budget. There was no block (no HTTP 403/444).
- 813 logs downloaded (187 were over 80 MB) and **298 passed** `gps_lag.py` 0.1.0's gates. The other reasons: the IMU explained too little of the GPS velocity change (181), no `vehicle_gps_position` in the log (141), too few in-flight GPS pairs (98), too little manoeuvring (86), and 9 others.

| receiver class | passing logs | median lag | p25 | p75 |
|---|---|---|---|---|
| u-blox M9 | 29 | **81.3 ms** | 62.0 | 100.0 |
| DroneCAN | 84 | 105.9 ms | 79.2 | 129.3 |
| u-blox M10 (`ubx_10`) | 7 | 105.2 ms | 92.7 | 133.5 |
| unknown | 20 | 105.8 ms | 72.4 | 134.4 |
| more than one receiver | 20 | 122.7 ms | 103.8 | 182.2 |
| u-blox, model not detected | 38 | 140.9 ms | 100.4 | 167.1 |
| u-blox F9P | 42 | **143.1 ms** | 119.8 | 180.1 |
| u-blox M8 | 12 | **145.3 ms** | 103.8 | 167.6 |
| NMEA | 24 | 208.4 ms | 77.5 | 255.7 |
| MAVLink-fed GPS | 13 | 18.9 ms | -3.6 | 135.1 |
| others (one u-blox 7, four unrecognised device types) | 9 | | | |

## Checks

| Check | Rule | Result | |
|---|---|---|---|
| E1 | M8, M9, F9P each ≥ 15 passing logs | M8 **12**, M9 29, F9P 42 | **fails** |
| F1 | M9 − M8 ≤ −20 ms, interval < 0 | M8 below 15 | not scored |
| F2 | M9 − F9P ≤ −20 ms, interval < 0 | **−61.8 ms (−88.4 to −42.1)** | meets its rule; exploratory because E1 failed |
| F3 | F9P and M8 within 30 ms | M8 below 15 | not scored |
| F4 | NMEA − serial u-blox ≥ +20 ms, interval > 0 | +83.0 ms (−40.2 to +128.1), n 24 vs 128 | **fails** |
| F5 | a per-class default puts ≥ 5 points more vehicles within 50 ms than 110 ms | 64.98% → 67.28% (+2.3 points, n 217) | **fails** |
| F6 | ≥ 70% of gridded M8, M9, F9P logs on the v1.15.4 driver's interval | M8 7 gridded (10 needed); M9 7/19 (37%); F9P 6/30 (20%) | not scored (M8 too few) |
| R2 | reported: M9 − other serial u-blox on the 125 ms grid | n 7 vs 8 | too few to compute |

**For the third time, E1 failed on the M8.** The plan expected about 25 M8 logs from receiver-2026's share (9.2% of passing logs). This sample had 12 (4.0%). By the plan's rule every result here is exploratory.

## Decisions, as written

- **D1 does not fire** (E1 failed). px4-log-health's checkup gets no per-receiver line, and the px4-gps-lag README keeps "exploratory".
- **D2 does not apply** (it needs E1). This sample is added to the README's receiver table as a third column, still exploratory.
- **D3 does not fire** (F4 failed). The README gets no NMEA note.

## What the three samples say together (exploratory)

No vehicle appears in more than one of these samples. None of them met its own enough-data rule, each time because of the M8 count, so this is a summary, not a confirmation:

| | receiver-2026 | receiver-confirm | fresh-2026 |
|---|---|---|---|
| M9 − F9P | 71.3 − 142.6 = −71.3 ms | −67.3 ms (−101.0 to −48.4) | **−61.8 ms (−88.4 to −42.1)** |
| M9 − M8 | 71.3 − 146.6 = −75.3 ms | 76.2 − 150.9 = −74.7 ms | 81.3 − 145.3 = −64.0 ms |
| F9P − M8 | −4.0 ms | −7.4 ms | −2.2 ms |

Three times the M9 was 60-75 ms less late than both the F9P and the M8. The two intervals computed for M9 − F9P are well clear of zero. Three times the F9P and the M8 sat within 8 ms of each other, which fits ArduPilot's assumption that the F9 lags like the M8. That assumption has still not been tested as planned, because the M8 class is rare among recent public PX4 logs.

**F5 failed:** a per-class default would bring only 2.3 points more vehicles within 50 ms of their measured lag. Within each class the spread is wide (F9P p25-p75: 120-180 ms), so knowing the receiver model does not replace measuring the vehicle. That fits the advice we already give: measure your own vehicle.

**F4 failed, and the NMEA class splits by update rate.** The NMEA logs whose receiver times sat on a 200 ms grid had a median lag of 102.0 ms (12 logs). The 8 NMEA logs that stepped 1,000 ms (1 Hz) had a median of 256.2 ms. rate-2026 saw the same thing: 238.5 ms for 1 Hz NMEA. A pooled "NMEA is later" figure mixes 1 Hz and 5 Hz receivers.

**F6 failed as rate-2026 predicted it would.** F6 used PX4 v1.15.4's driver rates (M9 125 ms, F9P 100 ms), which changed in v1.16. The release-aware rule, [`PLAN-rate2.md`](PLAN-rate2.md), was committed before this sample was downloaded and is scored from these rows separately (`rate2.py`).

## PX4 v1.18 logs: the delay setting is gone from the log

8 of the downloaded logs came from PX4 v1.18 pre-releases (4 alpha `-64`, 4 beta `-128`, uploaded June to October 2026). **None has `EKF2_GPS_DELAY`**: PX4 PR [#26660](https://github.com/PX4/PX4-Autopilot/pull/26660) removed it in favour of a delay per receiver (`SENS_GPS0_DELAY`, `SENS_GPS1_DELAY`). In all 8, the median of `vehicle_gps_position.timestamp − timestamp_sample` is **110.0 ms**: EKF2 fused every GPS sample 110 ms (the default) before it arrived. Three passed the lag gates:

| receiver | PX4 | measured lag | applied delay | difference |
|---|---|---|---|---|
| u-blox M8 | v1.18.0 alpha | 100.4 ms | 110.0 ms | −9.6 ms |
| u-blox M9 | v1.18.0 alpha | 70.7 ms | 110.0 ms | −39.3 ms |
| NMEA | v1.18.0 beta | 186.9 ms | 110.0 ms | **+76.9 ms** |

`gps_lag.py` 0.1.0 found no setting on these logs (its `lag_minus_param_ms` is empty), so `fresh.py`'s checks used only the lag. px4-log-health's checkup 0.3.2 reads the applied delay from the sample times instead, as here. No log in this sample used PX4 main's newer `vehicle_gnss` topic.

## Limits

- Flight Review uploads are self-selected, often after a problem. One log per vehicle.
- Classes come from the device id PX4's driver wrote. `ubx_generic` mixes M10 receivers with undetected u-blox units, and DroneCAN modules are not identified.
- The lag runs from the measurement to the flight controller's timestamp, so it includes PX4's configuration of each model (rate, baud, messages), not only the chip. Nothing here is about ArduPilot's own lag.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
