"""Edge-case tests for CodeAtlas.

Covers the inputs the happy-path suite never touches: malformed code,
empty repos, huge files, unicode, binary junk mixed into a repo, duplicate
symbol names, and repos with no git history.

Two rules govern this file:

* Every assertion was checked against the real implementation first
  (see the probes in the task report). Nothing here asserts behaviour
  the code does not actually have.
* Tests labelled KNOWN LIMITATION pin a real defect in the current
  implementation -- so a future fix fails loudly instead of silently
  changing behaviour. They assert what the code does today, not what
  it should do. (The JS/TS line-number and parser-coverage
  limitations used to be pinned this way; they were fixed on
  2026-11-11 and the tests now assert the correct behaviour.)
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codeatlas.archmap import build_architecture_map, diff_impact, git_changed_files  # noqa: E402
from codeatlas.context import build_context_pack  # noqa: E402
from codeatlas.graph import Graph, is_test_file, module_of  # noqa: E402
from codeatlas.indexer import Index, index_repo, init_repo  # noqa: E402
from codeatlas.parsers import language_for_path, parse_file  # noqa: E402
from codeatlas.search import search  # noqa: E402
from codeatlas.tools import (  # noqa: E402
    build_context_pack_tool,
    get_architecture_map,
    get_change_impact,
    get_file_outline,
    get_symbol,
    search_code,
)
from codeatlas.__main__ import main as cli_main  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
GIT = shutil.which("git")


class TempRepoCase(unittest.TestCase):
    """A fresh throwaway repo per test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="codeatlas-edge-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, content, encoding="utf-8"):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding=encoding) as fh:
            fh.write(content)
        return full

    def write_bytes(self, rel, data: bytes):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        return full

    def index(self):
        index, stats = index_repo(self.tmp)
        return index, stats, Graph.build(index)


# ---------------------------------------------------------------------------
# Malformed Python
# ---------------------------------------------------------------------------


class TestMalformedPython(unittest.TestCase):
    def test_unbalanced_bracket(self):
        parsed = parse_file("bad.py", "x = [1, 2\n")
        self.assertIsNotNone(parsed.parse_error)
        self.assertIn("never closed", parsed.parse_error)
        self.assertEqual(parsed.symbols, [])

    def test_broken_def(self):
        parsed = parse_file("bad.py", "def broken(:\n")
        self.assertIsNotNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])

    def test_incomplete_class(self):
        parsed = parse_file("bad.py", "class Foo:\n")
        self.assertIsNotNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])

    def test_unclosed_paren_in_return(self):
        parsed = parse_file("bad.py", "def f():\n  return (1 +\n")
        self.assertIsNotNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])

    def test_syntax_error_late_in_file_kills_earlier_defs(self):
        # ast.parse fails for the whole file: a valid def above the error
        # is NOT recovered. Callers must not assume partial symbols.
        parsed = parse_file("bad.py", "import os\ndef ok(): pass\nx = \n")
        self.assertIsNotNone(parsed.parse_error)
        self.assertEqual([s.name for s in parsed.symbols], [])

    def test_empty_source(self):
        parsed = parse_file("empty.py", "")
        self.assertIsNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])
        self.assertEqual(parsed.imports, [])

    def test_comment_only_source(self):
        parsed = parse_file("empty.py", "# just a comment\n# another\n")
        self.assertIsNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])

    def test_whitespace_only_source(self):
        parsed = parse_file("empty.py", "\n\n   \n")
        self.assertIsNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])


# ---------------------------------------------------------------------------
# Malformed JavaScript / TypeScript (regex parser: never raises)
# ---------------------------------------------------------------------------


class TestMalformedJavaScript(unittest.TestCase):
    def test_unbalanced_brace_still_extracts_function(self):
        # KNOWN LIMITATION: the JS parser is regex-based and never sets
        # parse_error, so broken JS is silently "parsed" anyway.
        parsed = parse_file("a.js", "function broken( {\n  return 1;\n")
        self.assertIsNone(parsed.parse_error)
        self.assertIn("broken", [s.name for s in parsed.symbols])

    def test_invalid_statement_does_not_hide_valid_function(self):
        parsed = parse_file("a.js", "const x = ;\nfunction ok() { return 1; }\n")
        self.assertIsNone(parsed.parse_error)
        self.assertIn("ok", [s.name for s in parsed.symbols])

    def test_unclosed_class_body(self):
        parsed = parse_file("a.js", "class Foo {\n  bar( { \n")
        self.assertIsNone(parsed.parse_error)
        self.assertIn("Foo", [s.name for s in parsed.symbols])

    def test_empty_and_comment_only(self):
        for source in ("", "// only a comment\n"):
            parsed = parse_file("a.js", source)
            self.assertIsNone(parsed.parse_error)
            self.assertEqual(parsed.symbols, [])


