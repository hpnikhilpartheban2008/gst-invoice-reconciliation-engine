#!/usr/bin/env python3
"""Local Audit Desk Pro, a stdlib-only GST reconciliation portal."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from urllib.parse import urlparse

from reconciler import ReconciliationInputError, TOLERANCE, load_records, reconcile

ROOT = Path(__file__).parent
MAX_UPLOAD = 10 * 1024 * 1024
CATEGORIES = ("Matched", "Missing in Return", "Value Mismatch")


def _read_upload(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".json"}:
        raise ReconciliationInputError("Use a .csv or .json file")
    if suffix == ".json":
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReconciliationInputError(f"Invalid JSON: {exc}") from exc
        if isinstance(payload, dict) and "records" in payload:
            payload = payload["records"]
        if not isinstance(payload, list):
            raise ReconciliationInputError("JSON root must be a record array or an object with a 'records' array")
        data = json.dumps(payload).encode("utf-8")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        temp.write(data)
        path = Path(temp.name)
    try:
        return load_records(path)
    finally:
        path.unlink(missing_ok=True)


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
            "category": result.category, "supplier_name": purchase.supplier_name or (vendor.supplier_name if vendor else "Supplier"),
            "description": purchase.description, "gstin": result.gstin, "invoice_number": result.invoice_number,
            "gst_rate": str(purchase.gst_rate), "purchase_taxable": str(purchase.taxable_value),
            "return_taxable": str(vendor.taxable_value) if vendor else "", "purchase_tax": str(purchase.tax_amount),
            "return_tax": str(vendor.tax_amount) if vendor else "", "purchase_cgst": str(purchase.cgst),
            "purchase_sgst": str(purchase.sgst), "purchase_igst": str(purchase.igst),
            "return_cgst": str(vendor.cgst) if vendor else "", "return_sgst": str(vendor.sgst) if vendor else "",
            "return_igst": str(vendor.igst) if vendor else "",
            "taxable_difference": str(result.taxable_difference) if result.taxable_difference is not None else "",
            "tax_difference": str(result.tax_difference) if result.tax_difference is not None else "",
        })
    claimable = sum((p.tax_amount for p in purchases if category_by_key[p.key] == "Matched"), Decimal("0.00"))
    at_risk = sum((p.tax_amount for p in purchases if category_by_key[p.key] != "Matched"), Decimal("0.00"))
    spend = sum((p.taxable_value + p.tax_amount for p in purchases), Decimal("0.00"))
    eligible = sum(category == "Matched" for category in category_by_key.values())
    return {
        "counts": {c: sum(row["category"] == c for row in rows) for c in CATEGORIES},
        "purchase_count": len(purchases), "return_count": len(returns), "rows": rows,
        "claimable_itc": str(claimable), "at_risk_itc": str(at_risk), "tolerance": str(tolerance),
        "total_spend": str(spend), "compliance_rate": round(eligible / len(purchases) * 100, 1) if purchases else 0,
        "audit_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def default_payload() -> dict:
    return audit_payload(load_records(ROOT / "data" / "purchase_ledger.csv"), load_records(ROOT / "data" / "vendor_returns.json"))


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Audit Desk Pro | Enterprise GST Reconciler</title><style>
:root{--navy:#0f172a;--canvas:#f8fafc;--paper:#fff;--ink:#17243b;--muted:#64748b;--line:#e2e8f0;--emerald:#047857;--amber:#b45309;--rose:#be123c}*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font:13px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}.top{background:#0f172a;color:white;padding:0 max(22px,calc((100vw - 1380px)/2));min-height:70px;display:flex;align-items:center;justify-content:space-between;gap:15px;box-shadow:0 5px 18px #0f172a25}.brand{display:flex;align-items:center;gap:12px}.logo{height:38px;width:38px;border-radius:11px;background:#10b981;display:grid;place-items:center;font-weight:900;font-size:18px}.brand h1{font-size:16px;margin:0;letter-spacing:-.02em}.brand small{display:block;color:#94a3b8;font-size:10px}.navtools{display:flex;align-items:center;gap:9px}.active-chip{font-size:10px;color:#a7f3d0;background:#064e3b;border:1px solid #047857;padding:6px 9px;border-radius:30px;white-space:nowrap}.period{font-size:11px;color:#e2e8f0;background:#1e293b;border:1px solid #334155;border-radius:8px;padding:8px}.quick{background:#fff;color:#0f172a;border:0;border-radius:8px;padding:8px;font-weight:650;font-size:11px}
main{max-width:1380px;margin:auto;padding:22px 22px 50px}.welcome{display:flex;justify-content:space-between;align-items:end;margin-bottom:17px}.eyebrow{color:#64748b;font-size:9px;font-weight:850;letter-spacing:.15em}.welcome h2{font-size:24px;letter-spacing:-.04em;margin:3px 0}.welcome p{margin:0;color:var(--muted);font-size:12px}.audit-time{font-size:10px;color:#64748b}.drop-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:10px}.drop{background:white;border:1px dashed #b7c4d3;border-radius:11px;padding:12px 14px;transition:.15s}.drop.over{border-color:#059669;background:#ecfdf5}.drop label{font-weight:750;font-size:11px}.drop p{color:#64748b;font-size:10px;margin:2px 0 6px}.drop input{font-size:11px;max-width:100%}.filebadge{font-size:10px;color:#047857;margin-top:5px;min-height:15px}.controls{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin:10px 0 14px}.btn{border:1px solid #dbe2eb;background:#fff;color:#334155;border-radius:8px;padding:8px 11px;font-size:10px;font-weight:750;cursor:pointer}.btn:hover{background:#f1f5f9}.btn.mainbtn{color:white;background:#047857;border-color:#047857}.btn.mainbtn:hover{background:#065f46}.btn:disabled{opacity:.55;cursor:wait}.tol{display:flex;align-items:center;gap:5px;background:#fff;border:1px solid var(--line);border-radius:8px;padding:3px}.tol span{color:#64748b;font-size:10px;padding:0 4px}.tol button{border:0;border-radius:6px;background:#f1f5f9;color:#334155;padding:6px 8px;font-size:10px;cursor:pointer}.tol button.selected{background:#d1fae5;color:#047857;font-weight:800}.search{margin-left:auto;border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:220px;font:inherit;font-size:11px}.status{font-size:10px;color:#64748b}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin:13px 0}.metric{background:white;border:1px solid var(--line);border-radius:11px;padding:14px 15px;box-shadow:0 3px 12px #0f172a09;min-width:0}.metric .label{color:#64748b;font-size:10px;font-weight:750}.metric .value{font-size:22px;font-weight:850;letter-spacing:-.04em;margin:4px 0 1px}.metric .foot{font-size:9px;color:#94a3b8}.metric.green .value{color:#047857}.metric.warn .value{color:#b45309}.metric.risk .value{color:#be123c}.progress{height:6px;border-radius:10px;background:#e2e8f0;margin-top:9px;overflow:hidden}.progress i{display:block;height:100%;background:#10b981;border-radius:10px;transition:width .25s}.filters{display:flex;gap:6px;overflow:auto;margin:17px 0 9px}.pill{border:1px solid var(--line);border-radius:20px;padding:7px 10px;background:white;color:#475569;white-space:nowrap;font-size:10px;font-weight:750;cursor:pointer}.pill.active{color:white;background:#0f172a;border-color:#0f172a}.tablebox{background:white;border:1px solid var(--line);border-radius:11px;overflow:hidden;box-shadow:0 3px 12px #0f172a09}.tablehead{padding:13px 15px;display:flex;justify-content:space-between;align-items:center}.tablehead strong{font-size:13px}.tablehead span{font-size:10px;color:#64748b}.scroll{overflow:auto;border-top:1px solid var(--line)}table{border-collapse:collapse;width:100%;white-space:nowrap;text-align:left}th{font-size:9px;letter-spacing:.055em;text-transform:uppercase;color:#64748b;background:#f8fafc;padding:10px 11px}td{padding:10px 11px;border-top:1px solid #edf1f5;font-size:10px;color:#334155}tbody tr:hover{background:#f8fafc}.supplier{font-weight:750;color:#17243b}.muted{display:block;color:#94a3b8;font-size:9px}.mono{font-family:ui-monospace,Consolas,monospace}.badge{display:inline-block;padding:4px 8px;border-radius:20px;font-size:9px;font-weight:850}.badge.eligible{background:#d1fae5;color:#047857}.badge.discrepancy{background:#ffe4e6;color:#be123c}.badge.blocked{background:#fef3c7;color:#a16207}.view{border:1px solid #dbe2eb;background:white;border-radius:6px;padding:5px 7px;font-size:9px;color:#334155;font-weight:700;cursor:pointer}.none{text-align:center;color:#94a3b8;padding:25px}.modal{width:min(620px,calc(100vw - 30px));border:0;border-radius:14px;padding:0;box-shadow:0 25px 70px #0f172a55}.modal::backdrop{background:#0f172a88}.modalheader{padding:16px 19px;background:#0f172a;color:white;display:flex;justify-content:space-between}.modalheader button{color:white;background:none;border:0;font-size:20px;cursor:pointer}.modalbody{padding:18px}.detailgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.detail{border:1px solid var(--line);border-radius:8px;padding:10px}.detail span{font-size:9px;color:#64748b;display:block}.detail strong{font-size:12px}.calc{margin-top:14px;border-top:1px solid var(--line);padding-top:12px;font-size:11px}.footer{margin-top:15px;font-size:9px;color:#94a3b8;text-align:center}.hidden{display:none!important}
@media(max-width:900px){.metrics{grid-template-columns:repeat(2,1fr)}.navtools{gap:5px}.brand h1{font-size:13px}}@media(max-width:650px){.top{padding:10px 12px;align-items:flex-start;flex-direction:column}.navtools{width:100%;justify-content:space-between}.drop-grid{grid-template-columns:1fr}main{padding:18px 11px}.metrics{gap:6px}.metric{padding:10px}.metric .value{font-size:18px}.search{margin:0;min-width:100%}.welcome{align-items:flex-start;flex-direction:column}.controls{gap:5px}}
@media print{body{background:#fff;font-size:9px}.top{-webkit-print-color-adjust:exact;print-color-adjust:exact}.drop-grid,.controls,.filters,.footer,.view{display:none!important}main{max-width:none;padding:9px}.welcome{margin:0 0 8px}.metrics{gap:5px;margin:6px 0}.metric,.tablebox{box-shadow:none;break-inside:avoid}.metric{padding:8px}.metric .value{font-size:15px}.scroll{overflow:visible}table{white-space:normal}td,th{font-size:7px;padding:5px}.pill{display:none}.tablehead{padding:7px}}
</style></head><body><header class="top"><div class="brand"><div class="logo">A</div><div><h1>Enterprise GST Reconciler &amp; ITC Audit Portal</h1><small>Audit Desk Pro · Supplier reconciliation workspace</small></div></div><div class="navtools"><span class="active-chip">● Production V1.2 - Active</span><span class="period">FY 2026-27 | Q3</span><select class="quick" id="quick"><option value="">Quick Import</option><option value="purchase">Import Purchase Ledger</option><option value="return">Import Vendor Return</option><option value="reset">Reload production dataset</option></select></div></header><main>
<div class="welcome"><div><span class="eyebrow">FINANCIAL CONTROL CENTER</span><h2>Quarterly reconciliation overview</h2><p>Industrial engineering supply chain · Tamil Nadu, Karnataka &amp; Maharashtra entities</p></div><div class="audit-time" id="auditTime"></div></div>
<div class="drop-grid"><div class="drop" id="dropP"><label for="fileP">Purchase Ledger · CSV</label><p>Drop ledger or browse to select. Leave blank to retain the production dataset.</p><input id="fileP" type="file" accept=".csv,text/csv"><div id="nameP" class="filebadge">Production ledger active</div></div><div class="drop" id="dropV"><label for="fileV">Vendor GST Return · JSON or CSV</label><p>Supports flat record arrays or a JSON object containing a records array.</p><input id="fileV" type="file" accept=".json,.csv,application/json,text/csv"><div id="nameV" class="filebadge">Production returns active</div></div></div>
<div class="controls"><button class="btn mainbtn" id="run">Run Reconciliation Audit</button><button class="btn" id="csv">Download Official Audit Report (CSV)</button><button class="btn" id="pdf">Download Reconciliation PDF</button><button class="btn" id="clear">Clear &amp; Upload Custom Files</button><div class="tol"><span>Tolerance</span><button data-t="0">₹0.00</button><button data-t="1" class="selected">₹1.00</button><button data-t="2">₹2.00</button><button data-t="5">₹5.00</button></div><span class="status" id="status" role="status"></span><input class="search" id="search" type="search" placeholder="Search supplier, GSTIN, invoice…"></div>
<div class="metrics"><article class="metric"><div class="label">Total Invoiced Spend</div><div class="value" id="spend"></div><div class="foot">Purchase ledger · taxable value plus tax</div></article><article class="metric green"><div class="label">Eligible ITC · Auto-Approved</div><div class="value" id="claim"></div><div class="foot">Matched invoices within selected tolerance</div></article><article class="metric warn"><div class="label">Blocked / At-Risk ITC · Pending Action</div><div class="value" id="risk"></div><div class="foot">Missing supplier filing or value discrepancy</div></article><article class="metric"><div class="label">Reconciliation Compliance Rate</div><div class="value" id="rate"></div><div class="progress"><i id="progress"></i></div><div class="foot" id="rateFoot"></div></article></div>
<div class="filters" id="filters"></div><section class="tablebox"><div class="tablehead"><strong>Supplier invoice register</strong><span id="visibleCount"></span></div><div class="scroll"><table><thead><tr><th>Supplier / Entity</th><th>GSTIN</th><th>Invoice ID</th><th>Purchase Tax</th><th>Vendor Tax Return</th><th>Variance</th><th>ITC Audit Status</th><th>Action</th></tr></thead><tbody id="rows"></tbody></table></div></section><div class="footer">Audit statuses are an operational review aid and do not replace applicable GST eligibility checks or filing controls.</div></main>
<dialog class="modal" id="modal"><div class="modalheader"><div><strong id="modalTitle">Audit breakdown</strong><div id="modalSub" style="font-size:10px;color:#cbd5e1"></div></div><button id="closeModal" aria-label="Close">×</button></div><div class="modalbody" id="modalBody"></div></dialog><script>
let data=__DATA__,tolerance=1,tab='All Records';const tabs=['All Records','Eligible ITC','Tax Discrepancies','Unfiled by Vendor'];const money=v=>'₹'+Number(v||0).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}),fmt=v=>v===''?'—':money(v),badge=r=>r.category==='Matched'?['Eligible (100%)','eligible']:r.category==='Missing in Return'?['Blocked (Missing)','blocked']:['Flagged (Discrepancy)','discrepancy'];
function countFor(t){return t==='All Records'?data.rows.length:t==='Eligible ITC'?data.counts['Matched']:t==='Tax Discrepancies'?data.counts['Value Mismatch']:data.counts['Missing in Return']}
function render(){document.getElementById('spend').textContent=money(data.total_spend);document.getElementById('claim').textContent=money(data.claimable_itc);document.getElementById('risk').textContent=money(data.at_risk_itc);document.getElementById('rate').textContent=data.compliance_rate.toFixed(1)+'%';document.getElementById('progress').style.width=data.compliance_rate+'%';document.getElementById('rateFoot').textContent=`${data.counts.Matched} of ${data.purchase_count} invoices reconciled`;document.getElementById('auditTime').textContent='Last audit · '+new Date(data.audit_timestamp).toLocaleString();
const f=document.getElementById('filters');f.replaceChildren(...tabs.map(t=>{let b=document.createElement('button');b.className='pill'+(tab===t?' active':'');b.textContent=`${t} (${countFor(t)})`;b.onclick=()=>{tab=t;renderRows();f.querySelectorAll('.pill').forEach(x=>x.classList.toggle('active',x===b))};return b}));renderRows()}
function renderRows(){let q=document.getElementById('search').value.trim().toLowerCase(),visible=data.rows.filter(r=>(tab==='All Records'||(tab==='Eligible ITC'&&r.category==='Matched')||(tab==='Tax Discrepancies'&&r.category==='Value Mismatch')||(tab==='Unfiled by Vendor'&&r.category==='Missing in Return'))&&[r.supplier_name,r.gstin,r.invoice_number].join(' ').toLowerCase().includes(q));document.getElementById('visibleCount').textContent=`Showing ${visible.length} of ${data.rows.length} transactions`;let body=document.getElementById('rows');body.replaceChildren();if(!visible.length){let tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=8;td.className='none';td.textContent='No transactions match these filters.';tr.append(td);body.append(tr);return}visible.forEach(r=>{let tr=document.createElement('tr'),b=badge(r);[null,r.gstin,r.invoice_number,fmt(r.purchase_tax),fmt(r.return_tax),r.category==='Missing in Return'?'Supplier return not found':`${money(r.tax_difference)} tax · ${money(r.taxable_difference)} taxable`,null,null].forEach((v,i)=>{let td=document.createElement('td');if(i===0){td.innerHTML=`<span class="supplier"></span><span class="muted"></span>`;td.children[0].textContent=r.supplier_name;td.children[1].textContent=r.description}else if(i===6){let s=document.createElement('span');s.className='badge '+b[1];s.textContent=b[0];td.append(s)}else if(i===7){let a=document.createElement('button');a.className='view';a.textContent='View Audit Breakdown';a.onclick=()=>showBreakdown(r);td.append(a)}else{td.textContent=v;if(i===1||i===2)td.className='mono'}tr.append(td)});body.append(tr)})}
function showBreakdown(r){document.getElementById('modalTitle').textContent=r.supplier_name;document.getElementById('modalSub').textContent=`${r.gstin} · ${r.invoice_number} · ${r.description}`;let body=document.getElementById('modalBody'),items=[['Taxable value — purchase',money(r.purchase_taxable)],['Taxable value — return',fmt(r.return_taxable)],['GST rate',r.gst_rate+'%'],['Purchase CGST / SGST / IGST',[r.purchase_cgst,r.purchase_sgst,r.purchase_igst].map(fmt).join(' / ')],['Return CGST / SGST / IGST',r.return_tax===''?'No supplier filing':[r.return_cgst,r.return_sgst,r.return_igst].map(fmt).join(' / ')],['Purchase tax total',money(r.purchase_tax)],['Vendor tax total',fmt(r.return_tax)],['Tax variance',r.tax_difference===''?'Unfiled':money(r.tax_difference)],['Taxable variance',r.taxable_difference===''?'Unfiled':money(r.taxable_difference)],['Tolerance applied',money(data.tolerance)],['Audit status',badge(r)[0]]];let grid=document.createElement('div');grid.className='detailgrid';items.forEach(([k,v])=>{let d=document.createElement('div');d.className='detail';let s=document.createElement('span'),strong=document.createElement('strong');s.textContent=k;strong.textContent=v;d.append(s,strong);grid.append(d)});body.replaceChildren(grid);document.getElementById('modal').showModal()}
document.getElementById('closeModal').onclick=()=>document.getElementById('modal').close();document.getElementById('search').oninput=renderRows;
function bindDrop(zoneId,inputId,nameId){let z=document.getElementById(zoneId),i=document.getElementById(inputId),n=document.getElementById(nameId);i.onchange=()=>n.textContent=i.files[0]?.name||'Production dataset active';z.ondragover=e=>{e.preventDefault();z.classList.add('over')};z.ondragleave=()=>z.classList.remove('over');z.ondrop=e=>{e.preventDefault();z.classList.remove('over');if(e.dataTransfer.files.length){let d=new DataTransfer();d.items.add(e.dataTransfer.files[0]);i.files=d.files;i.dispatchEvent(new Event('change'))}}}bindDrop('dropP','fileP','nameP');bindDrop('dropV','fileV','nameV');
async function runAudit(){let btn=document.getElementById('run'),s=document.getElementById('status');btn.disabled=true;s.textContent='Reconciling…';try{let f=new FormData(),p=document.getElementById('fileP').files[0],v=document.getElementById('fileV').files[0];if(p)f.append('purchases',p);if(v)f.append('returns',v);f.append('tolerance',String(tolerance));let res=await fetch('/api/reconcile',{method:'POST',body:f}),next=await res.json();if(!res.ok)throw Error(next.error||'Audit failed');data=next;render();s.textContent='Audit updated'}catch(e){s.textContent=e.message}finally{btn.disabled=false}}document.getElementById('run').onclick=runAudit;
document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{tolerance=Number(b.dataset.t);document.querySelectorAll('[data-t]').forEach(x=>x.classList.toggle('selected',x===b));runAudit()});
document.getElementById('quick').onchange=e=>{if(e.target.value==='purchase')document.getElementById('fileP').click();if(e.target.value==='return')document.getElementById('fileV').click();if(e.target.value==='reset')document.getElementById('clear').click();e.target.value=''};
document.getElementById('clear').onclick=async()=>{document.getElementById('fileP').value='';document.getElementById('fileV').value='';document.getElementById('nameP').textContent='Production ledger active';document.getElementById('nameV').textContent='Production returns active';document.getElementById('search').value='';tab='All Records';tolerance=1;document.querySelectorAll('[data-t]').forEach(x=>x.classList.toggle('selected',x.dataset.t==='1'));await fetch('/api/data').then(r=>r.json()).then(x=>data=x);render();document.getElementById('status').textContent='Production datasets restored'};
document.getElementById('pdf').onclick=()=>window.print();document.getElementById('csv').onclick=()=>{let status={'Matched':'Eligible (100%)','Value Mismatch':'Flagged (Discrepancy)','Missing in Return':'Blocked (Missing)'},now=new Date().toISOString(),heads=['Status','Supplier GSTIN','Invoice Number','Purchase Tax','Return Tax','Variance','ITC Eligibility','Audit Timestamp','Audit Trail Metadata'];let q=x=>'"'+String(x??'').replaceAll('"','""')+'"';let lines=[heads,...data.rows.map(r=>[status[r.category],r.gstin,r.invoice_number,r.purchase_tax,r.return_tax,r.category==='Missing in Return'?'Supplier filing not found':`Tax ${money(r.tax_difference)}; taxable ${money(r.taxable_difference)}`,r.category==='Matched'?'Eligible for ITC review':'At risk - action required',now,`Tolerance INR ${data.tolerance}; ${r.category}; ${r.description}`])].map(x=>x.map(q).join(','));let u=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=u;a.download='gst-quarterly-audit-report.csv';a.click();URL.revokeObjectURL(u)};render();
</script></body></html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status); self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health": self._send(200, b'{"status":"ok"}', "application/json; charset=utf-8")
        elif path == "/api/data": self._send(200, json.dumps(default_payload()).encode(), "application/json; charset=utf-8")
        elif path == "/": self._send(200, PAGE.replace("__DATA__", json.dumps(default_payload()).replace("</", "<\\/")).encode(), "text/html; charset=utf-8")
        else: self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/reconcile": self._send(404, b'{"error":"Not found"}', "application/json; charset=utf-8"); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2 * MAX_UPLOAD + 1024 * 1024: raise ReconciliationInputError("Upload is empty or exceeds the 20 MB combined limit")
            ctype = self.headers.get("Content-Type", "")
            if not ctype.lower().startswith("multipart/form-data"): raise ReconciliationInputError("Expected multipart form upload")
            msg = BytesParser(policy=policy.default).parsebytes(b"MIME-Version: 1.0\r\n" + f"Content-Type: {ctype}\r\n\r\n".encode() + self.rfile.read(length))
            files = {}; tolerance = TOLERANCE
            for part in msg.iter_parts():
                field = part.get_param("name", header="content-disposition"); filename = part.get_filename()
                if isinstance(filename, bytes): filename = filename.decode("utf-8", "replace")
                if field in {"purchases", "returns"} and filename:
                    content = part.get_payload(decode=True) or b""
                    if len(content) > MAX_UPLOAD: raise ReconciliationInputError("Each file must be 10 MB or less")
                    files[field] = (content, filename)
                elif field == "tolerance":
                    try: tolerance = Decimal((part.get_payload(decode=True) or b"").decode("ascii"))
                    except (InvalidOperation, UnicodeDecodeError): raise ReconciliationInputError("Invalid tolerance") from None
                    if not tolerance.is_finite() or not Decimal("0") <= tolerance <= Decimal("5"): raise ReconciliationInputError("Tolerance must be between INR 0 and INR 5")
            purchases = _read_upload(*files["purchases"]) if "purchases" in files else load_records(ROOT / "data" / "purchase_ledger.csv")
            returns = _read_upload(*files["returns"]) if "returns" in files else load_records(ROOT / "data" / "vendor_returns.json")
            self._send(200, json.dumps(audit_payload(purchases, returns, tolerance)).encode(), "application/json; charset=utf-8")
        except (ReconciliationInputError, OSError, ValueError, KeyError) as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None: print(f"[audit-desk] {self.address_string()} {fmt % args}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8000); args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler); print(f"Audit Desk Pro: http://{args.host}:{args.port}/", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopping Audit Desk Pro")
    finally: server.server_close()


if __name__ == "__main__": main()
