"""Example 2: incremental-index.

Show that CodeAtlas re-parses only changed files. It indexes the small
``fixtures/sample-py`` app three times through the real CLI
(``python -m codeatlas index``):

1. first run: every file is parsed;
2. second run, nothing changed: 0 files re-parsed;
3. one file edited: exactly that file re-parsed, and the new symbol it
   introduces is findable in the index.

The target is a temp copy, so the repo itself is never modified. Run
from the repo root or from this directory:

    python3 run.py
    python3 examples/incremental-index/run.py

Prints PASS/FAIL and exits 0 on success, 1 on failure.

Honest note: change detection here uses stored SHA-256 hashes (the temp
dir is not a Git checkout). In a Git repo CodeAtlas prefers ``git status``,
which is faster and authoritative; the hash fallback is what you see here.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

# Resolve the repo root from this file's location, so the example works
# no matter which directory it is launched from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from codeatlas.indexer import Index

NEW_FUNCTION = '''

def apply_surcharge(amount: float, pct: float = 5.0) -> float:
    """Added by the incremental-index example: surcharge on a total."""
    return amount * (1 + pct / 100)
'''

COUNT_RE = re.compile(r"indexed (\d+) file\(s\), (\d+) unchanged")


def run_cli_index(target: str) -> tuple[int, int, str]:
    """Run the real CLI once; return (indexed, unchanged, raw output)."""
    proc = subprocess.run(
        [sys.executable, "-m", "codeatlas", "index", target],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        raise RuntimeError(f"codeatlas index failed ({proc.returncode}): {out}")
    m = COUNT_RE.search(out)
    if not m:
        raise RuntimeError(f"unexpected CLI output: {out!r}")
    return int(m.group(1)), int(m.group(2)), out


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="codeatlas-example-incr-")
    checks: list[tuple[str, bool]] = []
    try:
        target = os.path.join(tmp, "sample-py")
        shutil.copytree(os.path.join(REPO_ROOT, "fixtures", "sample-py"), target)

        print("== 1. first index (everything is new) ==")
        indexed, unchanged, out = run_cli_index(target)
        print(f"  {out.splitlines()[0]}")
        checks.append(("first run parses all 5 files", indexed == 5 and unchanged == 0))

        print("\n== 2. second index, nothing changed ==")
        indexed, unchanged, out = run_cli_index(target)
        print(f"  {out.splitlines()[0]}")
        checks.append((
            "second run re-parses 0 files (all 5 unchanged)",
            indexed == 0 and unchanged == 5,
        ))

        print("\n== 3. edit exactly one file (billing.py), index again ==")
        billing = os.path.join(target, "billing.py")
        with open(billing, encoding="utf-8") as fh:
            content = fh.read()
        if not content.endswith("\n"):
            content += "\n"
        with open(billing, "w", encoding="utf-8") as fh:
            fh.write(content + NEW_FUNCTION)
        print("  appended apply_surcharge() to billing.py")
        indexed, unchanged, out = run_cli_index(target)
        print(f"  {out.splitlines()[0]}")
        checks.append((
            "third run re-parses exactly 1 file (4 unchanged)",
            indexed == 1 and unchanged == 4,
        ))

        # Prove the re-parse actually picked up the new symbol.
        index = Index.load(target)
        hits = index.find_symbol("apply_surcharge")
        print(f"  find_symbol('apply_surcharge'): "
              f"{[(p, s.line) for p, s in hits]}")
        checks.append((
            "new symbol apply_surcharge is in the index (billing.py)",
            len(hits) == 1 and hits[0][0] == "billing.py",
        ))

        print("\n== checks ==")
        failed = False
        for name, ok in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
            failed = failed or not ok
        print("\nRESULT:", "PASS" if not failed else "FAIL")
        return 0 if not failed else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
