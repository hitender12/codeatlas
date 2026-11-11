"""Incremental indexer.

Walks a repository, hashes each supported file, and re-parses only files
whose content changed since the last index. Change detection is by
SHA-256 content hash only -- git status is NOT used for indexing (it
is used only by the diff view in ``archmap.py``), so the indexer is
correct on non-git trees too.

Configuration in ``.codeatlas/config.json`` (written by ``init_repo``)
is read back on every index: the ignore list, the language list, and
the default context budget. Missing, corrupt, or invalid entries fall
back to the built-in defaults.

Safety: the walk never follows symlinks (a symlinked file inside the
repo could point outside it), and index records whose paths would
escape the repo root are rejected on load and on read.

The index lives in ``.codeatlas/index.json`` inside the indexed repo and is
plain JSON so it can be inspected with any tool.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from .parsers import SUPPORTED_EXTENSIONS, ParsedFile, language_for_path, parse_file

INDEX_DIR = ".codeatlas"
INDEX_FILE = "index.json"
CONFIG_FILE = "config.json"
INDEX_VERSION = 1

DEFAULT_IGNORES = {
    ".git", ".codeatlas", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    "target", ".idea", ".vscode",
}

# Ignored no matter what the config says: the index must never index
# its own directory, and .git contents are never source.
ALWAYS_IGNORED = {".git", ".codeatlas"}

DEFAULT_LANGUAGES = ["python", "javascript", "typescript"]
DEFAULT_CONTEXT_BUDGET_TOKENS = 4000


def _is_safe_rel_path(rel: str) -> bool:
    """True when ``rel`` is a repo-relative path that cannot escape the root.

    Rejects absolute paths, NUL bytes, and any ``..`` component, so a
    crafted ``.codeatlas/index.json`` cannot make the reader open
    files outside the indexed repository.
    """
    if not rel or "\x00" in rel or os.path.isabs(rel):
        return False
    parts = rel.replace("\\", "/").split("/")
    return ".." not in parts


@dataclass
class IndexConfig:
    """Effective configuration for one indexed repo.

    Built by :func:`load_config` from ``.codeatlas/config.json`` with
    the built-in defaults for anything missing or invalid.
    """

    languages: list[str] = field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    ignore: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORES))
    context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS


def load_config(root: str) -> IndexConfig:
    """Read ``.codeatlas/config.json``; defaults for anything absent/invalid."""
    config = IndexConfig()
    path = os.path.join(root, INDEX_DIR, CONFIG_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return config
    if not isinstance(raw, dict):
        return config
    langs = raw.get("languages")
    if isinstance(langs, list) and langs and all(isinstance(x, str) for x in langs):
        known = set(SUPPORTED_EXTENSIONS.values())
        kept = [x for x in langs if x in known]
        if kept:
            config.languages = kept
    ignore = raw.get("ignore")
    if isinstance(ignore, list) and all(isinstance(x, str) for x in ignore):
        config.ignore = set(ignore)
    budget = raw.get("context_budget_tokens")
    if isinstance(budget, int) and not isinstance(budget, bool) and budget > 0:
        config.context_budget_tokens = budget
    return config


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FileRecord:
    path: str
    language: str
    sha256: str
    mtime: float
    size: int
    parsed: ParsedFile

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "language": self.language,
            "sha256": self.sha256,
            "mtime": self.mtime,
            "size": self.size,
            "parsed": self.parsed.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileRecord":
        return cls(
            path=data["path"],
            language=data["language"],
            sha256=data["sha256"],
            mtime=data["mtime"],
            size=data["size"],
            parsed=ParsedFile.from_dict(data["parsed"]),
        )


@dataclass
class Index:
    root: str
    files: dict[str, FileRecord] = field(default_factory=dict)

    # -- persistence ---------------------------------------------------
    @property
    def index_path(self) -> str:
        return os.path.join(self.root, INDEX_DIR, INDEX_FILE)

    def save(self) -> None:
        os.makedirs(os.path.join(self.root, INDEX_DIR), exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "root": self.root,
            "files": {p: r.to_dict() for p, r in sorted(self.files.items())},
        }
        with open(self.index_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)

    @classmethod
    def load(cls, root: str) -> "Index":
        index = cls(root=root)
        path = os.path.join(root, INDEX_DIR, INDEX_FILE)
        if not os.path.exists(path):
            return index
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            return index
        if payload.get("version") != INDEX_VERSION:
            return index
        for rel, rec in payload.get("files", {}).items():
            if not _is_safe_rel_path(rel):
                # A crafted index must not smuggle in a path that
                # escapes the repo root (e.g. "../../etc/passwd").
                continue
            try:
                record = FileRecord.from_dict(rec)
            except (KeyError, TypeError):
                continue
            record.path = rel  # the key is authoritative, not the record
            index.files[rel] = record
        return index

    # -- queries -------------------------------------------------------
    @property
    def total_symbols(self) -> int:
        return sum(len(r.parsed.symbols) for r in self.files.values())

    @property
    def total_imports(self) -> int:
        return sum(len(r.parsed.imports) for r in self.files.values())

    def all_symbols(self):
        for rel, rec in self.files.items():
            for sym in rec.parsed.symbols:
                yield rel, sym

    def find_symbol(self, name: str):
        """Exact symbol lookup: returns [(rel_path, Symbol)] matches."""
        out = []
        for rel, sym in self.all_symbols():
            if sym.name == name or sym.qualified_name == name:
                out.append((rel, sym))
        return out

    def read_lines(self, rel_path: str, start: int, end: int) -> list[str]:
        """1-based inclusive line slice of a file in the index."""
        if not _is_safe_rel_path(rel_path):
            raise ValueError(f"refusing to read path outside the repo: {rel_path!r}")
        full = os.path.join(self.root, rel_path)
        with open(full, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return [ln.rstrip("\n") for ln in lines[start - 1:end]]


@dataclass
class IndexStats:
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    parse_errors: int = 0

    def to_dict(self) -> dict:
        return {
            "indexed": self.indexed,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "parse_errors": self.parse_errors,
        }


def _iter_source_files(root: str, ignore: set[str], languages: list[str] | None = None):
    """Yield ``(rel_path, full_path)`` for every indexable source file.

    Symlinked files are skipped: the walk never follows a symlink out
    of the repository (a link inside the repo could point at e.g.
    ``/etc/passwd`` and have its contents embedded in the index).
    Symlinked directories are not descended into either
    (``os.walk`` with ``followlinks=False``).
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore and not d.startswith(".")]
        for name in sorted(filenames):
            lang = language_for_path(name)
            if lang is None:
                continue
            if languages is not None and lang not in languages:
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, root)
            yield rel, full


