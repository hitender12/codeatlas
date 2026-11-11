"""Example 1: index-and-ask.

Index the bundled ``fixtures/shop-py`` sample app (a small shop with
auth, cart, catalog, orders and payments), then ask a question and build
a context pack for a task -- using the real CodeAtlas API, the same code
the CLI calls. No mocks, no network, nothing leaves this machine.

Run from the repo root or from this directory:

    python3 run.py
    python3 examples/index-and-ask/run.py

The script copies the fixture to a temp dir, so the repo itself is never
modified (the index is written to ``.codeatlas/`` inside the copy only).
It prints PASS/FAIL and exits 0 on success, 1 on failure.
"""

import os
import shutil
import sys
import tempfile

# Resolve the repo root from this file's location, so the example works
# no matter which directory it is launched from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from codeatlas.context import build_context_pack
from codeatlas.graph import Graph
from codeatlas.indexer import index_repo
from codeatlas.search import search
from codeatlas.tools import get_symbol

QUESTION = "Where is authentication handled?"
TASK = "charge a customer after authentication"
BUDGET_TOKENS = 400


def main() -> int:
    repo_root = REPO_ROOT
    tmp = tempfile.mkdtemp(prefix="codeatlas-example-ask-")
    checks: list[tuple[str, bool]] = []
    try:
        target = os.path.join(tmp, "shop-py")
        shutil.copytree(os.path.join(repo_root, "fixtures", "shop-py"), target)

        # 1. Index the sample app (real indexer, SHA-256 change detection).
        print("== 1. index fixtures/shop-py ==")
        index, stats = index_repo(target)
        print(f"indexed {stats.indexed} file(s), {index.total_symbols} symbols, "
              f"{index.total_imports} imports")
        graph = Graph.build(index)
        checks.append(("index found 11 files", len(index.files) == 11))

        # 2. Ask a question (hybrid search: symbols, full text, graph).
        print(f"\n== 2. ask: {QUESTION!r} ==")
        results = search(index, graph, "authenticate", limit=5)
        for r in results:
            loc = f"{r.path}:{r.line}" if r.line else r.path
            print(f"  [{r.kind}] {loc}  {r.name or r.snippet}")
            for reason in r.reasons:
                print(f"      why: {reason}")
        top = results[0] if results else None
        checks.append((
            "top hit is Authenticator.authenticate in shop/auth.py",
            top is not None and top.name == "Authenticator.authenticate"
            and top.path == "shop/auth.py",
        ))

        # 3. Look up one symbol exactly, with its callers.
        print("\n== 3. get_symbol('charge') ==")
        for sym in get_symbol(index, graph, "charge"):
            print(f"  defined: {sym['path']}:{sym['line']}  {sym['signature']}")
            print(f"  docstring: {sym['docstring']}")
            for caller in sym["callers"]:
                print(f"  called by: {caller['caller']} "
                      f"({caller['path']}:{caller['line']})")
        charge = get_symbol(index, graph, "charge")
        checks.append((
            "charge is defined in shop/payments.py and called by create_order",
            len(charge) == 1 and charge[0]["path"] == "shop/payments.py"
            and any(c["caller"] == "create_order" for c in charge[0]["callers"]),
        ))

        # 4. Build a bounded context pack for the task.
        print(f"\n== 4. context pack: {TASK!r} (budget {BUDGET_TOKENS} tokens) ==")
        pack = build_context_pack(index, graph, TASK, budget_tokens=BUDGET_TOKENS)
        print(f"used {pack.tokens}/{pack.budget_tokens} tokens, "
              f"{len(pack.snippets)} snippet(s)")
        for snip in pack.snippets:
            print(f"  - {snip.path}:{snip.start_line}-{snip.end_line} "
                  f"({snip.tokens} tokens): {snip.why}")
        pack_paths = {s.path for s in pack.snippets}
        checks.append((
            "context pack stays within budget and covers payments + auth",
            pack.tokens <= BUDGET_TOKENS and len(pack.snippets) >= 2
            and "shop/payments.py" in pack_paths
            and "shop/auth.py" in pack_paths,
        ))

        # 5. Report.
        print("\n== checks ==")
        failed = False
        for name, ok in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
            failed = failed or not ok
        print("\nRESULT:", "PASS" if not failed else "FAIL")
        print("Equivalent CLI commands (same engine underneath):")
        print("  python -m codeatlas index fixtures/shop-py")
        print("  python -m codeatlas ask 'Where is authentication handled?' "
              "fixtures/shop-py")
        print("  python -m codeatlas context 'charge a customer after "
              "authentication' fixtures/shop-py --budget 400")
        return 0 if not failed else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
