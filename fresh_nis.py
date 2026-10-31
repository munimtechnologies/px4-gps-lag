"""fresh_nis.py: run fresh.py 0.1.0 unchanged, and read both mismatch.py's
(studies/mismatch-2026/PLAN.md) and nis.py's (studies/nis-2026/PLAN.md)
figures from every log it downloads.

fresh.py reads each downloaded log with gps_lag.py, receiver.py and
rate.read_rate, then deletes it. This replaces rate.read_rate with a
function that returns exactly what fresh_mm.combine returns (rate.read_rate's
fields, or fresh.py's own error fields, plus the mm_ fields) plus
nis.read_nis's nis_ fields. fresh.py's scoring ignores mm_ and nis_ fields,
so its summary.json is what fresh.py alone would write; Flight Review sees
one download per log. After fresh.py finishes, mismatch.py and nis.py each
score the same logs.jsonl (mismatch-summary.json, nis-summary.json).

    python fresh_nis.py --out-dir out --exclude a.jsonl b.jsonl c.jsonl --budget-min 215 --max-logs 1000

By MV2 of Munim, Inc.; written with AI agents. Apache-2.0.
"""

from __future__ import annotations

import os
import sys

import fresh_mm
import mismatch as mm
import nis

__version__ = "0.1.0"


def combine3(read_rate, read_mismatch, read_nis):
    """fresh_mm.combine(read_rate, read_mismatch)'s fields plus read_nis's."""
    both = fresh_mm.combine(read_rate, read_mismatch)

    def read_all(path):
        try:
            extra = read_nis(path)
        except Exception as exc:  # a log the NIS reader cannot read
            extra = {"nis_ok": False, "nis_reason": "error: %s" % str(exc)[:200]}
        out = both(path)
        out.update(extra)
        return out
    return read_all


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    import fresh
    import rate as rt
    rt.read_rate = combine3(rt.read_rate, mm.read_mismatch, nis.read_nis)
    code = fresh.main(argv)
    out_dir = argv[argv.index("--out-dir") + 1]
    rows = fresh.load_rows(os.path.join(out_dir, "logs.jsonl"))
    extra = {"fresh_nis_py": __version__, "fresh_mm_py": fresh_mm.__version__, "fresh_py": fresh.__version__}
    mm.score(rows, out_dir, extra)
    nis.score(rows, out_dir, extra)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
