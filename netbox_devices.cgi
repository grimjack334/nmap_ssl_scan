#!/usr/bin/env python3
"""
CGI sortable/filterable combined list of NetBox devices and virtual machines.

Test locally (example data — no NetBox needed):
    python3 -m http.server --cgi 8080
    # Open http://localhost:8080/cgi-bin/netbox_devices.cgi

Connect to NetBox:
    NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=xxx python3 netbox_devices.cgi
"""

from __future__ import annotations

import cgitb
import html as _html
import json
import os
import urllib.request
import urllib.error

cgitb.enable()

# ── Config ────────────────────────────────────────────────────────────────────

NETBOX_URL         = os.environ.get("NETBOX_URL", "").rstrip("/")
NETBOX_TOKEN       = os.environ.get("NETBOX_TOKEN", "")
NETBOX_EXPORT_FILE = os.environ.get("NETBOX_EXPORT_FILE", "")
WIKI_URL           = os.environ.get("WIKI_URL", "http://localhost:8080/")
SCRIPT_NAME        = os.environ.get("SCRIPT_NAME", "netbox_devices.cgi")

STATUS_CLASS = {
    "active":          "ok",
    "offline":         "danger",
    "failed":          "danger",
    "planned":         "secondary",
    "staged":          "info",
    "decommissioning": "caution",
    "inventory":       "secondary",
}

DASH = '<span class="muted">—</span>'

# ── Example subset ────────────────────────────────────────────────────────────

def _dev(id_, name, tenant, role="Server", site="DC-Primary", status="active"):
    t = {"id": id_, "name": tenant} if tenant else None
    s = {"value": status, "label": status.replace("-", " ").title()}
    return {"id": id_, "name": name, "tenant": t,
            "device_role": {"name": role}, "site": {"name": site}, "status": s}

def _vm(id_, name, tenant, role="Application", status="active", site=None):
    t = {"id": id_, "name": tenant} if tenant else None
    s = {"value": status, "label": status.replace("-", " ").title()}
    return {"id": id_, "name": name, "tenant": t,
            "role": {"name": role}, "site": {"name": site} if site else None, "status": s}


EXAMPLE_DEVICES = [
    # Infrastructure – 12
    _dev(1,  "core-sw-01",  "Infrastructure", "Core Switch"),
    _dev(2,  "core-sw-02",  "Infrastructure", "Core Switch"),
    _dev(3,  "dist-sw-01",  "Infrastructure", "Distribution Switch"),
    _dev(4,  "dist-sw-02",  "Infrastructure", "Distribution Switch"),
    _dev(5,  "dist-sw-03",  "Infrastructure", "Distribution Switch", "DC-Secondary"),
    _dev(6,  "fw-01",       "Infrastructure", "Firewall"),
    _dev(7,  "fw-02",       "Infrastructure", "Firewall"),
    _dev(8,  "edge-rtr-01", "Infrastructure", "Router"),
    _dev(9,  "edge-rtr-02", "Infrastructure", "Router"),
    _dev(10, "kvm-host-01", "Infrastructure"),
    _dev(11, "kvm-host-02", "Infrastructure"),
    _dev(12, "kvm-host-03", "Infrastructure", "Server", "DC-Secondary", "staged"),
    # Acme Corp – 7
    _dev(13, "web-srv-01",  "Acme Corp"),
    _dev(14, "web-srv-02",  "Acme Corp"),
    _dev(15, "db-srv-01",   "Acme Corp", "Database Server"),
    _dev(16, "db-srv-02",   "Acme Corp", "Database Server", status="offline"),
    _dev(17, "app-srv-01",  "Acme Corp"),
    _dev(18, "app-srv-02",  "Acme Corp"),
    _dev(19, "lb-01",       "Acme Corp", "Load Balancer"),
    # Finance Dept – 4
    _dev(20, "fin-srv-01",  "Finance Dept"),
    _dev(21, "fin-db-01",   "Finance Dept", "Database Server"),
    _dev(22, "fin-bkp-01",  "Finance Dept"),
    _dev(23, "fin-fw-01",   "Finance Dept", "Firewall"),
    # Operations – 3
    _dev(24, "ops-srv-01",  "Operations"),
    _dev(25, "ops-srv-02",  "Operations"),
    _dev(26, "ops-mon-01",  "Operations", status="planned"),
    # Unassigned – 2
    _dev(27, "legacy-01",   None, status="decommissioning"),
    _dev(28, "legacy-02",   None),
]

