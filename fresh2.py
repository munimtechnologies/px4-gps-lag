"""f9p-2026's sample (studies/f9p-2026/PLAN.md): fresh-2026's pipeline, unchanged, with a new seed.

Runs fresh_nis.py 0.1.0 (which runs fresh.py, fresh_mm.py and nis.py 0.1.0 exactly as
fresh-2026 did) but draws with seed 20261109 instead of 20261102. Pass fresh-2026's own
logs.jsonl in --exclude, with the three earlier samples, so none of its logs or vehicles
are drawn again. Every argument goes to fresh_nis.py unchanged, e.g.

    python fresh2.py --out-dir /out --exclude a.jsonl b.jsonl c.jsonl d.jsonl --budget-min 215 --max-logs 1000

The draw stops before any download if receiver.py's draw is not called with the new seed.
By MV2 of Munim, Inc. (mv2@munimtech.com); written with AI agents. Apache-2.0.
"""

import sys

__version__ = "0.1.0"

SEED = 20261109   # = f9p.DRAW_SEED


def install(fresh_mod, rc_mod, seed=SEED):
    """Point fresh.py's draw at `seed` and make receiver.py's draw refuse any other seed."""
    fresh_mod.SEED = seed
    original = rc_mod.draw
    calls = []

    def checked_draw(*args, **kwargs):
        used = kwargs.get("seed", args[3] if len(args) > 3 else None)
        if used != seed:
            raise SystemExit("fresh2: the draw used seed %r, not %d; nothing downloaded" % (used, seed))
        calls.append(used)
        return original(*args, **kwargs)

    rc_mod.draw = checked_draw
    return calls


def main(argv=None):
    import fresh
    import receiver
    calls = install(fresh, receiver)
    import fresh_nis
    if argv is not None:
        sys.argv = [sys.argv[0]] + list(argv)
    result = fresh_nis.main()        # parses sys.argv[1:], as when fresh_nis.py runs as a script
    if not calls:
        raise SystemExit("fresh2: receiver.draw was never called with the new seed")
    print("fresh2: drew with seed %d" % SEED, flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