# ---------------------------------------------------------------------------
# Unicode
# ---------------------------------------------------------------------------


class TestUnicode(TempRepoCase):
    def test_python_unicode_identifiers(self):
        parsed = parse_file(
            "u.py",
            "# café comment — ünïcode\ndef café():\n    return 'héllo wörld ✓'\n",
        )
        self.assertIsNone(parsed.parse_error)
        self.assertIn("café", [s.name for s in parsed.symbols])

    def test_python_unicode_identifier_starting_non_ascii(self):
        parsed = parse_file("u.py", "def über():\n    return 1\n")
        self.assertIsNone(parsed.parse_error)
        self.assertIn("über", [s.name for s in parsed.symbols])

    def test_js_unicode_identifier_ascii_leading(self):
        parsed = parse_file("u.js", "function café() { return 'héllo'; }\n")
        self.assertIsNone(parsed.parse_error)
        self.assertIn("café", [s.name for s in parsed.symbols])

    def test_js_unicode_identifier_non_ascii_leading_is_missed(self):
        # KNOWN LIMITATION: the JS identifier regex starts [A-Za-z_$],
        # so a name starting with a non-ASCII letter is never extracted.
        parsed = parse_file("u.js", "function über() { return 1; }\n")
        self.assertIsNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])

    def test_unicode_strings_and_comments_do_not_break_js_parse(self):
        parsed = parse_file(
            "u.js",
            "function f() {\n  const s = 'café ☃';\n  // comment 日本語\n  return s;\n}\n",
        )
        self.assertIsNone(parsed.parse_error)
        self.assertIn("f", [s.name for s in parsed.symbols])

    def test_unicode_file_indexes_and_reads_back_intact(self):
        self.write(
            "u.py",
            "# café — ünïcode\ndef café():\n    return 'héllo wörld ✓'\n",
        )
        index, _, _ = self.index()
        self.assertEqual(len(index.files), 1)
        lines = index.read_lines("u.py", 1, 3)
        self.assertIn("café", lines[0])
        self.assertIn("✓", lines[2])

    def test_search_finds_unicode_symbol_by_exact_name(self):
        self.write("u.py", "def café():\n    return 'héllo'\n")
        index, _, graph = self.index()
        results = search(index, graph, "café")
        self.assertTrue(results)
        self.assertEqual(results[0].kind, "symbol")
        self.assertEqual(results[0].name, "café")
        self.assertEqual(results[0].path, "u.py")


# ---------------------------------------------------------------------------
# Empty repo / no git history
# ---------------------------------------------------------------------------