EXAMPLE_VMS = [
    # Infrastructure – 6
    _vm(1,  "dns-01",          "Infrastructure", site="DC-Primary"),
    _vm(2,  "dns-02",          "Infrastructure", site="DC-Secondary"),
    _vm(3,  "ntp-01",          "Infrastructure"),
    _vm(4,  "smtp-relay",      "Infrastructure"),
    _vm(5,  "proxy-01",        "Infrastructure"),
    _vm(6,  "bastion-01",      "Infrastructure", site="DC-Primary"),
    # Acme Corp – 12
    _vm(7,  "acme-web-01",     "Acme Corp"),
    _vm(8,  "acme-web-02",     "Acme Corp"),
    _vm(9,  "acme-web-03",     "Acme Corp",  status="staged"),
    _vm(10, "acme-api-01",     "Acme Corp"),
    _vm(11, "acme-api-02",     "Acme Corp"),
    _vm(12, "acme-cache-01",   "Acme Corp"),
    _vm(13, "acme-cache-02",   "Acme Corp"),
    _vm(14, "acme-worker-01",  "Acme Corp"),
    _vm(15, "acme-worker-02",  "Acme Corp"),
    _vm(16, "acme-worker-03",  "Acme Corp",  status="planned"),
    _vm(17, "acme-db-01",      "Acme Corp",  "Database"),
    _vm(18, "acme-db-replica", "Acme Corp",  "Database"),
    # Finance Dept – 6
    _vm(19, "fin-erp-01",      "Finance Dept"),
    _vm(20, "fin-erp-02",      "Finance Dept"),
    _vm(21, "fin-reporting",   "Finance Dept"),
    _vm(22, "fin-backup",      "Finance Dept"),
    _vm(23, "fin-archive",     "Finance Dept"),
    _vm(24, "fin-dev",         "Finance Dept", status="staged"),
    # Operations – 5
    _vm(25, "ops-monitoring",  "Operations"),
    _vm(26, "ops-alerting",    "Operations"),
    _vm(27, "ops-logging",     "Operations"),
    _vm(28, "ops-ticket",      "Operations"),
    _vm(29, "ops-ansible",     "Operations"),
    # Unassigned – 3
    _vm(30, "test-vm-01",      None),
    _vm(31, "test-vm-02",      None),
    _vm(32, "dev-sandbox",     None, status="offline"),
]

# ── NetBox fetch ──────────────────────────────────────────────────────────────

def _fetch_all(endpoint: str) -> list:
    items = []
    url = f"{NETBOX_URL}/api/{endpoint}/?limit=1000"
    headers = {"Authorization": f"Token {NETBOX_TOKEN}", "Accept": "application/json"}
    while url:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        items.extend(data.get("results", []))
        url = data.get("next")
    return items


def get_inventory() -> tuple:
    if NETBOX_EXPORT_FILE:
        try:
            with open(NETBOX_EXPORT_FILE) as f:
                data = json.load(f)
            devices     = data.get("devices", [])
            vms         = data.get("virtual_machines", [])
            exported_at = data.get("exported_at", "")
            label       = f"export file ({exported_at})" if exported_at else "export file"
            return devices, vms, label, None
        except Exception as exc:
            return EXAMPLE_DEVICES, EXAMPLE_VMS, "example data", f"Export file error: {exc}"
    if NETBOX_URL and NETBOX_TOKEN:
        try:
            devices = _fetch_all("dcim/devices")
            vms     = _fetch_all("virtualization/virtual-machines")
            return devices, vms, NETBOX_URL, None
        except urllib.error.URLError as exc:
            return EXAMPLE_DEVICES, EXAMPLE_VMS, "example data", f"NetBox unreachable: {exc.reason}"
        except Exception as exc:
            return EXAMPLE_DEVICES, EXAMPLE_VMS, "example data", str(exc)
    return EXAMPLE_DEVICES, EXAMPLE_VMS, "example data", None

# ── Data normalization ────────────────────────────────────────────────────────

