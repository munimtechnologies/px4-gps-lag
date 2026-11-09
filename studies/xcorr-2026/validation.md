# gnss_latency.py validation

Checks (criteria in CRITERIA.md): V0 held, V1 held, V2 held, V3 held, V4 held

| log | kind | bus | px4-gps-lag ms | xcorr total ms | diff | r | applied ms (source) | residual ms | residual direct ms |
|---|---|---|---|---|---|---|---|---|---|
| log_5_20 | zip | serial | 110.5 | 104.2 | -6.3 | 0.998 | 160.0 (EKF2_GPS_DELAY) | -55.8 | None |
| log_8_20 | zip | serial | 214.2 | 217.0 | 2.8 | 0.993 | 160.0 (EKF2_GPS_DELAY) | 57.0 | None |
| 5f1584c9 | main | UAVCAN | 166.3 | 166.1 | -0.2 | 0.999 | 85.7 (timestamp - timestamp_sample) | 80.5 | 79.0 |
| 5548f136 | main | UAVCAN | 110.3 | 103.9 | -6.4 | 0.979 | 98.0 (timestamp - timestamp_sample) | 5.9 | 3.4 |
| 53a8335a | main | serial | 189.5 | 183.8 | -5.7 | 0.995 | 110.0 (timestamp - timestamp_sample) | 73.8 | 73.8 |