class TestEmptyRepo(TempRepoCase):
    def test_index_empty_dir(self):
        index, stats, _ = self.index()
        self.assertEqual(len(index.files), 0)
        self.assertEqual(stats.indexed, 0)
        self.assertEqual(stats.unchanged, 0)
        self.assertEqual(stats.removed, 0)
        self.assertEqual(stats.parse_errors, 0)
        self.assertEqual(index.total_symbols, 0)

    def test_search_context_map_diff_on_empty_index(self):
        index, _, graph = self.index()
        self.assertEqual(search(index, graph, "charge"), [])
        pack = build_context_pack(index, graph, "charge", budget_tokens=400)
        self.assertEqual(pack.snippets, [])
        self.assertEqual(pack.tokens, 0)
        amap = build_architecture_map(index, graph)
        self.assertEqual(amap.modules, [])
        self.assertEqual(amap.edges, [])
        self.assertEqual(amap.to_mermaid(), "flowchart LR\n")
        impact = diff_impact(index, graph, [])
        self.assertEqual(impact.changed_files, [])
        self.assertEqual(impact.affected_tests, [])

    def test_empty_and_whitespace_queries(self):
        self.write("a.py", "def charge():\n    return 1\n")
        index, _, graph = self.index()
        self.assertEqual(search(index, graph, ""), [])
        self.assertEqual(search(index, graph, "   "), [])
        self.assertEqual(search(index, graph, "zzzzqqq"), [])

    def test_cli_commands_fail_cleanly_without_an_index(self):
        for args in (["map", self.tmp], ["ask", "charge", self.tmp],
                     ["context", "charge", self.tmp], ["diff", self.tmp]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli_main(args)
            self.assertEqual(code, 1, args)

    def test_no_git_history(self):
        self.assertIsNone(git_changed_files(self.tmp))
        index, _, graph = self.index()
        impact = get_change_impact(index, graph)
        self.assertEqual(impact["changed_files"], [])
        self.assertIn("not a git repository", impact["note"])

    def test_init_then_index_empty_repo(self):
        path = init_repo(self.tmp)
        self.assertTrue(os.path.exists(path))
        index, stats, _ = self.index()
        self.assertEqual(len(index.files), 0)
        self.assertEqual(stats.indexed, 0)


class TestRepoWithoutGit(TempRepoCase):
    def test_indexing_works_without_git(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.write("b.py", "from a import f\n\ndef g():\n    return f()\n")
        index, stats, graph = self.index()
        self.assertEqual(stats.indexed, 2)
        self.assertIn("a.py", graph.import_edges.get("b.py", set()))
        self.assertIsNone(git_changed_files(self.tmp))

    def test_cli_diff_needs_explicit_files_without_git(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.index()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["diff", self.tmp])
        self.assertEqual(code, 1)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["diff", self.tmp, "--files", "a.py"])
        self.assertEqual(code, 0)
        self.assertIn("a.py", buf.getvalue())


@unittest.skipUnless(GIT, "git not installed")
class TestGitRepo(TempRepoCase):
    def _git(self, *args):
        import subprocess

        subprocess.run(
            ["git", "-C", self.tmp, *args],
            check=True, capture_output=True, text=True,
        )

    def _init(self):
        self.write("a.py", "def f():\n    return 1\n")
        self._git("init", "-q")
        self._git("add", ".")
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "init")

    def test_clean_tree_reports_no_changes(self):
        self._init()
        self.assertEqual(git_changed_files(self.tmp), [])

    def test_modified_and_untracked_files_are_listed(self):
        self._init()
        with open(os.path.join(self.tmp, "a.py"), "a") as fh:
            fh.write("# tweak\n")
        self.write("new.py", "def g():\n    return 2\n")
        self.assertEqual(git_changed_files(self.tmp), ["a.py", "new.py"])

    def test_indexing_a_git_repo_still_works(self):
        self._init()
        index, stats, _ = self.index()
        self.assertEqual(len(index.files), 1)
        self.assertEqual(stats.indexed, 1)


# ---------------------------------------------------------------------------
# Huge file
# ---------------------------------------------------------------------------


class TestHugeFile(TempRepoCase):
    N_FUNCS = 4000  # 12,000 lines

    def test_ten_thousand_plus_lines(self):
        source = "".join(
            f"def generated_func_{i}(x):\n    return x + {i}\n\n"
            for i in range(self.N_FUNCS)
        )
        self.assertGreater(source.count("\n"), 10000)
        self.write("big.py", source)
        index, stats, graph = self.index()
        self.assertEqual(len(index.files), 1)
        self.assertEqual(stats.indexed, 1)
        self.assertEqual(index.total_symbols, self.N_FUNCS)
        # Exact symbol search still finds a needle deep in the file.
        results = search(index, graph, "generated_func_3999")
        symbols = [r for r in results if r.kind == "symbol"]
        self.assertTrue(symbols)
        self.assertEqual(symbols[0].path, "big.py")
        self.assertEqual(symbols[0].name, "generated_func_3999")
        # Context pack stays inside its budget on a huge file.
        pack = build_context_pack(
            index, graph, "generated_func_3999", budget_tokens=400
        )
        self.assertLessEqual(pack.tokens, 400)
        self.assertGreater(len(pack.snippets), 0)
        # Second index: nothing re-parsed.
        _, stats2, _ = self.index()
        self.assertEqual(stats2.indexed, 0)
        self.assertEqual(stats2.unchanged, 1)


# ---------------------------------------------------------------------------
# Binary files, ignored paths, unsupported extensions
# ---------------------------------------------------------------------------