def _parse_status(item: dict) -> tuple[str, str]:
    s = item.get("status") or {}
    if isinstance(s, dict):
        val   = s.get("value", "")
        label = s.get("label", val.replace("-", " ").title())
    else:
        val = str(s)
        label = val.replace("-", " ").title()
    return val, label


def normalize(item: dict, kind: str) -> dict:
    tenant = (item.get("tenant") or {}).get("name") or ""
    if kind == "device":
        role = (item.get("device_role") or {}).get("name") or ""
        site = (item.get("site") or {}).get("name") or ""
    else:
        role = (item.get("role") or {}).get("name") or ""
        site = (item.get("site") or {}).get("name") or ""
        if not site:
            site = ((item.get("cluster") or {}).get("site") or {}).get("name") or ""
    status_val, status_label = _parse_status(item)
    return {
        "name":         item.get("name") or "",
        "kind":         kind,
        "tenant":       tenant,
        "role":         role,
        "status_val":   status_val,
        "status_label": status_label,
        "site":         site,
    }


def get_all_items(devices: list, vms: list) -> list:
    items = [normalize(d, "device") for d in devices]
    items += [normalize(v, "vm") for v in vms]
    items.sort(key=lambda x: x["name"].lower())
    return items

# ── HTML helpers ──────────────────────────────────────────────────────────────

def h(val) -> str:
    return _html.escape(str(val)) if val is not None else ""


def status_badge(val: str, label: str) -> str:
    cls = STATUS_CLASS.get(val.lower(), "secondary")
    return f'<span class="badge {cls}">{h(label or val)}</span>'


def type_badge(kind: str) -> str:
    return ('<span class="badge accent">Device</span>' if kind == "device"
            else '<span class="badge ok">VM</span>')

# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg:            #0f1117;
  --sidebar-bg:    #13151f;
  --surface:       #1a1d27;
  --surface-hover: #1e2130;
  --border:        #2a2d3a;
  --text:          #e2e8f0;
  --text-muted:    #8892a4;
  --text-faint:    #4a5068;
  --accent:        #6366f1;
  --accent-dim:    #2d2b6b;
  --heading:       #f1f5f9;
  --link:          #818cf8;
  --link-hover:    #a5b4fc;
  --ok:            #22c55e;
  --warn:          #f59e0b;
  --danger:        #ef4444;
  --sidebar-width: 220px;
  --header-height: 48px;
  --radius:        8px;
  --sans: "Segoe UI", system-ui, -apple-system, Helvetica, Arial, sans-serif;
  --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; }
body { display: flex; min-height: 100vh; background: var(--bg); color: var(--text); font-family: var(--sans); line-height: 1.6; }
a { color: var(--link); text-decoration: none; }
a:hover { color: var(--link-hover); text-decoration: underline; }

#sidebar { position: fixed; top: 0; left: 0; width: var(--sidebar-width); height: 100vh; background: var(--sidebar-bg); border-right: 1px solid var(--border); display: flex; flex-direction: column; z-index: 100; transition: transform 0.22s ease; }
.sidebar-brand { display: flex; align-items: center; gap: 10px; padding: 0 16px; height: var(--header-height); border-bottom: 1px solid var(--border); flex-shrink: 0; }
.sidebar-brand a { font-size: 1.05rem; font-weight: 700; color: var(--heading); text-decoration: none; letter-spacing: 0.02em; }
.brand-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 6px var(--accent); flex-shrink: 0; }
.sidebar-nav { flex: 1; overflow-y: auto; padding: 10px 8px 24px; scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
.nav-label { padding: 8px 8px 4px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); }
.nav-link { display: flex; align-items: center; padding: 6px 8px; border-radius: var(--radius); color: var(--text-muted); text-decoration: none; font-size: 0.83rem; transition: background 0.12s, color 0.12s; margin: 1px 0; }
.nav-link:hover { background: var(--surface-hover); color: var(--text); text-decoration: none; }
.nav-link.active { background: var(--accent-dim); color: var(--accent); }
.nav-divider { height: 1px; background: var(--border); margin: 8px 8px; }

#overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 90; }
#overlay.show { display: block; }

main { flex: 1; margin-left: var(--sidebar-width); min-width: 0; display: flex; flex-direction: column; min-height: 100vh; }

