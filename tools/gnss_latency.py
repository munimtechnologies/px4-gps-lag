#!/usr/bin/env python3
"""
GNSS velocity latency analysis.

Estimates how far the GNSS velocity in a PX4 flight log lags the IMU, by
cross-correlating GNSS north/east velocity with IMU-derived velocity, and
compares the result with the delay PX4 already removes.

Three numbers are reported:
  total     GNSS velocity time-tagged with the time the flight controller
            received it (vehicle_gps_position.timestamp, or
            vehicle_gnss receiver.timestamp on PX4 main): measurement to arrival.
  applied   The delay PX4 subtracts before EKF2 fuses the sample:
            EKF2_GPS_DELAY up to v1.17; on v1.18 and main the median of
            timestamp - timestamp_sample (SENS_GNSSn_DELAY / SENS_GPSn_DELAY,
            or the driver's own sample stamp, e.g. DroneCAN since PR #27427).
  residual  What EKF2 still sees uncorrected: total - applied, and, when the
            log carries per-sample stamps, measured directly with the GNSS
            velocity time-tagged at timestamp_sample. Ideally close to 0.

Method:
  1. Rotate body specific force (sensor_combined) into NED with the attitude
     quaternion; north and east need no gravity removal.
  2. Integrate to north/east velocity (each sample is the mean since the
     previous one), interpolate onto a 200 Hz grid.
  3. Interpolate GNSS north/east velocity onto the same grid.
  4. Band-pass both identically and with zero phase (0.1 Hz high-pass removes
     integration drift, 2 Hz low-pass removes vibration).
  5. Cross-correlate over +-max lag, north and east pooled, weighted to the
     airborne part of the log; parabolic interpolation at the peak.

Usage: python3 gnss_latency.py <log.ulg> [--output-dir <dir>] [--json <file>]

Checked against px4-gps-lag on five public PX4 logs: studies/xcorr-2026/GRADE.md.
By MV2 of Munim, Inc.; made with AI agents. Apache-2.0 (this repository's LICENSE).
"""

import argparse
import json
import os
import sys

import numpy as np
from scipy import signal as sig

try:
    from pyulog import ULog
except ImportError:
    print("pyulog is required: pip install pyulog", file=sys.stderr)
    sys.exit(1)

GRID_FS = 200.0
HP_CUTOFF_HZ = 0.1
LP_CUTOFF_HZ = 2.0
MAX_GNSS_GAP_S = 0.5
MAX_IMU_GAP_S = 0.1
MIN_AIRBORNE_S = 20.0
RELATIVE_TIMESTAMP_INVALID = 0x7FFFFFFF
TOPICS = ["sensor_combined", "vehicle_attitude", "vehicle_gps_position", "vehicle_gnss",
          "vehicle_land_detected"]
BUS_TYPES = {0: "unknown", 1: "I2C", 2: "SPI", 3: "UAVCAN", 4: "simulation", 5: "serial", 6: "MAVLink"}


# ---------------------------------------------------------------------------
# ULog helpers
# ---------------------------------------------------------------------------

def get_topic(ulog, name, multi_id=0):
    for d in ulog.data_list:
        if d.name == name and d.multi_id == multi_id:
            return d
    return None


def field(d, *names):
    """First of names present in the topic, as a numpy array, else None."""
    for n in names:
        if n in d.data:
            return np.asarray(d.data[n])
    return None


def us_to_s(ts_us, start_us):
    return (np.asarray(ts_us).astype(np.int64) - np.int64(start_us)) / 1e6


def increasing(t, *arrays):
    """Sort by t and keep only strictly increasing times."""
    order = np.argsort(t, kind="stable")
    t = t[order]
    keep = np.concatenate(([True], np.diff(t) > 0)) if len(t) else np.zeros(0, bool)
    return (t[keep],) + tuple(a[order][keep] for a in arrays)


def bus_name(device_id):
    if device_id is None:
        return None
    return BUS_TYPES.get(int(device_id) & 0x7, "unknown")


# ---------------------------------------------------------------------------
# Signal processing
# ---------------------------------------------------------------------------

