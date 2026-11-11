"""CodeAtlas CLI.

Usage:
    codeatlas init [path]
    codeatlas index [path]
    codeatlas map [path] [--format mermaid|dot|json]
    codeatlas ask "question" [path]
    codeatlas context "task description" [path] [--budget N]
    codeatlas diff [path] [--ref REF]

Run as a module: ``python -m codeatlas <command> ...``
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .archmap import build_architecture_map, diff_impact, git_changed_files, render_impact
from .context import build_context_pack
from .graph import Graph
from .indexer import Index, index_repo, init_repo
from .search import search


def _load(root: str) -> tuple[Index, Graph]:
    index = Index.load(root)
    return index, Graph.build(index)


def _cmd_init(args) -> int:
    path = init_repo(args.path)
    print(f"initialized codeatlas in {path}")
    print("privacy: local-only -- codeatlas never uploads source code.")
    return 0


def _cmd_index(args) -> int:
    index, stats = index_repo(args.path, force=args.force)
    print(f"indexed {stats.indexed} file(s), {stats.unchanged} unchanged, "
          f"{stats.removed} removed")
    print(f"total: {len(index.files)} files, {index.total_symbols} symbols, "
          f"{index.total_imports} imports")
    if stats.parse_errors:
        print(f"warning: {stats.parse_errors} file(s) failed to parse "
              f"(see index for details)")
    return 0


def _cmd_map(args) -> int:
    index, graph = _load(args.path)
    if not index.files:
        print("no index found -- run `codeatlas index` first", file=sys.stderr)
        return 1
    amap = build_architecture_map(index, graph)
    if args.format == "mermaid":
        print(amap.to_mermaid(), end="")
    elif args.format == "dot":
        print(amap.to_dot(), end="")
    else:
        print(amap.to_json())
    return 0


def _cmd_ask(args) -> int:
    index, graph = _load(args.path)
    if not index.files:
        print("no index found -- run `codeatlas index` first", file=sys.stderr)
        return 1
    results = search(index, graph, args.question, limit=args.limit)
    if not results:
        print("No matches found.")
        return 0
    for r in results:
        loc = f"{r.path}:{r.line}" if r.line else r.path
        print(f"[{r.kind}] {loc}  ({r.score:.0f})  {r.name or r.snippet}")
        for reason in r.reasons:
            print(f"    why: {reason}")
    return 0


def _cmd_context(args) -> int:
    index, graph = _load(args.path)
    if not index.files:
        print("no index found -- run `codeatlas index` first", file=sys.stderr)
        return 1
    pack = build_context_pack(index, graph, args.task, budget_tokens=args.budget)
    if args.json:
        print(json.dumps(pack.to_dict(), indent=2))
        return 0
    print(f"task: {pack.task}")
    print(f"budget: {pack.budget_tokens} tokens | used: {pack.tokens} "
          f"({pack.bytes} bytes) | snippets: {len(pack.snippets)}")
    for snip in pack.snippets:
        print(f"\n--- {snip.path}:{snip.start_line}-{snip.end_line} "
              f"({snip.tokens} tokens) ---")
        print(f"# why: {snip.why}")
        print(snip.text)
    return 0


def _cmd_diff(args) -> int:
    index, graph = _load(args.path)
    if not index.files:
        print("no index found -- run `codeatlas index` first", file=sys.stderr)
        return 1
    if args.files:
        changed = args.files
    else:
        changed = git_changed_files(args.path, ref=args.ref)
    if changed is None:
        print("not a git repository and no files given", file=sys.stderr)
        return 1
    impact = diff_impact(index, graph, changed)
    print(render_impact(impact))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeatlas",
        description="Local-first codebase intelligence. No account, no API key.",
    )
    parser.add_argument("--version", action="version", version=f"codeatlas {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create .codeatlas/config.json in a repo")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("index", help="index (or incrementally re-index) a repo")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--force", action="store_true", help="re-parse every file")
    p.set_defaults(func=_cmd_index)

    p = sub.add_parser("map", help="print the architecture map")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--format", choices=["mermaid", "dot", "json"], default="mermaid")
    p.set_defaults(func=_cmd_map)

    p = sub.add_parser("ask", help="search the codebase")
    p.add_argument("question")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=_cmd_ask)

    p = sub.add_parser("context", help="build a bounded context pack for a task")
    p.add_argument("task")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--budget", type=int, default=4000, help="token budget")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=_cmd_context)

    p = sub.add_parser("diff", help="show what a change likely affects")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--ref", default=None, help="git ref to diff against")
    p.add_argument("--files", nargs="*", default=None,
                   help="explicit changed files (overrides git)")
    p.set_defaults(func=_cmd_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.path = os.path.abspath(args.path)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
