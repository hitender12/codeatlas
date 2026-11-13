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
    # function | method | class | variable | constant | interface | type | enum
    kind: str
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
    "export", "from", "extends", "super", "this", "console", "finally",
    "with",
}

# NOTE on whitespace in these patterns: every ``^`` anchor is followed by
# ``[ \t]*`` (never ``\s*``) and every intra-line gap is ``[ \t]``. ``\s``
# matches newlines, so a ``^\s*`` prefix let a match start on a blank
# line *before* the real definition and report the definition at the
# wrong line (which also leaked the definition site as a self-call and
# made context packs read a blank line as the symbol snippet). The only
# ``\s`` left is inside the import body class, where a multi-line
# ``import { ... } from`` statement genuinely spans lines -- the match
# still *starts* on the import's first line, so its line is exact.
#
# Definitions may also start mid-line after a statement boundary
# (``;`` or ``{``), so minified single-line code is still parsed: the
# prefix ``(?:^|(?<=[;{}]))`` is zero-width in both branches, so the
# match still starts at the keyword and reported lines stay exact.
# ``(`` is deliberately NOT a boundary: ``f(function g() {})`` is a
# function *expression*, not a declaration. Imports stay line-anchored:
# a mid-line ``import`` would be a dynamic ``import(...)`` call, not a
# static import. Module-level ``const`` stays column-0 anchored, so a
# function-local UPPER_SNAKE_CASE const is not mistaken for a symbol.
_BOUNDARY = r"(?:^|(?<=[;{}]))"
# One ``(...)`` group allowing nested parentheses up to three levels
# deep (``(a = g(1, 2))``). Deeper nesting is still a documented gap.
_PAREN_GROUP = r"\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)"

# ---------------------------------------------------------------------------
# Comment / string / template / regex stripping (round 2)
# ---------------------------------------------------------------------------
#
# The regex parser has no comment/string awareness, so code-like text
# inside a multi-line template literal or a /* */ block comment used to
# be indexed as real code (phantom symbols in search results and
# context packs), and calls inside template literals and line comments
# were recorded as real calls. _parse_javascript therefore runs every
# regex against the output of this pre-pass, which replaces comments,
# string literals, template literals and regex literals with spaces,
# preserving newlines -- so every line number and offset is identical
# to the original source. Import module names are recovered from the
# original source via the match spans (the quotes survive the pass,
# only their contents are blanked).
#
# Known simplifications, part of the contract: template-literal
# interpolations (``${...}``) are blanked along with the literal, so
# calls inside an interpolation are not tracked; a ``/`` is treated
# as a regex literal only by the _looks_like_regex_start heuristic.

_JS_REGEX_PREV_CHARS = set("=(:,[!&|?{};")
_JS_REGEX_PREV_KEYWORDS = {
    "return", "typeof", "case", "delete", "void", "in", "of",
    "instanceof", "new", "yield", "await", "throw",
}


def _looks_like_regex_start(source: str, pos: int) -> bool:
    """Heuristic: is the ``/`` at ``pos`` the start of a regex literal?

    A ``/`` starts a regex when the previous significant token cannot
    end an expression (``= ( , : [ ! & | ? { } ;`` or a keyword like
    ``return``/``typeof``), or when it is the first token in the file.
    ``/=`` (division-assign) and ``/`` after an identifier/literal
    are division.
    """
    if pos + 1 < len(source) and source[pos + 1] == "=":
        return False
    j = pos - 1
    while j >= 0 and source[j] in " \t\n\r":
        j -= 1
    if j < 0:
        return True
    prev = source[j]
    if prev in _JS_REGEX_PREV_CHARS:
        return True
    if prev.isalnum() or prev in "_$":
        k = j
        while k >= 0 and (source[k].isalnum() or source[k] in "_$"):
            k -= 1
        return source[k + 1:j + 1] in _JS_REGEX_PREV_KEYWORDS
    return False


