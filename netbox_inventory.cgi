#!/usr/bin/env python3
"""
CGI inventory summary dashboard sourced from NetBox.

Built-in example data is shown when NETBOX_URL is not configured.

Usage:
    NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=xxx python3 netbox_inventory.cgi
    python3 -m http.server --cgi 8080   # example mode, no env vars needed
    # Open http://localhost:8080/cgi-bin/netbox_inventory.cgi
"""

import cgitb
import html as _html
import json
import math
import os
import urllib.request
import urllib.error

cgitb.enable()

# ── Config ────────────────────────────────────────────────────────────────────

NETBOX_URL   = os.environ.get("NETBOX_URL", "").rstrip("/")
NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN", "")
WIKI_URL     = os.environ.get("WIKI_URL", "http://localhost:8080/")
SCRIPT_NAME  = os.environ.get("SCRIPT_NAME", "netbox_inventory.cgi")

CHART_COLORS = [
    "#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
    "#06b6d4", "#f97316", "#ec4899", "#14b8a6", "#a855f7",
]
DEVICE_COLOR = "#6366f1"
VM_COLOR     = "#22c55e"
UNASSIGNED   = "(Unassigned)"

# ── Example subset ────────────────────────────────────────────────────────────

def _dev(id_, name, tenant, role="Server", site="DC-Primary"):
    t = {"id": id_, "name": tenant} if tenant else None
    return {"id": id_, "name": name, "tenant": t,
            "device_role": {"name": role}, "site": {"name": site}}

def _vm(id_, name, tenant, role="Application"):
    t = {"id": id_, "name": tenant} if tenant else None
    return {"id": id_, "name": name, "tenant": t, "role": {"name": role}}


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
    _dev(12, "kvm-host-03", "Infrastructure", "Server", "DC-Secondary"),
    # Acme Corp – 7
    _dev(13, "web-srv-01",  "Acme Corp"),
    _dev(14, "web-srv-02",  "Acme Corp"),
    _dev(15, "db-srv-01",   "Acme Corp", "Database Server"),
    _dev(16, "db-srv-02",   "Acme Corp", "Database Server"),
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
    _dev(26, "ops-mon-01",  "Operations"),
    # Unassigned – 2
    _dev(27, "legacy-01",   None),
    _dev(28, "legacy-02",   None),
]

