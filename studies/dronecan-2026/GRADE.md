# dronecan-2026: grade of the first pass

Graded on 2026-11-09 against [PLAN.md](PLAN.md), which was put on `main` (commit 7f8ad21a) before any log in this study was read. The sealed job `px4-gps-lag-dronecan-v1` ran on 2026-11-09 from 01:38 to 01:52 UTC. It fetched px4-gps-lag 0.2.0 and gnss-2026's `gnss_logs.py` 0.1.0 from `main` (hashes in [job-fetched.json](job-fetched.json)), passed all three test suites, checked PLAN.md against `main`, and then read Flight Review's public list once. Every request is a row in [dronecan-rows.jsonl](dronecan-rows.jsonl); the scores are in [dronecan-summary.json](dronecan-summary.json).

## Result

| | prediction | prior | result |
|---|---|---|---|
| **D1** | at least 8 DroneCAN logs (8 vehicles) are read | 50% | **failed**: 4 |
| **D2** | at least half of the DroneCAN logs that are not unknown are self-stamped | 60% | **held**: 2 of 4 |
| **D3** | median residual of self-stamped DroneCAN logs that pass the gates > 20 ms (needs 5) | 65% | **not graded**: 1 passing log |
| **D4** | in two thirds of them the lag is closer to 110 ms than to the applied delay (needs 5) | 55% | **not graded**: 1 passing log |
| **D5** | control: at least 90% of serial-receiver logs have the applied delay within 1 ms of a delay parameter or 110 ms | 85% | **held**: 10 of 10 |

As the plan says for a D1 failure: nothing is claimed beyond gnss-2026's three receivers. The main question (does PR #27427's self-reported delay cover the measured lag?) is still open.

## Why so few

The list held 488,002 logs. 2,985 logs from 986 vehicles were candidates (real flights of at least 60 s, dated 2026-06-30 or later, v1.18 or newer or with no readable release, not one of gnss-2026's 11 vehicles). The pass stopped at its own limit of 40 downloaded logs, after 96 vehicles:

- 53 had `UAVCAN_ENABLE` 0, so only their definitions were read.
- 43 had it on: 40 were downloaded, 3 were over 150 MB.
- 37 were read; 3 had no `vehicle_gps_position` topic.
- Of the 37, the GPS sample's bus was **serial on 17, unknown on 16 and DroneCAN on 4**.

So a DroneCAN GNSS receiver was found on 4 of 96 vehicles (4%), and most vehicles with CAN on use a serial GPS. The download limit was set too low for that. 14 of the 16 unknown-bus logs carry release numbers that are not PX4's own (v2.x or v6.x, likely vendor builds) or none; the other two are v1.18 logs whose GPS sample has no device id (one of them has two receivers configured).

## The four DroneCAN logs

All four are DroneCAN GNSS (device type 0x85) on v1.18 pre-release builds, at node 125 or 124.

| order | log date | flight controller | release | device id | delay applied | measured lag (se) | gates | class | residual |
|---|---|---|---|---|---|---|---|---|---|
| 4 | 2026-11-07 | DAMIAO_DM_FC01 | v1.18.0-128 | 8748291 | 110.0 ms | 644.5 ms (0.9) | failed: IMU explains too little (R² −0.21) | not self-stamped | — |
| 15 | 2026-11-05 | ZEROONE_X6 | v1.18.0-64 | 8748035 | 110.0 ms | 37.1 ms (4.0) | passed | not self-stamped | −72.9 ms |
| 44 | 2026-11-02 | CUBEPILOT_CUBEORANGEPLUS | v1.18.0-128 | 8748291 | 83.3 ms | 155.3 ms (0.5) | passed | **self-stamped** | **+72.0 ms** |
| 60 | 2026-10-30 | CUAV_X7PRO | v1.18.0-128 | 8748291 | 10.2 ms | 55.2 ms (1.5) | failed: R² 0.599 < 0.6 | self-stamped | (+45.0 ms, not counted) |

"Delay applied" is the median of the GPS sample's `timestamp − timestamp_sample`; "residual" is the measured lag minus that. Row 60 misses the R² gate by 0.001, so it does not count, as the plan fixed.

What can be said without a grade:

- **The one counted self-stamped receiver sits 72 ms past the delay PX4 applied**, within the range of gnss-2026's three (12, 81 and 83 ms). One log is not a test.
- **Two DroneCAN receivers on v1.18 were not self-stamped**: PX4 applied the 110 ms parameter to them, so their nodes either ran older firmware or the build predates PR #27427 in that branch. On row 15 the measured lag was 37 ms, so the 110 ms default over-corrected by 73 ms.
- **Serial control**: all 10 serial receivers with an applied delay had it equal to a delay parameter or 110 ms (D5), and their median lag past it was 38 ms.

## What happens next

The plan's question needs more DroneCAN logs, and 890 candidate vehicles were never reached. [PLAN-ext.md](PLAN-ext.md), put on `main` with this grade and before any further log is read, continues the same pass on the vehicles this pass did not request, with the same predictions and thresholds, a larger download limit, and downloads only for releases numbered as PX4 v1.x. It is graded on its own logs; the pooled figures are reported beside it.

No comment goes to PR #27427 from this pass, and px4-log-health's checkup does not change.

## Limits

- One log per vehicle, mostly developers' pre-release test flights.
- The measured lag includes any smoothing inside the receiver, while PR #27427 targets the navigation epoch's time.
- The logs don't say which node firmware ran or whether PPS anchored the node's clock.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text and data CC BY 4.0, code Apache-2.0. Flight logs are public on [Flight Review](https://review.px4.io); no position is published.
