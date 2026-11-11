"""Hybrid search with explainable ranking.

Signals, in priority order:

1. Exact symbol lookup (name or qualified name matches the query).
2. Symbol substring match.
3. Full-text hits (token match in file lines, with line numbers).
4. Path ranking (query tokens in the file path).
5. Graph relevance (number of dependents / callers).

Every result carries ``reasons`` explaining why it ranked where it did,
so a user (or an AI assistant) can see the evidence instead of trusting
a black-box score. There is no embedding model here; semantic search is
an optional, disabled-by-default add-on in the blueprint.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .graph import Graph
from .indexer import Index

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "in", "on", "and", "or", "is",
    "are", "be", "by", "with", "as", "at", "from", "into", "after",
    "before", "then", "than", "that", "this", "it", "its", "i", "you",
    "we", "they", "he", "she", "not", "no", "do", "does", "did", "can",
    "could", "will", "would", "should", "if", "else", "when", "where",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def stem(word: str) -> str:
    """Tiny suffix stemmer so 'authenticate' matches 'authentication'.

    Deliberately small and documented: production search would use a real
    stemmer or embeddings. Rules are applied longest-suffix first.
    """
    w = word.lower()
    if len(w) > 6 and w.endswith("ation"):
        return w[:-5]
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 5 and w.endswith("ate"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es") and not w.endswith("ss"):
        return w[:-2]
    if len(w) > 3 and w.endswith("e") and not w.endswith("ee"):
        return w[:-1]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def content_tokens(text: str) -> list[str]:
    """Searchable tokens: lowercased, stopwords removed, stemmed."""
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS]


def split_identifier(name: str) -> list[str]:
    """Split camelCase / snake_case identifiers into lowercase tokens."""
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").split()
    return [p.lower() for p in parts if p]


@dataclass
class SearchResult:
    kind: str  # symbol | text | file
    path: str
    line: int = 0
    name: str = ""
    score: float = 0.0
    snippet: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "name": self.name,
            "score": round(self.score, 2),
            "snippet": self.snippet,
            "reasons": self.reasons,
        }


def search(index: Index, graph: Graph, query: str, limit: int = 10) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []
    q_tokens = tokenize(query)
    q_lower = query.lower()
    # Content tokens: stopwords removed, stemmed. A natural-language
    # question like "Where is authentication handled?" reduces to
    # {authentic, handl} -- the words that actually discriminate.
    q_content = content_tokens(query)
    results: dict[tuple[str, str, int], SearchResult] = {}

    def add(result: SearchResult) -> None:
        key = (result.kind, result.path, result.line)
        if key in results:
            existing = results[key]
            existing.score = max(existing.score, result.score)
            for reason in result.reasons:
                if reason not in existing.reasons:
                    existing.reasons.append(reason)
        else:
            results[key] = result

    # 1-2. Symbol lookup (exact, then substring, then token match).
    for rel, sym in index.all_symbols():
        name_lower = sym.name.lower()
        qual_lower = sym.qualified_name.lower()
        if name_lower == q_lower or qual_lower == q_lower:
            callers = len(graph.callers_of(sym.qualified_name))
            add(SearchResult(
                kind="symbol", path=rel, line=sym.line, name=sym.qualified_name,
                score=100.0 + min(20, 2 * callers),
                snippet=sym.signature or sym.name,
                reasons=["exact symbol match"]
                + ([f"{callers} caller(s) in the repo"] if callers else []),
            ))
        elif q_lower in name_lower or q_lower in qual_lower:
            add(SearchResult(
                kind="symbol", path=rel, line=sym.line, name=sym.qualified_name,
                score=60.0,
                snippet=sym.signature or sym.name,
                reasons=["symbol name contains the query"],
            ))
        elif q_content:
            sym_tokens = {stem(t) for t in split_identifier(sym.name)}
            if all(tok in sym_tokens for tok in q_content):
                add(SearchResult(
                    kind="symbol", path=rel, line=sym.line, name=sym.qualified_name,
                    score=55.0,
                    snippet=sym.signature or sym.name,
                    reasons=["symbol tokens match all query tokens"],
                ))

    # 3. Full-text search over file contents. A line scores by how many
    # content tokens it contains, so a natural-language question matches
    # the lines that actually discuss its subject.
    for rel in sorted(index.files):
        full = os.path.join(index.root, rel)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        total_overlap = 0
        line_hits = 0
        for lineno, line in enumerate(lines, start=1):
            overlap = len(set(q_content) & set(content_tokens(line)))
            if overlap:
                total_overlap += overlap
                line_hits += 1
                if line_hits <= 3:  # keep at most 3 line hits per file
                    add(SearchResult(
                        kind="text", path=rel, line=lineno,
                        score=5.0 * overlap,
                        snippet=line.strip()[:160],
                        reasons=["full-text match on this line"],
                    ))
        if total_overlap:
            key = ("file", rel, 0)
            if key not in results:
                add(SearchResult(
                    kind="file", path=rel, line=0,
                    score=min(30.0, 5.0 * total_overlap),
                    snippet=f"{total_overlap} matching token(s)",
                    reasons=[f"{total_overlap} full-text token hit(s) in file"],
                ))

    # 4. Path ranking.
    for rel in index.files:
        path_tokens = {stem(t) for t in tokenize(rel.replace(os.sep, " "))}
        overlap = len(set(q_content) & path_tokens)
        if overlap:
            add(SearchResult(
                kind="file", path=rel, line=0,
                score=25.0 * overlap,
                snippet="",
                reasons=["query token(s) appear in the file path"],
            ))

    # 5. Graph relevance: boost files with many dependents.
    for rel in index.files:
        deps = len(graph.dependents.get(rel, ()))
        if deps:
            key = ("file", rel, 0)
            if key in results:
                results[key].score += min(20.0, 2.0 * deps)
                results[key].reasons.append(f"imported by {deps} file(s)")

    ranked = sorted(results.values(), key=lambda r: (-r.score, r.path, r.line))
    return ranked[:limit]