def _strip_js_comments_and_strings(source: str) -> str:
    """Blank comments, strings, template literals and regex literals.

    Same length as ``source``; every newline is kept, so line numbers
    and offsets are unchanged. A backslash-newline (line continuation)
    keeps its newline. Unterminated strings/regexes are handled
    leniently: the rest of the line is blanked and scanning resumes
    on the next line.
    """
    out: list[str] = []
    n = len(source)
    i = 0
    # Frames: ("code",) ("line",) ("block",) ("sq",) ("dq",)
    # ("template",) ("interp", depth) ("regex",).
    stack: list[tuple] = [("code",)]

    def blank(ch: str) -> str:
        return "\n" if ch == "\n" else " "

    while i < n:
        tag = stack[-1][0]
        ch = source[i]
        two = source[i:i + 2]
        if tag in ("code", "interp"):
            if two == "//":
                stack.append(("line",))
                out.append("  ")
                i += 2
            elif two == "/*":
                stack.append(("block",))
                out.append("  ")
                i += 2
            elif ch == "'":
                stack.append(("sq",))
                out.append("'")  # keep the delimiters: import patterns
                i += 1           # match `['"]...['"]` on the cleaned text
            elif ch == '"':
                stack.append(("dq",))
                out.append('"')
                i += 1
            elif ch == "`":
                stack.append(("template",))
                out.append("`")
                i += 1
            elif ch == "/" and _looks_like_regex_start(source, i):
                stack.append(("regex",))
                out.append(" ")
                i += 1
            elif tag == "interp" and ch == "{":
                stack[-1] = ("interp", stack[-1][1] + 1)
                out.append(" ")
                i += 1
            elif tag == "interp" and ch == "}":
                depth = stack[-1][1] - 1
                if depth == 0:
                    stack.pop()
                else:
                    stack[-1] = ("interp", depth)
                out.append(" ")
                i += 1
            else:
                out.append(ch if tag == "code" else " ")
                i += 1
        elif tag == "line":
            if ch == "\n":
                stack.pop()
                out.append("\n")
            else:
                out.append(" ")
            i += 1
        elif tag == "block":
            if two == "*/":
                stack.pop()
                out.append("  ")
                i += 2
            else:
                out.append(blank(ch))
                i += 1
        elif tag in ("sq", "dq"):
            quote = "'" if tag == "sq" else '"'
            if ch == "\\" and i + 1 < n:
                out.append(" \n" if source[i + 1] == "\n" else "  ")
                i += 2
            elif ch == quote:
                stack.pop()
                out.append(quote)
                i += 1
            elif ch == "\n":  # unterminated string: be lenient
                stack.pop()
                out.append("\n")
                i += 1
            else:
                out.append(" ")
                i += 1
        elif tag == "template":
            if ch == "\\" and i + 1 < n:
                out.append(" \n" if source[i + 1] == "\n" else "  ")
                i += 2
            elif ch == "`":
                stack.pop()
                out.append("`")
                i += 1
            elif two == "${":
                stack.append(("interp", 1))
                out.append("  ")
                i += 2
            else:
                out.append(blank(ch))
                i += 1
        elif tag == "regex":
            if ch == "\\" and i + 1 < n:
                out.append(" \n" if source[i + 1] == "\n" else "  ")
                i += 2
            elif ch == "/":
                stack.pop()
                out.append(" ")
                i += 1
            elif ch == "\n":  # unterminated regex: be lenient
                stack.pop()
                out.append("\n")
                i += 1
            else:
                out.append(" ")
                i += 1
    return "".join(out)


def _class_body_ranges(source: str, class_matches) -> list[tuple[int, int]]:
    """(start, end) offsets of class bodies, for the field-arrow filter.

    Brace counting on the *cleaned* source is reliable: braces inside
    strings, comments and template literals are already spaces.
    """
    ranges = []
    for m in class_matches:
        brace = source.find("{", m.end())
        if brace == -1:
            continue
        depth = 0
        j = brace
        while j < len(source):
            if source[j] == "{":
                depth += 1
            elif source[j] == "}":
                depth -= 1
                if depth == 0:
                    ranges.append((m.start(), j))
                    break
            j += 1
    return ranges
