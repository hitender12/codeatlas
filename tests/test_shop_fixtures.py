"""Tests for the expanded fixtures: shop-py (Python) and shop-ts (TypeScript).

Both fixtures are small realistic shops (auth, catalog, cart, orders,
payments, API surface, tests) that exercise the indexer end to end:
multi-module imports, cross-file calls, test links, and the arch map.

Note on JS/TS line numbers: the regex parser mis-reports definition
lines after blank lines (see TestJavaScriptLineNumbers in
test_edge_cases.py), so TS assertions here check symbol *names*, kinds,
imports, and graph edges -- never exact definition lines.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codeatlas.archmap import build_architecture_map, diff_impact  # noqa: E402
from codeatlas.context import build_context_pack  # noqa: E402
from codeatlas.graph import Graph  # noqa: E402
from codeatlas.indexer import index_repo  # noqa: E402
from codeatlas.search import search  # noqa: E402
from codeatlas.tools import get_symbol  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


class FixtureCase(unittest.TestCase):
    fixture = None  # subclass sets this

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="codeatlas-shop-")
        self.repo = os.path.join(self.tmp, self.fixture)
        shutil.copytree(os.path.join(FIXTURES, self.fixture), self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self):
        index, stats = index_repo(self.repo)
        return index, stats, Graph.build(index)


class TestShopPy(FixtureCase):
    fixture = "shop-py"

    def test_indexes_everything_with_no_parse_errors(self):
        index, stats, _ = self.index()
        self.assertEqual(stats.indexed, 11)
        self.assertEqual(stats.parse_errors, 0)
        self.assertEqual(len(index.files), 11)
        self.assertEqual(index.total_symbols, 45)
        self.assertEqual(index.total_imports, 22)
        self.assertNotIn("README.md", index.files)  # non-source ignored

    def test_package_symbols(self):
        index, _, _ = self.index()
        auth_syms = {(s.name, s.kind)
                     for s in index.files["shop/auth.py"].parsed.symbols}
        self.assertIn(("hash_password", "function"), auth_syms)
        self.assertIn(("Authenticator", "class"), auth_syms)
        self.assertIn(("authenticate", "method"), auth_syms)
        self.assertIn(("login", "method"), auth_syms)
        self.assertIn(("SECRET", "constant"), auth_syms)
        self.assertIn(("Product", "class"),
                      {(s.name, s.kind) for s in
                       index.files["shop/catalog.py"].parsed.symbols})

    def test_import_edges_resolve_across_the_package(self):
        _, _, graph = self.index()
        edges = graph.import_edges
        self.assertIn("shop/auth.py", edges["shop/orders.py"])
        self.assertIn("shop/cart.py", edges["shop/orders.py"])
        self.assertIn("shop/payments.py", edges["shop/orders.py"])
        self.assertIn("shop/catalog.py", edges["shop/cart.py"])
        self.assertIn("shop/db.py", edges["shop/catalog.py"])
        self.assertIn("shop/auth.py", edges["shop/payments.py"])
        self.assertIn("shop/orders.py", edges["shop/api.py"])
        # Package __init__ re-exports resolve too.
        self.assertIn("shop/auth.py", edges["shop/__init__.py"])

    def test_cross_file_calls(self):
        _, _, graph = self.index()
        callers = graph.callers_of("authenticate")
        self.assertTrue(any(p == "shop/payments.py" and c == "charge"
                            for p, c, _ in callers))
        self.assertTrue(any(p == "shop/auth.py" and c == "Authenticator.login"
                            for p, c, _ in callers))
        charge_callers = graph.callers_of("charge")
        self.assertTrue(any(p == "shop/orders.py" and c == "create_order"
                            for p, c, _ in charge_callers))
        product_callers = graph.callers_of("get_product")
        self.assertTrue(any(p == "shop/cart.py" and c == "Cart.add_item"
                            for p, c, _ in product_callers))
        self.assertTrue(any(p == "shop/cart.py" and c == "Cart.total"
                            for p, c, _ in product_callers))

    def test_test_links_cover_both_test_files(self):
        _, _, graph = self.index()
        self.assertEqual(graph.test_links["tests/test_auth.py"], {"shop/auth.py"})
        self.assertIn("shop/orders.py", graph.test_links["tests/test_orders.py"])
        self.assertIn("shop/cart.py", graph.test_links["tests/test_orders.py"])
        self.assertIn("shop/catalog.py", graph.test_links["tests/test_orders.py"])

    def test_architecture_map_groups_the_package(self):
        index, _, graph = self.index()
        amap = build_architecture_map(index, graph)
        self.assertEqual(set(amap.modules), {"shop", "tests"})
        edges = {(e.source, e.target) for e in amap.edges}
        self.assertEqual(edges, {("tests", "shop")})  # intra-shop edges collapse

    def test_diff_impact_for_auth_reaches_both_test_files(self):
        index, _, graph = self.index()
        impact = diff_impact(index, graph, ["shop/auth.py"])
        self.assertIn("shop/orders.py", impact.affected_files)
        self.assertIn("shop/payments.py", impact.affected_files)
        self.assertEqual(set(impact.affected_tests),
                         {"tests/test_auth.py", "tests/test_orders.py"})

    def test_search_and_context_pack(self):
        index, _, graph = self.index()
        results = search(index, graph, "where is authentication handled?")
        self.assertEqual(results[0].path, "shop/auth.py")
        pack = build_context_pack(index, graph, "charge a customer",
                                  budget_tokens=400)
        self.assertLessEqual(pack.tokens, 400)
        self.assertIn("shop/payments.py", {s.path for s in pack.snippets})
        # Python snippets carry real code, never empty text.
        self.assertTrue(all(s.text.strip() for s in pack.snippets))

    def test_symbol_lookup(self):
        index, _, graph = self.index()
        syms = get_symbol(index, graph, "charge")
        self.assertEqual(len(syms), 1)
        self.assertEqual(syms[0]["path"], "shop/payments.py")
        self.assertTrue(any(c["path"] == "shop/orders.py"
                            for c in syms[0]["callers"]))


class TestShopTs(FixtureCase):
    fixture = "shop-ts"

    def test_indexes_everything_with_no_parse_errors(self):
        index, stats, _ = self.index()
        self.assertEqual(stats.indexed, 11)
        self.assertEqual(stats.parse_errors, 0)
        self.assertEqual(len(index.files), 11)
        self.assertEqual(index.total_symbols, 33)
        self.assertEqual(index.total_imports, 19)
        self.assertNotIn("package.json", index.files)  # non-source ignored

    def test_typescript_symbols(self):
        index, _, _ = self.index()
        auth_syms = {(s.name, s.kind)
                     for s in index.files["src/auth.ts"].parsed.symbols}
        self.assertIn(("hashPassword", "function"), auth_syms)
        self.assertIn(("Authenticator", "class"), auth_syms)
        self.assertIn(("authenticate", "method"), auth_syms)
        self.assertIn(("login", "method"), auth_syms)
        billing_syms = {s.name for s in
                        index.files["src/billing.ts"].parsed.symbols}
        self.assertIn("charge", billing_syms)
        self.assertIn("applyDiscount", billing_syms)
        # Arrow-function utils (no return annotation) are found.
        utils_syms = {s.name for s in
                      index.files["src/utils.ts"].parsed.symbols}
        self.assertEqual(utils_syms, {"formatPrice", "slugify", "shout"})
        # TSX component is found and typed as TypeScript.
        self.assertEqual(index.files["src/components/PriceTag.tsx"].language,
                         "typescript")
        self.assertIn("PriceTag", [s.name for s in
                      index.files["src/components/PriceTag.tsx"].parsed.symbols])

    def test_import_edges_resolve_across_src(self):
        _, _, graph = self.index()
        edges = graph.import_edges
        self.assertIn("src/auth.ts", edges["src/orders.ts"])
        self.assertIn("src/billing.ts", edges["src/orders.ts"])
        self.assertIn("src/cart.ts", edges["src/orders.ts"])
        self.assertIn("src/catalog.ts", edges["src/cart.ts"])
        self.assertIn("src/db.ts", edges["src/catalog.ts"])
        self.assertIn("src/auth.ts", edges["src/billing.ts"])
        self.assertIn("src/orders.ts", edges["src/api.ts"])
        self.assertIn("src/auth.ts", edges["test/auth.test.ts"])

    def test_import_type_counts_as_an_import(self):
        # catalog.ts has both `import { ... } from "./db"` and
        # `import type { ... } from "./db"`: two records, one target.
        index, _, graph = self.index()
        modules = [i.module for i in
                   index.files["src/catalog.ts"].parsed.imports]
        self.assertEqual(modules.count("./db"), 2)
        self.assertEqual(graph.import_edges["src/catalog.ts"], {"src/db.ts"})

    def test_cross_file_calls(self):
        _, _, graph = self.index()
        charge_callers = graph.callers_of("charge")
        self.assertTrue(any(p == "src/orders.ts" and c == "createOrder"
                            for p, c, _ in charge_callers))
        auth_callers = graph.callers_of("authenticate")
        self.assertTrue(any(p == "src/billing.ts" and c == "charge"
                            for p, c, _ in auth_callers))

    def test_test_links(self):
        _, _, graph = self.index()
        self.assertEqual(graph.test_links["test/auth.test.ts"], {"src/auth.ts"})
        self.assertIn("src/orders.ts", graph.test_links["test/orders.test.ts"])
        self.assertIn("src/cart.ts", graph.test_links["test/orders.test.ts"])

    def test_architecture_map(self):
        index, _, graph = self.index()
        amap = build_architecture_map(index, graph)
        # src/components maps to module "components" (top-dir rule).
        self.assertEqual(set(amap.modules), {"src", "test", "components"})
        edges = {(e.source, e.target) for e in amap.edges}
        self.assertEqual(edges, {("test", "src")})

    def test_diff_impact_for_auth(self):
        index, _, graph = self.index()
        impact = diff_impact(index, graph, ["src/auth.ts"])
        self.assertIn("src/orders.ts", impact.affected_files)
        self.assertIn("src/billing.ts", impact.affected_files)
        self.assertEqual(set(impact.affected_tests),
                         {"test/auth.test.ts", "test/orders.test.ts"})

    def test_search_finds_the_right_file_by_path_not_line(self):
        # Lines are unreliable for TS (see test_edge_cases.py), so assert
        # on the file and symbol name only.
        index, _, graph = self.index()
        results = search(index, graph, "charge")
        symbols = [r for r in results if r.kind == "symbol"]
        self.assertTrue(symbols)
        self.assertEqual(symbols[0].path, "src/billing.ts")
        self.assertEqual(symbols[0].name, "charge")
        auth_results = search(index, graph, "where is authentication handled?")
        self.assertEqual(auth_results[0].path, "src/auth.ts")

    def test_context_pack_respects_budget(self):
        index, _, graph = self.index()
        pack = build_context_pack(index, graph, "charge a customer",
                                  budget_tokens=400)
        self.assertLessEqual(pack.tokens, 400)
        self.assertGreater(len(pack.snippets), 0)
        self.assertIn("src/billing.ts", {s.path for s in pack.snippets})


if __name__ == "__main__":
    unittest.main()