def band(x, fs, hp=HP_CUTOFF_HZ, lp=LP_CUTOFF_HZ, order=2):
    """Zero-phase high-pass then low-pass along axis 0."""
    b, a = sig.butter(order, hp / (0.5 * fs), btype="highpass")
    x = sig.filtfilt(b, a, x, axis=0)
    if lp is not None and lp < 0.5 * fs:
        b, a = sig.butter(order, lp / (0.5 * fs), btype="lowpass")
        x = sig.filtfilt(b, a, x, axis=0)
    return x


def interp_quat(t, att_t, q):
    """Quaternions (w, x, y, z) at times t: sign-aligned, linear per component, renormalised."""
    q = np.array(q, dtype=float)
    if len(q) > 1:
        dots = np.sum(q[1:] * q[:-1], axis=1)
        flips = np.cumprod(np.where(dots < 0, -1.0, 1.0))
        q[1:] *= flips[:, None]
    out = np.column_stack([np.interp(t, att_t, q[:, k]) for k in range(4)])
    return out / np.linalg.norm(out, axis=1)[:, None]


def quat_to_ne(q, f_body):
    """North and east components of body-frame vectors rotated by body-to-NED quaternions."""
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    fx, fy, fz = f_body[:, 0], f_body[:, 1], f_body[:, 2]
    n = (1 - 2 * (y * y + z * z)) * fx + 2 * (x * y - w * z) * fy + 2 * (x * z + w * y) * fz
    e = 2 * (x * y + w * z) * fx + (1 - 2 * (x * x + z * z)) * fy + 2 * (y * z - w * x) * fz
    return np.column_stack((n, e))


def integrate(t, a):
    """Velocity from accelerations that are each the mean since the previous sample."""
    dt = np.diff(t, prepend=t[0])
    return np.cumsum(a * dt[:, None], axis=0)


def parabolic_peak(c, lags_s):
    """Refined lag at the maximum of c, the value there, and whether it sits at an edge."""
    i = int(np.argmax(c))
    if i == 0 or i == len(c) - 1:
        return float(lags_s[i]), float(c[i]), True
    y0, y1, y2 = c[i - 1], c[i], c[i + 1]
    den = y0 - 2 * y1 + y2
    off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return float(lags_s[i] + off * (lags_s[1] - lags_s[0])), float(y1), False


def weighted_xcorr(ref, test, w, max_lag_n):
    """Normalised c[k] = sum_t w(t) ref(t).test(t+k), k in [-K, K]; positive k: test lags ref."""
    n, K = len(ref), max_lag_n
    lo, hi = K, n - K
    r = ref[lo:hi] * w[lo:hi, None]
    rr = np.sum(r * ref[lo:hi])
    ks = np.arange(-K, K + 1)
    c = np.zeros(len(ks))
    for j, k in enumerate(ks):
        g = test[lo + k:hi + k]
        gg = np.sum(w[lo:hi, None] * g * g)
        if rr > 0 and gg > 0:
            c[j] = np.sum(r * g) / np.sqrt(rr * gg)
    return ks, c


def gap_mask(grid, t, max_gap):
    """True where the samples of t around each grid time are at most max_gap apart."""
    idx = np.searchsorted(t, grid)
    prev = t[np.clip(idx - 1, 0, len(t) - 1)]
    nxt = t[np.clip(idx, 0, len(t) - 1)]
    return (nxt - prev) <= max_gap


def air_intervals(t, landed, t_end):
    """(start, end) intervals where landed is false; each state holds until the next sample."""
    out, start = [], None
    for ti, lnd in zip(t, landed):
        if not lnd and start is None:
            start = float(ti)
        elif lnd and start is not None:
            out.append((start, float(ti)))
            start = None
    if start is not None:
        out.append((start, float(t_end)))
    return out


