# tools/

- `gnss_latency.py`: measures how far GNSS velocity lags the IMU in a PX4 flight log (ULog) by
  cross-correlation, and compares it with the delay PX4 applied (`EKF2_GPS_DELAY` up to v1.17;
  the log's own `timestamp - timestamp_sample` on v1.18 and main, which is where DroneCAN
  receivers' self-reported delay shows up). Writes a text summary, optional JSON and a 3-page PDF.
  It is written in the style of PX4's `Tools/dronecan_calibration/` latency scripts, as an
  independent check on px4-gps-lag's own method.

      pip install numpy scipy pyulog matplotlib
      python tools/gnss_latency.py flight.ulg --json result.json --output-dir out/

- `test_gnss_latency.py`: synthetic tests, no flight log needed
  (`cd tools && python -m unittest -v test_gnss_latency`).

How it was checked: on five public PX4 logs that px4-gps-lag had already measured, it agreed
within 6.4 ms on all five, with criteria fixed before the run (`studies/xcorr-2026/GRADE.md`).

By MV2 of Munim, Inc.; made with AI agents. Apache-2.0.