class TestBinaryAndIgnored(TempRepoCase):
    def test_binary_py_file_is_recorded_not_fatal(self):
        self.write_bytes("a.py", b"\x00\x01\x02\xff\xfe def notcode(:\n")
        self.write("good.py", "def ok():\n    return 1\n")
        index, stats, _ = self.index()
        self.assertEqual(stats.parse_errors, 1)
        self.assertIn("a.py", index.files)
        self.assertEqual(index.files["a.py"].parsed.symbols, [])
        self.assertIn("null bytes", index.files["a.py"].parsed.parse_error)
        self.assertIn("ok", [s.name for s in index.files["good.py"].parsed.symbols])

    def test_invalid_utf8_py_file(self):
        self.write_bytes("bad.py", b"\xff\xfe\xfd\n")
        self.write("good.py", "def ok():\n    return 1\n")
        index, stats, _ = self.index()
        self.assertEqual(stats.parse_errors, 1)
        self.assertIsNotNone(index.files["bad.py"].parsed.parse_error)
        self.assertIn("ok", [s.name for s in index.files["good.py"].parsed.symbols])

    def test_non_source_files_are_ignored(self):
        self.write_bytes("pic.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self.write_bytes("app.exe", b"MZ" + b"\x00" * 100)
        self.write("notes.md", "# hi\n\ndef not_code(): pass\n")
        self.write("data.json", '{"def": "not code"}')
        self.write("notes.txt", "def not_code(): pass\n")
        self.write("real.py", "def real():\n    return 1\n")
        index, stats, _ = self.index()
        self.assertEqual(sorted(index.files), ["real.py"])
        self.assertEqual(stats.indexed, 1)

    def test_ignored_directories_are_not_walked(self):
        self.write("node_modules/x/y.js", "function hidden() {}\n")
        self.write(".git/g.py", "def hidden2(): pass\n")
        self.write("__pycache__/m.py", "def hidden3(): pass\n")
        self.write(".venv/lib/v.py", "def hidden4(): pass\n")
        self.write("real.py", "def real():\n    return 1\n")
        index, _, _ = self.index()
        self.assertEqual(sorted(index.files), ["real.py"])

    def test_codeatlas_own_index_dir_is_not_indexed(self):
        self.write("real.py", "def real():\n    return 1\n")
        self.index()
        index, stats, _ = self.index()
        self.assertEqual(sorted(index.files), ["real.py"])
        self.assertEqual(stats.unchanged, 1)


class TestSyntaxErrorInRepo(TempRepoCase):
    def test_bad_file_does_not_take_down_the_repo(self):
        self.write("bad.py", "def broken(:\n")
        self.write("good.py", "def ok():\n    return 1\n")
        index, stats, graph = self.index()
        self.assertEqual(stats.parse_errors, 1)
        self.assertEqual(len(index.files), 2)
        self.assertEqual(index.files["bad.py"].parsed.symbols, [])
        self.assertIsNotNone(index.files["bad.py"].parsed.parse_error)
        self.assertEqual(
            search(index, graph, "ok")[0].path, "good.py"
        )
        outline = get_file_outline(index, "bad.py")
        self.assertIsNotNone(outline["parse_error"])

    def test_fixing_the_bad_file_is_picked_up_incrementally(self):
        self.write("bad.py", "def broken(:\n")
        self.write("good.py", "def ok():\n    return 1\n")
        _, stats, _ = self.index()
        self.assertEqual(stats.parse_errors, 1)
        self.write("bad.py", "def fixed():\n    return 2\n")
        index, stats, _ = self.index()
        self.assertEqual(stats.indexed, 1)
        self.assertEqual(stats.unchanged, 1)
        self.assertEqual(stats.parse_errors, 0)
        self.assertIn(
            "fixed", [s.name for s in index.files["bad.py"].parsed.symbols]
        )


# ---------------------------------------------------------------------------
# Duplicate symbol names
# ---------------------------------------------------------------------------


class TestDuplicateSymbols(TempRepoCase):
    def setUp(self):
        super().setUp()
        self.write("b.py", "def charge():\n    return 1\n")
        self.write("c.py", "def charge():\n    return 2\n")

    def test_find_symbol_returns_every_definition(self):
        index, _, _ = self.index()
        found = index.find_symbol("charge")
        self.assertEqual({p for p, _ in found}, {"b.py", "c.py"})
        self.assertEqual(len(found), 2)

    def test_get_symbol_tool_returns_every_definition(self):
        index, _, graph = self.index()
        syms = get_symbol(index, graph, "charge")
        self.assertEqual(len(syms), 2)
        self.assertEqual({s["path"] for s in syms}, {"b.py", "c.py"})

    def test_exact_search_returns_both_definitions(self):
        index, _, graph = self.index()
        results = search(index, graph, "charge")
        symbols = [r for r in results if r.kind == "symbol"]
        self.assertEqual({r.path for r in symbols}, {"b.py", "c.py"})
        self.assertTrue(all(r.score == 100.0 for r in symbols))

    def test_context_pack_covers_both_definitions(self):
        index, _, graph = self.index()
        pack = build_context_pack(index, graph, "charge", budget_tokens=4000)
        paths = {s.path for s in pack.snippets}
        self.assertIn("b.py", paths)
        self.assertIn("c.py", paths)

    def test_function_and_method_with_same_name(self):
        self.write(
            "d.py",
            "class Cart:\n    def charge(self):\n        return 3\n",
        )
        index, _, _ = self.index()
        found = index.find_symbol("charge")
        qualified = {s.qualified_name for _, s in found}
        self.assertIn("charge", qualified)
        self.assertIn("Cart.charge", qualified)


# ---------------------------------------------------------------------------
# Trivial files, CRLF, incremental behaviour, persistence
# ---------------------------------------------------------------------------


class TestTrivialFiles(TempRepoCase):
    def test_empty_comment_only_and_whitespace_files(self):
        self.write("empty.py", "")
        self.write("comment.js", "// nothing here\n")
        self.write("blank.ts", "\n\n   \n")
        index, stats, _ = self.index()
        self.assertEqual(len(index.files), 3)
        self.assertEqual(stats.parse_errors, 0)
        self.assertEqual(index.total_symbols, 0)

    def test_crlf_line_endings(self):
        parsed = parse_file("c.py", "def a():\r\n    return 1\r\ndef b():\r\n    return 2")
        self.assertEqual([(s.name, s.line) for s in parsed.symbols],
                         [("a", 1), ("b", 3)])

    def test_file_without_trailing_newline(self):
        parsed = parse_file("c.py", "def a():\n    return 1")
        self.assertEqual([(s.name, s.line) for s in parsed.symbols], [("a", 1)])


class TestIncrementalEdges(TempRepoCase):
    def test_mtime_only_touch_is_not_a_reparse(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.index()
        os.utime(os.path.join(self.tmp, "a.py"), (1700000000, 1700000000))
        _, stats, _ = self.index()
        self.assertEqual(stats.indexed, 0)
        self.assertEqual(stats.unchanged, 1)

    def test_deleted_file_is_removed(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.write("b.py", "def g():\n    return 2\n")
        self.index()
        os.remove(os.path.join(self.tmp, "a.py"))
        index, stats, _ = self.index()
        self.assertEqual(stats.removed, 1)
        self.assertNotIn("a.py", index.files)

    def test_rename_is_remove_plus_add(self):
        self.write("old.py", "def f():\n    return 1\n")
        self.index()
        os.rename(os.path.join(self.tmp, "old.py"),
                  os.path.join(self.tmp, "new.py"))
        index, stats, _ = self.index()
        self.assertEqual(stats.removed, 1)
        self.assertEqual(stats.indexed, 1)
        self.assertIn("new.py", index.files)

    def test_force_reparses_everything(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.write("b.py", "def g():\n    return 2\n")
        self.index()
        _, stats = index_repo(self.tmp, force=True)
        self.assertEqual(stats.indexed, 2)
        self.assertEqual(stats.unchanged, 0)


class TestIndexPersistence(TempRepoCase):
    def test_corrupt_index_json_loads_empty_and_recovers(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.index()
        with open(os.path.join(self.tmp, ".codeatlas", "index.json"), "w") as fh:
            fh.write("{not json")
        self.assertEqual(len(Index.load(self.tmp).files), 0)
        index, stats, _ = self.index()
        self.assertEqual(len(index.files), 1)
        self.assertEqual(stats.indexed, 1)

    def test_wrong_index_version_loads_empty(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.index()
        with open(os.path.join(self.tmp, ".codeatlas", "index.json"), "w") as fh:
            json.dump({"version": 999, "files": {}}, fh)
        self.assertEqual(len(Index.load(self.tmp).files), 0)

    def test_save_load_round_trip_preserves_symbols(self):
        self.write("a.py", "def f():\n    return 1\n")
        index, _, _ = self.index()
        loaded = Index.load(self.tmp)
        self.assertEqual(
            [s.name for s in loaded.files["a.py"].parsed.symbols],
            [s.name for s in index.files["a.py"].parsed.symbols],
        )
        self.assertEqual(loaded.total_symbols, index.total_symbols)


# ---------------------------------------------------------------------------
# Language detection, module boundaries, test detection
# ---------------------------------------------------------------------------


class TestLanguageDetection(unittest.TestCase):
    def test_supported_extensions(self):
        expected = {
            "a.py": "python", "a.ts": "typescript", "a.tsx": "typescript",
            "a.jsx": "javascript", "a.mjs": "javascript",
            "a.cjs": "javascript", "a.js": "javascript",
        }
        for path, lang in expected.items():
            self.assertEqual(language_for_path(path), lang, path)

    def test_unsupported_paths(self):
        for path in ("a.md", "a.txt", "a.json", "a.png", "a.exe",
                     "foo.py.bak", "a.PY", "Makefile", "a.pyc"):
            self.assertIsNone(language_for_path(path), path)

    def test_module_boundaries(self):
        self.assertEqual(module_of("billing.py"), "billing")
        self.assertEqual(module_of("tests/test_auth.py"), "tests")
        self.assertEqual(module_of("src/pkg/mod.py"), "pkg")
        self.assertEqual(module_of("src/mod.py"), "src")
        self.assertEqual(module_of("a/b.py"), "a")
        self.assertEqual(module_of("lib/util/x.py"), "util")

    def test_test_file_detection(self):
        for path in ("test_foo.py", "foo_test.py", "foo.test.js",
                     "tests/x.py", "test/x.py"):
            self.assertTrue(is_test_file(path), path)
        for path in ("billing.py", "contest.py", "mytest.py", "latest.py"):
            self.assertFalse(is_test_file(path), path)

    def test_name_based_test_detection_catches_utils(self):
        # KNOWN QUIRK: detection is name-based, so a helper called
        # test_utils.py counts as a test file even though it is not one.
        self.assertTrue(is_test_file("src/test_utils.py"))


class TestRelativeImports(TempRepoCase):
    def test_relative_and_absolute_imports_resolve_to_same_file(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/a.py", "def helper():\n    return 1\n")
        self.write(
            "pkg/b.py",
            "from .a import helper\n"
            "from pkg.a import helper as h2\n"
            "\ndef use():\n    return helper()\n",
        )
        _, _, graph = self.index()
        self.assertEqual(graph.import_edges.get("pkg/b.py"), {"pkg/a.py"})
        callers = graph.callers_of("helper")
        self.assertTrue(any(p == "pkg/b.py" and c == "use"
                            for p, c, _ in callers))


# ---------------------------------------------------------------------------
# TypeScript / JS parser gaps (known limitations)
# ---------------------------------------------------------------------------


class TestTypeScriptGaps(unittest.TestCase):
    def test_return_annotated_arrow_function_is_found(self):
        # Fixed 2026-11-11: the arrow regex allows a return-type
        # annotation between the parameter list and `=>`.
        parsed = parse_file(
            "u.ts", "export const greet = (n: string): string => `hi ${n}`;\n"
        )
        self.assertIn("greet", [s.name for s in parsed.symbols])
        # The same arrow without the annotation is still found.
        parsed = parse_file("u.ts", "export const greet = (n: string) => `hi ${n}`;\n")
        self.assertIn("greet", [s.name for s in parsed.symbols])

    def test_single_param_arrow_without_parens_is_found(self):
        parsed = parse_file("u.ts", "const double = x => x * 2;\n")
        self.assertIn("double", [s.name for s in parsed.symbols])

    def test_function_expression_const_is_found(self):
        parsed = parse_file(
            "u.ts", "export const handler = async function (req) { return req; };\n"
        )
        self.assertIn("handler", [s.name for s in parsed.symbols])

    def test_return_annotated_methods_and_getters_are_found(self):
        # Fixed 2026-11-11: the method regex allows a return-type
        # annotation between `)` and `{`, and getters (no parens).
        parsed = parse_file(
            "s.ts",
            "export class Cart {\n"
            "  constructor(private items: string[]) {}\n"
            "  async add(item: string): Promise<void> { this.items.push(item); }\n"
            "  static create(): Cart { return new Cart([]); }\n"
            "  get total(): number { return 0; }\n"
            "}\n",
        )
        names = {s.name for s in parsed.symbols}
        self.assertIn("Cart", names)
        self.assertIn("constructor", names)
        self.assertIn("add", names)
        self.assertIn("create", names)
        self.assertIn("total", names)
        kinds = {(s.name, s.kind) for s in parsed.symbols}
        self.assertIn(("add", "method"), kinds)
        self.assertIn(("total", "method"), kinds)

    def test_plain_methods_without_annotations_are_found(self):
        parsed = parse_file(
            "s.ts",
            "export class Cart {\n"
            "  add(item: string) { return item; }\n"
            "  total() { return 0; }\n"
            "}\n",
        )
        names = {(s.name, s.kind) for s in parsed.symbols}
        self.assertIn(("add", "method"), names)
        self.assertIn(("total", "method"), names)

    def test_typescript_interface_and_type_alias_are_symbols(self):
        # Fixed 2026-11-11: interfaces and type aliases are extracted
        # (kinds "interface" and "type"), as are enums.
        parsed = parse_file(
            "d.ts",
            "export interface Product {\n  sku: string;\n  price: number;\n}\n"
            "export type ProductId = string;\n"
            "export enum Status { Active, Archived }\n"
            "export function getProduct(): Product { return null; }\n",
        )
        kinds = {(s.name, s.kind) for s in parsed.symbols}
        self.assertIn(("Product", "interface"), kinds)
        self.assertIn(("ProductId", "type"), kinds)
        self.assertIn(("Status", "enum"), kinds)
        self.assertIn(("getProduct", "function"), kinds)

    def test_js_constants_are_symbols(self):
        # Fixed 2026-11-11: module-level UPPER_SNAKE_CASE consts are
        # extracted as "constant" symbols, mirroring the Python rule.
        # Lowercase consts are ordinary values, not symbols.
        parsed = parse_file(
            "b.js",
            "const TAX_RATE = 0.2;\n"
            "const lowercase = 1;\n"
            "export const MAX_RETRIES = 3;\n"
            "function f() {}\n",
        )
        kinds = {(s.name, s.kind) for s in parsed.symbols}
        self.assertIn(("TAX_RATE", "constant"), kinds)
        self.assertIn(("MAX_RETRIES", "constant"), kinds)
        self.assertNotIn(("lowercase", "constant"), kinds)
        self.assertIn(("f", "function"), kinds)

    def test_object_literal_braces_are_not_methods(self):
        # A `name: {` object-literal line must not be read as a method
        # (regression guard for the getter/annotation support).
        parsed = parse_file(
            "o.js",
            "const config = {\n"
            "  options: {\n"
            "    retries: 3\n"
            "  }\n"
            "};\n",
        )
        self.assertEqual(
            [s.name for s in parsed.symbols if s.kind == "method"], []
        )

    def test_tsx_arrow_component_is_found(self):
        parsed = parse_file(
            "c.tsx",
            "export const PriceTag = (props: { price: number }) => {\n"
            "  return <span>{props.price}</span>;\n"
            "};\n",
        )
        self.assertIn("PriceTag", [s.name for s in parsed.symbols])


# ---------------------------------------------------------------------------
# JavaScript line numbers (known limitation -- read the docstring)
# ---------------------------------------------------------------------------


class TestJavaScriptLineNumbers(unittest.TestCase):
    """JS/TS definition lines are exact.

    Fixed 2026-11-11: every JS/TS regex used to start with ``^\\s*``
    and ``\\s`` matches newlines, so a definition preceded by blank
    line(s) was reported at the first preceding blank line. The
    definition-site skip in the call extractor compared against that
    wrong line, so the definition also leaked as a self-call, and
    context packs read a blank line as the symbol snippet. The
    regexes now use ``[ \\t]`` at line starts, so lines are exact --
    these tests pin the correct lines.
    """

    def test_def_after_one_blank_line_reports_its_real_line(self):
        parsed = parse_file(
            "a.js", "const a = 1;\n\nfunction target() {\n  return 1;\n}\n"
        )
        self.assertEqual([(s.name, s.line) for s in parsed.symbols],
                         [("target", 3)])

    def test_def_after_two_blank_lines_reports_its_real_line(self):
        parsed = parse_file(
            "a.js", "const a = 1;\n\n\nfunction target() {\n  return 1;\n}\n"
        )
        self.assertEqual([(s.name, s.line) for s in parsed.symbols],
                         [("target", 4)])

    def test_def_at_file_start_is_exact(self):
        parsed = parse_file("a.js", "function first() {}\n")
        self.assertEqual([(s.name, s.line) for s in parsed.symbols],
                         [("first", 1)])

    def test_def_after_code_line_is_exact(self):
        parsed = parse_file("a.js", "const a = 1;\nfunction target() {}\n")
        self.assertEqual([(s.name, s.line) for s in parsed.symbols],
                         [("target", 2)])

    def test_definition_site_is_not_a_self_call_after_blank_line(self):
        parsed = parse_file(
            "a.js", "const a = 1;\n\nfunction target() {\n  return 1;\n}\n"
        )
        self.assertEqual(parsed.calls, [])

    def test_no_self_call_without_preceding_blank_line(self):
        parsed = parse_file("a.js", "function target() {\n  return 1;\n}\n")
        self.assertEqual(parsed.calls, [])

    def test_import_after_blank_line_reports_its_real_line(self):
        parsed = parse_file("a.js", "const a = 1;\n\nimport { x } from './m';\n")
        self.assertEqual([(i.module, i.line) for i in parsed.imports],
                         [("./m", 3)])

    def test_method_after_blank_line_inside_class_reports_its_real_line(self):
        parsed = parse_file(
            "a.js", "class Foo {\n\n  bar() {\n    return 1;\n  }\n}\n"
        )
        self.assertEqual([(s.name, s.line) for s in parsed.symbols],
                         [("Foo", 1), ("bar", 3)])

    def test_sample_js_search_points_at_the_definition_line(self):
        with open(os.path.join(FIXTURES, "sample-js", "billing.js")) as fh:
            source = fh.read()
        # The true def line is 10; the old parser reported 9 (blank).
        parsed = parse_file("billing.js", source)
        charge = [s for s in parsed.symbols if s.name == "charge"][0]
        self.assertEqual(charge.line, 10)
        self.assertEqual(
            source.splitlines()[charge.line - 1],
            "function charge(auth, username, password, amount) {",
        )


class TestJavaScriptContextPackEmptySnippet(TempRepoCase):
    def test_js_symbol_snippets_carry_real_code(self):
        # Fixed 2026-11-11 (consequence of the line-number bug): the
        # symbol snippet for a JS function used to be read from the
        # (blank) reported line, so packs contained empty snippets.
        # Every snippet now carries real code.
        shutil.copytree(os.path.join(FIXTURES, "sample-js"),
                        os.path.join(self.tmp, "sample-js"))
        repo = os.path.join(self.tmp, "sample-js")
        index, _ = index_repo(repo)
        graph = Graph.build(index)
        pack = build_context_pack(index, graph, "charge a customer",
                                  budget_tokens=400)
        self.assertLessEqual(pack.tokens, 400)
        self.assertTrue(all(s.text.strip() for s in pack.snippets),
                        "no snippet may be empty text")
        self.assertTrue(any(s.path == "billing.js" and s.start_line == 10
                            and "function charge" in s.text
                            for s in pack.snippets))


# ---------------------------------------------------------------------------
# Search / context-pack / tools / CLI edges
# ---------------------------------------------------------------------------


class TestSearchAndContextEdges(TempRepoCase):
    def test_zero_budget_pack_is_empty(self):
        self.write("a.py", "def ok():\n    return 1\n")
        index, _, graph = self.index()
        pack = build_context_pack(index, graph, "ok", budget_tokens=0)
        self.assertEqual(pack.snippets, [])
        self.assertEqual(pack.tokens, 0)

    def test_stopwords_only_task_is_empty(self):
        self.write("a.py", "def ok():\n    return 1\n")
        index, _, graph = self.index()
        pack = build_context_pack(index, graph, "the and of", budget_tokens=400)
        self.assertEqual(pack.snippets, [])

    def test_empty_task_pack_is_empty(self):
        self.write("a.py", "def ok():\n    return 1\n")
        index, _, graph = self.index()
        pack = build_context_pack(index, graph, "", budget_tokens=400)
        self.assertEqual(pack.snippets, [])

    def test_pack_snippet_line_ranges_are_real_for_python(self):
        self.write("a.py", "def ok():\n    return 1\n\ndef other():\n    return 2\n")
        index, _, graph = self.index()
        pack = build_context_pack(index, graph, "ok", budget_tokens=4000)
        for snip in pack.snippets:
            lines = index.read_lines(snip.path, snip.start_line, snip.end_line)
            self.assertEqual(len(lines), snip.end_line - snip.start_line + 1)

    def test_cli_ask_no_match_and_context_json(self):
        self.write("a.py", "def ok():\n    return 1\n")
        self.index()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["ask", "zzzzqqq", self.tmp])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue(), "No matches found.\n")

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["context", "ok", self.tmp, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["task"], "ok")
        self.assertLessEqual(payload["tokens"], 4000)

    def test_cli_diff_unknown_file_reports_none(self):
        self.write("a.py", "def ok():\n    return 1\n")
        self.index()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["diff", self.tmp, "--files", "nope.py"])
        self.assertEqual(code, 0)
        self.assertIn("(none)", buf.getvalue())

    def test_tool_edges(self):
        self.write("a.py", "def ok():\n    return 1\n")
        index, _, graph = self.index()
        self.assertEqual(get_symbol(index, graph, "nope"), [])
        self.assertIsNone(get_file_outline(index, "nope.py"))
        self.assertEqual(len(search_code(index, graph, "ok", limit=1)), 1)
        pack = build_context_pack_tool(index, graph, "ok", 200)
        self.assertLessEqual(pack["tokens"], 200)
        amap = get_architecture_map(index, graph, fmt="dot")
        self.assertIn("digraph codeatlas", amap)
        # Single root-level file a.py is its own module "a".
        self.assertIn("a", get_architecture_map(index, graph, fmt="mermaid"))

    def test_empty_architecture_map_renders(self):
        index, _, graph = self.index()
        amap = build_architecture_map(index, graph)
        self.assertEqual(amap.to_mermaid(), "flowchart LR\n")
        self.assertIn("digraph codeatlas", amap.to_dot())
        self.assertEqual(json.loads(amap.to_json()),
                         {"modules": [], "edges": []})


if __name__ == "__main__":
    unittest.main()