EXAMPLE_VMS = [
    # Infrastructure – 6
    _vm(1,  "dns-01",          "Infrastructure"),
    _vm(2,  "dns-02",          "Infrastructure"),
    _vm(3,  "ntp-01",          "Infrastructure"),
    _vm(4,  "smtp-relay",      "Infrastructure"),
    _vm(5,  "proxy-01",        "Infrastructure"),
    _vm(6,  "bastion-01",      "Infrastructure"),
    # Acme Corp – 12
    _vm(7,  "acme-web-01",     "Acme Corp"),
    _vm(8,  "acme-web-02",     "Acme Corp"),
    _vm(9,  "acme-web-03",     "Acme Corp"),
    _vm(10, "acme-api-01",     "Acme Corp"),
    _vm(11, "acme-api-02",     "Acme Corp"),
    _vm(12, "acme-cache-01",   "Acme Corp"),
    _vm(13, "acme-cache-02",   "Acme Corp"),
    _vm(14, "acme-worker-01",  "Acme Corp"),
    _vm(15, "acme-worker-02",  "Acme Corp"),
    _vm(16, "acme-worker-03",  "Acme Corp"),
    _vm(17, "acme-db-01",      "Acme Corp", "Database"),
    _vm(18, "acme-db-replica", "Acme Corp", "Database"),
    # Finance Dept – 6
    _vm(19, "fin-erp-01",      "Finance Dept"),
    _vm(20, "fin-erp-02",      "Finance Dept"),
    _vm(21, "fin-reporting",   "Finance Dept"),
    _vm(22, "fin-backup",      "Finance Dept"),
    _vm(23, "fin-archive",     "Finance Dept"),
    _vm(24, "fin-dev",         "Finance Dept"),
    # Operations – 5
    _vm(25, "ops-monitoring",  "Operations"),
    _vm(26, "ops-alerting",    "Operations"),
    _vm(27, "ops-logging",     "Operations"),
    _vm(28, "ops-ticket",      "Operations"),
    _vm(29, "ops-ansible",     "Operations"),
    # Unassigned – 3
    _vm(30, "test-vm-01",      None),
    _vm(31, "test-vm-02",      None),
    _vm(32, "dev-sandbox",     None),
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
    """Return (devices, vms, source_label, error_msg|None)."""
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

# ── Data processing ───────────────────────────────────────────────────────────

def group_by_tenant(devices: list, vms: list) -> list:
    counts: dict = {}
    for item in devices:
        t = (item.get("tenant") or {}).get("name") or UNASSIGNED
        counts.setdefault(t, [0, 0])[0] += 1
    for item in vms:
        t = (item.get("tenant") or {}).get("name") or UNASSIGNED
        counts.setdefault(t, [0, 0])[1] += 1
    rows = [
        {"tenant": k, "devices": v[0], "vms": v[1], "total": v[0] + v[1]}
        for k, v in counts.items()
    ]
    rows.sort(key=lambda r: (r["tenant"] == UNASSIGNED, -r["total"]))
    return rows

# ── SVG donut chart ───────────────────────────────────────────────────────────

def _svg_donut(slices: list, size: int = 180, hole: float = 0.55,
               center_val: str = "", center_sub: str = "") -> str:
    total = sum(v for _, v, _ in slices)
    if total == 0:
        return (f'<svg width="{size}" height="{size}"><text x="50%" y="50%" '
                f'dominant-baseline="middle" text-anchor="middle" fill="#8892a4" '
                f'font-size="12">No data</text></svg>')

    cx = cy = size / 2
    r_out = size / 2 - 4
    r_in  = r_out * hole
    paths = []
    angle = -math.pi / 2

    for label, value, color in slices:
        if value <= 0:
            continue
        sweep = 2 * math.pi * value / total
        if sweep >= 2 * math.pi:
            sweep = 2 * math.pi - 1e-6
        a2 = angle + sweep
        x1o = cx + r_out * math.cos(angle); y1o = cy + r_out * math.sin(angle)
        x2o = cx + r_out * math.cos(a2);    y2o = cy + r_out * math.sin(a2)
        x1i = cx + r_in  * math.cos(a2);    y1i = cy + r_in  * math.sin(a2)
        x2i = cx + r_in  * math.cos(angle); y2i = cy + r_in  * math.sin(angle)
        lg = 1 if sweep > math.pi else 0
        d = (f"M{x1o:.2f},{y1o:.2f} A{r_out:.2f},{r_out:.2f} 0 {lg},1 "
             f"{x2o:.2f},{y2o:.2f} L{x1i:.2f},{y1i:.2f} "
             f"A{r_in:.2f},{r_in:.2f} 0 {lg},0 {x2i:.2f},{y2i:.2f} Z")
        pct = value / total * 100
        paths.append(
            f'<path d="{d}" fill="{color}" stroke="#0f1117" stroke-width="2" '
            f'data-label="{_html.escape(label)}" data-value="{value}" data-pct="{pct:.1f}" '
            f'style="cursor:pointer;transition:opacity 0.15s"></path>'
        )
        angle += sweep

    center = ""
    if center_val:
        center = (
            f'<text x="{cx:.1f}" y="{cy - 7:.1f}" dominant-baseline="middle" '
            f'text-anchor="middle" fill="#f1f5f9" font-size="24" font-weight="700" '
            f'font-family="Segoe UI,system-ui,sans-serif">{_html.escape(center_val)}</text>'
        )
    if center_sub:
        center += (
            f'<text x="{cx:.1f}" y="{cy + 14:.1f}" dominant-baseline="middle" '
            f'text-anchor="middle" fill="#8892a4" font-size="10" '
            f'font-family="Segoe UI,system-ui,sans-serif">{_html.escape(center_sub)}</text>'
        )

    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            + "".join(paths) + center + '</svg>')


