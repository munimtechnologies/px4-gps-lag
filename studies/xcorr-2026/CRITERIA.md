# gnss_latency.py: validation criteria (fixed before the job runs)

`gnss_latency.py` is a draft tool in the style of PX4's `Tools/dronecan_calibration/`
(`range_sensor_latency.py`, `flow_sensor_latency.py`): it estimates GNSS velocity delay by
cross-correlating GNSS velocity with IMU-integrated velocity. MV2's px4-gps-lag
(`gps_lag.py`) measures the same delay by a different method (least-squares fit of GPS
velocity changes against IMU integrals over shifted intervals, per GPS sample pair).

The job runs both on five public PX4 logs that px4-gps-lag has already measured and
published, so this is a **method-agreement check, not a new result**:

| log | source | px4-gps-lag lag (ms) | applied by PX4 (ms) |
|---|---|---|---|
| log_5_2025-5-27-11-50-34.ulg | PX4 PR #24831 attachment, model 7 | 110.5 | 110 (EKF2_GPS_DELAY) |
| log_8_2025-5-27-12-55-02.ulg | PX4 PR #24831 attachment, model 6 | 214.2 | 110 (EKF2_GPS_DELAY) |
| 5f1584c9-83ad-4d5e-97ac-46b3ed19f8e6 | Flight Review, PX4 main, DroneCAN | 166.3 | 85.65 (sample stamps) |
| 5548f136-8ecc-4b45-8c14-721bdf888a62 | Flight Review, PX4 main, DroneCAN | 110.3 | 98.03 (sample stamps) |
| 53a8335a-3705-4d98-acff-5d21cae8e6de | Flight Review, PX4 main, serial u-blox | 189.5 | 110 (sample stamps) |

Checks (all fixed now; the job reports each as held or not, whatever comes out):

- **V0**: the synthetic unit tests pass (known delays 0, 40, 150, 210 ms recovered within 3 ms).
- **V1**: each of the five logs gives an interior correlation peak with r >= 0.5.
- **V2**: |total_delay_ms - px4-gps-lag lag| <= 20 ms on at least 4 of the 5 logs.
- **V3**: on the three PX4 main logs, the residual measured directly with timestamp_sample
  and total - applied agree within 10 ms.
- **V4**: a PDF report is written for every log that passes V1.

If V2 fails, the two methods disagree on real logs; that is reported as found, and the
upstream proposal waits until the reason is understood.

By MV2 of Munim, Inc.; made with AI agents. Apache-2.0.