_IMPORT_RE = re.compile(
    r"""^[ \t]*import\s+(?:type\s+)?(?:[\w*{}\s,]+?[ \t]+from[ \t]+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_EXPORT_FROM_RE = re.compile(
    r"""^[ \t]*export[ \t]+(?:\*|\{[^}]*\})[ \t]+from[ \t]+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_FUNCTION_RE = re.compile(
    _BOUNDARY + r"""[ \t]*(?:export[ \t]+(?:default[ \t]+)?)?(?:async[ \t]+)?"""
    r"""function[ \t]*\*?[ \t]*([A-Za-z_$][\w$]*)[ \t]*(?:<[^>]*>)?[ \t]*\(""",
    re.MULTILINE,
)
# Arrow functions: optional return-type annotation between the parameter
# list and `=>` (``(n: string): string =>``), single-identifier params
# without parens (``x => x * 2``), and an optional ``<T>`` type-parameter
# list before the params (``const wrap = <T>(x: T) => x``).
_ARROW_RE = re.compile(
    _BOUNDARY + r"""[ \t]*(?:export[ \t]+)?const[ \t]+([A-Za-z_$][\w$]*)[ \t]*=[ \t]*"""
    r"""(?:async[ \t]+)?(?:<[^>]*>[ \t]*)?(?:(?:""" + _PAREN_GROUP + r""")|[A-Za-z_$][\w$]*)[ \t]*"""
    r"""(?::[ \t]*[A-Za-z_$<\[{][^=;]*?)?[ \t]*=>""",
    re.MULTILINE,
)
# `const name = function (...) {...}` / `const name = async function ...`,
# including generic function expressions (`const f = function<T>(...)`).
_FUNC_EXPR_RE = re.compile(
    _BOUNDARY + r"""[ \t]*(?:export[ \t]+)?const[ \t]+([A-Za-z_$][\w$]*)[ \t]*=[ \t]*"""
    r"""(?:async[ \t]+)?function[ \t]*\*?[ \t]*(?:<[^>]*>)?[ \t]*\(""",
    re.MULTILINE,
)
_CLASS_RE = re.compile(
    _BOUNDARY + r"""[ \t]*(?:export[ \t]+)?(?:default[ \t]+)?(?:abstract[ \t]+)?"""
    r"""(?:declare[ \t]+)?class[ \t]+([A-Za-z_$][\w$]*)\b""",
    re.MULTILINE,
)
_INTERFACE_RE = re.compile(
    _BOUNDARY + r"""[ \t]*(?:export[ \t]+)?(?:declare[ \t]+)?interface[ \t]+([A-Za-z_$][\w$]*)\b""",
    re.MULTILINE,
)
_TYPE_ALIAS_RE = re.compile(
    _BOUNDARY + r"""[ \t]*(?:export[ \t]+)?type[ \t]+([A-Za-z_$][\w$]*)[ \t]*=""",
    re.MULTILINE,
)
_ENUM_RE = re.compile(
    _BOUNDARY + r"""[ \t]*(?:export[ \t]+)?(?:declare[ \t]+)?(?:const[ \t]+)?enum[ \t]+([A-Za-z_$][\w$]*)\b""",
    re.MULTILINE,
)
# Module-level UPPER_SNAKE_CASE consts only (column 0, optional
# `export`), mirroring the Python rule for module-level constants.
# Lowercase consts are ordinary locals/values and are not symbols.
_CONST_RE = re.compile(
    r"""^(?:export[ \t]+)?const[ \t]+([A-Z][A-Z0-9_]*)[ \t]*(?::[ \t]*[^=;]+?)?=""",
    re.MULTILINE,
)
# Methods: indented `name(...) {` lines. The parameter list is optional
# (getters have none: `get total(): number {`), a return-type annotation
# may sit between `)` and `{` (`: Promise<void>`), and a `<T>` type
# parameter list may sit between the name and `(`. The annotation's
# first character must start a type (`: {` is an object type, but a bare
# `foo: {` object literal is not a method -- the annotation needs a type
# token after the colon). The name may be `#private` or computed
# (`['save']`, `["reset"]`, `[Symbol.iterator]`). Parameter lists allow
# nested parentheses (see _PAREN_GROUP).
_METHOD_RE = re.compile(
    r"""^([ \t]+)(?:(?:async|static|get|set)[ \t]+)*"""
    r"""(?:(?P<plain>#?[A-Za-z_$][\w$]*)|\[\s*(?:'(?P<csq>[^']+)'|"(?P<cdq>[^"]+)"|`(?P<cbt>[^`]+)`|(?P<cexpr>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?))\s*\])"""
    r"""[ \t]*(?:<[^>]*>)?[ \t]*(?:(?:""" + _PAREN_GROUP + r"""))?[ \t]*(?::[ \t]*[A-Za-z_$<\[{][^{;]*?)?\{""",
    re.MULTILINE,
)
# Class-field arrow functions: indented `name = (...) => {` lines
# (`handler = (e: Event): void => {}`). These are only accepted inside
# a class body (see _class_body_ranges in _parse_javascript): the same
# shape at module/function scope is an ordinary variable assignment.
_FIELD_ARROW_RE = re.compile(
    r"""^([ \t]+)(?:(?:public|private|protected|readonly|static|declare|abstract)[ \t]+)*"""
    r"""(#?[A-Za-z_$][\w$]*)[ \t]*=[ \t]*(?:async[ \t]+)?"""
    r"""(?:(?:""" + _PAREN_GROUP + r""")|[A-Za-z_$][\w$]*)[ \t]*"""
    r"""(?::[ \t]*[A-Za-z_$<\[{][^=;]*?)?[ \t]*=>""",
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
    # Every regex below runs against the cleaned source: comments,
    # strings, template literals and regex literals are spaces there,
    # so code-like text inside them can never be mistaken for code.
    # Lengths and newlines are preserved, so line numbers are the
    # same as in the original source. Import module names are the one
    # exception: they live inside string literals, so they are read
    # back from the original source at the match's span.
    cleaned = _strip_js_comments_and_strings(source)
    starts = _line_starts(cleaned)

    def _module(m) -> str:
        start, end = m.span(1)
        return source[start:end]

    for m in _IMPORT_RE.finditer(cleaned):
        parsed.imports.append(Import(module=_module(m), line=_line_of(starts, m.start())))
    for m in _REQUIRE_RE.finditer(cleaned):
        parsed.imports.append(Import(module=_module(m), line=_line_of(starts, m.start())))
    for m in _EXPORT_FROM_RE.finditer(cleaned):
        parsed.imports.append(Import(module=_module(m), line=_line_of(starts, m.start())))

    for m in _FUNCTION_RE.finditer(cleaned):
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="function", line=_line_of(starts, m.start()),
                   end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
    for m in _ARROW_RE.finditer(cleaned):
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="function", line=_line_of(starts, m.start()),
                   end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
    for m in _FUNC_EXPR_RE.finditer(cleaned):
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="function", line=_line_of(starts, m.start()),
                   end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
    class_matches = list(_CLASS_RE.finditer(cleaned))
    for m in class_matches:
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="class", line=_line_of(starts, m.start()),
                   end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
    for regex, kind in ((_INTERFACE_RE, "interface"), (_TYPE_ALIAS_RE, "type"),
                        (_ENUM_RE, "enum")):
        for m in regex.finditer(cleaned):
            parsed.symbols.append(
                Symbol(name=m.group(1), kind=kind, line=_line_of(starts, m.start()),
                       end_line=_line_of(starts, m.start()), qualified_name=m.group(1),
                       signature=m.group(0).strip())
            )
    # Module-level UPPER_SNAKE_CASE consts; skip any already captured as
    # an arrow/function-expression symbol on the same line.
    seen = {(s.name, s.line) for s in parsed.symbols}
    for m in _CONST_RE.finditer(cleaned):
        line = _line_of(starts, m.start())
        if (m.group(1), line) in seen:
            continue
        parsed.symbols.append(
            Symbol(name=m.group(1), kind="constant", line=line,
                   end_line=line, qualified_name=m.group(1),
                   signature=m.group(0).strip())
        )
        seen.add((m.group(1), line))
    # Methods: indented `name(...) {` lines that are not top-level functions.
    seen = {(s.name, s.line) for s in parsed.symbols}
    for m in _METHOD_RE.finditer(cleaned):
        # The name lives in the match groups; for computed names the
        # string itself was blanked by the pre-pass, so read the name
        # back from the original source at the group's span (same
        # offsets: the pass preserves length). The signature is taken
        # from the original source for the same reason.
        name = m.group("plain")
        if name is None:
            for grp in ("csq", "cdq", "cbt", "cexpr"):
                if m.group(grp) is not None:
                    start, end = m.span(grp)
                    name = source[start:end]
                    break
        if name in _JS_KEYWORDS:
            continue
        line = _line_of(starts, m.start())
        if (name, line) in seen:
            continue
        parsed.symbols.append(
            Symbol(name=name, kind="method", line=line, end_line=line,
                   qualified_name=name, signature=source[m.start():m.end()].strip())
        )
        seen.add((name, line))
    # Class-field arrow functions: only inside a class body, so an
    # ordinary `x = () => {}` assignment in a function body is not
    # mistaken for a method.
    class_ranges = _class_body_ranges(cleaned, class_matches)
    for m in _FIELD_ARROW_RE.finditer(cleaned):
        if not any(start <= m.start() <= end for start, end in class_ranges):
            continue
        name = m.group(2)
        line = _line_of(starts, m.start())
        if (name, line) in seen:
            continue
        parsed.symbols.append(
            Symbol(name=name, kind="method", line=line, end_line=line,
                   qualified_name=name, signature=m.group(0).strip())
        )
        seen.add((name, line))

    # Calls: every `name(` that is not a definition keyword and not a
    # definition site. Caller attribution is best-effort: the nearest
    # preceding function/class symbol in the file. Interfaces, type
    # aliases, enums and constants are not call scopes, so they are
    # excluded from the attribution list (a module-level call after an
    # interface would otherwise be attributed to the interface).
    defs = sorted(
        (s for s in parsed.symbols if s.kind in ("function", "method", "class")),
        key=lambda s: s.line,
    )
    for m in _CALL_RE.finditer(cleaned):
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
