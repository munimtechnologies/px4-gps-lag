"""For the px4-gps-lag-gnss job only (not published). Builds gps_lag.py 0.2.0 from main's 0.1.0
(gps_lag_main.py, saved by job_fetch.py) by exact text edits, each of which must match exactly
once, and writes job-diff.txt (main -> 0.2.0).

0.2.0 reads PX4 main's vehicle_gnss topic. PX4 PR #24399 (on main since 2026-09-29) renamed
vehicle_gps_position to vehicle_gnss: the selected receiver's sensor_gnss sample is nested as
'receiver' (pyulog names its fields 'receiver.<field>'), the velocity fields vel_n_m_s / vel_e_m_s
became vel_north / vel_east (msg/SensorGnss.msg), and the delay-corrected sample time is
vehicle_gnss.timestamp_sample (msg/VehicleGnss.msg). When a log has no vehicle_gps_position but
has vehicle_gnss, read_log now takes the GPS columns from vehicle_gnss under their old names.
Logs with vehicle_gps_position are read exactly as before.
By MV2 of Munim, Inc.; written with AI agents. Apache-2.0."""

import difflib
import sys

EDITS = [
    # 0: version
    ('__version__ = "0.1.0"', '__version__ = "0.2.0"'),
    # 1: docstring
    ("Reads sensor_combined, vehicle_attitude, vehicle_gps_position and\n"
     "vehicle_land_detected with pyulog.",
     "Reads sensor_combined, vehicle_attitude, vehicle_gps_position (or, on PX4\n"
     "main since PR #24399, vehicle_gnss; new in 0.2.0) and vehicle_land_detected\n"
     "with pyulog."),
    # 2: topics, and where vehicle_gnss keeps the columns read_log reads
    ('TOPICS = ("sensor_combined", "vehicle_attitude", "vehicle_gps_position",\n'
     '          "vehicle_land_detected")\n',
     'TOPICS = ("sensor_combined", "vehicle_attitude", "vehicle_gps_position",\n'
     '          "vehicle_land_detected", "vehicle_gnss")\n'
     "# PX4 main (PR #24399, 2026-09-29) logs vehicle_gnss instead of vehicle_gps_position. The selected\n"
     "# receiver's sensor_gnss sample is nested as 'receiver' (pyulog: 'receiver.<field>'), its velocity\n"
     "# is vel_north / vel_east, and the delay-corrected sample time is the top-level timestamp_sample.\n"
     "# For each vehicle_gps_position column read_log reads: where vehicle_gnss has it, first match wins.\n"
     "GNSS_COLUMNS = ((\"timestamp\", (\"receiver.timestamp\", \"timestamp\")),\n"
     "                (\"vel_n_m_s\", (\"receiver.vel_north\", \"receiver.vel_n_m_s\")),\n"
     "                (\"vel_e_m_s\", (\"receiver.vel_east\", \"receiver.vel_e_m_s\")),\n"
     "                (\"fix_type\", (\"receiver.fix_type\",)),\n"
     "                (\"vel_ned_valid\", (\"receiver.vel_ned_valid\",)),\n"
     "                (\"timestamp_sample\", (\"timestamp_sample\", \"receiver.timestamp_sample\")),\n"
     "                (\"device_id\", (\"receiver.device_id\",)))\n"),
    # 3: the conversion
    ("def read_log(path):\n",
     "def gnss_as_gps(g):\n"
     '    """The vehicle_gps_position columns read_log reads, from a vehicle_gnss topic (PX4 main).\n'
     "    A column vehicle_gnss doesn't have is left out, so read_log names what is missing.\"\"\"\n"
     "    out = {}\n"
     "    for name, sources in GNSS_COLUMNS:\n"
     "        src = next((s for s in sources if s in g), None)\n"
     "        if src is not None:\n"
     "            out[name] = g[src]\n"
     "    return out\n"
     "\n"
     "\n"
     "def read_log(path):\n"),
    # 4: use it when the old topic is missing
    ('    for name in ("sensor_combined", "vehicle_attitude", "vehicle_gps_position"):\n',
     '    if "vehicle_gps_position" not in data and "vehicle_gnss" in data:\n'
     '        data["vehicle_gps_position"] = gnss_as_gps(data["vehicle_gnss"])\n'
     '    for name in ("sensor_combined", "vehicle_attitude", "vehicle_gps_position"):\n'),
]


def build(old_text):
    text = old_text.replace("\r\n", "\n")
    for i, (a, b) in enumerate(EDITS):
        n = text.count(a)
        if n != 1:
            sys.exit("edit %d matches %d times in main's gps_lag.py" % (i, n))
        text = text.replace(a, b)
    return text


if __name__ == "__main__":
    old = open("gps_lag_main.py", encoding="utf-8").read()
    new = build(old)
    with open("gps_lag.py", "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    diff = list(difflib.unified_diff(old.replace("\r\n", "\n").splitlines(True), new.splitlines(True),
                                     "main/gps_lag.py", "v0.2.0/gps_lag.py"))
    with open("job-diff.txt", "w", encoding="utf-8") as f:
        f.writelines(diff)
    print("".join(diff), flush=True)
