"""Language-aware parsing for CodeAtlas.

Python is parsed with the real ``ast`` module. JavaScript/TypeScript is
parsed with targeted regular expressions (a deliberate, documented
approximation). The production path for every language is Tree-sitter
grammars; this module is the seam that a Tree-sitter adapter replaces.

A parsed file yields:

* ``symbols`` -- definitions with exact line numbers
* ``imports`` -- module names the file depends on
* ``calls`` -- (caller symbol, callee name, line) triples
"""

from __future__ import annotations

import ast
import bisect
import re
from dataclasses import dataclass, field

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

# ---------------------------------------------------------------------------
# Shared data model
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    name: str
    kind: str  # function | method | class | variable | constant
    line: int
    end_line: int
    qualified_name: str = ""
    signature: str = ""
    docstring: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "end_line": self.end_line,
            "qualified_name": self.qualified_name or self.name,
            "signature": self.signature,
            "docstring": self.docstring,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Symbol":
        return cls(
            name=data["name"],
            kind=data["kind"],
            line=data["line"],
            end_line=data["end_line"],
            qualified_name=data.get("qualified_name", data["name"]),
            signature=data.get("signature", ""),
            docstring=data.get("docstring", ""),
        )


@dataclass
class Import:
    module: str
    names: list[str] = field(default_factory=list)
    line: int = 0
    level: int = 0  # 0 = absolute, >0 = relative (dots)

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "names": self.names,
            "line": self.line,
            "level": self.level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Import":
        return cls(
            module=data["module"],
            names=data.get("names", []),
            line=data.get("line", 0),
            level=data.get("level", 0),
        )


@dataclass
class Call:
    caller: str  # qualified name of the enclosing symbol, "" for module level
    callee: str
    line: int

    def to_dict(self) -> dict:
        return {"caller": self.caller, "callee": self.callee, "line": self.line}

    @classmethod
    def from_dict(cls, data: dict) -> "Call":
        return cls(caller=data["caller"], callee=data["callee"], line=data["line"])


@dataclass
class ParsedFile:
    path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    parse_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "language": self.language,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": [i.to_dict() for i in self.imports],
            "calls": [c.to_dict() for c in self.calls],
            "parse_error": self.parse_error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParsedFile":
        return cls(
            path=data["path"],
            language=data["language"],
            symbols=[Symbol.from_dict(s) for s in data.get("symbols", [])],
            imports=[Import.from_dict(i) for i in data.get("imports", [])],
            calls=[Call.from_dict(c) for c in data.get("calls", [])],
            parse_error=data.get("parse_error"),
        )


def language_for_path(path: str) -> str | None:
    for ext, lang in SUPPORTED_EXTENSIONS.items():
        if path.endswith(ext):
            return lang
    return None


def parse_file(path: str, source: str) -> ParsedFile:
    lang = language_for_path(path)
    if lang is None:
        return ParsedFile(path=path, language="unknown")
    if lang == "python":
        return _parse_python(path, source)
    return _parse_javascript(path, source, lang)


# ---------------------------------------------------------------------------
# Python (real AST parsing)
# ---------------------------------------------------------------------------


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[Symbol] = []
        self.imports: list[Import] = []
        self.calls: list[Call] = []
        self._scope: list[str] = []
        self._scope_kinds: list[str] = []

    def _current(self) -> str:
        return ".".join(self._scope)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [ast.unparse(b) for b in node.bases] if node.bases else []
        sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
        self.symbols.append(
            Symbol(
                name=node.name,
                kind="class",
                line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                qualified_name=".".join(self._scope + [node.name]),
                signature=sig,
                docstring=ast.get_docstring(node) or "",
            )
        )
        self._scope.append(node.name)
        self._scope_kinds.append("class")
        self.generic_visit(node)
        self._scope.pop()
        self._scope_kinds.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = ast.unparse(node.args) if node.args else ""
        is_method = bool(self._scope_kinds) and self._scope_kinds[-1] == "class"
        self.symbols.append(
            Symbol(
                name=node.name,
                kind="method" if is_method else "function",
                line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                qualified_name=".".join(self._scope + [node.name]),
                signature=f"def {node.name}({args})",
                docstring=ast.get_docstring(node) or "",
            )
        )
        self._scope.append(node.name)
        self._scope_kinds.append("function")
        self.generic_visit(node)
        self._scope.pop()
        self._scope_kinds.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                Import(module=alias.name, names=[alias.asname or alias.name.split(".")[0]], line=node.lineno)
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = [a.asname or a.name for a in node.names]
        self.imports.append(
            Import(module=node.module or "", names=names, line=node.lineno, level=node.level)
        )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        callee = self._callee_name(node.func)
        if callee:
            self.calls.append(Call(caller=self._current(), callee=callee, line=node.lineno))
        self.generic_visit(node)

    @staticmethod
    def _callee_name(func: ast.AST) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts: list[str] = []
            cur: ast.AST = func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                return ".".join(reversed(parts))
            return ".".join(reversed(parts))
        return None


