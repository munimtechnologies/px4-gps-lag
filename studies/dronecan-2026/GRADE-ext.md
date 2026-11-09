# dronecan-2026 extension: grade

Graded on 2026-11-09 exactly against [PLAN-ext.md](PLAN-ext.md), which was committed before the job read any log. The job (`px4-gps-lag-dronecan-ext-v1`) ran in a sealed container from 12:20 to 14:07 UTC on 2026-11-09. The four test files passed before any log was read, and the plan on `main` matched the job's copy. Rows: [dronecan-ext-rows.jsonl](dronecan-ext-rows.jsonl). Scores: [dronecan-ext-summary.json](dronecan-ext-summary.json). Fetched code and hashes: [job-fetched-ext.json](job-fetched-ext.json).

**In one line:** public PX4 v1.18+ logs held 31 DroneCAN GNSS logs, but only 4 self-stamped ones passed gps_lag's gates, one short of the 5 the main prediction (D3) needs. So D3 is **not graded for the second time**. As the plan says for this case, this line of study now pauses until more v1.18 logs are public.

## The pass

| | |
|---|---|
| Flight Review list | 488,002 logs listed, 2,515 eligible (v1.18+ or no readable release, real, >= 60 s, dated 2026-06-30 or later), from 890 vehicles not read before |
| Requests | 890 (every candidate vehicle; the list ran out before any limit) |
| `UAVCAN_ENABLE` off | 256 |
| UAVCAN on, release not PX4 v1.x (not downloaded, by plan) | 505 |
| UAVCAN on, too big | 6 |
| Downloaded | 123; read OK 90; 33 had no `vehicle_gps_position` |
| GPS bus of the 90 | serial 50, DroneCAN 31, unknown 8, simulation 1 |

## Predictions

| | prediction | result | grade |
|---|---|---|---|
| **D1** | at least 8 DroneCAN logs (from 8 vehicles) are read | 31 logs from 31 vehicles | **held** |
| **D2** | in at least half of the DroneCAN logs that are not unknown, the receiver is self-stamped | 5 of 22 (23%) | **failed** |
| **D3** | given at least 5 passing self-stamped logs, their median residual is over 20 ms | 4 passed | **not graded** |
| **D4** | given at least 5 passing, in at least two thirds the lag is closer to 110 ms than to the applied delay | 4 passed | **not graded** |
| **D5** | control: at least 90% of serial-receiver logs have the applied delay within 1 ms of a delay parameter or 110 ms | 48 of 48 | **held** |

"Not graded" is not the same as failed: the minimum the plan set was not met.

## What the rows show (description, not a grade)

The four self-stamped DroneCAN logs that passed the gates (residual = measured lag - delay PX4 applied):

| board | applied | measured lag | residual |
|---|---|---|---|
| CubeOrange+ | 69.2 ms | 89.0 ms | +19.8 ms |
| CubeOrange+ | 47.2 ms | 92.2 ms | +45.0 ms |
| CUAV V6X | 10.4 ms | 65.4 ms | +55.0 ms |
| CubeOrange+ | 9.9 ms | 180.4 ms | +170.5 ms |

Their median is +50.0 ms, and in 3 of 4 the lag is closer to 110 ms than to the applied delay. Both point the way D3 and D4 predicted, but four logs are below the minimum the plan set, so neither is graded.

- **D2 failed, and that matters for the question.** In 17 of the 22 DroneCAN logs with a known receiver, the receiver was not self-stamped: PX4 applied a delay parameter or the 110 ms default, as before PR #27427. The four of those that passed the gates had residuals of -63.1, +0.4, +91.4 and +95.2 ms, so the fixed delay was off by tens of ms in both directions.
- **Control held.** On all 48 serial-receiver logs with a known receiver, the applied delay matched a delay parameter or 110 ms (median residual -16.8 ms), so the reader tells the two cases apart.
- **Two more vehicles had DroneCAN receivers but no device id on the GPS sample.** By plan they are listed and not graded: an EchoPilot AI (applied 110 ms, lag 175.5 ms, failed the gates) and a ZeroOne X6 with two receivers (applied 10.7 ms, lag 63.9 ms, passed).
- **Pooled with the first pass (not the grade).** 5 passing self-stamped logs, median residual +55.0 ms, 4 of 5 closer to 110 ms. The first pass's row (+72.0 ms) helped generate the hypothesis, which is why the plan grades the extension alone.
- **Cross-check from another method.** The independent cross-correlation tool ([tools/gnss_latency.py](../../tools/gnss_latency.py), validated in [studies/xcorr-2026](../xcorr-2026/GRADE.md)) agreed with gps_lag on the two DroneCAN units in the PX4 main logs it was checked on. The lags were 166.3 vs 166.1 ms and 110.3 vs 103.9 ms (gps_lag vs cross-correlation), against applied delays of 85.7 and 98.0 ms. That gives residuals of about +80 ms on one unit and about +6 ms on the other.

## What follows (as the plan set it)

D3 was not graded again, so:

- The result is reported as it stands. On public PX4 v1.18+ flights, DroneCAN GNSS is rare: 31 of 890 vehicles in this pass, about 3.5%. Self-stamped DroneCAN receivers are rarer still: 5 of the 22 with a known receiver.
- The dronecan-2026 study pauses until more v1.18 logs are public. Re-checking the list for new self-stamped logs no earlier than 2026-12-15 is reasonable.
- The node-firmware add-on ([PLAN-nodefw.md](PLAN-nodefw.md)) still runs on these rows. Its N2 depends only on the rows and can be scored now. There are 2 passing short self-reports (applied < 40 ms; residuals +55.0 and +170.5 ms), and N2 needs 3, so **N2 is not graded**. N3 and N4 need more passing logs than this extension has, so they cannot be graded either. N1 (node names) and the node table will come from the add-on's job.

## Limits

- By plan, 505 vehicles with UAVCAN on were not downloaded because their release is not PX4 v1.x: vendor version numbers such as v2.0, v5.x, v6.x and v8.6, or no release. DroneCAN receivers on vendor forks are therefore not in these rows. In the first pass, 19 such logs held no DroneCAN receiver, which is why the plan skipped them.
- Public Flight Review uploads are not a random sample of PX4 vehicles, and 33 downloaded logs had no GPS topic.
- gps_lag's gates fail most DroneCAN logs (18 of 31: 8 with too little velocity change explained by the IMU, 6 with too little manoeuvring, 4 with too few in-flight GPS pairs). The four that passed may not be typical.
- PPS wiring and receiver-side smoothing cannot be seen in a log.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0 (code Apache-2.0).
