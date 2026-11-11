"""Example 3: impact-of-a-change.

Answer "if I change this, what breaks?" for the bundled
``fixtures/shop-py`` sample app, using the real CodeAtlas API:

- file-level impact: which modules, files and tests depend (directly or
  transitively) on the changed file;
- symbol-level impact: who calls the changed symbol;
- a contrast between a narrow change (payments) and a wide one (auth),
  so the blast radius is visible, not just asserted.

The target is a temp copy, so the repo itself is never modified. Run
from the repo root or from this directory:

    python3 run.py
    python3 examples/impact-of-a-change/run.py

Prints PASS/FAIL and exits 0 on success, 1 on failure.

Honest note: impact is computed from the static import/call graph --
it is "likely affected", not a proof. A change can also affect code the
graph cannot see (dynamic imports, config, runtime behaviour), and
CodeAtlas does not run your tests; it only tells you which ones to run.
"""

import os
import shutil
import sys
import tempfile

# Resolve the repo root from this file's location, so the example works
# no matter which directory it is launched from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from codeatlas.graph import Graph
from codeatlas.indexer import index_repo
from codeatlas.tools import get_change_impact, get_symbol


def show_impact(label: str, impact: dict) -> None:
    print(f"\n== {label} ==")
    print(f"  changed files:    {', '.join(impact['changed_files'])}")
    print(f"  affected modules: {', '.join(impact['affected_modules'])}")
    print(f"  affected files:")
    for path in impact["affected_files"]:
        print(f"    - {path}")
    print(f"  affected tests (re-run these):")
    for path in impact["affected_tests"] or ["(none)"]:
        print(f"    - {path}")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="codeatlas-example-impact-")
    checks: list[tuple[str, bool]] = []
    try:
        target = os.path.join(tmp, "shop-py")
        shutil.copytree(os.path.join(REPO_ROOT, "fixtures", "shop-py"), target)
        index, stats = index_repo(target)
        print(f"indexed {stats.indexed} file(s), {index.total_symbols} symbols")
        graph = Graph.build(index)

        # 1. Narrow change: the payments module.
        payments = get_change_impact(index, graph, changed_files=["shop/payments.py"])
        show_impact("change shop/payments.py (charge / refund live here)", payments)
        checks.append((
            "payments change reaches shop/orders.py and tests/test_orders.py",
            "shop/orders.py" in payments["affected_files"]
            and "tests/test_orders.py" in payments["affected_tests"],
        ))
        checks.append((
            "payments change does NOT reach tests/test_auth.py",
            "tests/test_auth.py" not in payments["affected_tests"],
        ))

        # 2. Symbol-level: who depends on charge() specifically?
        print("\n== who calls charge()? ==")
        charge = get_symbol(index, graph, "charge")
        for sym in charge:
            print(f"  {sym['name']} defined at {sym['path']}:{sym['line']}")
            for caller in sym["callers"]:
                print(f"  called by {caller['caller']} "
                      f"({caller['path']}:{caller['line']})")
        print("  -> changing charge()'s behaviour or signature means "
              "reviewing create_order() first.")
        checks.append((
            "charge() is called by create_order in shop/orders.py",
            len(charge) == 1
            and any(c["caller"] == "create_order"
                    and c["path"] == "shop/orders.py"
                    for c in charge[0]["callers"]),
        ))

        # 3. Wide change: auth is imported almost everywhere -- contrast.
        auth = get_change_impact(index, graph, changed_files=["shop/auth.py"])
        show_impact("change shop/auth.py (contrast: a wide blast radius)", auth)
        checks.append((
            "auth change affects strictly more files than payments change",
            len(auth["affected_files"]) > len(payments["affected_files"])
            and len(auth["affected_tests"]) > len(payments["affected_tests"]),
        ))

        print("\n== checks ==")
        failed = False
        for name, ok in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
            failed = failed or not ok
        print("\nRESULT:", "PASS" if not failed else "FAIL")
        print("Equivalent CLI command (same engine underneath):")
        print("  python -m codeatlas diff fixtures/shop-py "
              "--files shop/payments.py")
        return 0 if not failed else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
