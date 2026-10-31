#!/usr/bin/env python3
"""Reconcile an internal purchase ledger with a supplier GST return.

The implementation uses only the Python standard library. Records are joined
on normalized GSTIN + invoice number; amount differences up to INR 1.00 are
treated as rounding tolerance, while larger differences are reported.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence

TOLERANCE = Decimal("1.00")
REQUIRED_FIELDS = ("gstin", "invoice_number", "taxable_value", "tax_amount")


class ReconciliationInputError(ValueError):
    """Raised when an input file or record is invalid."""


@dataclass(frozen=True)
class Invoice:
    gstin: str
    invoice_number: str
    taxable_value: Decimal
    tax_amount: Decimal

    @property
    def key(self) -> tuple[str, str]:
        # Whitespace and case normalization handles formatting differences while
        # preserving exact identifier equality after normalization.
        return self.gstin.strip().upper(), self.invoice_number.strip().upper()


@dataclass(frozen=True)
class ReconciliationResult:
    category: str
    gstin: str
    invoice_number: str
    taxable_difference: Decimal | None = None
    tax_difference: Decimal | None = None
    note: str = ""


def _decimal(value: object, field: str, row_number: int) -> Decimal:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ReconciliationInputError(
            f"Row {row_number}: {field} must be a valid decimal amount; got {value!r}"
        ) from None
    if not amount.is_finite() or amount < 0:
        raise ReconciliationInputError(
            f"Row {row_number}: {field} must be a finite, non-negative amount"
        )
    return amount


def _record_to_invoice(record: object, row_number: int) -> Invoice:
    if not isinstance(record, dict):
        raise ReconciliationInputError(f"Row {row_number}: expected a JSON object / CSV row")
    missing = [field for field in REQUIRED_FIELDS if field not in record or record[field] is None]
    if missing:
        raise ReconciliationInputError(f"Row {row_number}: missing required field(s): {', '.join(missing)}")
    gstin = str(record["gstin"]).strip()
    invoice_number = str(record["invoice_number"]).strip()
    if not gstin or not invoice_number:
        raise ReconciliationInputError(f"Row {row_number}: gstin and invoice_number cannot be blank")
    return Invoice(
        gstin=gstin,
        invoice_number=invoice_number,
        taxable_value=_decimal(record["taxable_value"], "taxable_value", row_number),
        tax_amount=_decimal(record["tax_amount"], "tax_amount", row_number),
    )


def load_records(path: str | Path) -> list[Invoice]:
    """Load invoice records from a JSON array or CSV file, inferred by suffix."""
    source = Path(path)
    if not source.is_file():
        raise ReconciliationInputError(f"Input file does not exist: {source}")
    suffix = source.suffix.lower()
    try:
        if suffix == ".json":
            with source.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if isinstance(payload, dict) and "records" in payload:
                payload = payload["records"]
            if not isinstance(payload, list):
                raise ReconciliationInputError(
                    f"{source}: JSON root must be an array or an object containing a 'records' array"
                )
            rows: Iterable[object] = payload
        elif suffix == ".csv":
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                headers = set(reader.fieldnames or [])
                missing = sorted(set(REQUIRED_FIELDS) - headers)
                if missing:
                    raise ReconciliationInputError(f"{source}: missing CSV column(s): {', '.join(missing)}")
                rows = list(reader)
        else:
            raise ReconciliationInputError(f"Unsupported input format {suffix!r}; use .json or .csv")
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        raise ReconciliationInputError(f"Could not read {source}: {exc}") from exc

    invoices = [_record_to_invoice(row, index) for index, row in enumerate(rows, start=1)]
    seen: set[tuple[str, str]] = set()
    for invoice in invoices:
        if invoice.key in seen:
            raise ReconciliationInputError(
                f"{source}: duplicate invoice key GSTIN={invoice.gstin!r}, "
                f"invoice_number={invoice.invoice_number!r}"
            )
        seen.add(invoice.key)
    return invoices


def reconcile(
    purchases: Sequence[Invoice],
    returns: Sequence[Invoice],
    tolerance: Decimal = TOLERANCE,
) -> list[ReconciliationResult]:
    """Classify each purchase as Matched, Missing in Return, or Value Mismatch."""
    return_by_key = {invoice.key: invoice for invoice in returns}
    results: list[ReconciliationResult] = []
    for purchase in purchases:
        vendor = return_by_key.get(purchase.key)
        if vendor is None:
            results.append(ReconciliationResult(
                "Missing in Return", purchase.gstin, purchase.invoice_number,
                note="No exact GSTIN + invoice number match in vendor return",
            ))
            continue
        taxable_difference = abs(purchase.taxable_value - vendor.taxable_value)
        tax_difference = abs(purchase.tax_amount - vendor.tax_amount)
        if taxable_difference > tolerance or tax_difference > tolerance:
            results.append(ReconciliationResult(
                "Value Mismatch", purchase.gstin, purchase.invoice_number,
                taxable_difference, tax_difference,
                "One or more amount differences exceed INR 1.00",
            ))
        else:
            results.append(ReconciliationResult(
                "Matched", purchase.gstin, purchase.invoice_number,
                taxable_difference, tax_difference,
                f"Amounts are within INR {tolerance:.2f} tolerance",
            ))
    return results


def print_summary(results: Sequence[ReconciliationResult]) -> None:
    categories = ("Matched", "Missing in Return", "Value Mismatch")
    counts = {category: sum(item.category == category for item in results) for category in categories}
    print("GST INVOICE RECONCILIATION")
    print("=" * 72)
    for category in categories:
        print(f"{category:<22} {counts[category]:>5}")
    print("-" * 72)
    if not results:
        print("No purchase invoices to reconcile.")
        return
    for result in results:
        print(f"{result.category:<20} {result.gstin} | {result.invoice_number}")
        if result.taxable_difference is not None:
            print(f"  taxable difference INR {result.taxable_difference:.2f} | tax difference INR {result.tax_difference:.2f}")
        if result.note:
            print(f"  {result.note}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purchases", type=Path, default=Path(__file__).parent / "data" / "purchase_ledger.csv",
                        help="Internal purchase ledger (.csv or .json)")
    parser.add_argument("--returns", type=Path, default=Path(__file__).parent / "data" / "vendor_returns.json",
                        help="Vendor GST return (.csv or .json)")
    args = parser.parse_args(argv)
    try:
        purchases = load_records(args.purchases)
        returns = load_records(args.returns)
        results = reconcile(purchases, returns)
    except ReconciliationInputError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    print(f"Purchase records: {len(purchases)} | Vendor return records: {len(returns)}")
    print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
