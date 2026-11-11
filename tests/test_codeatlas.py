"""Tests for CodeAtlas.

All tests index copies of the fixture repositories in a temp directory,
so they never touch the real repo and never need network access.
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

from codeatlas import __version__  # noqa: E402
from codeatlas.archmap import (  # noqa: E402
    build_architecture_map,
    diff_impact,
)
from codeatlas.context import build_context_pack  # noqa: E402
from codeatlas.graph import Graph, is_test_file, module_of  # noqa: E402
from codeatlas.indexer import Index, index_repo, init_repo  # noqa: E402
from codeatlas.parsers import parse_file  # noqa: E402
from codeatlas.search import search  # noqa: E402
from codeatlas.tools import (  # noqa: E402
    build_context_pack_tool,
    get_architecture_map,
    get_file_outline,
    get_symbol,
    search_code,
)
from codeatlas.__main__ import main as cli_main  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="codeatlas-test-")
        self.py_repo = os.path.join(self.tmp, "sample-py")
        self.js_repo = os.path.join(self.tmp, "sample-js")
        shutil.copytree(os.path.join(FIXTURES, "sample-py"), self.py_repo)
        shutil.copytree(os.path.join(FIXTURES, "sample-js"), self.js_repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index_py(self):
        index, _ = index_repo(self.py_repo)
        return index, Graph.build(index)

    def index_js(self):
        index, _ = index_repo(self.js_repo)
        return index, Graph.build(index)


class TestPythonParser(unittest.TestCase):
    def test_extracts_functions_classes_methods_imports_calls(self):
        with open(os.path.join(FIXTURES, "sample-py", "auth.py")) as fh:
            source = fh.read()
        parsed = parse_file("auth.py", source)
        names = {(s.name, s.kind) for s in parsed.symbols}
        self.assertIn(("hash_password", "function"), names)
        self.assertIn(("Authenticator", "class"), names)
        self.assertIn(("authenticate", "method"), names)
        self.assertIn(("SECRET", "constant"), names)
        self.assertTrue(any(i.module == "hashlib" for i in parsed.imports))
        callees = {c.callee for c in parsed.calls}
        self.assertIn("verify_token", callees)

    def test_syntax_error_is_recorded_not_raised(self):
        parsed = parse_file("bad.py", "def broken(:\n")
        self.assertIsNotNone(parsed.parse_error)
        self.assertEqual(parsed.symbols, [])


class TestJavaScriptParser(unittest.TestCase):
    def test_extracts_functions_class_imports_calls(self):
        with open(os.path.join(FIXTURES, "sample-js", "billing.js")) as fh:
            source = fh.read()
        parsed = parse_file("billing.js", source)
        names = {(s.name, s.kind) for s in parsed.symbols}
        self.assertIn(("applyDiscount", "function"), names)
        self.assertIn(("charge", "function"), names)
        self.assertTrue(any(i.module == "./auth" for i in parsed.imports))
        callees = {c.callee for c in parsed.calls}
        self.assertTrue(any("authenticate" in c for c in callees))

    def test_class_and_methods(self):
        with open(os.path.join(FIXTURES, "sample-js", "auth.js")) as fh:
            source = fh.read()
        parsed = parse_file("auth.js", source)
        names = {(s.name, s.kind) for s in parsed.symbols}
        self.assertIn(("Authenticator", "class"), names)
        self.assertIn(("hashPassword", "function"), names)


class TestIndexer(FixtureCase):
    def test_first_index_parses_everything(self):
        index, stats = index_repo(self.py_repo)
        self.assertEqual(stats.indexed, 5)
        self.assertEqual(len(index.files), 5)
        self.assertGreater(index.total_symbols, 10)

    def test_incremental_reindex_only_touches_changed_files(self):
        index, stats = index_repo(self.py_repo)
        self.assertEqual(stats.indexed, 5)
        self.assertEqual(stats.unchanged, 0)
        # Second run: nothing changed, nothing re-parsed.
        index, stats = index_repo(self.py_repo)
        self.assertEqual(stats.indexed, 0)
        self.assertEqual(stats.unchanged, 5)
        # Touch one file (content change): only that file is re-parsed.
        with open(os.path.join(self.py_repo, "billing.py"), "a") as fh:
            fh.write("\n# a comment\n")
        index, stats = index_repo(self.py_repo)
        self.assertEqual(stats.indexed, 1)
        self.assertEqual(stats.unchanged, 4)
        # Delete a file: it is removed from the index.
        os.remove(os.path.join(self.py_repo, "api.py"))
        index, stats = index_repo(self.py_repo)
        self.assertEqual(stats.removed, 1)
        self.assertNotIn("api.py", index.files)

    def test_init_creates_config(self):
        path = init_repo(self.py_repo)
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            config = json.load(fh)
        self.assertIn("local-only", config["privacy"])


class TestGraph(FixtureCase):
    def test_import_edges_resolve_between_files(self):
        index, graph = self.index_py()
        self.assertIn("auth.py", graph.import_edges.get("billing.py", set()))
        self.assertIn("billing.py", graph.import_edges.get("api.py", set()))
        self.assertIn("api.py", graph.dependents.get("billing.py", set()))

    def test_test_links(self):
        index, graph = self.index_py()
        self.assertIn("auth.py", graph.test_links.get("tests/test_auth.py", set()))
        self.assertIn("billing.py", graph.test_links.get("tests/test_billing.py", set()))

    def test_js_relative_imports(self):
        index, graph = self.index_js()
        self.assertIn("auth.js", graph.import_edges.get("billing.js", set()))
        self.assertIn("billing.js", graph.import_edges.get("index.js", set()))

    def test_module_boundaries(self):
        self.assertEqual(module_of("billing.py"), "billing")
        self.assertEqual(module_of("tests/test_auth.py"), "tests")
        self.assertTrue(is_test_file("tests/test_auth.py"))
        self.assertFalse(is_test_file("billing.py"))


class TestSearch(FixtureCase):
    def test_symbol_search_finds_definition_with_line_numbers(self):
        index, graph = self.index_py()
        results = search(index, graph, "charge", limit=5)
        symbols = [r for r in results if r.kind == "symbol"]
        self.assertTrue(symbols, "expected a symbol result for 'charge'")
        top = symbols[0]
        self.assertEqual(top.path, "billing.py")
        self.assertGreater(top.line, 0)
        self.assertIn("charge", top.name)
        # The reported line is the real definition line.
        lines = index.read_lines("billing.py", top.line, top.line)
        self.assertIn("def charge", lines[0])

    def test_search_results_explain_themselves(self):
        index, graph = self.index_py()
        results = search(index, graph, "authenticate")
        self.assertTrue(results)
        for r in results:
            self.assertTrue(r.reasons, "every result must carry reasons")

    def test_natural_language_question_finds_the_right_code(self):
        # The blueprint's canonical example question.
        index, graph = self.index_py()
        results = search(index, graph, "Where is authentication handled?")
        self.assertTrue(results, "the canonical question must match something")
        paths = {r.path for r in results}
        self.assertIn("auth.py", paths)

    def test_callers_of_symbol(self):
        index, graph = self.index_py()
        callers = graph.callers_of("authenticate")
        self.assertTrue(any(path == "billing.py" for path, _, _ in callers))


class TestContextPack(FixtureCase):
    def test_pack_respects_budget(self):
        index, graph = self.index_py()
        pack = build_context_pack(
            index, graph, "charge a customer after authentication", budget_tokens=400
        )
        self.assertLessEqual(pack.tokens, 400)
        self.assertGreater(len(pack.snippets), 0)
        # Stemming must connect "authentication" (task) to "authenticate".
        paths = {s.path for s in pack.snippets}
        self.assertIn("billing.py", paths)  # charge
        self.assertIn("auth.py", paths)  # authenticate
        for snip in pack.snippets:
            self.assertTrue(snip.why)
            self.assertTrue(snip.path.endswith(".py"))
        # A small budget still holds: the top snippet alone must fit.
        small = build_context_pack(
            index, graph, "charge a customer after authentication", budget_tokens=100
        )
        self.assertLessEqual(small.tokens, 100)
        self.assertGreater(len(small.snippets), 0)

    def test_tiny_budget_still_enforced(self):
        index, graph = self.index_py()
        pack = build_context_pack(
            index, graph, "charge a customer", budget_tokens=10
        )
        self.assertLessEqual(pack.tokens, 10)

    def test_pack_snippets_have_real_line_ranges(self):
        index, graph = self.index_py()
        pack = build_context_pack(
            index, graph, "authenticate a user", budget_tokens=4000
        )
        for snip in pack.snippets:
            self.assertLessEqual(snip.start_line, snip.end_line)
            lines = index.read_lines(snip.path, snip.start_line, snip.end_line)
            self.assertEqual(len(lines), snip.end_line - snip.start_line + 1)


class TestArchitectureMap(FixtureCase):
    def test_map_shows_real_import_edge(self):
        index, graph = self.index_py()
        amap = build_architecture_map(index, graph)
        edges = {(e.source, e.target) for e in amap.edges}
        self.assertIn(("billing", "auth"), edges)
        self.assertIn(("api", "billing"), edges)

    def test_mermaid_and_dot_render(self):
        index, graph = self.index_py()
        amap = build_architecture_map(index, graph)
        self.assertIn("billing --> auth", amap.to_mermaid())
        self.assertIn('"billing" -> "auth"', amap.to_dot())
        data = json.loads(amap.to_json())
        self.assertIn("modules", data)
        self.assertIn("edges", data)


class TestDiffImpact(FixtureCase):
    def test_diff_impact_lists_the_affected_test(self):
        index, graph = self.index_py()
        impact = diff_impact(index, graph, ["billing.py"])
        self.assertIn("billing.py", impact.changed_files)
        self.assertIn("api.py", impact.affected_files)  # api imports billing
        self.assertIn("tests/test_billing.py", impact.affected_tests)
        self.assertNotIn("tests/test_auth.py", impact.affected_tests)

    def test_diff_impact_for_auth_reaches_billing_tests(self):
        index, graph = self.index_py()
        impact = diff_impact(index, graph, ["auth.py"])
        self.assertIn("tests/test_auth.py", impact.affected_tests)
        self.assertIn("tests/test_billing.py", impact.affected_tests)


class TestTools(FixtureCase):
    def test_tool_surface(self):
        index, graph = self.index_py()
        hits = search_code(index, graph, "charge")
        self.assertTrue(any(h["kind"] == "symbol" for h in hits))
        syms = get_symbol(index, graph, "charge")
        self.assertEqual(len(syms), 1)
        self.assertEqual(syms[0]["path"], "billing.py")
        self.assertTrue(syms[0]["callers"])  # api.create_order calls charge
        outline = get_file_outline(index, "auth.py")
        self.assertIsNotNone(outline)
        self.assertGreater(len(outline["symbols"]), 0)
        self.assertIsNone(get_file_outline(index, "nope.py"))
        pack = build_context_pack_tool(index, graph, "charge a customer", 200)
        self.assertLessEqual(pack["tokens"], 200)
        amap = get_architecture_map(index, graph, fmt="mermaid")
        self.assertIn("billing --> auth", amap)


class TestCLI(FixtureCase):
    def test_cli_ask_and_context_and_map(self):
        self.index_py()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["ask", "charge", self.py_repo])
        self.assertEqual(code, 0)
        self.assertIn("billing.py", buf.getvalue())

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["context", "charge a customer", self.py_repo, "--budget", "200"])
        self.assertEqual(code, 0)
        self.assertIn("budget: 200 tokens", buf.getvalue())

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["map", self.py_repo, "--format", "mermaid"])
        self.assertEqual(code, 0)
        self.assertIn("billing --> auth", buf.getvalue())

    def test_cli_diff_with_explicit_files(self):
        self.index_py()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["diff", self.py_repo, "--files", "billing.py"])
        self.assertEqual(code, 0)
        self.assertIn("tests/test_billing.py", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
