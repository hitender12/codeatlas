"""CodeAtlas demo: index the fixture repos and answer the question from
the blueprint -- "If I change the billing interface, what code and tests
are likely affected?"

Run:  python demo.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codeatlas.archmap import build_architecture_map, diff_impact, render_impact
from codeatlas.context import build_context_pack
from codeatlas.graph import Graph
from codeatlas.indexer import index_repo
from codeatlas.search import search


def main() -> int:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    tmp = tempfile.mkdtemp(prefix="codeatlas-demo-")
    target = os.path.join(tmp, "sample-py")
    shutil.copytree(os.path.join(repo_root, "fixtures", "sample-py"), target)

    print("== 1. index ==")
    index, stats = index_repo(target)
    print(f"indexed {stats.indexed} files, {index.total_symbols} symbols, "
          f"{index.total_imports} imports")

    graph = Graph.build(index)

    print("\n== 2. architecture map (Mermaid) ==")
    print(build_architecture_map(index, graph).to_mermaid(), end="")

    print("== 3. ask: 'Where is authentication handled?' ==")
    for r in search(index, graph, "authenticate", limit=5):
        loc = f"{r.path}:{r.line}" if r.line else r.path
        print(f"  [{r.kind}] {loc}  {r.name or r.snippet}")
        print(f"      why: {'; '.join(r.reasons)}")

    print("\n== 4. diff impact: if I change the billing interface ==")
    print(render_impact(diff_impact(index, graph, ["billing.py"])))

    print("\n== 5. context pack: 'charge a customer after authentication' ==")
    pack = build_context_pack(index, graph, "charge a customer after authentication",
                              budget_tokens=400)
    print(f"budget 400 tokens, used {pack.tokens} tokens, "
          f"{len(pack.snippets)} snippet(s)")
    for snip in pack.snippets:
        print(f"  - {snip.path}:{snip.start_line}-{snip.end_line} "
              f"({snip.tokens} tokens): {snip.why}")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nDemo complete. Nothing was uploaded anywhere: "
          "CodeAtlas is local-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
