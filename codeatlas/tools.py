"""Read-only tool surface.

These are the plain-Python equivalents of the MCP tools from the
blueprint (``search_code``, ``get_symbol``, ``get_file_outline``,
``build_context_pack``). They are read-only by construction: nothing in
this module writes, executes, or uploads code. A future MCP adapter or
local HTTP API calls these exact functions, so the tool contract stays
stable across transports.
"""

from __future__ import annotations

from .archmap import build_architecture_map, diff_impact, git_changed_files
from .context import build_context_pack
from .graph import Graph
from .indexer import Index
from .search import search


def search_code(index: Index, graph: Graph, query: str, limit: int = 10) -> list[dict]:
    """Hybrid search: symbols, full text, paths, graph relevance."""
    return [r.to_dict() for r in search(index, graph, query, limit=limit)]


def get_symbol(index: Index, graph: Graph, name: str) -> list[dict]:
    """Exact symbol lookup with definition, callers, and line numbers."""
    out = []
    for rel, sym in index.find_symbol(name):
        callers = graph.callers_of(sym.qualified_name)
        out.append({
            "name": sym.qualified_name,
            "kind": sym.kind,
            "path": rel,
            "line": sym.line,
            "end_line": sym.end_line,
            "signature": sym.signature,
            "docstring": sym.docstring,
            "callers": [
                {"path": path, "caller": caller, "line": line}
                for path, caller, line in callers
            ],
        })
    return out


def get_file_outline(index: Index, rel_path: str) -> dict | None:
    """Symbols, imports, and size for one file."""
    rec = index.files.get(rel_path)
    if rec is None:
        return None
    return {
        "path": rel_path,
        "language": rec.language,
        "size_bytes": rec.size,
        "symbols": [s.to_dict() for s in rec.parsed.symbols],
        "imports": [i.to_dict() for i in rec.parsed.imports],
        "parse_error": rec.parsed.parse_error,
    }


def build_context_pack_tool(
    index: Index, graph: Graph, task: str, budget_tokens: int = 4000
) -> dict:
    """Bounded context pack for a task description."""
    return build_context_pack(index, graph, task, budget_tokens).to_dict()


def get_architecture_map(index: Index, graph: Graph, fmt: str = "json") -> str:
    """Architecture map as JSON, Mermaid, or DOT."""
    amap = build_architecture_map(index, graph)
    if fmt == "mermaid":
        return amap.to_mermaid()
    if fmt == "dot":
        return amap.to_dot()
    return amap.to_json()


def get_change_impact(
    index: Index, graph: Graph, changed_files: list[str] | None = None, ref: str | None = None
) -> dict:
    """Which modules and tests a change likely affects.

    ``changed_files`` overrides git; otherwise git status (working tree)
    or ``git diff <ref>`` is used. Returns an empty impact with a note
    when git is unavailable and no files were given.
    """
    if changed_files is None:
        changed_files = git_changed_files(index.root, ref=ref)
    if changed_files is None:
        return {
            "changed_files": [],
            "affected_modules": [],
            "affected_files": [],
            "affected_tests": [],
            "note": "not a git repository and no changed files given",
        }
    return diff_impact(index, graph, changed_files).to_dict()
