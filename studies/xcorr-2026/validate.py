"""validate.py: test gnss_latency.py, then run it on five public PX4 logs px4-gps-lag already measured.

Checks V0-V4 are fixed in CRITERIA.md. Writes validation.json, validation.md, tests.txt,
one <log>.json and one PDF per log into OUT.

    python validate.py /out

By MV2 of Munim, Inc.; made with AI agents. Apache-2.0.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import traceback
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "gnss-latency-validate/0.1 (MV2 of Munim, Inc.; mv2@munimtech.com)"
ZIP = "https://github.com/user-attachments/files/20456409/logs_dynmodel.zip"
ZIP_SHA = "aa6997a9754d4a11149bb4aa23f9721e16450eba4dc4808c0644ed2e04343b49"
FR = "https://review.px4.io/download?log=%s"
# name: (px4-gps-lag published lag ms, kind)
REF = {
    "log_5_2025-5-27-11-50-34": (110.5, "zip"),
    "log_8_2025-5-27-12-55-02": (214.2, "zip"),
    "5f1584c9-83ad-4d5e-97ac-46b3ed19f8e6": (166.3, "main"),
    "5548f136-8ecc-4b45-8c14-721bdf888a62": (110.3, "main"),
    "53a8335a-3705-4d98-acff-5d21cae8e6de": (189.5, "main"),
}


def get(url, timeout=900):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_logs(res):
    paths = {}
    os.makedirs("/tmp/dyn", exist_ok=True)
    data = get(ZIP, 300)
    assert hashlib.sha256(data).hexdigest() == ZIP_SHA, "logs_dynmodel.zip changed"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = os.path.basename(info.filename.replace("\\", "/"))
            if name[:-4] in REF and name.endswith(".ulg"):
                path = os.path.join("/tmp/dyn", name)
                with open(path, "wb") as f:
                    f.write(z.read(info))
                paths[name[:-4]] = path
    folder = "/data/px4main" if os.path.isdir("/data") else "/tmp/px4main"
    os.makedirs(folder, exist_ok=True)
    for name, (_, kind) in REF.items():
        if kind != "main":
            continue
        path = os.path.join(folder, name + ".ulg")
        try:
            if not (os.path.exists(path) and os.path.getsize(path) > 1000):
                blob = get(FR % name)
                assert blob[:4] == b"ULog", "not a ULog"
                with open(path, "wb") as f:
                    f.write(blob)
            paths[name] = path
        except Exception as exc:
            res["fetch_errors"][name] = str(exc)[:300]
    for name, path in paths.items():
        with open(path, "rb") as f:
            res["logs_sha256"][name] = hashlib.sha256(f.read()).hexdigest()
    return paths


def main(out):
    os.makedirs(out, exist_ok=True)
    pdf_dir = os.path.join(out, "pdf")
    res = {"checks": {}, "rows": [], "fetch_errors": {}, "logs_sha256": {}, "ok": False}
    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "-v", "test_gnss_latency"], cwd=HERE,
                           capture_output=True, text=True)
        with open(os.path.join(out, "tests.txt"), "w", encoding="utf-8") as f:
            f.write(p.stdout + p.stderr)
        res["tests"] = [l for l in (p.stdout + p.stderr).splitlines() if l.startswith(("Ran ", "OK", "FAILED"))]
        res["checks"]["V0"] = p.returncode == 0
        assert p.returncode == 0, "unit tests failed: %s" % res["tests"]

        paths = fetch_logs(res)
        for name, (ref_ms, kind) in REF.items():
            row = {"log": name, "kind": kind, "px4_gps_lag_ms": ref_ms}
            if name not in paths:
                row["error"] = "not downloaded"
                res["rows"].append(row)
                continue
            js = os.path.join(out, name + ".json")
            p = subprocess.run([sys.executable, os.path.join(HERE, "gnss_latency.py"), paths[name],
                                "--output-dir", pdf_dir, "--json", js], capture_output=True, text=True)
            row["exit"] = p.returncode
            row["stdout"] = p.stdout[-1500:]
            row["stderr"] = p.stderr[-1500:]
            if p.returncode == 0 and os.path.exists(js):
                with open(js, encoding="utf-8") as f:
                    r = json.load(f)
                row.update({k: r.get(k) for k in ("gnss_topic", "device_id", "bus", "gnss_rate_hz", "airborne_s",
                                                  "excitation_m_s", "total_delay_ms", "total_r", "total_at_edge",
                                                  "applied_delay_ms", "applied_source", "residual_ms",
                                                  "residual_direct_ms", "residual_direct_r")})
                row["diff_vs_px4_gps_lag_ms"] = round(r["total_delay_ms"] - ref_ms, 1)
                row["pdf"] = os.path.exists(os.path.join(pdf_dir, name + "_gnss_latency.pdf"))
            res["rows"].append(row)

        rows = res["rows"]
        ran = [r for r in rows if r.get("total_delay_ms") is not None]
        v1 = [r for r in ran if not r["total_at_edge"] and r["total_r"] >= 0.5]
        res["checks"]["V1"] = len(v1) == len(REF)
        res["checks"]["V2"] = sum(1 for r in ran if abs(r["diff_vs_px4_gps_lag_ms"]) <= 20) >= 4
        main_rows = [r for r in ran if r["kind"] == "main"]
        res["checks"]["V3"] = (len(main_rows) == 3 and all(
            r["residual_direct_ms"] is not None and r["residual_ms"] is not None
            and abs(r["residual_direct_ms"] - r["residual_ms"]) <= 10 for r in main_rows))
        res["checks"]["V4"] = len(v1) > 0 and all(r.get("pdf") for r in v1)
        res["ok"] = True
    except Exception:
        res["error"] = traceback.format_exc()[-3000:]
        print(res["error"], flush=True)

    with open(os.path.join(out, "validation.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
        f.write("\n")
    md = ["# gnss_latency.py validation", "", "Checks (criteria in CRITERIA.md): " + ", ".join(
        "%s %s" % (k, "held" if v else "did not hold") for k, v in sorted(res["checks"].items())), "",
          "| log | kind | bus | px4-gps-lag ms | xcorr total ms | diff | r | applied ms (source) | "
          "residual ms | residual direct ms |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s (%s) | %s | %s |" % (
            r["log"][:8], r["kind"], r.get("bus"), r["px4_gps_lag_ms"], r.get("total_delay_ms"),
            r.get("diff_vs_px4_gps_lag_ms"), r.get("total_r"), r.get("applied_delay_ms"), r.get("applied_source"),
            r.get("residual_ms"), r.get("residual_direct_ms")))
    with open(os.path.join(out, "validation.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md), flush=True)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/out"))