def estimate_delay(imu_t, f_body, att_t, q, gnss_t, vel_ne, air, max_lag_s=0.5, fs=GRID_FS):
    """
    Delay of GNSS velocity behind the IMU, in seconds.

    imu_t (N,) s; f_body (N,3) specific force, each the mean since the previous sample;
    att_t (M,) s; q (M,4) body-to-NED (w, x, y, z); gnss_t (G,) s, the time tag under test;
    vel_ne (G,2) GNSS north/east velocity; air: list of (start, end) airborne intervals, s.
    Returns None when there is too little airborne overlap.
    """
    a_ne = quat_to_ne(interp_quat(imu_t, att_t, q), f_body)
    v_imu = integrate(imu_t, a_ne)
    t0, t1 = max(imu_t[0], gnss_t[0]), min(imu_t[-1], gnss_t[-1])
    K = int(round(max_lag_s * fs))
    grid = np.arange(t0, t1, 1.0 / fs)
    if len(grid) < 2 * K + int(MIN_AIRBORNE_S * fs):
        return None
    ref = band(np.column_stack([np.interp(grid, imu_t, v_imu[:, k]) for k in range(2)]), fs)
    test = band(np.column_stack([np.interp(grid, gnss_t, vel_ne[:, k]) for k in range(2)]), fs)
    w = np.zeros(len(grid))
    for a0, a1 in air:
        w[(grid >= a0) & (grid <= a1)] = 1.0
    w *= gap_mask(grid, gnss_t, MAX_GNSS_GAP_S) & gap_mask(grid, imu_t, MAX_IMU_GAP_S)
    airborne_s = float(np.sum(w[K:len(grid) - K]) / fs)
    if airborne_s < MIN_AIRBORNE_S:
        return None
    ks, c = weighted_xcorr(ref, test, w, K)
    lags_s = ks / fs
    delay_s, r, edge = parabolic_peak(c, lags_s)
    wsum = np.sum(w)
    excitation = float(np.sqrt(np.sum(w[:, None] * ref * ref) / max(wsum, 1.0) / 2.0))
    return {"delay_s": delay_s, "r": r, "edge": edge, "lags_s": lags_s, "c": c,
            "airborne_s": airborne_s, "excitation_m_s": excitation, "fs": fs,
            "grid": grid, "ref": ref, "test": test, "w": w}


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def applied_delay(params, receive_us, sample_us):
    """Delay (ms) PX4 subtracts from the GNSS receive time before fusion, and its source."""
    if "EKF2_GPS_DELAY" in params:
        return float(params["EKF2_GPS_DELAY"]), "EKF2_GPS_DELAY"
    if sample_us is not None and len(sample_us):
        rec = np.asarray(receive_us).astype(np.int64)
        smp = np.asarray(sample_us).astype(np.int64)
        d = rec - smp
        ok = (smp > 0) & (d > 0)
        if np.count_nonzero(ok) >= 0.5 * len(d):
            return float(np.median(d[ok]) / 1000.0), "timestamp - timestamp_sample"
    for name in ("SENS_GNSS0_DELAY", "SENS_GPS0_DELAY"):
        if name in params:
            return float(params[name]), name
    return None, None


def extract_imu(ulog, start):
    d = get_topic(ulog, "sensor_combined")
    if d is None:
        return None
    t = np.asarray(d.data["timestamp"]).astype(np.int64)
    rel = field(d, "accelerometer_timestamp_relative")
    ok = np.ones(len(t), bool)
    if rel is not None:
        rel = rel.astype(np.int64)
        ok = rel != RELATIVE_TIMESTAMP_INVALID
        t = t + np.where(ok, rel, 0)
    f = np.column_stack([d.data["accelerometer_m_s2[%d]" % k] for k in range(3)]).astype(float)
    ok &= np.all(np.isfinite(f), axis=1)
    return increasing(us_to_s(t[ok], start), f[ok])


def extract_attitude(ulog, start):
    d = get_topic(ulog, "vehicle_attitude")
    if d is None:
        return None
    ts = field(d, "timestamp_sample")
    if ts is None or not np.all(ts > 0):
        ts = field(d, "timestamp")
    q = np.column_stack([d.data["q[%d]" % k] for k in range(4)]).astype(float)
    return increasing(us_to_s(ts, start), q)