def _donut_legend(slices: list, total: int) -> str:
    items = []
    for label, value, color in slices:
        if value <= 0:
            continue
        pct = value / total * 100 if total else 0
        items.append(
            f'<div class="legend-item" data-label="{_html.escape(label)}" '
            f'data-value="{value}" data-pct="{pct:.1f}" '
            f'style="cursor:default;transition:opacity 0.15s">'
            f'<span class="legend-swatch" style="background:{color}"></span>'
            f'<span class="legend-label">{_html.escape(label)}</span>'
            f'<span class="legend-val">{value:,}</span>'
            f'<span class="legend-pct">{pct:.1f}%</span>'
            f'</div>'
        )
    return '<div class="donut-legend">' + "".join(items) + '</div>'


def _chart_card(title: str, slices: list, center_sub: str = "total") -> str:
    total = sum(v for _, v, _ in slices)
    svg   = _svg_donut(slices, size=180, center_val=f"{total:,}", center_sub=center_sub)
    leg   = _donut_legend(slices, total)
    return (f'<div class="chart-card"><h3>{_html.escape(title)}</h3>'
            f'<div class="chart-body">{svg}{leg}</div></div>')

# ── HTML ──────────────────────────────────────────────────────────────────────

def h(val) -> str:
    return _html.escape(str(val)) if val is not None else ""


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

body {
  display: flex; min-height: 100vh;
  background: var(--bg); color: var(--text);
  font-family: var(--sans); line-height: 1.6;
}

a { color: var(--link); text-decoration: none; }
a:hover { color: var(--link-hover); text-decoration: underline; }

#sidebar {
  position: fixed; top: 0; left: 0;
  width: var(--sidebar-width); height: 100vh;
  background: var(--sidebar-bg); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; z-index: 100;
  transition: transform 0.22s ease;
}
.sidebar-brand {
  display: flex; align-items: center; gap: 10px;
  padding: 0 16px; height: var(--header-height);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}
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

.topbar {
  position: sticky; top: 0; z-index: 50;
  height: var(--header-height);
  background: rgba(15,17,23,0.92);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(8px);
  display: flex; align-items: center; padding: 0 24px; gap: 16px;
}
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

