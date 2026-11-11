# incremental-index

Show that CodeAtlas re-parses only changed files. It indexes the small
`fixtures/sample-py` app three times through the real CLI
(`python -m codeatlas index`):

1. **First run** — everything is new: 5 files parsed, 0 unchanged.
2. **Second run, nothing changed** — 0 files re-parsed, 5 unchanged.
3. **Edit exactly one file** (`billing.py`, a new `apply_surcharge`
   function is appended) and index again — exactly 1 file re-parsed,
   4 unchanged, and the new symbol is findable in the index.

## Run it

From the repo root or from this directory:

```bash
python3 run.py
python3 examples/incremental-index/run.py
```

## What it checks (self-checking, exits 0 on success)

- First run parses all 5 files.
- Second run re-parses 0 files.
- Third run re-parses exactly 1 file.
- The new symbol `apply_surcharge` is in the index, in `billing.py`.

## Honest note

Change detection here uses stored SHA-256 hashes, because the target is
a temp copy, not a Git checkout. In a real Git repo CodeAtlas prefers
`git status`, which is faster and authoritative; the hash fallback is
what you see here. Either way, unchanged content is never re-parsed —
even if its mtime moved.

The script works on a temp copy of the fixture, so the repo itself is
never modified.
