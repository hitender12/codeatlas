"""Tests for the retrieval-quality eval (tests/retrieval_eval.py).

The eval measures precision/recall of hybrid search and context packs on
the fixtures for 17 known questions. The thresholds here are FLOORS with
a wide margin under the measured numbers -- they guard against
regressions, they do not claim the measured numbers are good. The
measured numbers (run ``python3 tests/retrieval_eval.py``)::

    17 cases
    mean search precision 0.337, mean search recall 1.000, hit@1 0.824
    mean pack   precision 0.320, mean pack   recall 1.000
    12 empty-text snippets in TS context packs (JS line-number bug)

Precision is low by design of the metric: relevance is one strict file
per case (the file that *defines* the answer), while search returns
3-6 files that genuinely mention the words or import the answer, so
every extra file counts against precision even though it is a
reasonable near-miss. Recall 1.0 means the defining file is always in
the top 10 / in the pack. Hit@1 0.824 means the top hit is the defining
file in 14 of 17 cases; the 3 misses are a near-miss file ranking
above it (e.g. cart.py outranking catalog.py for "search the product
catalog").
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import retrieval_eval  # noqa: E402


class TestRetrievalEval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = retrieval_eval.evaluate()
        cls.summary = cls.report["summary"]
        cls.rows = cls.report["cases"]

    def test_eval_is_well_formed(self):
        self.assertEqual(len(self.rows), 17)
        self.assertEqual(self.summary["n_cases"], 17)
        for row in self.rows:
            for key in ("search_precision", "search_recall",
                        "pack_precision", "pack_recall"):
                self.assertGreaterEqual(row[key], 0.0, (row, key))
                self.assertLessEqual(row[key], 1.0, (row, key))
            self.assertLessEqual(row["pack_tokens"], 4000)
            self.assertTrue(row["search_retrieved"], row)
            self.assertTrue(row["pack_retrieved"], row)

    def test_mean_recall_floors(self):
        # Measured 1.000 / 1.000; floors leave room for fixture churn.
        self.assertGreaterEqual(self.summary["mean_search_recall"], 0.9)
        self.assertGreaterEqual(self.summary["mean_pack_recall"], 0.9)

    def test_mean_precision_floors(self):
        # Measured 0.337 / 0.320 against strict single-file relevance.
        self.assertGreaterEqual(self.summary["mean_search_precision"], 0.15)
        self.assertGreaterEqual(self.summary["mean_pack_precision"], 0.15)

    def test_hit_at_1_floor(self):
        # Measured 0.824 (14/17); the 3 misses are near-miss files
        # ranking above the defining file, not empty results.
        self.assertGreaterEqual(self.summary["search_hit_at_1"], 0.7)

    def test_no_case_has_zero_recall(self):
        for row in self.rows:
            self.assertGreater(row["search_recall"], 0.0, row)
            self.assertGreater(row["pack_recall"], 0.0, row)

    def test_canonical_auth_question_recalls_on_every_fixture(self):
        auth_rows = [r for r in self.rows
                     if r["query"] == "where is authentication handled?"]
        self.assertEqual(len(auth_rows), 3)  # sample-py, shop-py, shop-ts
        for row in auth_rows:
            self.assertEqual(row["search_recall"], 1.0, row)
            self.assertEqual(row["pack_recall"], 1.0, row)

    def test_eval_is_deterministic(self):
        again = retrieval_eval.evaluate()
        self.assertEqual(again["summary"], self.summary)
        self.assertEqual(again["cases"], self.rows)


if __name__ == "__main__":
    unittest.main()
