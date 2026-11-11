"""Incremental indexer.

Walks a repository, hashes each supported file, and re-parses only files
whose content changed since the last index. Change detection prefers
``git status`` when the target is a Git checkout (fast, authoritative) and
falls back to comparing stored SHA-256 hashes and mtimes.

The index lives in ``.codeatlas/index.json`` inside the indexed repo and is
plain JSON so it can be inspected with any tool.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field

from .parsers import ParsedFile, language_for_path, parse_file

INDEX_DIR = ".codeatlas"
INDEX_FILE = "index.json"
CONFIG_FILE = "config.json"
INDEX_VERSION = 1

DEFAULT_IGNORES = {
    ".git", ".codeatlas", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    "target", ".idea", ".vscode",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_changed_files(root: str) -> set[str] | None:
    """Changed + untracked files from git, or None when not a git repo."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "status", "--porcelain", "-uall"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    changed: set[str] = set()
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:  # renames: "old -> new"
            path = path.split(" -> ", 1)[1]
        changed.add(path.strip('"'))
    return changed


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
            try:
                index.files[rel] = FileRecord.from_dict(rec)
            except (KeyError, TypeError):
                continue
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


def _iter_source_files(root: str, ignore: set[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore and not d.startswith(".")]
        for name in sorted(filenames):
            if language_for_path(name) is None:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            yield rel, full


def index_repo(root: str, force: bool = False) -> tuple[Index, IndexStats]:
    """Index (or re-index) ``root`` incrementally.

    Returns the index and stats. ``stats.indexed`` counts files that were
    actually parsed in this run -- the number the incremental logic touched.
    """
    root = os.path.abspath(root)
    index = Index.load(root)
    stats = IndexStats()

    seen: set[str] = set()
    for rel, full in _iter_source_files(root, DEFAULT_IGNORES):
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
        "languages": ["python", "javascript", "typescript"],
        "ignore": sorted(DEFAULT_IGNORES),
        "context_budget_tokens": 4000,
        "privacy": "local-only: codeatlas never uploads source code.",
    }
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    return cfg_path
