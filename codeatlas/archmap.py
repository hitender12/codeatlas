"""Architecture map and Git-aware change view.

The architecture map groups files into modules (top-level directories)
and draws dependency edges between modules from the import graph. It
renders as Mermaid, Graphviz DOT, and JSON -- the same data, three
views, so the map can be pasted into docs or piped into other tools.

The change view takes a set of changed files (from ``git diff`` /
``git status`` or an explicit list) and reports which modules and tests
are likely affected, by walking the reverse dependency graph.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field

from .graph import Graph, is_test_file, module_of
from .indexer import Index


@dataclass
class ModuleEdge:
    source: str
    target: str
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "files": sorted(self.files)}


@dataclass
class ArchitectureMap:
    modules: list[str]
    edges: list[ModuleEdge]

    def to_dict(self) -> dict:
        return {
            "modules": sorted(self.modules),
            "edges": [e.to_dict() for e in sorted(self.edges, key=lambda e: (e.source, e.target))],
        }

    def to_mermaid(self) -> str:
        lines = ["flowchart LR"]
        for edge in sorted(self.edges, key=lambda e: (e.source, e.target)):
            lines.append(f"    {edge.source} --> {edge.target}")
        for module in sorted(self.modules):
            if not any(e.source == module or e.target == module for e in self.edges):
                lines.append(f"    {module}")
        return "\n".join(lines) + "\n"

    def to_dot(self) -> str:
        lines = ["digraph codeatlas {", '    rankdir="LR";']
        for edge in sorted(self.edges, key=lambda e: (e.source, e.target)):
            lines.append(f'    "{edge.source}" -> "{edge.target}";')
        for module in sorted(self.modules):
            if not any(e.source == module or e.target == module for e in self.edges):
                lines.append(f'    "{module}";')
        lines.append("}")
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def build_architecture_map(index: Index, graph: Graph) -> ArchitectureMap:
    modules: set[str] = set()
    edge_map: dict[tuple[str, str], set[str]] = {}
    for rel in index.files:
        modules.add(module_of(rel))
    for src, targets in graph.import_edges.items():
        src_mod = module_of(src)
        for tgt in targets:
            tgt_mod = module_of(tgt)
            if src_mod == tgt_mod:
                continue
            edge_map.setdefault((src_mod, tgt_mod), set()).add(f"{src} -> {tgt}")
    edges = [
        ModuleEdge(source=s, target=t, files=sorted(fs))
        for (s, t), fs in edge_map.items()
    ]
    return ArchitectureMap(modules=sorted(modules), edges=edges)


# ---------------------------------------------------------------------------
# Git-aware change view
# ---------------------------------------------------------------------------


@dataclass
class ChangeImpact:
    changed_files: list[str]
    affected_modules: list[str]
    affected_files: list[str]
    affected_tests: list[str]

    def to_dict(self) -> dict:
        return {
            "changed_files": self.changed_files,
            "affected_modules": self.affected_modules,
            "affected_files": self.affected_files,
            "affected_tests": self.affected_tests,
        }


def git_changed_files(root: str, ref: str | None = None) -> list[str] | None:
    """Changed files from git, or None when git is unavailable / not a repo.

    With ``ref``: ``git diff --name-only <ref>`` (committed changes).
    Without: working-tree + staged changes (``git status --porcelain``).

    ``ref`` is passed after ``--end-of-options`` so a ref starting
    with ``-`` cannot be parsed as a git option (e.g. ``--output``).
    """
    try:
        if ref:
            out = subprocess.run(
                ["git", "-C", root, "diff", "--name-only",
                 "--end-of-options", ref],
                capture_output=True, text=True, timeout=30,
            )
        else:
            out = subprocess.run(
                ["git", "-C", root, "status", "--porcelain", "-uall"],
                capture_output=True, text=True, timeout=30,
            )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    changed: list[str] = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip() if not ref else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path.strip('"'))
    return sorted(set(changed))


def diff_impact(index: Index, graph: Graph, changed_files: list[str]) -> ChangeImpact:
    """Impact of changing files: the files themselves plus everything that
    depends on them (transitively), and the tests covering any of those.

    Dependencies (things the changed files import) are deliberately NOT
    included: changing a caller does not change the code it calls.
    """
    changed = [f for f in changed_files if f in index.files]
    affected: set[str] = set(changed)
    for f in changed:
        affected |= graph.dependents_of(f)
    tests: set[str] = set()
    for f in list(affected):
        tests |= graph.tests_for(f)
        if is_test_file(f):
            tests.add(f)
    modules = sorted({module_of(f) for f in affected})
    return ChangeImpact(
        changed_files=sorted(changed),
        affected_modules=modules,
        affected_files=sorted(affected),
        affected_tests=sorted(tests),
    )


def render_impact(impact: ChangeImpact) -> str:
    lines = ["Changed files:"]
    for f in impact.changed_files or ["(none)"]:
        lines.append(f"  - {f}")
    lines.append("Affected modules:")
    for m in impact.affected_modules or ["(none)"]:
        lines.append(f"  - {m}")
    lines.append("Affected files:")
    for f in impact.affected_files or ["(none)"]:
        lines.append(f"  - {f}")
    lines.append("Affected tests:")
    for t in impact.affected_tests or ["(none)"]:
        lines.append(f"  - {t}")
    return "\n".join(lines)
