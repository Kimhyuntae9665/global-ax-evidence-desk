import csv
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from axdesk.core import Desk, DeskError, digest, validate

ROOT = Path(__file__).resolve().parents[1]


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "data", self.root / "data")
        self.desk = Desk(self.root / "runtime" / "desk.sqlite3", self.root / "data")

    def tearDown(self):
        self.temp.cleanup()

    def fix_all(self):
        self.desk.repair({"id": "S004", "excluded": True, "reason": "Source cross-check: redundant submission."})
        self.desk.repair({"id": "S003", "value": "9500"})
        self.desk.repair({"id": "S005", "value": "0.7", "unit": "MWh"})
        return self.desk.repair({"id": "S006", "value": "10", "period": "2026-09"})

    def test_initial_issues_exclude_unknown_and_duplicates_from_totals(self):
        state = self.desk.state()
        self.assertEqual(state["summary"]["normalized_kwh"], "14000")
        self.assertEqual(state["summary"]["invalid_count"], 5)
        by_id = {r["id"]: r for r in state["records"]}
        self.assertIsNone(by_id["S003"]["normalized_kwh"])
        self.assertIsNone(by_id["S001"]["normalized_kwh"])
        self.assertEqual({i["code"] for i in by_id["S006"]["issues"]}, {"negative_value", "stale_period"})
        self.assertEqual(by_id["S002"]["normalized_kwh"], "14000")

    def test_decimal_conversion_avoids_binary_float_error(self):
        state = self.desk.repair({"id": "S002", "value": "0.100000001", "unit": "MWh"})
        record = next(r for r in state["records"] if r["id"] == "S002")
        self.assertEqual(record["normalized_kwh"], "100.000001000")
        self.assertEqual(state["summary"]["normalized_kwh"], "100.000001000")

    def test_exclusion_requires_reason_and_retains_history(self):
        with self.assertRaises(DeskError) as caught:
            self.desk.repair({"id": "S004", "excluded": True})
        self.assertEqual(caught.exception.code, "reason_required")
        state = self.desk.repair({"id": "S004", "excluded": True, "reason": "Duplicate source confirmed."})
        by_id = {r["id"]: r for r in state["records"]}
        self.assertEqual(by_id["S001"]["status"], "valid")
        self.assertEqual(by_id["S004"]["status"], "excluded")
        self.assertEqual(state["summary"]["normalized_kwh"], "26000")
        self.assertEqual(state["audit"][0]["before"]["version"], 1)
        self.assertEqual(state["audit"][0]["after"]["version"], 2)
        state = self.desk.repair({"id": "S004", "excluded": False})
        self.assertEqual(state["records"][0]["status"], "invalid")

    def test_review_and_export_block_until_repaired_and_reviewed(self):
        with self.assertRaises(DeskError) as caught:
            self.desk.review({"reviewer": "Demo reviewer", "note": "Checked.", "digests": self.desk.state()["digests"]})
        self.assertEqual(caught.exception.code, "validation_blocked")
        with self.assertRaises(DeskError):
            self.desk.export()
        state = self.fix_all()
        self.assertEqual(state["summary"]["unresolved_count"], 0)
        self.assertEqual(state["summary"]["normalized_kwh"], "46200.0")
        with self.assertRaises(DeskError) as caught:
            self.desk.export()
        self.assertEqual(caught.exception.code, "review_required")
        state = self.desk.review({"reviewer": "Demo reviewer", "note": "Checked synthetic sources and corrections.",
                                  "digests": self.desk.state()["digests"]})
        self.assertEqual(state["review"]["status"], "current")
        rows = list(csv.DictReader(io.StringIO(self.desk.export())))
        self.assertEqual(len(rows), 5)
        self.assertNotIn("S004", {r["id"] for r in rows})

    def test_edit_invalidates_review_even_if_new_value_valid(self):
        self.fix_all()
        self.desk.review({"reviewer": "Demo", "note": "Checked.", "digests": self.desk.state()["digests"]})
        state = self.desk.repair({"id": "S001", "value": "12001"})
        self.assertEqual(state["review"]["status"], "stale")
        with self.assertRaises(DeskError) as caught:
            self.desk.export()
        self.assertEqual(caught.exception.code, "review_required")

    def test_current_corpus_revision_invalidates_review(self):
        self.fix_all()
        self.desk.review({"reviewer": "Demo", "note": "Checked.", "digests": self.desk.state()["digests"]})
        path = self.root / "data" / "sop.json"
        docs = json.loads(path.read_text(encoding="utf-8"))
        docs[0]["revision"] = "3.0"
        path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.desk.state()["review"]["status"], "stale")
        with self.assertRaises(DeskError):
            self.desk.export()

    def test_superseded_document_change_does_not_invalidate_current_corpus(self):
        self.fix_all()
        self.desk.review({"reviewer": "Demo", "note": "Checked.", "digests": self.desk.state()["digests"]})
        path = self.root / "data" / "sop.json"
        docs = json.loads(path.read_text(encoding="utf-8"))
        docs[-1]["text"] = "An archived document edit."
        path.write_text(json.dumps(docs), encoding="utf-8")
        self.assertEqual(self.desk.state()["review"]["status"], "current")

    def test_retrieval_only_current_docs_and_exact_citations(self):
        result = self.desk.ask({"question": "How do we handle missing values?", "language": "en"})
        self.assertFalse(result["abstained"])
        self.assertEqual(result["mode"], "retrieval-only")
        docs = self.desk.documents()
        for citation in result["citations"]:
            doc = next(d for d in docs if d["id"] == citation["doc_id"] and d["revision"] == citation["revision"])
            self.assertEqual(doc["status"], "current")
            self.assertIn(citation["quote"], doc["text"])
            self.assertEqual(citation["source_digest"], digest(doc))
            self.assertNotIn("may be replaced with zero", citation["quote"])
        self.assertIn("never zero", result["answer"])

    def test_retrieval_abstains_on_unsupported_questions(self):
        result = self.desk.ask({"question": "Banana spacecraft propulsion", "language": "en"})
        self.assertTrue(result["abstained"])
        self.assertEqual(result["citations"], [])

    def test_multilingual_citations(self):
        for language, question in [("ko", "누락 값은 어떻게 처리합니까?"), ("vi", "Giá trị thiếu")]:
            with self.subTest(language=language):
                result = self.desk.ask({"question": question, "language": language})
                self.assertFalse(result["abstained"])
                self.assertTrue(all(c["language"] == language for c in result["citations"]))

    def test_invalid_numeric_forms_never_sum_or_allocate_huge_output(self):
        for value in ["NaN", "Infinity", "garbage", "1e1000000", "-1e1000000", "1e-1000000", "1000000000001", "-0.1"]:
            with self.subTest(value=value):
                state = self.desk.repair({"id": "S002", "value": value})
                record = next(r for r in state["records"] if r["id"] == "S002")
                self.assertEqual(record["status"], "invalid")
                self.assertIsNone(record["normalized_kwh"])

    def test_reset_preserves_audit_and_clears_review(self):
        self.fix_all()
        self.desk.review({"reviewer": "Demo", "note": "Checked.", "digests": self.desk.state()["digests"]})
        state = self.desk.reset()
        self.assertEqual(state["review"]["status"], "unreviewed")
        self.assertEqual(state["summary"]["normalized_kwh"], "14000")
        self.assertEqual(state["audit"][0]["action"], "reset_demo")
        self.assertEqual(len(state["audit"]), 6)

    def test_sqlite_persists_repairs_on_reopen(self):
        self.desk.repair({"id": "S003", "value": "9500"})
        reopened = Desk(self.root / "runtime" / "desk.sqlite3", self.root / "data")
        self.assertEqual(next(r for r in reopened.state()["records"] if r["id"] == "S003")["value"], "9500")

    def test_unexpected_repair_fields_rejected(self):
        with self.assertRaises(DeskError):
            self.desk.repair({"id": "S003", "source_doc": "invented"})

    def test_stale_other_tab_snapshot_cannot_approve_latest_data(self):
        self.fix_all()
        displayed = self.desk.state()["digests"]
        other_tab = Desk(self.root / "runtime" / "desk.sqlite3", self.root / "data")
        other_tab.repair({"id": "S001", "value": "12001"})
        with self.assertRaises(DeskError) as caught:
            self.desk.review({"reviewer": "Old tab", "note": "Checked previous view.", "digests": displayed})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "stale_snapshot")
        self.assertEqual(self.desk.state()["review"]["status"], "unreviewed")

    def test_changed_sop_snapshot_cannot_be_approved(self):
        self.fix_all()
        displayed = self.desk.state()["digests"]
        path = self.root / "data" / "sop.json"
        docs = json.loads(path.read_text(encoding="utf-8"))
        docs[0]["revision"] = "3.0"
        path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(DeskError) as caught:
            self.desk.review({"reviewer": "Old SOP view", "note": "Checked previous view.", "digests": displayed})
        self.assertEqual(caught.exception.code, "stale_snapshot")
        self.assertEqual(self.desk.state()["review"]["status"], "unreviewed")

    def test_review_requires_exact_snapshot_shape(self):
        self.fix_all()
        for digests in [None, {}, {"data": "x", "corpus": "x"},
                        {**self.desk.state()["digests"], "extra": "x"},
                        {"data": 123, "corpus": "0" * 64}]:
            with self.subTest(digests=digests), self.assertRaises(DeskError) as caught:
                self.desk.review({"reviewer": "Demo", "note": "Checked.", "digests": digests})
            self.assertEqual(caught.exception.code, "invalid_snapshot")

    def test_finite_zero_with_extreme_exponent_is_normalized_safely(self):
        for value in ["0e1000000", "0e-1000000", "-0e1000000"]:
            with self.subTest(value=value):
                state = self.desk.repair({"id": "S002", "value": value})
                record = next(r for r in state["records"] if r["id"] == "S002")
                self.assertEqual(record["status"], "valid")
                self.assertEqual(record["normalized_kwh"], "0")


if __name__ == "__main__":
    unittest.main()