def index_repo(root: str, force: bool = False,
               config: IndexConfig | None = None) -> tuple[Index, IndexStats]:
    """Index (or re-index) ``root`` incrementally.

    Change detection is by SHA-256 content hash only. The ignore list
    and language filter come from ``.codeatlas/config.json`` when it
    exists (see :func:`load_config`); ``.git`` and ``.codeatlas`` are
    always ignored regardless of the config.

    Returns the index and stats. ``stats.indexed`` counts files that were
    actually parsed in this run -- the number the incremental logic touched.
    """
    root = os.path.abspath(root)
    if config is None:
        config = load_config(root)
    ignore = ALWAYS_IGNORED | set(config.ignore)
    index = Index.load(root)
    stats = IndexStats()

    seen: set[str] = set()
    for rel, full in _iter_source_files(root, ignore, config.languages):
        seen.add(rel)
        try:
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        digest = _sha256(data)
        mtime = os.path.getmtime(full)
        prev = index.files.get(rel)
        if not force and prev is not None and prev.sha256 == digest:
            # Content unchanged: skip re-parsing even if mtime moved.
            prev.mtime = mtime
            stats.unchanged += 1
            continue
        try:
            source = data.decode("utf-8")
        except UnicodeDecodeError:
            source = data.decode("utf-8", errors="replace")
        parsed = parse_file(rel, source)
        if parsed.parse_error:
            stats.parse_errors += 1
        index.files[rel] = FileRecord(
            path=rel,
            language=parsed.language,
            sha256=digest,
            mtime=mtime,
            size=len(data),
            parsed=parsed,
        )
        stats.indexed += 1

    for rel in list(index.files):
        if rel not in seen:
            del index.files[rel]
            stats.removed += 1

    index.save()
    return index, stats


def init_repo(root: str) -> str:
    """Create ``.codeatlas/config.json``. Returns the config path."""
    root = os.path.abspath(root)
    cfg_dir = os.path.join(root, INDEX_DIR)
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_path = os.path.join(cfg_dir, CONFIG_FILE)
    config = {
        "version": INDEX_VERSION,
        "languages": list(DEFAULT_LANGUAGES),
        "ignore": sorted(DEFAULT_IGNORES),
        "context_budget_tokens": DEFAULT_CONTEXT_BUDGET_TOKENS,
        "privacy": "local-only: codeatlas never uploads source code.",
    }
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    return cfg_path
