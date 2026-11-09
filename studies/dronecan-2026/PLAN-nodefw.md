# dronecan-2026 add-on: which DroneCAN GNSS nodes leave lag uncovered? (pre-registered)

Written and committed 2026-11-09, **before** the extension pass (PLAN-ext.md, job `px4-gps-lag-dronecan-ext-v1`) read any log. No one has seen the extension's rows. The reasoning is in MECHANISM.md, next to this file.

By MV2 of Munim, Inc. (mv2@munimtech.com). Written with AI agents. Text CC BY 4.0, code Apache-2.0.

## Question

Since PX4 PR #27427, a DroneCAN GNSS node's own time stamps set the delay PX4 applies. Code reading (MECHANISM.md) gives two reasons that delay can fall short of the measured GPS lag:

- **(a)** The node stamps from UART arrival rather than the navigation epoch. AP_Periph does this without PPS. It shows as a small applied delay with a large residual.
- **(b)** Smoothing inside the receiver, which no stamp can show.

This add-on asks whether (a) shows up on vehicles nobody has looked at, and which node firmware the short self-reports come from.

## Data

- **Graded:** the extension's rows (`studies/dronecan-2026/dronecan-ext-rows.jsonl`, once published with its grade). Every row read OK whose GPS sample is on DroneCAN (`measure.gps_bus == "uavcan"`).
- **Reported beside, never graded:** the DroneCAN rows of gnss-2026 (`gnss-rows.jsonl`, 3 logs) and the first dronecan pass (`dronecan-rows.jsonl`, 4 logs). These generated the hypotheses.

## Definitions (fixed now)

- **applied**, **lag**, **residual = lag - applied**, **passed** and **self-stamped** are exactly as in dronecan_logs.py 0.1.0. Self-stamped means the applied delay is more than 1 ms from every SENS_GNSS*/SENS_GPS*_DELAY parameter and from 110 ms. For gnss-2026 rows: applied = `measure.receiver_minus_sample_ms`, lag and passed come from `measure.gps_lag`, and the bus is `measure.bus`.
- **short self-report:** a self-stamped log with applied < 40 ms.
- **node name:** nodefw.py 0.1.0 downloads each selected log again and reads `device_information`.
  - The name is taken from the entries whose `device_id` equals the GPS sample's device id, if exactly one name is there.
  - Otherwise, if exactly one name has `device_type` 4 (GPS), that one is taken.
  - Otherwise there is no name. The match method is recorded.
- **family:**
  - `ap_periph` if the name, lower-cased, starts with `org.ardupilot.` or equals a `CAN_APP_NODE_NAME` string found in any file under `libraries/AP_HAL_ChibiOS/hwdef/` of ArduPilot master. The job streams the tarball and records how many files and names it found.
  - `other` for any other name.
  - None without a name.

## Predictions (graded on extension logs only)

| id | prediction | my probability |
|---|---|---|
| N1 | Of the extension's DroneCAN logs that nodefw reads again, at least 60% get a node name. | 50% |
| N2 | Given at least 3 passing short self-reports, their median residual is over 40 ms. | 60% |
| N3 | Given at least 3 passing short self-reports with a name, at least two thirds are `ap_periph`. | 50% |
| N4 | Given at least 3 passing self-stamped logs with a name in each family, the median residual of `ap_periph` exceeds that of `other` by at least 20 ms. | 45% |

A prediction whose minimum is not met is **not graded**, which is not the same as failed. N2 uses only the extension's own rows, so it can be graded as soon as they are published, even before nodefw runs.

## What each outcome means

- **N2 holds:** short self-reports leave a large share of the lag uncovered on new vehicles, as reason (a) predicts. With N3, this goes into the dronecan-2026 report for PR #27427 as a finding about stamping from UART arrival in node firmware without PPS. It suggests no parameter values.
- **N2 fails:** short self-reports did not leave large residuals on new vehicles. Reason (a) is not supported, and that is reported.
- **N4 fails while N2 holds:** the shortfall is not specific to AP_Periph.
- **Not graded:** the table of node names, firmware versions, applied delays and residuals is published as description only.

## Method limits

- Few vehicles: DroneCAN GNSS was about 4% of v1.18+ vehicles in the first pass.
- PPS wiring cannot be seen in a log. A vendor may ship AP_Periph under a name that is in no hwdef file.
- `device_information` may be missing on builds before PX4 commit 11acc3a19e (2026-09-22) for nodes whose GetNodeInfo arrived before their first Fix2. N1 measures that.

## Run limits

- Each selected log is downloaded at most once, at most 60 logs in all, at most 150 MB each, 6 s apart.
- The pass stops at the first block (403/429/444) or after five errors in a row, and has a 120-minute budget.
- No position is read or written, and device serial numbers are not written. Each file is deleted after it is read.
- Before any log is read, the job checks that this file on px4-gps-lag's main matches its local copy.
