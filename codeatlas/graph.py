"""Repository graph.

Nodes: files, symbols, modules. Edges: imports (file -> file), calls
(symbol -> symbol, best-effort name resolution), and test links
(test file -> source file under test).

Module boundaries are the top-level directory of a file (``src/``,
``tests/``, ...); a file at the repo root is its own module named after the
file stem. This keeps the map readable on real repos without guessing a
packaging layout.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass, field

from .indexer import Index

TEST_MARKERS = ("test_", "_test", ".test.", "/test/", "/tests/", "tests/")


def is_test_file(rel_path: str) -> bool:
    base = os.path.basename(rel_path)
    lowered = rel_path.replace(os.sep, "/").lower()
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or ".test." in base
        or "/tests/" in lowered
        or lowered.startswith("tests/")
        or lowered.startswith("test/")
    )


def module_of(rel_path: str) -> str:
    """Top-level module boundary for a file."""
    parts = rel_path.replace(os.sep, "/").split("/")
    if len(parts) == 1:
        return os.path.splitext(parts[0])[0]
    top = parts[0]
    if top in ("src", "lib", "app", "packages", "pkg"):
        return parts[1] if len(parts) > 2 else top
    return top


@dataclass
class Graph:
    index: Index
    # file -> set of files it imports
    import_edges: dict[str, set[str]] = field(default_factory=dict)
    # file -> set of files that import it (reverse edges)
    dependents: dict[str, set[str]] = field(default_factory=dict)
    # qualified symbol name -> set of (file, symbol) definitions
    symbols_by_name: dict[str, list[tuple[str, object]]] = field(default_factory=dict)
    # test file -> source file(s) under test
    test_links: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, index: Index) -> "Graph":
        graph = cls(index=index)
        files = set(index.files)
        for rel, rec in index.files.items():
            graph.import_edges.setdefault(rel, set())
            for imp in rec.parsed.imports:
                target = _resolve_import(index.root, rel, imp.module, imp.level, files)
                if target:
                    graph.import_edges[rel].add(target)
        for src, targets in graph.import_edges.items():
            for tgt in targets:
                graph.dependents.setdefault(tgt, set()).add(src)
        for rel, sym in index.all_symbols():
            graph.symbols_by_name.setdefault(sym.name, []).append((rel, sym))
            graph.symbols_by_name.setdefault(sym.qualified_name, []).append((rel, sym))
        for rel in files:
            if is_test_file(rel):
                graph.test_links[rel] = _find_test_targets(rel, files, graph)
        return graph

    # -- queries -------------------------------------------------------
    def dependents_of(self, rel_path: str) -> set[str]:
        """Files that (transitively) depend on ``rel_path``."""
        seen: set[str] = set()
        stack = list(self.dependents.get(rel_path, ()))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.dependents.get(cur, ()))
        return seen

    def dependencies_of(self, rel_path: str) -> set[str]:
        """Files ``rel_path`` (transitively) depends on."""
        seen: set[str] = set()
        stack = list(self.import_edges.get(rel_path, ()))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.import_edges.get(cur, ()))
        return seen

    def tests_for(self, rel_path: str) -> set[str]:
        """Test files that cover ``rel_path`` (direct links + dependents)."""
        out: set[str] = set()
        for test, targets in self.test_links.items():
            if rel_path in targets:
                out.add(test)
        for dep in self.dependents_of(rel_path):
            if is_test_file(dep):
                out.add(dep)
        return out

    def callers_of(self, symbol_name: str) -> list[tuple[str, str, int]]:
        """(file, caller symbol, line) triples calling ``symbol_name``."""
        out = []
        short = symbol_name.split(".")[-1]
        for rel, rec in self.index.files.items():
            for call in rec.parsed.calls:
                if call.callee == symbol_name or call.callee.split(".")[-1] == short:
                    out.append((rel, call.caller, call.line))
        return out


def _resolve_import(
    root: str, from_file: str, module: str, level: int, files: set[str]
) -> str | None:
    """Resolve an import to a file inside the repo, or None."""
    if not module:
        return None
    # JavaScript relative imports: './billing' -> billing.js
    if module.startswith("."):
        base_dir = posixpath.dirname(from_file.replace(os.sep, "/"))
        target = posixpath.normpath(posixpath.join(base_dir, module))
        for cand in (
            target + ".js", target + ".ts", target + ".jsx", target + ".tsx",
            target + "/index.js", target + "/index.ts", target + ".py",
            target + "/__init__.py",
        ):
            if cand in files:
                return cand
        return None
    if "/" in module and not module.startswith("@"):
        # Bare specifier with a path (e.g. 'lodash/fp') is external.
        pass
    # Python-style: 'pkg.mod' or 'mod' -> search for a matching file.
    dotted = module.replace("/", ".")
    parts = dotted.split(".")
    candidates = []
    for i in range(len(parts), 0, -1):
        prefix = "/".join(parts[:i])
        candidates.append(prefix + ".py")
        candidates.append(prefix + "/__init__.py")
    for cand in candidates:
        if cand in files:
            return cand
    # Same-directory fallback: 'billing' imported from 'api.py' in the
    # same folder as 'billing.py'.
    same_dir = posixpath.join(posixpath.dirname(from_file.replace(os.sep, "/")), parts[-1] + ".py")
    if same_dir in files:
        return same_dir
    return None


def _find_test_targets(test_path: str, files: set[str], graph: Graph) -> set[str]:
    """Guess which source files a test file covers."""
    targets: set[str] = set()
    # 1. Direct import edges from the test file.
    for tgt in graph.import_edges.get(test_path, ()):
        if not is_test_file(tgt):
            targets.add(tgt)
    # 2. Name matching: test_auth.py / auth.test.js -> auth.py / auth.js
    base = os.path.basename(test_path)
    stem = base
    for marker in ("test_", "_test", ".test"):
        stem = stem.replace(marker, "")
    stem = os.path.splitext(stem)[0]
    for f in files:
        if is_test_file(f):
            continue
        if os.path.splitext(os.path.basename(f))[0] == stem:
            targets.add(f)
    return targets
