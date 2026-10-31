"""fresh_mm.py: run fresh.py 0.1.0 unchanged, and also read mismatch.py's
figures from every log it downloads (studies/mismatch-2026/PLAN.md).

fresh.py reads each downloaded log with gps_lag.py, receiver.py and
rate.read_rate, then deletes it. This replaces rate.read_rate with a
function that returns exactly what rate.read_rate returns (or, if it fails,
exactly the fields fresh.py itself would set) plus mismatch.read_mismatch's
mm_ fields. fresh.py's scoring ignores the mm_ fields, so its summary.json is
what fresh.py alone would write; Flight Review sees one download per log, not
two. After fresh.py finishes, mismatch.py scores the same logs.jsonl into
mismatch-summary.json.

    python fresh_mm.py --out-dir out --exclude a.jsonl b.jsonl c.jsonl --budget-min 215 --max-logs 1000

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import os
import sys

import mismatch as mm

__version__ = "0.1.0"


def combine(read_rate, read_mismatch):
    """read_rate's fields (or fresh.py's own error fields) plus read_mismatch's."""
    def read_both(path):
        try:
            extra = read_mismatch(path)
        except Exception as exc:  # a log the mismatch reader cannot read
            extra = {"mm_ok": False, "mm_reason": "error: %s" % str(exc)[:200]}
        try:
            out = dict(read_rate(path))
        except Exception as exc:  # what fresh.py sets when rate.read_rate fails
            out = {"grid_ms": None, "grid_reason": "error: %s" % str(exc)[:200]}
        out.update(extra)
        return out
    return read_both


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    import fresh
    import rate as rt
    rt.read_rate = combine(rt.read_rate, mm.read_mismatch)
    code = fresh.main(argv)
    out_dir = argv[argv.index("--out-dir") + 1]
    rows = fresh.load_rows(os.path.join(out_dir, "logs.jsonl"))
    mm.score(rows, out_dir, {"fresh_mm_py": __version__, "fresh_py": fresh.__version__})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