.topbar { position: sticky; top: 0; z-index: 50; height: var(--header-height); background: rgba(15,17,23,0.92); border-bottom: 1px solid var(--border); backdrop-filter: blur(8px); display: flex; align-items: center; padding: 0 24px; gap: 16px; }
#menu-btn { display: none; background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.1rem; padding: 4px; flex-shrink: 0; }
.topbar-title { font-size: 0.88rem; color: var(--text-muted); }
.topbar-title strong { color: var(--heading); font-weight: 600; }
.topbar-sub { margin-left: auto; font-size: 0.75rem; color: var(--text-faint); font-family: var(--mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 400px; }

.content-wrap { flex: 1; padding: 28px 28px 60px; }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.stat-card .num { font-size: 1.9rem; font-weight: 700; line-height: 1.1; }
.stat-card .lbl { color: var(--text-muted); font-size: .75rem; text-transform: uppercase; letter-spacing: .05em; margin-top: 4px; }
.num.ok     { color: var(--ok); }
.num.accent { color: var(--accent); }

.toolbar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.toolbar input[type=text] { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 7px 12px; border-radius: var(--radius); font-size: .82rem; flex: 1; min-width: 180px; font-family: var(--sans); outline: none; transition: border-color 0.15s; }
.toolbar input:focus { border-color: var(--accent); }
.toolbar select { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 7px 10px; border-radius: var(--radius); font-size: .82rem; font-family: var(--sans); cursor: pointer; outline: none; transition: border-color 0.15s; }
.toolbar select:focus { border-color: var(--accent); }
.btn { background: var(--accent); color: #fff; border: none; padding: 7px 16px; border-radius: var(--radius); cursor: pointer; font-size: .82rem; white-space: nowrap; font-family: var(--sans); transition: opacity 0.12s; }
.btn:hover { opacity: .85; }
.btn.secondary { background: var(--surface); border: 1px solid var(--border); color: var(--text); }
.row-count { margin-left: auto; color: var(--text-faint); font-size: .8rem; white-space: nowrap; }

table { width: 100%; border-collapse: collapse; font-size: .84rem; }
thead th { background: var(--surface); border-bottom: 1px solid var(--border); padding: 9px 12px; text-align: left; color: var(--text-muted); font-weight: 600; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.75rem; user-select: none; }
thead th[data-col] { cursor: pointer; }
thead th[data-col]:hover { color: var(--text); }
.sort-ind { color: var(--text-faint); }
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover { background: var(--surface-hover); }
td { padding: 9px 12px; vertical-align: middle; }
.mono { font-family: var(--mono); font-size: .8rem; }
.muted { color: var(--text-muted); }

.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: .72rem; font-weight: 600; }
.badge.ok        { background: #14532d; color: #86efac; }
.badge.danger    { background: #7f1d1d; color: #fca5a5; }
.badge.secondary { background: var(--border); color: var(--text-muted); }
.badge.info      { background: #1e1b4b; color: #a5b4fc; }
.badge.caution   { background: #7c2d12; color: #fed7aa; }
.badge.accent    { background: var(--accent-dim); color: var(--accent); }

.alert { padding: 10px 16px; border-radius: var(--radius); border: 1px solid; margin-bottom: 16px; font-size: .85rem; }
.alert-warn { background: #431407; border-color: #92400e; color: #fde68a; }
.alert-info { background: #1e1b4b; border-color: #3730a3; color: #a5b4fc; }

.empty { text-align: center; padding: 48px; color: var(--text-muted); }

@media (max-width: 768px) {
  #sidebar { transform: translateX(-100%); }
  #sidebar.open { transform: translateX(0); }
  main { margin-left: 0; }
  #menu-btn { display: block; }
  .topbar-sub { display: none; }
  .content-wrap { padding: 20px 16px 48px; }
  .row-count { display: none; }
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::selection { background: var(--accent-dim); color: var(--text); }
"""

# ── Page wrap ─────────────────────────────────────────────────────────────────

def page_wrap(title: str, body: str) -> str:
    js = r"""
(function(){
  // Sidebar toggle
  var btn = document.getElementById('menu-btn'),
      sb  = document.getElementById('sidebar'),
      ov  = document.getElementById('overlay');
  if(btn){
    function open(){ sb.classList.add('open'); ov.classList.add('show'); document.body.style.overflow='hidden'; }
    function close(){ sb.classList.remove('open'); ov.classList.remove('show'); document.body.style.overflow=''; }
    btn.addEventListener('click', function(){ sb.classList.contains('open') ? close() : open(); });
    ov.addEventListener('click', close);
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
  }

  // Filter + sort
  var tbody   = document.getElementById('device-tbody');
  if(!tbody) return;
  var rows    = Array.from(tbody.querySelectorAll('tr'));
  var countEl = document.getElementById('row-count');
  var fText   = document.getElementById('f-text');
  var fType   = document.getElementById('f-type');
  var fStatus = document.getElementById('f-status');
  var fTenant = document.getElementById('f-tenant');
  var sortCol = 'name';
  var sortDir = 'asc';

  function updateCount(){
    if(!countEl) return;
    var n = rows.filter(function(r){ return r.style.display !== 'none'; }).length;
    countEl.textContent = 'Showing ' + n.toLocaleString() + ' of ' + rows.length.toLocaleString();
  }

  function applyFilters(){
    var text   = fText   ? fText.value.trim().toLowerCase()   : '';
    var type   = fType   ? fType.value   : '';
    var status = fStatus ? fStatus.value : '';
    var tenant = fTenant ? fTenant.value : '';
    rows.forEach(function(row){
      var show = true;
      if(text   && !row.textContent.toLowerCase().includes(text)) show = false;
      if(type   && row.dataset.kind   !== type)   show = false;
      if(status && row.dataset.status !== status) show = false;
      if(tenant && row.dataset.tenant !== tenant) show = false;
      row.style.display = show ? '' : 'none';
    });
    updateCount();
  }

  function sortRows(col){
    sortDir = (sortCol === col && sortDir === 'asc') ? 'desc' : 'asc';
    sortCol = col;
    document.querySelectorAll('th[data-col] .sort-ind').forEach(function(el){
      var th = el.closest('th');
      el.textContent = th.dataset.col === sortCol
        ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ' ↕';
    });
    rows.sort(function(a, b){
      var av = (a.dataset[col] || '').toLowerCase();
      var bv = (b.dataset[col] || '').toLowerCase();
      return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    rows.forEach(function(row){ tbody.appendChild(row); });
    applyFilters();
  }

  [fText, fType, fStatus, fTenant].forEach(function(el){
    if(el) el.addEventListener('input', applyFilters);
  });

  document.querySelectorAll('th[data-col]').forEach(function(th){
    th.addEventListener('click', function(){ sortRows(th.dataset.col); });
  });

  var resetBtn = document.getElementById('f-reset');
  if(resetBtn){
    resetBtn.addEventListener('click', function(){
      if(fText)   fText.value   = '';
      if(fType)   fType.value   = '';
      if(fStatus) fStatus.value = '';
      if(fTenant) fTenant.value = '';
      applyFilters();
    });
  }

  updateCount();
})();
"""
    return (
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{h(title)} — NetBox — UNIXWeb</title>
<style>{CSS}</style>
</head>
<body>
<div id="overlay"></div>
<nav id="sidebar">
  <div class="sidebar-brand">
    <span class="brand-dot"></span>
    <a href="{WIKI_URL}">UNIXWeb</a>
  </div>
  <div class="sidebar-nav">
    <a href="{WIKI_URL}" class="nav-link">&#8592; Wiki Home</a>
    <div class="nav-divider"></div>
    <div class="nav-label">NetBox</div>
    <a href="netbox_inventory.cgi" class="nav-link">Inventory Summary</a>
    <a href="{SCRIPT_NAME}" class="nav-link active">Devices &amp; VMs</a>
  </div>
</nav>
<main>
  <div class="topbar">
    <button id="menu-btn" aria-label="Toggle menu">&#9776;</button>
    <div class="topbar-title"><strong>Devices &amp; Virtual Machines</strong></div>
    <div class="topbar-sub">{h(NETBOX_URL or NETBOX_EXPORT_FILE or "example data mode")}</div>
  </div>
  <div class="content-wrap">
    {body}
  </div>
  <footer style="padding:16px 28px;border-top:1px solid var(--border);
                 color:var(--text-faint);font-size:.75rem;text-align:center">
    UNIXWeb &mdash; NetBox Devices &amp; VMs
  </footer>
</main>
<script>{js}</script>
</body>
</html>"""
    )

# ── View ──────────────────────────────────────────────────────────────────────

def view_list(items: list, source: str, error: str | None) -> str:
    total         = len(items)
    total_devices = sum(1 for r in items if r["kind"] == "device")
    total_vms     = total - total_devices
    total_active  = sum(1 for r in items if r["status_val"] == "active")

    alerts = ""
    if error:
        alerts += f'<div class="alert alert-warn">&#9888; {h(error)} &mdash; showing example data.</div>'
    if source.startswith("export file"):
        alerts += (f'<div class="alert alert-info">&#9432; Showing exported data from '
                   f'<code>{h(NETBOX_EXPORT_FILE)}</code> &mdash; {h(source)}.</div>')
    elif source == "example data":
        alerts += ('<div class="alert alert-info">&#9432; Showing built-in example data. '
                   'Set <code>NETBOX_URL</code> and <code>NETBOX_TOKEN</code> '
                   'to connect to a real NetBox instance.</div>')

    stats_html = f"""
    <div class="stats">
      <div class="stat-card"><div class="num">{total:,}</div><div class="lbl">Total</div></div>
      <div class="stat-card"><div class="num accent">{total_devices:,}</div><div class="lbl">Devices</div></div>
      <div class="stat-card"><div class="num ok">{total_vms:,}</div><div class="lbl">Virtual Machines</div></div>
      <div class="stat-card"><div class="num ok">{total_active:,}</div><div class="lbl">Active</div></div>
    </div>"""

    tenants  = sorted(set(r["tenant"] for r in items if r["tenant"]))
    statuses = sorted(set((r["status_val"], r["status_label"]) for r in items),
                      key=lambda x: x[0])

    tenant_opts = '<option value="">All Tenants</option>' + "".join(
        f'<option value="{h(t)}">{h(t)}</option>' for t in tenants
    )
    status_opts = '<option value="">All Statuses</option>' + "".join(
        f'<option value="{h(v)}">{h(l)}</option>' for v, l in statuses
    )

    toolbar = f"""
    <div class="toolbar">
      <input id="f-text" type="text" placeholder="Search name, role, site&#x2026;" autocomplete="off">
      <select id="f-type">
        <option value="">All Types</option>
        <option value="device">Device</option>
        <option value="vm">VM</option>
      </select>
      <select id="f-status">{status_opts}</select>
      <select id="f-tenant">{tenant_opts}</select>
      <button id="f-reset" class="btn secondary">Reset</button>
      <span id="row-count" class="row-count"></span>
    </div>"""

    if not items:
        return alerts + stats_html + toolbar + '<div class="empty">No items found.</div>'

    rows_html = []
    for r in items:
        rows_html.append(
            f'<tr data-name="{h(r["name"])}" data-kind="{h(r["kind"])}" '
            f'data-tenant="{h(r["tenant"])}" data-role="{h(r["role"])}" '
            f'data-status="{h(r["status_val"])}" data-site="{h(r["site"])}">'
            f'<td class="mono">{h(r["name"])}</td>'
            f'<td>{type_badge(r["kind"])}</td>'
            f'<td>{h(r["tenant"]) or DASH}</td>'
            f'<td>{h(r["role"])   or DASH}</td>'
            f'<td>{status_badge(r["status_val"], r["status_label"])}</td>'
            f'<td>{h(r["site"])   or DASH}</td>'
            f'</tr>'
        )

    table_html = f"""
    <table>
      <thead>
        <tr>
          <th data-col="name">Name<span class="sort-ind"> &#x2195;</span></th>
          <th data-col="kind">Type<span class="sort-ind"> &#x2195;</span></th>
          <th data-col="tenant">Tenant<span class="sort-ind"> &#x2195;</span></th>
          <th data-col="role">Role<span class="sort-ind"> &#x2195;</span></th>
          <th data-col="status">Status<span class="sort-ind"> &#x2195;</span></th>
          <th data-col="site">Site<span class="sort-ind"> &#x2195;</span></th>
        </tr>
      </thead>
      <tbody id="device-tbody">{"".join(rows_html)}</tbody>
    </table>"""

    return alerts + stats_html + toolbar + table_html

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    devices, vms, source, error = get_inventory()
    items = get_all_items(devices, vms)
    body  = view_list(items, source, error)
    print(page_wrap("Devices & VMs", body))


if __name__ == "__main__":
    main()
