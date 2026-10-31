#!/usr/bin/env python3
"""Local interactive GST reconciliation dashboard using only Python's stdlib."""
from __future__ import annotations

from email import policy
from email.parser import BytesParser
import html
import json
import tempfile
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from reconciler import ReconciliationInputError, TOLERANCE, load_records, reconcile

ROOT = Path(__file__).parent
MAX_UPLOAD = 10 * 1024 * 1024
CATEGORIES = ("Matched", "Missing in Return", "Value Mismatch")


def _read_upload(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".json"}:
        raise ReconciliationInputError("Only .csv and .json files are supported")
    if suffix == ".json":
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReconciliationInputError(f"Invalid JSON upload: {exc}") from exc
        if isinstance(payload, dict) and "records" in payload:
            payload = payload["records"]
        if not isinstance(payload, list):
            raise ReconciliationInputError("JSON upload root must be an array or an object containing a 'records' array")
        data = json.dumps(payload).encode("utf-8")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        temp.write(data)
        name = temp.name
    try:
        return load_records(name)
    finally:
        Path(name).unlink(missing_ok=True)


def audit_payload(purchases, returns, tolerance: Decimal = TOLERANCE) -> dict:
    vendor_by_key = {row.key: row for row in returns}
    results = reconcile(purchases, returns, tolerance=tolerance)
    category_by_key = {(r.gstin.strip().upper(), r.invoice_number.strip().upper()): r.category for r in results}
    rows = []
    for result in results:
        key = (result.gstin.strip().upper(), result.invoice_number.strip().upper())
        purchase = next(row for row in purchases if row.key == key)
        vendor = vendor_by_key.get(purchase.key)
        rows.append({
            "category": result.category, "gstin": result.gstin, "invoice_number": result.invoice_number,
            "purchase_taxable": str(purchase.taxable_value), "return_taxable": str(vendor.taxable_value) if vendor else "",
            "purchase_tax": str(purchase.tax_amount), "return_tax": str(vendor.tax_amount) if vendor else "",
            "taxable_difference": str(result.taxable_difference) if result.taxable_difference is not None else "",
            "tax_difference": str(result.tax_difference) if result.tax_difference is not None else "",
        })
    claimable = sum((p.tax_amount for p in purchases if category_by_key[p.key] == "Matched"), Decimal("0.00"))
    at_risk = sum((p.tax_amount for p in purchases if category_by_key[p.key] != "Matched"), Decimal("0.00"))
    return {
        "counts": {category: sum(row["category"] == category for row in rows) for category in CATEGORIES},
        "purchase_count": len(purchases), "return_count": len(returns), "rows": rows,
        "claimable_itc": str(claimable), "at_risk_itc": str(at_risk), "tolerance": str(tolerance),
    }


