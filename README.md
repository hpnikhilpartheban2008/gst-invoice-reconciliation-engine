# GST Invoice Reconciliation Engine

A small, dependency-free Python 3 ETL utility that compares an enterprise purchase ledger with supplier GST return data. It checks invoice identity, applies an explicit INR 1.00 amount tolerance, and produces an audit summary that helps finance teams investigate exceptions before claiming Input Tax Credit (ITC).

## Problem

Manually matching internal purchase records with supplier tax invoices consumes finance time and makes small GSTIN, invoice number, and amount differences easy to miss. This engine automates the repeatable first-pass checks and surfaces exceptions for human review. It is an operational reconciliation aid, not tax or legal advice and not a substitute for filing-system validation.

## Workflow architecture

```text
 Internal Purchase Ledger                  Vendor GST Return
       CSV or JSON                              CSV or JSON
            │                                        │
            └───────────────┬────────────────────────┘
                            ▼
                  Parse + validate fields
                            │
                            ▼
             Exact normalized GSTIN + invoice key
                            │
                            ▼
       Compare taxable value and tax (INR 1.00 tolerance)
                            │
                            ▼
    Matched  |  Missing in Return  |  Value Mismatch
                            │
                            ▼
                 Console audit summary
```

The optional browser dashboard uses the same reconciliation functions and renders summary cards plus separate transaction tables for each category.

## Requirements

- Python 3.10 or newer
- No third-party packages

## Quick start

Run the included audit example from the repository root:

```bash
python reconciler.py
```

Pass other CSV or JSON files:

```bash
python reconciler.py --purchases path/to/purchases.csv --returns path/to/vendor_returns.json
```

The JSON format is an array of objects; CSV uses a header row. Both require `gstin`, `invoice_number`, `taxable_value`, and `tax_amount`. Amounts are parsed as decimal values (not binary floats), must be finite and non-negative, and duplicate normalized invoice keys are rejected. Input suffixes must be `.csv` or `.json`.

Identifiers are trimmed and compared case-insensitively, then must match exactly. A purchase with no corresponding GSTIN + invoice number key is `Missing in Return`. Where the key exists, either taxable value or tax difference greater than INR 1.00 is `Value Mismatch`; differences of exactly INR 1.00 or less are `Matched`. Vendor-only invoices are not currently categorized because the requested summary is purchase-ledger oriented.

## Tests

Run the standard-library test suite:

```bash
python -m unittest discover -s tests -v
```

## Sample audit

The bundled input data exercises all three categories, including a sub-tolerance difference and a material difference. Expected counts:

```text
Matched                    2
Missing in Return          1
Value Mismatch             1
```

Exit code is `0` for a completed audit and `2` for invalid or unreadable input.

## Browser dashboard

Start the local dashboard with Python's built-in HTTP server:

```bash
python dashboard.py
```

Open <http://127.0.0.1:8000/>. The dashboard supports drag-and-drop or file selection for a CSV purchase ledger and CSV/JSON vendor return. Leave either input untouched to use its sample dataset. **Run Reconciliation Audit** sends the files to the local server and updates the results without reloading the page. Search filters all three tables by GSTIN or invoice number; **Export Audit Report (CSV)** downloads the current audit rows. Uploads are limited to 10 MB per file.

The service binds to localhost by default. Use `python dashboard.py --port 8080` to select another port, and stop it with `Ctrl+C`.

## Business impact 

For finance, compliance, and technology work, the project demonstrates a controlled data pipeline: structured ingestion, deterministic business rules, exception reporting, and repeatable testing. Automating first-pass comparisons can reduce spreadsheet handling and review time, improve traceability of discrepancies, and help teams prioritize supplier follow-up. Any recovered time or ITC benefit depends on input quality, review controls, applicable tax rules, and the enterprise's filing process; the sample data is illustrative only.

## Repository layout

```text
.
├── data/
│   ├── purchase_ledger.csv
│   └── vendor_returns.json
├── tests/
│   └── test_reconciler.py
├── .gitignore
├── README.md
└── reconciler.py
```
