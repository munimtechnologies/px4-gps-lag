# dronecan-2026 add-on (node firmware): graded

Graded by MV2 of Munim, Inc. (mv2@munimtech.com) on 2026-11-10, exactly against
[PLAN-nodefw.md](PLAN-nodefw.md), which was committed on 2026-11-09 before the extension pass read
any log. The job (`px4-gps-lag-nodefw-v1`) ran nodefw.py 0.1.0 once, after its synthetic tests
passed. The grade and code were made with AI agents working in MV2's name. Text CC BY 4.0, code
Apache-2.0.

Files: [nodefw-rows.jsonl](nodefw-rows.jsonl), [nodefw-summary.json](nodefw-summary.json) (every
figure below, the extension's table, and the earlier passes shown separately),
[job-fetched-nodefw.json](job-fetched-nodefw.json).

## What was read

- All 31 DroneCAN rows of the extension pass ([GRADE-ext.md](GRADE-ext.md)) were downloaded again
  and read; none failed.
- ArduPilot master's `libraries/AP_HAL_ChibiOS/hwdef/` (2,063 files) gave 34 `CAN_APP_NODE_NAME`
  strings. Together with the `org.ardupilot.` prefix rule, these decide the `ap_periph` family.

## Predictions (extension logs only)

| id | prediction | minimum | result | grade |
|---|---|---|---|---|
| N1 | At least 60 % of the extension's DroneCAN logs get a node name | none | 22 of 31 (**71 %**), all by device id | **holds** |
| N2 | Median residual of passing short self-reports is over 40 ms | 3 such logs | 2 logs (residuals 170.5 and 55.0 ms) | **not graded** |
| N3 | At least two thirds of named passing short self-reports are `ap_periph` | 3 such logs | 2 logs (1 `ap_periph`, 1 `other`) | **not graded** |
| N4 | `ap_periph` median residual exceeds `other` by at least 20 ms | 3 passing self-stamped named logs per family | `ap_periph` 1, `other` 3 | **not graded** |

One prediction held. Three could not be graded because too few new vehicles had a passing
self-stamped DroneCAN receiver. Not graded is not the same as failed: reason (a) of
[MECHANISM.md](MECHANISM.md), stamping from UART arrival without PPS, is neither supported nor
refuted by new vehicles.

## Description (not graded)

- **Names.** 22 of 31 logs named the GPS node: `com.cubepilot.here4` 6, `net.cuav.neo-4-se` 3,
  `org.ardupilot.HolybroG4_GPS` 3, `org.ardupilot.cuav_gps` 3, and one each of
  `net.cuav.c-rtk-3-g5`, `org.agam.can-gnss`, `org.ardupilot.CUAV_NEO_3X`,
  `org.ardupilot.ZeroOne_GNSS`, `org.ardupilot.ZeroOne_GNSS_AIR`, `org.ark.can-rtk-gps` and
  `org.puerari.can-gnss`. The 9 without a name had no `device_information` at all; all 9 come from
  two vendor builds whose version strings are not PX4's (v1.24.2 on GDCX_H743VI, 7 logs; v1.50.0 on
  DRONEYEE_AUTOFLY_V3, 2 logs).
- **Self-stamped receivers on new vehicles:** 5, of which 4 passed the lag fit:

  | node | family | applied | lag | residual |
  |---|---|---|---|---|
  | com.cubepilot.here4 (fw 1.15) | other | 9.9 ms | 180.4 ms | +170.5 ms |
  | org.ardupilot.CUAV_NEO_3X (fw 1.8) | ap_periph | 10.4 ms | 65.4 ms | +55.0 ms |
  | com.cubepilot.here4 (fw 1.15) | other | 47.2 ms | 92.2 ms | +45.0 ms |
  | com.cubepilot.here4 (fw 1.14) | other | 69.2 ms | 89.0 ms | +19.8 ms |

  Every passing self-stamped receiver left lag uncovered (+19.8 to +170.5 ms). Both short
  self-reports (under 40 ms) did, by 55 and 170 ms, and one of them is not AP_Periph by the
  plan's rule.
- **All passes pooled (7 earlier rows that generated the hypotheses, plus the extension; not a
  grade):** 3 passing short self-reports, median residual 82.6 ms, 2 of the 3 `ap_periph`. On this
  pooled set every prediction would hold, which is why it cannot be used to test them.
- **Extension receivers on PX4's 110 ms default** (not self-stamped) with a measured lag: residuals from
  -104.4 to +125.6 ms. The default fits some receivers and is far off for others.

## Limits

- Few vehicles: DroneCAN GNSS is a few percent of public v1.18 vehicles, and only 5 new ones
  stamped their own delay.
- PPS wiring cannot be seen in a log.
- The plan's rule puts `com.cubepilot.here4` in `other` (ArduPilot's hwdef files name
  `com.cubepilot.here4fc`, not `com.cubepilot.here4`). We did not check which time-stamping code
  CubePilot's Here4 firmware uses.

## What follows

- checkup keeps adding no DroneCAN warning beyond naming who set the delay (0.3.7 onward).
- The DroneCAN line is paused until more v1.18 self-stamped public logs exist (re-check from
  2026-12-15). The table above is offered as description for PX4 PR #27427's request for flight
  validation, not as a finding.

MV2, Munim, Inc. (mv2@munimtech.com)