def extract_gnss(ulog, instance=0):
    """Receive and sample stamps (us), north/east velocity and validity from either GNSS topic."""
    d = get_topic(ulog, "vehicle_gps_position", instance)
    if d is not None:
        topic = "vehicle_gps_position"
        recv, sample = field(d, "timestamp"), field(d, "timestamp_sample")
        vn, ve = field(d, "vel_n_m_s"), field(d, "vel_e_m_s")
        fix, vvalid, dev = field(d, "fix_type"), field(d, "vel_ned_valid"), field(d, "device_id")
    else:
        d = get_topic(ulog, "vehicle_gnss", instance)
        if d is None:
            return None
        topic = "vehicle_gnss"
        recv = field(d, "receiver.timestamp", "timestamp")
        sample = field(d, "timestamp_sample", "receiver.timestamp_sample")
        vn = field(d, "receiver.vel_north", "receiver.vel_n_m_s")
        ve = field(d, "receiver.vel_east", "receiver.vel_e_m_s")
        fix = field(d, "receiver.fix_type", "fix_type")
        vvalid = field(d, "receiver.vel_ned_valid", "vel_ned_valid")
        dev = field(d, "receiver.device_id", "device_id")
    if recv is None or vn is None or ve is None:
        return None
    vel = np.column_stack((vn, ve)).astype(float)
    valid = np.all(np.isfinite(vel), axis=1)
    if fix is not None:
        valid &= fix >= 3
    if vvalid is not None:
        valid &= vvalid.astype(bool)
    device_id = None
    if dev is not None and len(dev):
        vals, counts = np.unique(dev, return_counts=True)
        device_id = int(vals[np.argmax(counts)])
    return {"topic": topic, "recv_us": np.asarray(recv).astype(np.int64),
            "sample_us": None if sample is None else np.asarray(sample).astype(np.int64),
            "vel": vel, "valid": valid, "device_id": device_id}


def extract_air(ulog, start, t_end):
    d = get_topic(ulog, "vehicle_land_detected")
    if d is None:
        return None
    return air_intervals(us_to_s(d.data["timestamp"], start), np.asarray(d.data["landed"]).astype(bool), t_end)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(log_path, instance=0, max_lag_s=0.5):
    """Returns (results dict, fits dict) or raises ValueError with a reason."""
    ulog = ULog(log_path, TOPICS)
    start = ulog.start_timestamp
    params = ulog.initial_parameters
    imu = extract_imu(ulog, start)
    att = extract_attitude(ulog, start)
    gnss = extract_gnss(ulog, instance)
    if imu is None or att is None:
        raise ValueError("log has no sensor_combined or vehicle_attitude")
    if gnss is None:
        raise ValueError("log has no vehicle_gps_position or vehicle_gnss (instance %d)" % instance)
    imu_t, f_body = imu
    att_t, q = att
    air = extract_air(ulog, start, imu_t[-1])
    air_source = "vehicle_land_detected"
    if air is None:
        air, air_source = [(float(imu_t[0]), float(imu_t[-1]))], "whole log (no vehicle_land_detected)"

    valid = gnss["valid"]
    recv, sample = gnss["recv_us"][valid], None if gnss["sample_us"] is None else gnss["sample_us"][valid]
    if len(recv) < 20:
        raise ValueError("fewer than 20 valid GNSS velocity samples")
    applied_ms, applied_src = applied_delay(params, recv, sample)

    t_recv, vel_recv = increasing(us_to_s(recv, start), gnss["vel"][valid])
    fits = {"total": estimate_delay(imu_t, f_body, att_t, q, t_recv, vel_recv, air, max_lag_s)}
    if fits["total"] is None:
        raise ValueError("less than %.0f s of airborne IMU and GNSS overlap" % MIN_AIRBORNE_S)
    fits["residual"] = None
    if applied_src == "timestamp - timestamp_sample":
        ok = (sample > 0) & (sample < recv)
        t_smp, vel_smp = increasing(us_to_s(sample[ok], start), gnss["vel"][valid][ok])
        fits["residual"] = estimate_delay(imu_t, f_body, att_t, q, t_smp, vel_smp, air, max_lag_s)

    tot = fits["total"]
    res = {
        "log": os.path.basename(log_path),
        "gnss_topic": gnss["topic"],
        "instance": instance,
        "device_id": None if gnss["device_id"] is None else "0x%06X" % gnss["device_id"],
        "bus": bus_name(gnss["device_id"]),
        "gnss_samples": int(len(t_recv)),
        "gnss_rate_hz": float(1.0 / np.median(np.diff(t_recv))),
        "imu_rate_hz": float(1.0 / np.median(np.diff(imu_t))),
        "airborne_from": air_source,
        "airborne_s": round(tot["airborne_s"], 1),
        "excitation_m_s": round(tot["excitation_m_s"], 3),
        "max_lag_ms": max_lag_s * 1000.0,
        "total_delay_ms": round(tot["delay_s"] * 1000.0, 1),
        "total_r": round(tot["r"], 3),
        "total_at_edge": tot["edge"],
        "applied_delay_ms": None if applied_ms is None else round(applied_ms, 1),
        "applied_source": applied_src,
        "residual_ms": None if applied_ms is None else round(tot["delay_s"] * 1000.0 - applied_ms, 1),
        "residual_direct_ms": None,
        "residual_direct_r": None,
        "params": {k: float(params[k]) for k in ("EKF2_GPS_DELAY", "SENS_GNSS0_DELAY", "SENS_GPS0_DELAY",
                                          "GPS_UBX_DYNMODEL") if k in params},
    }
    if fits["residual"] is not None:
        res["residual_direct_ms"] = round(fits["residual"]["delay_s"] * 1000.0, 1)
        res["residual_direct_r"] = round(fits["residual"]["r"], 3)
    return res, fits


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def result_lines(res):
    lines = ["Estimated GNSS velocity delay behind the IMU:",
             "  total (receive time):   %+.1f ms  (r = %.3f)%s" % (
                 res["total_delay_ms"], res["total_r"], "  AT WINDOW EDGE" if res["total_at_edge"] else "")]
    if res["applied_delay_ms"] is not None:
        lines.append("  applied by PX4:         %+.1f ms  (%s)" % (res["applied_delay_ms"], res["applied_source"]))
        lines.append("  residual (total-applied): %+.1f ms" % res["residual_ms"])
    else:
        lines.append("  applied by PX4:         unknown (no delay parameter or sample stamps in the log)")
    if res["residual_direct_ms"] is not None:
        lines.append("  residual (sample time): %+.1f ms  (r = %.3f)" % (res["residual_direct_ms"],
                                                                      res["residual_direct_r"]))
    return lines