def _parse_python(path: str, source: str) -> ParsedFile:
    parsed = ParsedFile(path=path, language="python")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        parsed.parse_error = f"SyntaxError line {exc.lineno}: {exc.msg}"
        return parsed
    visitor = _PythonVisitor()
    visitor.visit(tree)
    # Module-level constants / assignments.
    constants: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants.append(
                        Symbol(
                            name=target.id,
                            kind="constant",
                            line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                            qualified_name=target.id,
                        )
                    )
    parsed.symbols = visitor.symbols + constants
    parsed.imports = visitor.imports
    parsed.calls = visitor.calls
    return parsed


# ---------------------------------------------------------------------------
# JavaScript / TypeScript (regex-based approximation)
# ---------------------------------------------------------------------------

_JS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "function", "class",
    "new", "typeof", "instanceof", "else", "do", "try", "throw", "await",
    "yield", "delete", "void", "in", "of", "case", "default", "import",
    "export", "from", "extends", "super", "this", "console",
}

_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:type\s+)?(?:[\w*{}\s,]+?\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_EXPORT_FROM_RE = re.compile(
    r"""^\s*export\s+(?:\*|\{[^}]*\})\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE
)
_FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(""",
    re.MULTILINE,
)
_ARROW_RE = re.compile(
    r"""^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>""",
    re.MULTILINE,
)
_CLASS_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)\b""",
    re.MULTILINE,
)
_METHOD_RE = re.compile(
    r"""^(\s+)(?:async\s+|static\s+|get\s+|set\s+)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{""",
    re.MULTILINE,
)
_CALL_RE = re.compile(r"""([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(""")


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _line_of(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def _parse_javascript(path: str, source: str, lang: str) -> ParsedFile:
    parsed = ParsedFile(path=path, language=lang)
    starts = _line_starts(source)

    for m in _IMPORT_RE.finditer(source):
        parsed.imports.append(Import(module=m.group(1), line=_line_of(starts, m.start())))
    for m in _REQUIRE_RE.finditer(source):
        parsed.imports.append(Import(module=m.group(1), line=_line_of(starts, m.start())))
    for m in _EXPORT_FROM_RE.finditer(source):
        parsed.imports.append(Import(module=m.group(1), line=_line_of(starts, m.start())))

    for m in _FUNCTION_RE.finditer(source):
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="function", line=_line_of(starts, m.start()),
                   end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
    for m in _ARROW_RE.finditer(source):
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="function", line=_line_of(starts, m.start()),
                   end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
    for m in _CLASS_RE.finditer(source):
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="class", line=_line_of(starts, m.start()),
                   end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
    # Methods: indented `name(...) {` lines that are not top-level functions.
    seen = {(s.name, s.line) for s in parsed.symbols}
    for m in _METHOD_RE.finditer(source):
        name = m.group(2)
        if name in _JS_KEYWORDS:
            continue
        line = _line_of(starts, m.start())
        if (name, line) in seen:
            continue
        parsed.symbols.append(
            Symbol(name=name, kind="method", line=line, end_line=line,
                   qualified_name=name, signature=m.group(0).strip())
        )

    # Calls: every `name(` that is not a definition keyword and not a
    # definition site. Caller attribution is best-effort: the nearest
    # preceding function/class symbol in the file.
    defs = sorted(parsed.symbols, key=lambda s: s.line)
    for m in _CALL_RE.finditer(source):
        callee = m.group(1)
        head = callee.split(".")[0]
        if head in _JS_KEYWORDS:
            continue
        line = _line_of(starts, m.start())
        if any(s.line == line and s.name == head for s in defs):
            continue  # definition site, not a call
        caller = ""
        for sym in defs:
            if sym.line <= line:
                caller = sym.qualified_name
            else:
                break
        parsed.calls.append(Call(caller=caller, callee=callee, line=line))

    parsed.symbols.sort(key=lambda s: (s.line, s.name))
    return parsed
