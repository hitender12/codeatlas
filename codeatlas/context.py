"""Context packs: bounded, explainable sets of snippets for a task.

Given a task description, CodeAtlas ranks files and symbols by
deterministic signals (token overlap with the task, symbol matches,
graph centrality) and assembles snippets with exact file paths and line
ranges. The pack is strictly bounded by a token budget.

Tokens are approximated as ``characters / 4`` -- the same approximation
many tokenizers land near for code. This is documented, not hidden: the
pack reports both its token estimate and its byte size. A future version
can plug in a real tokenizer behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph import Graph
from .indexer import Index
from .search import content_tokens, search, split_identifier, stem

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class Snippet:
    path: str
    start_line: int
    end_line: int
    text: str
    why: str

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "tokens": self.tokens,
            "why": self.why,
            "text": self.text,
        }


@dataclass
class ContextPack:
    task: str
    budget_tokens: int
    snippets: list[Snippet] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(s.tokens for s in self.snippets)

    @property
    def bytes(self) -> int:
        return sum(len(s.text.encode("utf-8")) for s in self.snippets)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "budget_tokens": self.budget_tokens,
            "tokens": self.tokens,
            "bytes": self.bytes,
            "snippets": [s.to_dict() for s in self.snippets],
        }


def build_context_pack(
    index: Index, graph: Graph, task: str, budget_tokens: int = 4000
) -> ContextPack:
    task_tokens = set(content_tokens(task))
    pack = ContextPack(task=task, budget_tokens=budget_tokens)
    if not task_tokens:
        return pack

    # Candidate snippets: one per matching symbol (its definition body) and
    # one per top text hit. Ranked by overlap with the task, then by graph
    # centrality (dependents) so widely-used code wins ties.
    candidates: list[tuple[float, Snippet]] = []

    for rel, sym in index.all_symbols():
        sym_tokens = {stem(t) for t in split_identifier(sym.name)} | set(
            content_tokens(sym.docstring)
        )
        overlap = len(task_tokens & sym_tokens)
        if overlap == 0:
            continue
        dependents = len(graph.dependents.get(rel, ()))
        score = 10.0 * overlap + min(10.0, dependents)
        try:
            lines = index.read_lines(rel, sym.line, sym.end_line)
        except (OSError, ValueError):
            continue
        text = "\n".join(lines)
        candidates.append((
            score,
            Snippet(
                path=rel, start_line=sym.line, end_line=sym.end_line,
                text=text,
                why=f"symbol '{sym.qualified_name}' matches task tokens "
                    f"({overlap} overlap); file imported by {dependents} file(s)",
            ),
        ))

    # Text hits from hybrid search, as file-level context when no symbol hit.
    for result in search(index, graph, task, limit=20):
        if result.kind != "text" or result.line == 0:
            continue
        try:
            lines = index.read_lines(result.path, result.line, result.line)
        except (OSError, ValueError):
            continue
        candidates.append((
            5.0,
            Snippet(
                path=result.path, start_line=result.line, end_line=result.line,
                text=lines[0] if lines else "",
                why=f"text match for task: {result.snippet[:80]}",
            ),
        ))

    candidates.sort(key=lambda item: (-item[0], item[1].path, item[1].start_line))

    seen: set[tuple[str, int, int]] = set()
    for _, snippet in candidates:
        key = (snippet.path, snippet.start_line, snippet.end_line)
        if key in seen:
            continue
        seen.add(key)
        # Enforce the budget: truncate the snippet to the remaining budget.
        remaining = budget_tokens - pack.tokens
        if remaining <= 0:
            break
        if snippet.tokens > remaining:
            allowed_chars = remaining * CHARS_PER_TOKEN
            truncated = snippet.text[:allowed_chars]
            # Cut at a line boundary so we never emit a half line.
            if "\n" in truncated:
                truncated = truncated.rsplit("\n", 1)[0]
            if not truncated.strip():
                continue
            snippet = Snippet(
                path=snippet.path, start_line=snippet.start_line,
                end_line=snippet.start_line + truncated.count("\n"),
                text=truncated, why=snippet.why + " (truncated to fit budget)",
            )
        pack.snippets.append(snippet)

    return pack
