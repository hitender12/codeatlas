"""Regression tests for the CodeAtlas round-2 fix round (2026-11-11).

One class per fixed finding from the independent re-audit:

* Finding 1 -- phantom symbols/calls from template literals, block
  comments, line comments and string literals: the parser now runs
  against a comment/string-stripped pre-pass that preserves line
  numbers (see parsers._strip_js_comments_and_strings).
* Finding 2 -- `export default function` produced zero symbols.
* Finding 3 -- TypeScript generics silently missed.
* Finding 4 -- class-field arrow functions missed.
* Finding 5 -- private `#method()` and computed `['name']()` missed.
* Finding 6 -- nested parentheses in arrow/method params missed.
* Finding 7 -- minified single-line JS only yielded the first def.

Documented limits pinned here (not bugs): parameter lists nested
more than three levels deep, and methods inside a minified
single-line class body, are still missed -- see docs/architecture.md.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codeatlas.parsers import _strip_js_comments_and_strings, parse_file  # noqa: E402


def names(parsed):
    return {(s.name, s.kind) for s in parsed.symbols}


def by_name(parsed):
    return {s.name: s for s in parsed.symbols}


# ---------------------------------------------------------------------------
# Finding 1: comment / string / template pre-pass
# ---------------------------------------------------------------------------


class TestCommentStringPrepass(unittest.TestCase):
    def test_template_literal_phantom_not_indexed(self):
        parsed = parse_file(
            "a.ts",
            "const greeting = `hello\nfunction phantomHelper() {\n  return 1;\n}\n`;\n"
            "function realOne() {\n  return greeting;\n}\n",
        )
        self.assertNotIn("phantomHelper", by_name(parsed))
        self.assertIn("realOne", by_name(parsed))

    def test_block_comment_phantom_not_indexed(self):
        parsed = parse_file(
            "a.ts",
            "/*\nfunction commentedOut() {}\nconst hidden = () => {};\n*/\n"
            "function realTwo() {}\n",
        )
        found = by_name(parsed)
        self.assertNotIn("commentedOut", found)
        self.assertNotIn("hidden", found)
        self.assertIn("realTwo", found)

    def test_calls_inside_template_literal_and_line_comment_not_recorded(self):
        parsed = parse_file(
            "a.ts",
            "function realTwo() {}\n"
            "// realTwo();\n"
            "const msg = `call ${realTwo()} now`;\n",
        )
        self.assertEqual(
            [c.callee for c in parsed.calls], [],
            "no call may come from a comment or a template literal",
        )

    def test_string_literal_phantom_not_indexed(self):
        parsed = parse_file(
            "b.js",
            "function outer() {\n"
            "  const s = \"function stringPhantom() {}\";\n"
            "  const t = 'callMe()';\n"
            "  return s + t;\n"
            "}\n",
        )
        found = by_name(parsed)
        self.assertNotIn("stringPhantom", found)
        self.assertNotIn("callMe", {c.callee for c in parsed.calls})
        self.assertEqual(found["outer"].line, 1)

    def test_imports_survive_the_prepass_with_exact_lines(self):
        parsed = parse_file(
            "c.js",
            "import { x } from './mod';\n"
            "const u = require('./other');\n"
            "function afterImport() {}\n",
        )
        self.assertEqual(
            {(i.module, i.line) for i in parsed.imports},
            {("./mod", 1), ("./other", 2)},
        )

    def test_line_numbers_preserved_across_multiline_template_and_comment(self):
        parsed = parse_file(
            "d.ts",
            "const t = `one\ntwo\nthree\nfour\nfive`;\n"
            "/* a\nb\nc */\n"
            "function afterAllThat() {}\n",
        )
        self.assertEqual(by_name(parsed)["afterAllThat"].line, 9)

    def test_nested_template_literal_in_interpolation(self):
        parsed = parse_file(
            "e.ts",
            "const t = `outer ${`inner ${x}`} end`;\n"
            "function afterNested() {}\n",
        )
        self.assertEqual(
            [(s.name, s.line) for s in parsed.symbols], [("afterNested", 2)]
        )
        self.assertEqual(parsed.calls, [])

    def test_regex_literal_with_code_like_text_is_not_parsed(self):
        parsed = parse_file(
            "f.js",
            "const re = /function fake() {} \\/\\/ not a comment/;\n"
            "function realAfterRegex() {}\n",
        )
        found = by_name(parsed)
        self.assertNotIn("fake", found)
        self.assertEqual(found["realAfterRegex"].line, 2)

    def test_division_slash_is_not_a_regex_or_comment(self):
        parsed = parse_file(
            "g.js", "const q = a / b;\nfunction afterDivision() {}\n"
        )
        self.assertEqual(by_name(parsed)["afterDivision"].line, 2)

    def test_escaped_quote_does_not_end_string_early(self):
        parsed = parse_file(
            "h.js", "const s = 'it\\'s fine';\nfunction afterEscaped() {}\n"
        )
        self.assertEqual(by_name(parsed)["afterEscaped"].line, 2)

    def test_prepass_preserves_length_and_newlines(self):
        src = "function a() {}\n/* multi\nline */\nconst s = `x ${y}`;\n"
        cleaned = _strip_js_comments_and_strings(src)
        self.assertEqual(len(cleaned), len(src))
        self.assertEqual(cleaned.count("\n"), src.count("\n"))


# ---------------------------------------------------------------------------
# Finding 2: export default function
# ---------------------------------------------------------------------------


class TestExportDefaultFunction(unittest.TestCase):
    def test_export_default_function(self):
        parsed = parse_file("a.ts", "export default function serve() {}\n")
        self.assertIn(("serve", "function"), names(parsed))

    def test_export_default_async_function(self):
        parsed = parse_file("a.ts", "export default async function boot() {}\n")
        self.assertIn(("boot", "function"), names(parsed))

    def test_export_default_class_still_works(self):
        parsed = parse_file("a.ts", "export default class Server {}\n")
        self.assertIn(("Server", "class"), names(parsed))


# ---------------------------------------------------------------------------
# Finding 3: TypeScript generics
# ---------------------------------------------------------------------------


class TestGenerics(unittest.TestCase):
    def test_generic_function(self):
        parsed = parse_file("a.ts", "function id<T>(x: T): T { return x; }\n")
        self.assertIn(("id", "function"), names(parsed))

    def test_generic_async_function(self):
        parsed = parse_file(
            "a.ts", "async function load<T>(url: string): Promise<T> { return null as any; }\n"
        )
        self.assertIn(("load", "function"), names(parsed))

    def test_generic_arrow(self):
        parsed = parse_file("a.ts", "const wrap = <T>(x: T) => x;\n")
        self.assertIn(("wrap", "function"), names(parsed))

    def test_generic_function_expression(self):
        parsed = parse_file("a.ts", "const f = function<T>(x: T): T { return x; };\n")
        self.assertIn(("f", "function"), names(parsed))

    def test_generic_method(self):
        parsed = parse_file(
            "a.ts", "class C {\n  get<T>(key: string): T | undefined { return undefined; }\n}\n"
        )
        self.assertIn(("get", "method"), names(parsed))


# ---------------------------------------------------------------------------
# Finding 4: class-field arrow functions
# ---------------------------------------------------------------------------


class TestClassFieldArrows(unittest.TestCase):
    def test_field_arrows_are_methods(self):
        parsed = parse_file(
            "a.ts",
            "class Widget {\n"
            "  handler = (e: Event): void => {}\n"
            "  onClick = () => {}\n"
            "  static make = () => new Widget();\n"
            "  render() {}\n"
            "}\n",
        )
        found = names(parsed)
        self.assertIn(("handler", "method"), found)
        self.assertIn(("onClick", "method"), found)
        self.assertIn(("make", "method"), found)
        self.assertIn(("render", "method"), found)
        self.assertIn(("Widget", "class"), found)

    def test_arrow_assignment_inside_function_body_is_not_a_method(self):
        parsed = parse_file(
            "b.ts", "function outer() {\n  x = () => {}\n  return x;\n}\n"
        )
        self.assertEqual(names(parsed), {("outer", "function")})


# ---------------------------------------------------------------------------
# Finding 5: private and computed methods
# ---------------------------------------------------------------------------


class TestPrivateAndComputedMethods(unittest.TestCase):
    def test_private_and_computed_methods(self):
        parsed = parse_file(
            "a.ts",
            "class Store {\n"
            "  #load() {}\n"
            "  ['save']() {}\n"
            "  [\"reset\"]() {}\n"
            "  [Symbol.iterator]() {}\n"
            "  normal() {}\n"
            "}\n",
        )
        found = names(parsed)
        self.assertIn(("#load", "method"), found)
        self.assertIn(("save", "method"), found)
        self.assertIn(("reset", "method"), found)
        self.assertIn(("Symbol.iterator", "method"), found)
        self.assertIn(("normal", "method"), found)

    def test_computed_name_signature_uses_the_real_name(self):
        parsed = parse_file("a.ts", "class Store {\n  ['save']() {}\n}\n")
        self.assertEqual(by_name(parsed)["save"].signature, "['save']() {")


# ---------------------------------------------------------------------------
# Finding 6: nested parentheses in params
# ---------------------------------------------------------------------------


class TestNestedParens(unittest.TestCase):
    def test_arrow_with_nested_paren_default(self):
        parsed = parse_file("a.ts", "const arrow = (a = g(1, 2)) => a;\n")
        self.assertIn(("arrow", "function"), names(parsed))

    def test_method_with_nested_paren_default(self):
        parsed = parse_file(
            "a.ts", "class C {\n  method(a = bar(1, 2)) {}\n}\n"
        )
        self.assertIn(("method", "method"), names(parsed))

    def test_three_levels_of_nesting(self):
        parsed = parse_file("a.ts", "const a3 = (x = f(g(1))) => x;\n")
        self.assertIn(("a3", "function"), names(parsed))


# ---------------------------------------------------------------------------
# Finding 7: minified single-line JS
# ---------------------------------------------------------------------------


class TestMinifiedJs(unittest.TestCase):
    def test_all_defs_on_one_line_found(self):
        parsed = parse_file(
            "a.js",
            "function a(){} function b(){} const c=()=>{}; class D{} function e(){}\n",
        )
        self.assertEqual(
            {s.name for s in parsed.symbols}, {"a", "b", "c", "D", "e"}
        )
        self.assertTrue(all(s.line == 1 for s in parsed.symbols))

    def test_minified_interface_and_enum(self):
        parsed = parse_file(
            "b.ts", "interface I { x: number } enum E { A } type T = string;\n"
        )
        found = names(parsed)
        self.assertIn(("I", "interface"), found)
        self.assertIn(("E", "enum"), found)
        self.assertIn(("T", "type"), found)


if __name__ == "__main__":
    unittest.main()
