"""Retrieval-quality eval for CodeAtlas.

Measures precision/recall of hybrid search (top-10 distinct files) and of
context packs (distinct snippet files, budget 4000) on the bundled
fixtures, for questions whose correct file is known in advance.

Run directly::

    python3 tests/retrieval_eval.py

or import :func:`evaluate` from the test-suite wrapper
``tests/test_retrieval_eval.py``. Fixtures are copied to a temp dir first,
so the eval never writes ``.codeatlas/`` into the real fixture repos.

The numbers are reported honestly: relevance is a single strict file per
case (the file that *defines* the thing asked about), so a query whose
answer is spread over two files, or whose top hit is a near-miss file
that merely mentions the words, scores below 1.0. See the per-case table
in the output for exactly which cases miss, and why.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codeatlas.context import build_context_pack  # noqa: E402
from codeatlas.graph import Graph  # noqa: E402
from codeatlas.indexer import index_repo  # noqa: E402
from codeatlas.search import search  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


@dataclass(frozen=True)
class EvalCase:
    fixture: str  # fixture repo dir under fixtures/
    query: str
    relevant: frozenset  # files that define the thing asked about
    note: str = ""


# One strict relevant file per case: the file that *defines* the answer.
# A near-miss file that only mentions the words (e.g. cart.py importing
# catalog.py) is not relevant, so precision below 1.0 is expected.
CASES = [
    EvalCase("sample-py", "where is authentication handled?",
             frozenset({"auth.py"})),
    EvalCase("sample-py", "charge a customer",
             frozenset({"billing.py"})),
    EvalCase("sample-py", "apply a discount",
             frozenset({"billing.py"})),
    EvalCase("sample-py", "create an order",
             frozenset({"api.py"})),
    EvalCase("sample-py", "refund a charge",
             frozenset({"billing.py"})),
    EvalCase("shop-py", "where is authentication handled?",
             frozenset({"shop/auth.py"})),
    EvalCase("shop-py", "charge a customer",
             frozenset({"shop/payments.py"})),
    EvalCase("shop-py", "create an order",
             frozenset({"shop/orders.py"}),
             note="shop/api.py also creates orders via checkout()"),
    EvalCase("shop-py", "search the product catalog",
             frozenset({"shop/catalog.py"})),
    EvalCase("shop-py", "shopping cart total",
             frozenset({"shop/cart.py"})),
    EvalCase("shop-py", "format a price",
             frozenset({"shop/utils.py"})),
    EvalCase("shop-ts", "where is authentication handled?",
             frozenset({"src/auth.ts"})),
    EvalCase("shop-ts", "charge a customer",
             frozenset({"src/billing.ts"})),
    EvalCase("shop-ts", "create an order",
             frozenset({"src/orders.ts"}),
             note="src/api.ts also creates orders via checkout()"),
    EvalCase("shop-ts", "search the product catalog",
             frozenset({"src/catalog.ts"})),
    EvalCase("shop-ts", "shopping cart total",
             frozenset({"src/cart.ts"})),
    EvalCase("shop-ts", "format a price",
             frozenset({"src/utils.ts"})),
]


def _precision_recall(retrieved: set, relevant: set) -> tuple[float, float]:
    if not retrieved:
        return 0.0, 0.0
    hit = len(retrieved & relevant)
    return hit / len(retrieved), hit / len(relevant)


def evaluate(cases: list[EvalCase] | None = None) -> dict:
    """Run every case for both search and context packs.

    Returns ``{"cases": [...per-case rows...], "summary": {...}}`` where
    each row carries precision/recall and hit@1 for search and for the
    context pack, plus the retrieved file sets for inspection.
    """
    cases = list(cases if cases is not None else CASES)
    tmp = tempfile.mkdtemp(prefix="codeatlas-eval-")
    rows: list[dict] = []
    try:
        loaded: dict[str, tuple] = {}
        for case in cases:
            if case.fixture not in loaded:
                repo = os.path.join(tmp, case.fixture)
                shutil.copytree(os.path.join(FIXTURES, case.fixture), repo)
                index, _ = index_repo(repo)
                loaded[case.fixture] = (index, Graph.build(index))
            index, graph = loaded[case.fixture]

            results = search(index, graph, case.query, limit=10)
            search_paths = {r.path for r in results}
            s_prec, s_rec = _precision_recall(search_paths, set(case.relevant))
            hit_at_1 = bool(results) and results[0].path in case.relevant

            pack = build_context_pack(index, graph, case.query, budget_tokens=4000)
            pack_paths = {s.path for s in pack.snippets}
            p_prec, p_rec = _precision_recall(pack_paths, set(case.relevant))
            # Empty-text snippets still "retrieve" their path, but carry no
            # code: on JS/TS fixtures the symbol snippet can be a blank line
            # (see test_edge_cases.py::TestJavaScriptLineNumbers). Count them
            # so the headline recall is not read as "useful" recall.
            pack_empty = sum(1 for s in pack.snippets if not s.text.strip())

            rows.append({
                "fixture": case.fixture,
                "query": case.query,
                "relevant": sorted(case.relevant),
                "note": case.note,
                "search_precision": round(s_prec, 3),
                "search_recall": round(s_rec, 3),
                "search_hit_at_1": hit_at_1,
                "search_retrieved": sorted(search_paths),
                "pack_precision": round(p_prec, 3),
                "pack_recall": round(p_rec, 3),
                "pack_tokens": pack.tokens,
                "pack_snippets": len(pack.snippets),
                "pack_empty_snippets": pack_empty,
                "pack_retrieved": sorted(pack_paths),
            })
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    def mean(key: str) -> float:
        return round(sum(r[key] for r in rows) / len(rows), 3) if rows else 0.0

    summary = {
        "n_cases": len(rows),
        "mean_search_precision": mean("search_precision"),
        "mean_search_recall": mean("search_recall"),
        "search_hit_at_1": round(
            sum(1 for r in rows if r["search_hit_at_1"]) / len(rows), 3
        ) if rows else 0.0,
        "mean_pack_precision": mean("pack_precision"),
        "mean_pack_recall": mean("pack_recall"),
        "total_pack_empty_snippets": sum(r["pack_empty_snippets"] for r in rows),
    }
    return {"cases": rows, "summary": summary}


def main() -> int:
    report = evaluate()
    print(f"{'fixture':<10} {'query':<34} {'P@10':>5} {'R@10':>5} {'hit1':>4} "
          f"{'packP':>5} {'packR':>5}")
    for row in report["cases"]:
        print(f"{row['fixture']:<10} {row['query'][:34]:<34} "
              f"{row['search_precision']:>5.2f} {row['search_recall']:>5.2f} "
              f"{'Y' if row['search_hit_at_1'] else 'n':>4} "
              f"{row['pack_precision']:>5.2f} {row['pack_recall']:>5.2f}  "
              f"relevant={','.join(row['relevant'])}")
        if row["note"]:
            print(f"{'':<10}   note: {row['note']}")
        if row["search_recall"] < 1.0:
            print(f"{'':<10}   search retrieved: {','.join(row['search_retrieved'])}")
        if not row["search_hit_at_1"]:
            print(f"{'':<10}   top search hit was not the relevant file")
        if row["pack_empty_snippets"]:
            print(f"{'':<10}   pack has {row['pack_empty_snippets']} empty-text snippet(s)")
        if row["pack_recall"] < 1.0:
            print(f"{'':<10}   pack retrieved: {','.join(row['pack_retrieved'])}")
    print()
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
