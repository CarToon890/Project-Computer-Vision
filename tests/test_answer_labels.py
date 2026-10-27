"""Data-loss checks for refreshing and merging human answer labels."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from apply_answer_labels import merge_labels
from build_answer_labels_template import refresh_labels


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class AnswerLabelTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / "presentation_build"
        scratch.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.inventory = self.root / "inventory.csv"
        self.labels = self.root / "labels.csv"
        self.source = self.root / "import.csv"
        self.fields = ["sheet_id", "question_no", "ground_truth"]
        write_csv(self.inventory, ["sheet_id", "capture_role", "pair_status"], [
            {"sheet_id": sheet, "capture_role": role, "pair_status": "verified"}
            for sheet in ["S0001", "S0002"] for role in ["A", "B"]
        ])
        write_csv(self.labels, self.fields, [{"sheet_id": "S0001", "question_no": 1, "ground_truth": "3"}])

    def test_refresh_preserves_answers_and_adds_missing_slots(self):
        self.assertEqual(refresh_labels(self.inventory, self.labels), (2, 1))
        with self.labels.open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 200)
        self.assertEqual(rows[0]["ground_truth"], "3")
        self.assertEqual(len(list(self.root.glob("labels_before_refresh_*.csv"))), 1)

    def test_blank_import_does_not_erase_and_new_answer_is_merged(self):
        refresh_labels(self.inventory, self.labels)
        write_csv(self.source, self.fields, [
            {"sheet_id": "S0001", "question_no": 1, "ground_truth": ""},
            {"sheet_id": "S0002", "question_no": 100, "ground_truth": "blank"},
        ])
        self.assertEqual(merge_labels(self.source, self.labels), 1)
        with self.labels.open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["ground_truth"], "3")
        self.assertEqual(rows[-1]["ground_truth"], "blank")

    def test_conflict_or_duplicate_import_does_not_change_destination(self):
        refresh_labels(self.inventory, self.labels)
        before = self.labels.read_bytes()
        for entries in [
            [{"sheet_id": "S0001", "question_no": 1, "ground_truth": "4"}],
            [{"sheet_id": "S0001", "question_no": 2, "ground_truth": "2"}] * 2,
        ]:
            write_csv(self.source, self.fields, entries)
            with self.assertRaises(ValueError):
                merge_labels(self.source, self.labels)
            self.assertEqual(self.labels.read_bytes(), before)

    def test_pairing_hold_rejects_labels_before_any_write(self):
        refresh_labels(self.inventory,self.labels)
        write_csv(self.root/'pairing_review_holds.csv',['sheet_id','review_status','reason'],[{'sheet_id':'S0002','review_status':'pending','reason':'Pair under review'}])
        write_csv(self.source,self.fields,[{'sheet_id':'S0002','question_no':1,'ground_truth':'2'}])
        before=self.labels.read_bytes()
        with self.assertRaisesRegex(ValueError,'on hold'):
            merge_labels(self.source,self.labels)
        self.assertEqual(self.labels.read_bytes(),before)


if __name__ == "__main__":
    unittest.main()