def default_payload() -> dict:
    return audit_payload(load_records(ROOT / "data" / "purchase_ledger.csv"), load_records(ROOT / "data" / "vendor_returns.json"))


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GST Reconciliation | Executive Audit Desk</title><style>
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--paper:#fff;--bg:#f8fafc;--navy:#0f172a;--emerald:#047857;--amber:#b45309;--rose:#be123c}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.topbar{height:68px;background:#0f172a;color:white;display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1280px)/2));box-shadow:0 4px 16px #0f172a24}.brand{display:flex;align-items:center;gap:12px;font-weight:750}.logo{height:36px;width:36px;border-radius:10px;background:#10b981;display:grid;place-items:center;font-weight:900}.topright{display:flex;align-items:center;gap:8px;color:#cbd5e1;font-size:12px}.live{height:8px;width:8px;background:#34d399;border-radius:50%}
main{max-width:1280px;margin:auto;padding:28px 24px 56px}.title-row{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px;gap:14px}.eyebrow{font-size:10px;letter-spacing:.15em;font-weight:800;color:#64748b}h1{font-size:27px;letter-spacing:-.04em;margin:3px 0}.sub{color:var(--muted);margin:0}.period{font-size:12px;color:#475569;background:white;border:1px solid var(--line);padding:8px 12px;border-radius:9px;white-space:nowrap}
.upload-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}.drop{background:white;border:1px dashed #a8b6c9;border-radius:12px;padding:14px 16px;transition:.15s}.drop.over{border-color:#059669;background:#ecfdf5}.drop label{font-weight:700;display:block}.drop p{color:var(--muted);font-size:11px;margin:2px 0 7px}.drop input{font-size:12px;max-width:100%}.file-name{font-size:11px;color:var(--emerald);min-height:16px;margin-top:4px}
.toolbar{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:14px 0 18px}.button{border:1px solid transparent;border-radius:9px;padding:10px 14px;font-weight:700;font-size:12px;cursor:pointer}.primary{background:#047857;color:white;box-shadow:0 3px 9px #04785730}.primary:hover{background:#065f46}.secondary{background:white;border-color:var(--line);color:#334155}.secondary:hover{background:#f1f5f9}.button:disabled{opacity:.55;cursor:wait}.status{font-size:11px;color:var(--muted)}.search{margin-left:auto;min-width:220px;border:1px solid var(--line);border-radius:9px;padding:9px 11px;background:white;font:inherit}.tolerance{display:flex;align-items:center;gap:9px;background:white;border:1px solid var(--line);border-radius:9px;padding:5px 10px;color:#475569;font-size:11px}.tolerance input[type=range]{width:120px;accent-color:#047857}.tolerance input[type=number]{width:66px;border:1px solid var(--line);border-radius:6px;padding:4px}
.impact{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:0 0 17px}.impact-card{background:white;border:1px solid var(--line);border-radius:12px;padding:15px 18px;box-shadow:0 4px 14px #0f172a08;display:flex;justify-content:space-between;align-items:center}.impact-card.claim{border-left:4px solid #10b981}.impact-card.risk{border-left:4px solid #f43f5e}.impact-label{font-size:11px;font-weight:700;color:#475569}.impact-value{font-size:24px;letter-spacing:-.03em;font-weight:800;margin-top:2px}.impact-note{font-size:10px;color:#94a3b8}.impact-icon{font-size:20px;background:#ecfdf5;color:#047857;border-radius:10px;padding:9px}.risk .impact-icon{background:#fff1f2;color:#be123c}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}.card{background:white;border:1px solid var(--line);border-radius:12px;padding:15px 18px;box-shadow:0 4px 14px #0f172a08;position:relative}.card:before{content:"";position:absolute;inset:0 auto 0 0;width:4px;border-radius:12px 0 0 12px;background:#10b981}.card.missing:before{background:#f59e0b}.card.mismatch:before{background:#f43f5e}.card span{font-size:12px;color:#475569;font-weight:700}.card strong{display:block;font-size:29px;line-height:1.35;margin-top:3px}.card small{color:#94a3b8;font-size:10px}
.tabs{display:flex;gap:7px;overflow:auto;margin:20px 0 10px}.tab{white-space:nowrap;border:1px solid var(--line);border-radius:20px;background:white;padding:7px 12px;font-size:11px;font-weight:700;color:#475569;cursor:pointer}.tab.active{background:#0f172a;border-color:#0f172a;color:white}.panel{background:white;border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden;box-shadow:0 4px 14px #0f172a08}.panel-head{display:flex;align-items:center;justify-content:space-between;padding:13px 17px}.panel h2{font-size:15px;margin:2px 0}.badge{border-radius:20px;padding:4px 9px;font-size:10px;font-weight:800;white-space:nowrap}.badge.matched{color:#047857;background:#d1fae5}.badge.missing{color:#a16207;background:#fef3c7}.badge.mismatch{color:#be123c;background:#ffe4e6}.table-wrap{overflow:auto;border-top:1px solid var(--line)}table{width:100%;border-collapse:collapse;white-space:nowrap;text-align:left}th{font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:#64748b;background:#f8fafc;padding:10px 12px}td{padding:10px 12px;border-top:1px solid #edf1f5;font-size:11px;color:#334155}tbody tr:hover{background:#f8fafc}.mono{font-family:ui-monospace,Consolas,monospace}.empty{text-align:center;color:#94a3b8;padding:20px}.hidden{display:none!important}footer{text-align:center;color:#94a3b8;font-size:10px;margin-top:20px}
@media(max-width:720px){main{padding:20px 12px}.topbar{padding:0 14px}.upload-grid,.impact{grid-template-columns:1fr}.cards{gap:7px}.card{padding:12px 9px}.card span{font-size:10px}.card strong{font-size:24px}.card small{font-size:9px}.title-row{align-items:flex-start;flex-direction:column}h1{font-size:23px}.search{margin:0;width:100%}.tolerance{flex-wrap:wrap}}
@media print{body{background:white;color:#0f172a;font-size:10px}.topbar{background:#0f172a!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}.topbar,.drop,.toolbar,.tabs,footer{display:none!important}main{max-width:none;padding:10px}.title-row{margin-bottom:10px}.impact,.cards{gap:8px;margin-bottom:10px}.impact-card,.card,.panel{box-shadow:none;break-inside:avoid;border-color:#cbd5e1}.impact-value{font-size:18px}.card strong{font-size:22px}.panel{margin:8px 0}.table-wrap{overflow:visible}table{white-space:normal}th,td{padding:6px;font-size:8px}.badge{border:1px solid currentColor}.eyebrow{font-size:8px}}
</style></head><body><header class="topbar"><div class="brand"><div class="logo">G</div><span>GST Audit Desk</span></div><div class="topright"><i class="live"></i> LOCAL AUDIT WORKSPACE</div></header><main>
<div class="title-row"><div><span class="eyebrow">INPUT TAX CREDIT · RECONCILIATION</span><h1>Invoice audit overview</h1><p class="sub">A clear view of supplier alignment, exceptions, and ITC exposure.</p></div><div class="period" id="recordCounts"></div></div>
<div class="upload-grid"><div class="drop" id="purchaseDrop"><label for="purchaseFile">Purchase Ledger (.csv)</label><p>Drop a CSV or choose a file. Leave blank to use the sample ledger.</p><input id="purchaseFile" type="file" accept=".csv,text/csv"><div class="file-name" id="purchaseName">Sample purchase ledger active</div></div><div class="drop" id="returnDrop"><label for="returnFile">Vendor Return (.json or .csv)</label><p>Drop a JSON or CSV or choose a file. Leave blank to use the sample return.</p><input id="returnFile" type="file" accept=".json,.csv,application/json,text/csv"><div class="file-name" id="returnName">Sample vendor return active</div></div></div>
<div class="toolbar"><button class="button primary" id="runAudit">Run Reconciliation Audit</button><button class="button secondary" id="exportCsv">Export Audit Report (CSV)</button><button class="button secondary" id="reset">Reset to Sample Data</button><button class="button secondary" id="print">Print / Export PDF Summary</button><label class="tolerance">Tolerance <input type="range" id="tolRange" min="0" max="5" step="0.05" value="1"><input type="number" id="tolNumber" min="0" max="5" step="0.05" value="1.00" aria-label="Tolerance in rupees">₹</label><span class="status" id="status" role="status" aria-live="polite"></span><input class="search" id="search" type="search" placeholder="Search GSTIN or invoice number…" aria-label="Search GSTIN or invoice number"></div>
<div class="impact"><article class="impact-card claim"><div><div class="impact-label">Total Claimable ITC</div><div class="impact-value" id="claimable"></div><div class="impact-note">Tax from invoices matched within tolerance</div></div><div class="impact-icon">↗</div></article><article class="impact-card risk"><div><div class="impact-label">Blocked / At-Risk ITC</div><div class="impact-value" id="atRisk"></div><div class="impact-note">Tax associated with missing or mismatched invoices</div></div><div class="impact-icon">!</div></article></div>
<div class="cards" id="cards"></div><div class="tabs" id="tabs"></div><div id="tables"></div><footer>ITC eligibility is indicative and based on reconciliation status. Confirm applicable rules and supporting records before filing.</footer></main>
<script>
let auditData=__INITIAL_DATA__,activeTab='All Invoices',busy=false;const cats=['Matched','Missing in Return','Value Mismatch'],styles=['matched','missing','mismatch'],badges=['Auto-Approved','Action Required: Supplier Pending','High Risk: ITC Variance'],keys=['purchase_taxable','return_taxable','purchase_tax','return_tax','taxable_difference','tax_difference'],cols=['Purchase taxable','Return taxable','Purchase tax','Return tax','Taxable diff.','Tax diff.'];
const money=v=>v===''?'—':'₹'+Number(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
function render(){document.getElementById('recordCounts').textContent=`${auditData.purchase_count} purchase records · ${auditData.return_count} return records · tolerance ${money(auditData.tolerance)}`;document.getElementById('claimable').textContent=money(auditData.claimable_itc);document.getElementById('atRisk').textContent=money(auditData.at_risk_itc);
document.getElementById('cards').replaceChildren(...cats.map((c,i)=>{let e=document.createElement('article');e.className=`card ${styles[i]}`;e.innerHTML=`<span>${c}</span><strong>${auditData.counts[c]}</strong><small>${badges[i]}</small>`;return e}));
const tabs=document.getElementById('tabs');tabs.replaceChildren(...['All Invoices',...cats].map(t=>{let b=document.createElement('button');b.className='tab'+(activeTab===t?' active':'');b.textContent=t;b.onclick=()=>{activeTab=t;render()};return b}));
const root=document.getElementById('tables'),show=activeTab==='All Invoices'?cats:[activeTab];root.replaceChildren(...show.map(c=>{let ix=cats.indexOf(c),section=document.createElement('section');section.className='panel';section.dataset.category=c;let head=document.createElement('div');head.className='panel-head';head.innerHTML=`<div><span class="eyebrow">RECONCILIATION STATUS</span><h2>${c}</h2></div><span class="badge ${styles[ix]}">${badges[ix]} · ${auditData.counts[c]}</span>`;section.append(head);let wrap=document.createElement('div');wrap.className='table-wrap';let table=document.createElement('table');let thead=document.createElement('thead'),hr=document.createElement('tr');['Supplier GSTIN','Invoice Number',...cols].forEach(t=>{let th=document.createElement('th');th.textContent=t;hr.append(th)});thead.append(hr);table.append(thead);let body=document.createElement('tbody');auditData.rows.filter(r=>r.category===c).forEach(r=>{let tr=document.createElement('tr');tr.dataset.search=(r.gstin+' '+r.invoice_number).toLowerCase();[r.gstin,r.invoice_number,...keys.map(k=>money(r[k]))].forEach((v,i)=>{let td=document.createElement('td');td.textContent=v;if(i<2)td.className='mono';tr.append(td)});body.append(tr)});if(!body.children.length){let tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=8;td.className='empty';td.textContent='No invoices in this category.';tr.append(td);body.append(tr)}table.append(body);wrap.append(table);section.append(wrap);return section}));filterRows()}
function filterRows(){let q=document.getElementById('search').value.trim().toLowerCase();document.querySelectorAll('tbody tr[data-search]').forEach(r=>r.classList.toggle('hidden',!r.dataset.search.includes(q)))}document.getElementById('search').addEventListener('input',filterRows);
function bindDrop(zoneId,inputId,nameId){let z=document.getElementById(zoneId),f=document.getElementById(inputId),n=document.getElementById(nameId);f.onchange=()=>n.textContent=f.files[0]?.name||'Sample data active';z.ondragover=e=>{e.preventDefault();z.classList.add('over')};z.ondragleave=()=>z.classList.remove('over');z.ondrop=e=>{e.preventDefault();z.classList.remove('over');if(e.dataTransfer.files.length){let d=new DataTransfer();d.items.add(e.dataTransfer.files[0]);f.files=d.files;f.dispatchEvent(new Event('change'))}}}bindDrop('purchaseDrop','purchaseFile','purchaseName');bindDrop('returnDrop','returnFile','returnName');
async function runAudit(){if(busy)return;busy=true;let btn=document.getElementById('runAudit'),st=document.getElementById('status');btn.disabled=true;st.textContent='Running audit…';try{let form=new FormData(),p=document.getElementById('purchaseFile').files[0],v=document.getElementById('returnFile').files[0];if(p)form.append('purchases',p);if(v)form.append('returns',v);form.append('tolerance',document.getElementById('tolNumber').value);let res=await fetch('/api/reconcile',{method:'POST',body:form}),data=await res.json();if(!res.ok)throw Error(data.error||'Audit failed');auditData=data;render();st.textContent=`Audit complete · ${data.rows.length} invoices`}catch(e){st.textContent=e.message}finally{btn.disabled=false;busy=false}}
document.getElementById('runAudit').onclick=runAudit;let range=document.getElementById('tolRange'),num=document.getElementById('tolNumber'),timer;function syncTolerance(from){let value=Math.min(5,Math.max(0,Number(from.value)||0));range.value=num.value=value.toFixed(2);clearTimeout(timer);timer=setTimeout(runAudit,250)}range.oninput=()=>syncTolerance(range);num.oninput=()=>syncTolerance(num);num.onchange=()=>syncTolerance(num);
document.getElementById('reset').onclick=async()=>{document.getElementById('purchaseFile').value='';document.getElementById('returnFile').value='';document.getElementById('purchaseName').textContent='Sample purchase ledger active';document.getElementById('returnName').textContent='Sample vendor return active';document.getElementById('search').value='';activeTab='All Invoices';range.value='1';num.value='1.00';document.getElementById('status').textContent='Restored sample datasets';try{let r=await fetch('/api/data'),d=await r.json();if(!r.ok)throw Error();auditData=d;render()}catch{runAudit()}};
document.getElementById('print').onclick=()=>window.print();document.getElementById('exportCsv').onclick=()=>{const status={Matched:'Auto-Approved','Missing in Return':'Action Required: Supplier Pending','Value Mismatch':'High Risk: ITC Variance'},elig={Matched:'Claimable ITC','Missing in Return':'At risk - supplier pending','Value Mismatch':'At risk - ITC variance'};const heads=['Status','Supplier GSTIN','Invoice Number','Purchase Tax','Return Tax','Variance','ITC Eligibility'];const q=v=>'"'+String(v??'').replaceAll('"','""')+'"';const lines=[heads,...auditData.rows.map(r=>[status[r.category],r.gstin,r.invoice_number,r.purchase_tax,r.return_tax,[r.tax_difference!==''?'Tax '+money(r.tax_difference):'',r.taxable_difference!==''?'Taxable '+money(r.taxable_difference):''].filter(Boolean).join('; ')||'—',elig[r.category]])].map(row=>row.map(q).join(','));let url=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='gst-executive-audit-report.csv';a.click();URL.revokeObjectURL(url)};render();
</script></body></html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health": self._send(200, b'{"status":"ok"}', "application/json; charset=utf-8")
        elif path == "/api/data": self._send(200, json.dumps(default_payload()).encode(), "application/json; charset=utf-8")
        elif path == "/": self._send(200, PAGE.replace("__INITIAL_DATA__", json.dumps(default_payload()).replace("</", "<\\/")).encode(), "text/html; charset=utf-8")
        else: self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/reconcile": self._send(404, b'{"error":"Not found"}', "application/json; charset=utf-8"); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2 * MAX_UPLOAD + 1024 * 1024: raise ReconciliationInputError("Upload request is empty or exceeds the 20 MB combined limit")
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("multipart/form-data"): raise ReconciliationInputError("Expected multipart form upload")
            raw = self.rfile.read(length); message = BytesParser(policy=policy.default).parsebytes(b"MIME-Version: 1.0\r\n" + f"Content-Type: {content_type}\r\n\r\n".encode() + raw)
            uploaded = {}; tolerance = TOLERANCE
            for part in message.iter_parts():
                field = part.get_param("name", header="content-disposition"); filename = part.get_filename()
                if isinstance(filename, bytes): filename = filename.decode("utf-8", errors="replace")
                if field in {"purchases", "returns"} and filename:
                    data = part.get_payload(decode=True) or b""
                    if len(data) > MAX_UPLOAD: raise ReconciliationInputError("Each upload must be 10 MB or smaller")
                    uploaded[field] = (data, filename)
                elif field == "tolerance":
                    try: tolerance = Decimal((part.get_payload(decode=True) or b"").decode("ascii"))
                    except (InvalidOperation, UnicodeDecodeError): raise ReconciliationInputError("Tolerance must be a number from INR 0.00 to INR 5.00") from None
                    if not tolerance.is_finite() or not Decimal("0") <= tolerance <= Decimal("5"): raise ReconciliationInputError("Tolerance must be from INR 0.00 to INR 5.00")
            purchases = _read_upload(*uploaded["purchases"]) if "purchases" in uploaded else load_records(ROOT / "data" / "purchase_ledger.csv")
            returns = _read_upload(*uploaded["returns"]) if "returns" in uploaded else load_records(ROOT / "data" / "vendor_returns.json")
            self._send(200, json.dumps(audit_payload(purchases, returns, tolerance)).encode(), "application/json; charset=utf-8")
        except (ReconciliationInputError, OSError, ValueError, KeyError) as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None: print(f"[dashboard] {self.address_string()} - {fmt % args}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8000); args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler); print(f"GST reconciliation dashboard: http://{args.host}:{args.port}/", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopping dashboard server.")
    finally: server.server_close()


if __name__ == "__main__": main()