def warnings(res):
    out = []
    if res["total_at_edge"]:
        out.append("Peak at the edge of the window: increase --max-lag-ms.")
    if res["total_r"] < 0.6:
        out.append("Weak correlation (r < 0.6): fly more horizontal manoeuvres for a reliable estimate.")
    if res["excitation_m_s"] < 0.2:
        out.append("Little horizontal motion: the estimate may not be resolvable.")
    if res["residual_ms"] is not None and abs(res["residual_ms"]) > 50:
        out.append("Residual above 50 ms: EKF2 fuses this GNSS later or earlier than it was measured.")
    return out


def make_report(log_path, res, fits, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    name = os.path.splitext(os.path.basename(log_path))[0]
    pdf_path = os.path.join(output_dir, name + "_gnss_latency.pdf")
    tot = fits["total"]
    fs, grid, ref, test, w = tot["fs"], tot["grid"], tot["ref"], tot["test"], tot["w"]
    win = min(int(30 * fs), len(grid) - 1)
    energy = np.cumsum(w * np.sum(ref * ref, axis=1))
    i0 = int(np.argmax(energy[win:] - energy[:-win])) if len(energy) > win else 0
    sl = slice(i0, i0 + win)
    with PdfPages(pdf_path) as pdf:
        fig, axes = plt.subplots(2, 1, figsize=(11, 8.5), sharex=True)
        for k, (ax, axis) in enumerate(zip(axes, ("north", "east"))):
            ax.plot(grid[sl], ref[sl, k], label="IMU-integrated velocity", lw=1.2)
            ax.plot(grid[sl], test[sl, k], label="GNSS velocity at receive time", lw=1.0, alpha=0.8)
            shifted = np.interp(grid[sl] + tot["delay_s"], grid, test[:, k])
            ax.plot(grid[sl], shifted, "--", label="GNSS shifted by %.1f ms" % (tot["delay_s"] * 1000), lw=1.0)
            ax.set_ylabel("%s velocity, band-passed [m/s]" % axis)
            ax.grid(True, alpha=0.3)
            ax.legend(loc="upper right", fontsize=8)
        axes[-1].set_xlabel("time since log start [s] (30 s with the most motion)")
        fig.suptitle("%s: GNSS vs IMU velocity" % res["log"])
        pdf.savefig(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(11, 8.5))
        ax.plot(tot["lags_s"] * 1000, tot["c"], label="GNSS at receive time: peak %.1f ms, r=%.3f" % (
            tot["delay_s"] * 1000, tot["r"]))
        ax.axvline(tot["delay_s"] * 1000, color="C0", ls=":")
        if res["applied_delay_ms"] is not None:
            ax.axvline(res["applied_delay_ms"], color="k", ls="--",
                       label="applied by PX4: %.1f ms (%s)" % (res["applied_delay_ms"], res["applied_source"]))
        if fits.get("residual") is not None:
            rf = fits["residual"]
            ax.plot(rf["lags_s"] * 1000, rf["c"], label="GNSS at timestamp_sample: peak %.1f ms, r=%.3f" % (
                rf["delay_s"] * 1000, rf["r"]))
            ax.axvline(rf["delay_s"] * 1000, color="C1", ls=":")
        ax.set_xlabel("lag [ms] (positive: GNSS behind IMU)")
        ax.set_ylabel("normalised correlation")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
        ax.set_title("Cross-correlation, north and east pooled")
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=(11, 8.5))
        text = [
            "GNSS velocity latency analysis", "",
            "Log:            %s" % res["log"],
            "GNSS topic:     %s (instance %d), device %s, bus %s" % (res["gnss_topic"], res["instance"],
                                                                   res["device_id"], res["bus"]),
            "GNSS samples:   %d valid, %.1f Hz logged" % (res["gnss_samples"], res["gnss_rate_hz"]),
            "IMU:            sensor_combined %.0f Hz, vehicle_attitude quaternion" % res["imu_rate_hz"],
            "Airborne:       %.1f s used (%s)" % (res["airborne_s"], res["airborne_from"]),
            "Excitation:     %.3f m/s RMS band-passed horizontal velocity" % res["excitation_m_s"],
            "Grid:           %.0f Hz, band-pass %.1f-%.1f Hz (zero phase), window +-%.0f ms" % (
                GRID_FS, HP_CUTOFF_HZ, LP_CUTOFF_HZ, res["max_lag_ms"]),
            "", ] + result_lines(res) + [""] + warnings(res) + [
            "",
            "total:    lag of GNSS velocity, tagged with the flight-controller receive time, behind the IMU.",
            "applied:  the delay PX4 removes before EKF2 fuses the sample.",
            "residual: what is left; a large residual means the delay setting or the driver's",
            "          sample stamp does not match this receiver.",
        ]
        fig.text(0.05, 0.95, "\n".join(text), family="monospace", fontsize=9, va="top")
        pdf.savefig(fig)
        plt.close(fig)
    return pdf_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="GNSS velocity latency analysis")
    parser.add_argument("log", help="ULog file (.ulg)")
    parser.add_argument("--output-dir", help="Output directory (default: logs/<name>/)")
    parser.add_argument("--instance", type=int, default=0, help="GNSS topic instance (default: 0)")
    parser.add_argument("--max-lag-ms", type=float, default=500.0, help="Correlation window, +- ms (default: 500)")
    parser.add_argument("--json", help="Also write the results to this JSON file")
    parser.add_argument("--no-pdf", action="store_true", help="Do not write the PDF report")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.log):
        print("Error: %s not found" % args.log, file=sys.stderr)
        return 1
    name = os.path.splitext(os.path.basename(args.log))[0]
    output_dir = args.output_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs", name)

    print("Loading %s ..." % args.log)
    try:
        res, fits = analyse(args.log, args.instance, args.max_lag_ms / 1000.0)
    except ValueError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1
    print("  %s: %d valid samples, %.1f Hz, device %s (%s)" % (res["gnss_topic"], res["gnss_samples"],
                                                              res["gnss_rate_hz"], res["device_id"], res["bus"]))
    print("  sensor_combined: %.0f Hz; airborne %.1f s (%s)" % (res["imu_rate_hz"], res["airborne_s"],
                                                                res["airborne_from"]))
    print("=" * 50)
    for line in result_lines(res):
        print(line)
    print("=" * 50)
    for line in warnings(res):
        print("Note: " + line)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
            f.write("\n")
    if not args.no_pdf:
        os.makedirs(output_dir, exist_ok=True)
        print("Report: %s" % make_report(args.log, res, fits, output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