.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
.chart-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
.chart-card h3 { font-size: .72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 16px; }
.chart-body { display: flex; align-items: center; gap: 20px; }
.donut-legend { flex: 1; min-width: 0; }
.legend-item { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; font-size: .83rem; }
.legend-swatch { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
.legend-label { color: var(--text-muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.legend-val   { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
.legend-pct   { color: var(--text-faint); font-size: .75rem; min-width: 3.5em; text-align: right; }

table { width: 100%; border-collapse: collapse; font-size: .84rem; }
thead th { background: var(--surface); border-bottom: 1px solid var(--border); padding: 9px 12px; text-align: left; color: var(--text-muted); font-weight: 600; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.75rem; }
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover { background: var(--surface-hover); }
td { padding: 9px 12px; vertical-align: middle; }

.detail-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
.detail-card h3 { font-size: .72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 14px; }

.alert { padding: 10px 16px; border-radius: var(--radius); border: 1px solid; margin-bottom: 16px; font-size: .85rem; }
.alert-warn { background: #431407; border-color: #92400e; color: #fde68a; }
.alert-info { background: #1e1b4b; border-color: #3730a3; color: #a5b4fc; }

.empty { text-align: center; padding: 48px; color: var(--text-muted); }

@media (max-width: 900px) { .charts-row { grid-template-columns: 1fr; } }
@media (max-width: 768px) {
  #sidebar { transform: translateX(-100%); }
  #sidebar.open { transform: translateX(0); }
  main { margin-left: 0; }
  #menu-btn { display: block; }
  .topbar-sub { display: none; }
  .content-wrap { padding: 20px 16px 48px; }
  .chart-body { flex-direction: column; align-items: flex-start; }
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::selection { background: var(--accent-dim); color: var(--text); }

#chart-tip {
  display: none;
  position: absolute;
  z-index: 9999;
  background: #1a1d27;
  border: 1px solid #2a2d3a;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: .82rem;
  color: #e2e8f0;
  pointer-events: none;
  white-space: nowrap;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  font-family: "Segoe UI", system-ui, sans-serif;
}
#chart-tip strong { color: #f1f5f9; display: block; margin-bottom: 3px; font-size: .88rem; }
"""


def page_wrap(title: str, body: str) -> str:
    js = """
(function(){
  // Sidebar toggle
  var btn=document.getElementById('menu-btn'),
      sb=document.getElementById('sidebar'),
      ov=document.getElementById('overlay');
  if(btn){
    function open(){ sb.classList.add('open'); ov.classList.add('show'); document.body.style.overflow='hidden'; }
    function close(){ sb.classList.remove('open'); ov.classList.remove('show'); document.body.style.overflow=''; }
    btn.addEventListener('click', function(){ sb.classList.contains('open') ? close() : open(); });
    ov.addEventListener('click', close);
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
  }

  // Chart tooltips
  var tip = document.createElement('div');
  tip.id = 'chart-tip';
  document.body.appendChild(tip);

  function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function tipShow(e, label, value, pct){
    tip.innerHTML = '<strong>' + esc(label) + '</strong>'
      + '<div style="display:flex;gap:10px;align-items:baseline;margin-top:2px">'
      + '<span style="font-size:1.05em;font-weight:600">' + Number(value).toLocaleString() + '</span>'
      + '<span style="color:#8892a4;font-size:.85em">' + pct + '%</span>'
      + '</div>';
    tip.style.display = 'block';
    tipMove(e);
  }

  function tipMove(e){
    var x = e.clientX + window.pageXOffset + 16;
    var y = e.clientY + window.pageYOffset - 10;
    if(e.clientX + 170 > window.innerWidth) x = e.clientX + window.pageXOffset - (tip.offsetWidth || 150) - 10;
    tip.style.left = x + 'px';
    tip.style.top  = y + 'px';
  }

  function tipHide(){ tip.style.display = 'none'; }

  function highlight(card, activeLabel){
    card.querySelectorAll('path[data-label]').forEach(function(p){
      p.style.opacity = (!activeLabel || p.dataset.label === activeLabel) ? '1' : '0.25';
    });
    card.querySelectorAll('.legend-item[data-label]').forEach(function(li){
      li.style.opacity = (!activeLabel || li.dataset.label === activeLabel) ? '1' : '0.35';
    });
  }

  document.addEventListener('mouseover', function(e){
    var el = e.target.closest && e.target.closest('path[data-label], .legend-item[data-label]');
    if(!el) return;
    var card = el.closest('.chart-card');
    if(!card) return;
    highlight(card, el.dataset.label);
    tipShow(e, el.dataset.label, el.dataset.value, el.dataset.pct);
  });

  document.addEventListener('mousemove', function(e){
    if(tip.style.display === 'block') tipMove(e);
  });

  document.addEventListener('mouseout', function(e){
    var el = e.target.closest && e.target.closest('path[data-label], .legend-item[data-label]');
    if(!el) return;
    var card = el.closest('.chart-card');
    if(!card) return;
    var related = e.relatedTarget;
    if(related && related.closest && related.closest('.chart-card') === card) return;
    highlight(card, null);
    tipHide();
  });
})();
"""
    return (
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{h(title)} — NetBox Inventory — UNIXWeb</title>
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
    <a href="{SCRIPT_NAME}" class="nav-link active">Inventory Summary</a>
  </div>
</nav>
<main>
  <div class="topbar">
    <button id="menu-btn" aria-label="Toggle menu">&#9776;</button>
    <div class="topbar-title"><strong>NetBox Inventory</strong></div>
    <div class="topbar-sub">{h(NETBOX_URL or "example data mode")}</div>
  </div>
  <div class="content-wrap">
    {body}
  </div>
  <footer style="padding:16px 28px;border-top:1px solid var(--border);
                 color:var(--text-faint);font-size:.75rem;text-align:center">
    UNIXWeb &mdash; NetBox Inventory Summary
  </footer>
</main>
<script>{js}</script>
</body>
</html>"""
    )

# ── View ──────────────────────────────────────────────────────────────────────

def view_summary(rows: list, total_devices: int, total_vms: int,
                 source: str, error: str | None) -> str:
    total   = total_devices + total_vms
    tenants = len(rows)

    alerts = ""
    if error:
        alerts += f'<div class="alert alert-warn">&#9888; {h(error)} &mdash; showing example data.</div>'
    if source == "example data":
        alerts += ('<div class="alert alert-info">&#9432; Showing built-in example data. '
                   'Set <code>NETBOX_URL</code> and <code>NETBOX_TOKEN</code> '
                   'environment variables to connect to a real NetBox instance.</div>')

    stats_html = f"""
    <div class="stats">
      <div class="stat-card"><div class="num">{total:,}</div><div class="lbl">Total Items</div></div>
      <div class="stat-card"><div class="num accent">{total_devices:,}</div><div class="lbl">Devices</div></div>
      <div class="stat-card"><div class="num ok">{total_vms:,}</div><div class="lbl">Virtual Machines</div></div>
      <div class="stat-card"><div class="num">{tenants:,}</div><div class="lbl">Tenants</div></div>
    </div>"""

    tenant_slices = [
        (r["tenant"], r["total"], CHART_COLORS[i % len(CHART_COLORS)])
        for i, r in enumerate(rows)
    ]
    type_slices = [
        ("Devices",          total_devices, DEVICE_COLOR),
        ("Virtual Machines", total_vms,     VM_COLOR),
    ]

    charts_html = f"""
    <div class="charts-row">
      {_chart_card("Inventory by Tenant", tenant_slices, "items")}
      {_chart_card("Devices vs Virtual Machines", type_slices, "items")}
    </div>"""

    if not rows:
        table_html = '<div class="empty">No inventory found.</div>'
    else:
        rows_html = []
        for i, r in enumerate(rows):
            color   = CHART_COLORS[i % len(CHART_COLORS)]
            pct     = r["total"] / total * 100 if total else 0
            dev_pct = r["devices"] / r["total"] * 100 if r["total"] else 0
            vm_pct  = r["vms"]     / r["total"] * 100 if r["total"] else 0
            rows_html.append(f"""
        <tr>
          <td>
            <span style="display:inline-block;width:10px;height:10px;border-radius:2px;
                         background:{color};margin-right:8px;vertical-align:middle"></span>
            {h(r["tenant"])}
          </td>
          <td style="text-align:right">{r["devices"]:,}</td>
          <td style="text-align:right">{r["vms"]:,}</td>
          <td style="text-align:right"><strong>{r["total"]:,}</strong></td>
          <td style="min-width:110px">
            <div style="display:flex;align-items:center;gap:8px">
              <div style="flex:1;background:var(--border);border-radius:3px;height:5px;overflow:hidden">
                <div style="width:{min(100,pct):.1f}%;background:{color};height:100%"></div>
              </div>
              <span style="color:var(--text-muted);font-size:.8rem;min-width:3.2em;text-align:right">{pct:.1f}%</span>
            </div>
          </td>
          <td style="min-width:120px">
            <div style="display:flex;border-radius:3px;overflow:hidden;height:6px" title="Devices {dev_pct:.0f}% / VMs {vm_pct:.0f}%">
              <div style="width:{dev_pct:.1f}%;background:{DEVICE_COLOR}"></div>
              <div style="width:{vm_pct:.1f}%;background:{VM_COLOR}"></div>
            </div>
          </td>
        </tr>""")

        table_html = f"""
    <div class="detail-card">
      <h3>Breakdown by Tenant</h3>
      <table>
        <thead>
          <tr>
            <th>Tenant</th>
            <th style="text-align:right">Devices</th>
            <th style="text-align:right">VMs</th>
            <th style="text-align:right">Total</th>
            <th>Share of Inventory</th>
            <th title="Indigo = devices, green = VMs">Device / VM Split</th>
          </tr>
        </thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>"""

    return alerts + stats_html + charts_html + table_html

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    devices, vms, source, error = get_inventory()
    rows = group_by_tenant(devices, vms)
    body = view_summary(rows, len(devices), len(vms), source, error)
    print(page_wrap("Inventory Summary", body))


if __name__ == "__main__":
    main()
