# census-2026, amendment 1: a reading fix, code only (2026-11-07)

Written before any log for this census has been read. [`PLAN.md`](PLAN.md) is unchanged.

## What happened

The sealed job for `census.py` 0.1.0 started on 2026-11-06 at 22:24 UTC. It checked that the plan and the code on `main` matched its own copies, and its 25 synthetic tests passed. It then asked Flight Review for the public log list (`/dbinfo`) and stopped after one second:

```
ijson.common.IncompleteJSONError: lexical error: invalid char in json text.
    \x1f\x8b\x08\x08...
```

`\x1f\x8b` is the start of a gzip stream. Flight Review sends the list gzip-compressed. Python's `urllib` does not decompress it, so 0.1.0 passed compressed bytes to the JSON parser. (upgrade.py 0.1.0 read the same list with `requests`, which decompresses by itself, so the problem never showed there.) The job failed while parsing the list. It read no log, and no log's parameters were seen. Its only output is `job-fetched.json`, the record of what it checked on `main`.

## What changes

`census.py` 0.1.1:

- `open_stream()` looks at a response's first two bytes. If they are the gzip magic bytes, it decompresses the stream. Otherwise it passes the bytes through unchanged. The list is read through it, and so is each log's start, in case a log is ever sent compressed. Logs came uncompressed in dynmodel-2026.
- `plain()` also writes `Decimal` values, which `ijson` returns for numbers with a fraction, as plain floats.
- Seven new tests in `test_census.py`: plain and gzip streams read whole or in 1-, 3-, 5- and 7-byte pieces, short and empty streams, a ULog start sent plain and gzip-compressed, a gzip-compressed list parsed by `ijson` and grouped by `build()`, and a `Decimal` written as JSON.

Nothing else changes: the filters, the seed (20261117), the draw, the 6 s spacing, the stop rules, what is read and kept, the measure, the thresholds E0 and C1-C3, and the decisions H0-H3.

## The new job

`px4-gps-lag-census-v2` waits until this amendment is on `main`. It checks that `PLAN.md` is the same file the 0.1.0 job saw (sha256 `5da57c61…`, line endings normalised), that its own `census.py` and `test_census.py` are `main`'s copies, and that dynmodel-2026's rows are the published copy (`96bc66f6…`). It runs the tests, and only then reads the list.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name. Text CC BY 4.0, code Apache-2.0.
