import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from reconciler import Invoice, ReconciliationInputError, load_records, reconcile
from dashboard import _read_upload


def invoice(gstin, number, taxable, tax):
    return Invoice(gstin, number, Decimal(taxable), Decimal(tax))


class ReconciliationTests(unittest.TestCase):
    def test_classifies_matched_within_tolerance(self):
        results = reconcile([invoice("aa", "1", "10", "2")], [invoice("AA", "1", "11", "2.50")])
        self.assertEqual(results[0].category, "Matched")

    def test_flags_amount_difference_over_one(self):
        results = reconcile([invoice("aa", "1", "10", "2")], [invoice("aa", "1", "11.01", "2")])
        self.assertEqual(results[0].category, "Value Mismatch")

    def test_missing_exact_identifier_is_missing(self):
        results = reconcile([invoice("aa", "1", "10", "2")], [invoice("bb", "1", "10", "2")])
        self.assertEqual(results[0].category, "Missing in Return")

    def test_loads_json_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            path.write_text(json.dumps([{"gstin": "AA", "invoice_number": "1", "taxable_value": "1.25", "tax_amount": "0.23"}]))
            self.assertEqual(load_records(path)[0].tax_amount, Decimal("0.23"))

    def test_loads_json_object_with_records_array(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            path.write_text(json.dumps({"financial_year": "2025-26", "records": [
                {"gstin": "AA", "invoice_number": "1", "taxable_value": "1.25", "tax_amount": "0.23"}
            ]}))
            self.assertEqual(load_records(path)[0].invoice_number, "1")

    def test_dashboard_accepts_wrapped_json_upload(self):
        payload = b'{"financial_year":"2025-26","records":[{"gstin":"AA","invoice_number":"1","taxable_value":"1.25","tax_amount":"0.23"}]}'
        self.assertEqual(_read_upload(payload, "returns.json")[0].gstin, "AA")

    def test_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            record = {"gstin": "AA", "invoice_number": "1", "taxable_value": "1", "tax_amount": "1"}
            path.write_text(json.dumps([record, record]))
            with self.assertRaises(ReconciliationInputError):
                load_records(path)


if __name__ == "__main__":
    unittest.main()
