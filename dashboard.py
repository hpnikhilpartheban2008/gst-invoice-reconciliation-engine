#!/usr/bin/env python3
"""Local interactive GST reconciliation dashboard using only Python's stdlib."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
import html
import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from reconciler import ReconciliationInputError, load_records, reconcile

ROOT = Path(__file__).parent
MAX_UPLOAD = 10 * 1024 * 1024
CATEGORIES = ("Matched", "Missing in Return", "Value Mismatch")
FIELDS = ("gstin", "invoice_number", "taxable_value", "tax_amount")


def _read_upload(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".json"}:
        raise ReconciliationInputError("Only .csv and .json files are supported")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        temp.write(data)
        name = temp.name
    try:
        return load_records(name)
    finally:
        Path(name).unlink(missing_ok=True)


def audit_payload(purchases, returns) -> dict:
    vendor_by_key = {row.key: row for row in returns}
    results = reconcile(purchases, returns)
    rows = []
    for result in results:
        purchase = next(row for row in purchases if row.key == (result.gstin.strip().upper(), result.invoice_number.strip().upper()))
        vendor = vendor_by_key.get(purchase.key)
        rows.append({
            "category": result.category,
            "gstin": result.gstin,
            "invoice_number": result.invoice_number,
            "purchase_taxable": str(purchase.taxable_value),
            "return_taxable": str(vendor.taxable_value) if vendor else "",
            "purchase_tax": str(purchase.tax_amount),
            "return_tax": str(vendor.tax_amount) if vendor else "",
            "taxable_difference": str(result.taxable_difference) if result.taxable_difference is not None else "",
            "tax_difference": str(result.tax_difference) if result.tax_difference is not None else "",
        })
    return {
        "counts": {category: sum(row["category"] == category for row in rows) for category in CATEGORIES},
        "purchase_count": len(purchases), "return_count": len(returns), "rows": rows,
    }


def default_payload() -> dict:
    return audit_payload(
        load_records(ROOT / "data" / "purchase_ledger.csv"),
        load_records(ROOT / "data" / "vendor_returns.json"),
    )


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GST Reconciliation | Audit Desk</title><style>
:root{--ink:#17243b;--muted:#728097;--line:#e6eaf1;--paper:#fff;--bg:#f5f7fb;--navy:#112541;--teal:#0a8f78;--amber:#c47a09;--red:#c34c51}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.topbar{height:70px;background:var(--navy);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1240px)/2))}.brand{display:flex;align-items:center;gap:12px;font-weight:700}.logo{height:36px;width:36px;border-radius:11px;background:#1b987e;display:grid;place-items:center;font-weight:800}.topmeta{color:#cfdae8;font-size:12px}
main{max-width:1240px;margin:auto;padding:30px 24px 56px}.eyebrow{font-size:10px;letter-spacing:.15em;font-weight:800;color:#7c8aa0}h1{font-size:28px;letter-spacing:-.035em;margin:4px 0}.sub{color:var(--muted);margin:0 0 22px}.upload-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}.drop{background:#fff;border:1px dashed #b9c5d5;border-radius:12px;padding:16px;transition:.15s}.drop.over{border-color:var(--teal);background:#f0fbf8}.drop label{font-weight:700;display:block;margin-bottom:4px}.drop p{color:var(--muted);font-size:12px;margin:0 0 8px}.drop input{max-width:100%;font-size:12px}.file-name{min-height:18px;color:var(--teal);font-size:11px;margin-top:5px}
.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:22px}.button{border:0;border-radius:9px;padding:11px 17px;font-weight:700;font-size:13px;cursor:pointer}.primary{background:#087f6d;color:white;box-shadow:0 4px 10px #087f6d2a}.primary:hover{background:#066c5c}.secondary{background:#fff;border:1px solid var(--line);color:#34435a}.button:disabled{opacity:.6;cursor:wait}.status{color:var(--muted);font-size:12px}.search{margin-left:auto;min-width:230px;border:1px solid var(--line);border-radius:9px;padding:10px 12px;font:inherit;background:white}
.heading{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:18px;gap:16px}.period{font-size:12px;color:#617087;background:#fff;border:1px solid var(--line);padding:8px 12px;border-radius:9px;white-space:nowrap}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:26px}.card{background:var(--paper);padding:17px 21px;border:1px solid var(--line);border-radius:13px;box-shadow:0 3px 12px #1c35500a;position:relative}.card:before{content:"";position:absolute;inset:0 auto 0 0;width:4px;background:var(--teal)}.card.missing:before{background:var(--amber)}.card.mismatch:before{background:var(--red)}.card span{display:block;color:#53627a;font-weight:600}.card strong{display:block;font-size:34px;line-height:1.35;margin-top:4px}.card small{color:#8995a8}
.panel{background:var(--paper);border:1px solid var(--line);border-radius:13px;margin:15px 0;overflow:hidden;box-shadow:0 3px 12px #1c35500a}.panel-head{display:flex;align-items:center;justify-content:space-between;padding:15px 20px}.panel h2{font-size:17px;margin:3px 0 0}.count{padding:4px 10px;border-radius:20px;background:#e8f6f2;color:#087b68;font-weight:700;font-size:12px}.count.missing{background:#fff4de;color:#9b6204}.count.mismatch{background:#fdeced;color:#a83b41}.table-wrap{overflow:auto;border-top:1px solid var(--line)}table{width:100%;border-collapse:collapse;white-space:nowrap;text-align:left}th{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#8190a5;background:#fafbfd;padding:10px 13px}td{padding:12px 13px;border-top:1px solid #edf0f5;font-size:12px;color:#34435a}tbody tr:hover{background:#fbfcfe}.mono{font-family:ui-monospace,Consolas,monospace}.empty{text-align:center;color:#8b97a8;padding:20px}footer{margin-top:22px;color:#8a96a8;font-size:11px;text-align:center}.hidden{display:none!important}
@media(max-width:700px){main{padding:22px 13px}.topbar{padding:0 15px}.upload-grid{grid-template-columns:1fr}.cards{gap:8px}.card{padding:13px 11px}.card span{font-size:11px}.card strong{font-size:27px}.card small{font-size:10px}.search{margin:0;width:100%}.heading{align-items:flex-start;flex-direction:column}h1{font-size:24px}}
</style></head><body><header class="topbar"><div class="brand"><div class="logo">G</div><span>GST Audit Desk</span></div><div class="topmeta">Local reconciliation dashboard</div></header><main>
<span class="eyebrow">INPUT TAX CREDIT · RECONCILIATION</span><h1>Invoice audit overview</h1><p class="sub">Drop in your ledgers, run an audit, and review supplier exceptions.</p>
<div class="upload-grid"><div class="drop" id="purchaseDrop"><label for="purchaseFile">Purchase Ledger (.csv)</label><p>Drop a CSV here or choose a file. Sample ledger stays active if left empty.</p><input id="purchaseFile" type="file" accept=".csv,text/csv"><div class="file-name" id="purchaseName">Using sample purchase ledger</div></div>
<div class="drop" id="returnDrop"><label for="returnFile">Vendor Return (.json or .csv)</label><p>Drop a JSON or CSV here, or choose a file. Sample return stays active if left empty.</p><input id="returnFile" type="file" accept=".json,.csv,application/json,text/csv"><div class="file-name" id="returnName">Using sample vendor return</div></div></div>
<div class="actions"><button class="button primary" id="runAudit">Run Reconciliation Audit</button><button class="button secondary" id="exportCsv">Export Audit Report (CSV)</button><span class="status" id="status" role="status" aria-live="polite"></span><input class="search" id="search" type="search" placeholder="Search GSTIN or invoice number…" aria-label="Search GSTIN or invoice number"></div>
<div class="heading"><div><span class="eyebrow">AUDIT SUMMARY</span></div><div class="period" id="recordCounts"></div></div><div class="cards" id="cards"></div><div id="tables"></div>
<footer>Amount differences up to INR 1.00 are treated as rounding tolerance. Review exceptions before filing.</footer></main>
<script>
let auditData = __INITIAL_DATA__;
const cats=['Matched','Missing in Return','Value Mismatch'];
const css=['matched','missing','mismatch'];
const labels=['Purchase taxable','Return taxable','Purchase tax','Return tax','Taxable diff.','Tax diff.'];
const keys=['purchase_taxable','return_taxable','purchase_tax','return_tax','taxable_difference','tax_difference'];
const money=v=>v===''?'—':'₹'+Number(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
function render(){
 document.getElementById('recordCounts').textContent=`${auditData.purchase_count} purchase records · ${auditData.return_count} return records`;
 document.getElementById('cards').replaceChildren(...cats.map((c,i)=>{let a=document.createElement('article');a.className=`card ${css[i]}`;a.innerHTML=`<span>${c}</span><strong>${auditData.counts[c]}</strong><small>purchase invoices</small>`;return a}));
 const host=document.getElementById('tables');host.replaceChildren(...cats.map((c,i)=>{let section=document.createElement('section');section.className='panel';let head=document.createElement('div');head.className='panel-head';head.innerHTML=`<div><span class="eyebrow">RECONCILIATION</span><h2>${c}</h2></div><span class="count ${css[i]}">${auditData.counts[c]}</span>`;section.append(head);let wrap=document.createElement('div');wrap.className='table-wrap';let table=document.createElement('table');let thead=document.createElement('thead'),hr=document.createElement('tr');['Supplier GSTIN','Invoice',...labels].forEach(t=>{let th=document.createElement('th');th.textContent=t;hr.append(th)});thead.append(hr);table.append(thead);let body=document.createElement('tbody');auditData.rows.filter(r=>r.category===c).forEach(r=>{let tr=document.createElement('tr');tr.dataset.search=(r.gstin+' '+r.invoice_number).toLowerCase();[r.gstin,r.invoice_number,...keys.map(k=>money(r[k]))].forEach((v,j)=>{let td=document.createElement('td');td.textContent=v;if(j<2)td.className='mono';tr.append(td)});body.append(tr)});if(!body.children.length){let tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=8;td.className='empty';td.textContent='No records in this category.';tr.append(td);body.append(tr)}table.append(body);wrap.append(table);section.append(wrap);return section}));filterRows();
}
function filterRows(){const q=document.getElementById('search').value.trim().toLowerCase();document.querySelectorAll('tbody tr[data-search]').forEach(tr=>tr.classList.toggle('hidden',!tr.dataset.search.includes(q)))}
document.getElementById('search').addEventListener('input',filterRows);
function bindDrop(zoneId,inputId,nameId){const zone=document.getElementById(zoneId),input=document.getElementById(inputId),name=document.getElementById(nameId);input.addEventListener('change',()=>name.textContent=input.files[0]?.name||'Using sample data');zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('over')});zone.addEventListener('dragleave',()=>zone.classList.remove('over'));zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('over');if(e.dataTransfer.files.length){const dt=new DataTransfer();dt.items.add(e.dataTransfer.files[0]);input.files=dt.files;input.dispatchEvent(new Event('change'))}})}
bindDrop('purchaseDrop','purchaseFile','purchaseName');bindDrop('returnDrop','returnFile','returnName');
document.getElementById('runAudit').addEventListener('click',async()=>{const btn=document.getElementById('runAudit'),status=document.getElementById('status');btn.disabled=true;status.textContent='Reconciling…';try{const form=new FormData();const p=document.getElementById('purchaseFile').files[0],v=document.getElementById('returnFile').files[0];if(p)form.append('purchases',p);if(v)form.append('returns',v);const response=await fetch('/api/reconcile',{method:'POST',body:form});const payload=await response.json();if(!response.ok)throw new Error(payload.error||'Audit failed');auditData=payload;render();status.textContent=`Audit complete · ${payload.rows.length} purchase records`}catch(err){status.textContent=err.message}finally{btn.disabled=false}});
document.getElementById('exportCsv').addEventListener('click',()=>{const cols=['category','gstin','invoice_number',...keys];const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';const csv=[cols.map(quote).join(','),...auditData.rows.map(r=>cols.map(c=>quote(r[c])).join(','))].join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='gst-reconciliation-audit.csv';a.click();URL.revokeObjectURL(url)});
render();
</script></body></html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, b'{"status":"ok"}', "application/json; charset=utf-8")
        elif path == "/api/data":
            self._send(200, json.dumps(default_payload()).encode(), "application/json; charset=utf-8")
        elif path == "/":
            page = PAGE.replace("__INITIAL_DATA__", json.dumps(default_payload()).replace("</", "<\\/"))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/reconcile":
            self._send(404, b'{"error":"Not found"}', "application/json; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2 * MAX_UPLOAD + 1024 * 1024:
                raise ReconciliationInputError("Upload request is empty or exceeds the 20 MB combined limit")
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("multipart/form-data"):
                raise ReconciliationInputError("Expected multipart form upload")
            raw = self.rfile.read(length)
            message = BytesParser(policy=policy.default).parsebytes(
                b"MIME-Version: 1.0\r\n" + f"Content-Type: {content_type}\r\n\r\n".encode() + raw
            )
            uploaded = {}
            for part in message.iter_parts():
                field = part.get_param("name", header="content-disposition")
                filename = part.get_filename()
                if isinstance(filename, bytes):
                    filename = filename.decode("utf-8", errors="replace")
                if field in {"purchases", "returns"} and filename:
                    data = part.get_payload(decode=True) or b""
                    if len(data) > MAX_UPLOAD:
                        raise ReconciliationInputError("Each upload must be 10 MB or smaller")
                    uploaded[field] = (data, filename)
            if "purchases" in uploaded:
                purchases = _read_upload(*uploaded["purchases"])
            else:
                purchases = load_records(ROOT / "data" / "purchase_ledger.csv")
            if "returns" in uploaded:
                returns = _read_upload(*uploaded["returns"])
            else:
                returns = load_records(ROOT / "data" / "vendor_returns.json")
            payload = json.dumps(audit_payload(purchases, returns)).encode("utf-8")
            self._send(200, payload, "application/json; charset=utf-8")
        except (ReconciliationInputError, OSError, ValueError, KeyError) as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode("utf-8"), "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        print(f"[dashboard] {self.address_string()} - {fmt % args}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost only)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"GST reconciliation dashboard: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
