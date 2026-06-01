#!/usr/bin/env python3
"""
CGI script to display SSL certificate SQLite database contents.

Setup:
    chmod +x ssl_certs.cgi
    cp ssl_certs.cgi /usr/lib/cgi-bin/
    cp ssl_certs.db  /usr/lib/cgi-bin/   # or set DB_PATH below

Test locally (no web server needed):
    python3 -m http.server --cgi 8080
    # then open http://localhost:8080/cgi-bin/ssl_certs.cgi
"""

import cgi
import cgitb
import html
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

cgitb.enable()  # show tracebacks in browser during development

# ── Config ────────────────────────────────────────────────────────────────────

# Path to the database — override via env var or edit here
DB_PATH = os.environ.get("SSL_DB_PATH",
          os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssl_certs.db"))

PAGE_SIZE = 50

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def qs() -> dict:
    """Parse query string into a flat dict of first values."""
    raw = os.environ.get("QUERY_STRING", "")
    parsed = parse_qs(raw)
    return {k: v[0] for k, v in parsed.items()}


def h(val) -> str:
    """HTML-escape a value."""
    return html.escape(str(val)) if val is not None else ""


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{h(text)}</span>'


def expiry_badge(is_expired: int, days: int | None) -> str:
    if is_expired:
        return badge("EXPIRED", "danger")
    if days is None:
        return badge("unknown", "secondary")
    if days <= 14:
        return badge(f"{days}d", "warning")
    if days <= 30:
        return badge(f"{days}d", "caution")
    return badge(f"{days}d", "ok")


def compute_expiry(not_after_str: str) -> tuple[bool, int | None]:
    """Dynamically compute (is_expired, days_remaining) from a not_after string."""
    if not not_after_str:
        return False, None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%b %d %H:%M:%S %Y GMT"):
        try:
            exp = datetime.strptime(not_after_str, fmt).replace(tzinfo=timezone.utc)
            delta = (exp - datetime.now(tz=timezone.utc)).days
            return delta < 0, delta
        except ValueError:
            continue
    return False, None


# ── Queries ───────────────────────────────────────────────────────────────────

def summary_stats(conn) -> dict:
    row = conn.execute("""
        SELECT
            COUNT(*)                                                                AS total,
            SUM(CASE WHEN julianday(not_after) < julianday('now') THEN 1 END)      AS expired,
            SUM(CASE WHEN julianday(not_after) - julianday('now') BETWEEN 0 AND 30
                      THEN 1 END)                                                  AS expiring_soon,
            COUNT(DISTINCT host)                                                    AS unique_hosts,
            MAX(created_at)                                                         AS last_scan
        FROM certificates
    """).fetchone()
    return dict(row) if row else {}


def list_certificates(conn, params: dict) -> tuple[list, int]:
    where, args = [], []

    if params.get("filter"):
        f = f"%{params['filter']}%"
        where.append("(c.host LIKE ? OR c.subject_cn LIKE ? OR c.issuer_org LIKE ?)")
        args += [f, f, f]
    if params.get("expired") == "1":
        where.append("julianday(c.not_after) < julianday('now')")
    if params.get("expiring") == "1":
        where.append("julianday(c.not_after) - julianday('now') BETWEEN 0 AND 30")
    if params.get("scan_id"):
        where.append("c.scan_id = ?")
        args.append(params["scan_id"])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM certificates c {where_sql}", args
    ).fetchone()[0]

    page   = max(1, int(params.get("page", 1)))
    offset = (page - 1) * PAGE_SIZE

    rows = conn.execute(f"""
        SELECT c.id, c.host, c.ip, c.port, c.subject_cn, c.subject_org,
               c.issuer_org, c.not_before, c.not_after,
               c.is_expired, c.days_remaining,
               c.key_type, c.key_bits, c.sig_algo,
               c.fingerprint_sha1, c.subject_alt_names,
               c.scan_id, s.scanned_at
        FROM   certificates c
        JOIN   scans s ON c.scan_id = s.id
        {where_sql}
        ORDER  BY c.not_after ASC
        LIMIT  ? OFFSET ?
    """, args + [PAGE_SIZE, offset]).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        is_expired, days = compute_expiry(d.get("not_after", ""))
        d["is_expired"] = int(is_expired)
        d["days_remaining"] = days
        result.append(d)
    return result, total


def get_certificate(conn, cert_id: int) -> dict | None:
    row = conn.execute("""
        SELECT c.*, s.scanned_at, s.target, s.nmap_args
        FROM   certificates c
        JOIN   scans s ON c.scan_id = s.id
        WHERE  c.id = ?
    """, [cert_id]).fetchone()
    if not row:
        return None
    cert = dict(row)
    is_expired, days = compute_expiry(cert.get("not_after", ""))
    cert["is_expired"] = int(is_expired)
    cert["days_remaining"] = days
    return cert


def list_scans(conn) -> list:
    rows = conn.execute("""
        SELECT s.id, s.scanned_at, s.target, s.nmap_args,
               COUNT(c.id) AS cert_count
        FROM   scans s
        LEFT JOIN certificates c ON c.scan_id = s.id
        GROUP  BY s.id
        ORDER  BY s.scanned_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


# ── HTML layout ───────────────────────────────────────────────────────────────

SCRIPT_NAME = os.environ.get("SCRIPT_NAME", "ssl_certs.cgi")

CSS = """
:root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e2e8f0; --muted: #8892a4; --accent: #6366f1;
    --ok: #22c55e; --warn: #f59e0b; --danger: #ef4444; --caution: #fb923c;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font: 14px/1.6 'Segoe UI', system-ui, sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

header { background: var(--surface); border-bottom: 1px solid var(--border);
         padding: 14px 24px; display: flex; align-items: center; gap: 16px; }
header h1 { font-size: 1.1rem; font-weight: 600; }
header .sub { color: var(--muted); font-size: .85rem; }

.container { max-width: 1400px; margin: 0 auto; padding: 24px; }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr));
         gap: 12px; margin-bottom: 24px; }
.stat-card { background: var(--surface); border: 1px solid var(--border);
             border-radius: 8px; padding: 16px; }
.stat-card .num { font-size: 2rem; font-weight: 700; }
.stat-card .lbl { color: var(--muted); font-size: .8rem; text-transform: uppercase;
                  letter-spacing: .05em; }
.num.danger { color: var(--danger); }
.num.warn   { color: var(--warn); }
.num.ok     { color: var(--ok); }

.toolbar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.toolbar input[type=text] {
    background: var(--surface); border: 1px solid var(--border); color: var(--text);
    padding: 7px 12px; border-radius: 6px; font-size: .9rem; flex: 1; min-width: 200px; }
.toolbar input:focus { outline: none; border-color: var(--accent); }
.btn { background: var(--accent); color: #fff; border: none; padding: 7px 16px;
       border-radius: 6px; cursor: pointer; font-size: .85rem; white-space: nowrap; }
.btn:hover { opacity: .85; }
.btn.secondary { background: var(--surface); border: 1px solid var(--border); color: var(--text); }
.btn.danger-btn { background: #7f1d1d; }

table { width: 100%; border-collapse: collapse; font-size: .85rem; }
thead th { background: var(--surface); border-bottom: 1px solid var(--border);
           padding: 10px 12px; text-align: left; color: var(--muted);
           font-weight: 600; white-space: nowrap; }
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover { background: var(--surface); }
td { padding: 9px 12px; vertical-align: middle; }
.mono { font-family: monospace; font-size: .8rem; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
         font-size: .75rem; font-weight: 600; }
.badge.ok       { background: #14532d; color: #86efac; }
.badge.warn     { background: #713f12; color: #fde68a; }
.badge.caution  { background: #7c2d12; color: #fed7aa; }
.badge.danger   { background: #7f1d1d; color: #fca5a5; }
.badge.secondary{ background: var(--border); color: var(--muted); }
.badge.info     { background: #1e3a5f; color: #93c5fd; }

.pagination { display: flex; gap: 8px; margin-top: 20px; align-items: center; }
.pagination a, .pagination span {
    padding: 5px 12px; border-radius: 6px; border: 1px solid var(--border);
    font-size: .85rem; }
.pagination a:hover { background: var(--surface); text-decoration: none; }
.pagination .current { background: var(--accent); color: #fff; border-color: var(--accent); }

.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.detail-card { background: var(--surface); border: 1px solid var(--border);
               border-radius: 8px; padding: 20px; }
.detail-card h3 { font-size: .85rem; color: var(--muted); text-transform: uppercase;
                  letter-spacing: .05em; margin-bottom: 14px; }
.kv { display: flex; gap: 12px; margin-bottom: 8px; font-size: .875rem; }
.kv .k { color: var(--muted); min-width: 130px; flex-shrink: 0; }
.kv .v { word-break: break-all; }
pre { background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
      padding: 14px; font-size: .8rem; overflow-x: auto; white-space: pre-wrap; }
.tabs { display: flex; gap: 0; margin-bottom: 0; border-bottom: 1px solid var(--border); }
.tabs a { padding: 10px 20px; border-bottom: 2px solid transparent; color: var(--muted);
          font-size: .9rem; }
.tabs a.active { border-bottom-color: var(--accent); color: var(--text); }
.tab-content { padding-top: 24px; }
.scans-table td, .scans-table th { padding: 10px 14px; }
.empty { text-align: center; padding: 48px; color: var(--muted); }
"""


def page_wrap(title: str, body: str, active_tab: str = "certs") -> str:
    tabs = [
        ("certs",  f"{SCRIPT_NAME}",              "Certificates"),
        ("scans",  f"{SCRIPT_NAME}?view=scans",   "Scans"),
    ]
    tab_html = "".join(
        f'<a href="{url}" class="{"active" if t == active_tab else ""}">{label}</a>'
        for t, url, label in tabs
    )
    return f"""Content-Type: text/html; charset=utf-8\r\n\r\n<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{h(title)} — SSL Cert DB</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div>
    <h1>🔒 SSL Certificate Database</h1>
    <div class="sub">{h(DB_PATH)}</div>
  </div>
</header>
<div class="container">
  <nav class="tabs">{tab_html}</nav>
  <div class="tab-content">{body}</div>
</div>
</body></html>"""


# ── Views ─────────────────────────────────────────────────────────────────────

def view_certs(conn, params: dict) -> str:
    stats  = summary_stats(conn)
    rows, total = list_certificates(conn, params)
    page   = max(1, int(params.get("page", 1)))
    pages  = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Stats bar
    stat_html = f"""
    <div class="stats">
      <div class="stat-card"><div class="num ok">{stats.get('total',0)}</div><div class="lbl">Total Certs</div></div>
      <div class="stat-card"><div class="num {'danger' if stats.get('expired',0) else 'ok'}">{stats.get('expired',0)}</div><div class="lbl">Expired</div></div>
      <div class="stat-card"><div class="num {'warn' if stats.get('expiring_soon',0) else 'ok'}">{stats.get('expiring_soon',0)}</div><div class="lbl">Expiring ≤30d</div></div>
      <div class="stat-card"><div class="num">{stats.get('unique_hosts',0)}</div><div class="lbl">Unique Hosts</div></div>
      <div class="stat-card"><div class="num" style="font-size:1rem">{h(stats.get('last_scan','—'))}</div><div class="lbl">Last Scan</div></div>
    </div>"""

    # Toolbar
    fval    = h(params.get("filter", ""))
    exp_chk = 'checked' if params.get("expired") == "1" else ""
    soon_chk= 'checked' if params.get("expiring") == "1" else ""
    toolbar = f"""
    <form method="get" action="{SCRIPT_NAME}">
      <div class="toolbar">
        <input type="text" name="filter" value="{fval}" placeholder="Filter by host, CN, or issuer…">
        <label style="color:var(--muted);font-size:.85rem">
          <input type="checkbox" name="expired" value="1" {exp_chk}> Expired only
        </label>
        <label style="color:var(--muted);font-size:.85rem">
          <input type="checkbox" name="expiring" value="1" {soon_chk}> Expiring ≤30d
        </label>
        <button class="btn" type="submit">Filter</button>
        <a class="btn secondary" href="{SCRIPT_NAME}">Reset</a>
        <a class="btn secondary" href="{SCRIPT_NAME}?fmt=json{('&filter='+h(params.get('filter','')))}">⬇ JSON</a>
      </div>
    </form>"""

    # Table
    if not rows:
        table = '<div class="empty">No certificates found.</div>'
    else:
        def row_html(r):
            host  = h(r["host"] or r["ip"])
            port  = h(r["port"])
            cn    = h(r["subject_cn"] or "—")
            issuer= h(r["issuer_org"] or "—")
            algo  = h(r["sig_algo"] or "—")
            key   = f'{h(r["key_type"] or "")} {h(r["key_bits"] or "")}b' if r.get("key_type") else "—"
            expiry= expiry_badge(r["is_expired"], r["days_remaining"])
            nb    = h(r["not_before"] or "—")
            na    = h(r["not_after"] or "—")
            detail= f'{SCRIPT_NAME}?id={r["id"]}'
            return (f'<tr>'
                    f'<td><a href="{detail}">{host}</a></td>'
                    f'<td>{port}</td>'
                    f'<td class="mono">{cn}</td>'
                    f'<td>{issuer}</td>'
                    f'<td>{nb}</td>'
                    f'<td>{na}</td>'
                    f'<td>{expiry}</td>'
                    f'<td>{key}</td>'
                    f'<td class="mono" style="font-size:.75rem">{algo}</td>'
                    f'</tr>')

        rows_html = "\n".join(row_html(r) for r in rows)
        table = f"""
        <table>
          <thead><tr>
            <th>Host</th><th>Port</th><th>Subject CN</th><th>Issuer</th>
            <th>Not Before</th><th>Not After</th><th>Expiry</th>
            <th>Key</th><th>Sig Algo</th>
          </tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        <div style="color:var(--muted);font-size:.8rem;margin-top:8px">
          Showing {len(rows)} of {total} record(s)
        </div>"""

    # Pagination
    def page_url(p):
        parts = [f"page={p}"]
        if params.get("filter"):  parts.append(f"filter={h(params['filter'])}")
        if params.get("expired"): parts.append("expired=1")
        if params.get("expiring"):parts.append("expiring=1")
        return f"{SCRIPT_NAME}?{'&'.join(parts)}"

    pag = '<div class="pagination">'
    if page > 1:
        pag += f'<a href="{page_url(page-1)}">← Prev</a>'
    for p in range(max(1, page-2), min(pages+1, page+3)):
        cls = "current" if p == page else ""
        pag += f'<a href="{page_url(p)}" class="{cls}">{p}</a>'
    if page < pages:
        pag += f'<a href="{page_url(page+1)}">Next →</a>'
    pag += f'<span style="color:var(--muted)">Page {page}/{pages}</span></div>'

    return stat_html + toolbar + table + pag


def view_detail(conn, cert_id: int) -> str:
    cert = get_certificate(conn, cert_id)
    if not cert:
        return '<div class="empty">Certificate not found.</div>'

    sans = json.loads(cert.get("subject_alt_names") or "[]")
    sans_html = ", ".join(f'<code>{h(s)}</code>' for s in sans) or "—"

    def kv(k, v, mono=False):
        cls = ' class="mono"' if mono else ""
        return f'<div class="kv"><span class="k">{h(k)}</span><span class="v"{cls}>{v}</span></div>'

    expiry = expiry_badge(cert["is_expired"], cert["days_remaining"])

    return f"""
    <div style="margin-bottom:16px">
      <a href="{SCRIPT_NAME}">← Back to list</a>
    </div>
    <h2 style="margin-bottom:20px">{h(cert['subject_cn'] or cert['host'])}</h2>
    <div class="detail-grid">

      <div class="detail-card">
        <h3>Host</h3>
        {kv('Host', h(cert['host']))}
        {kv('IP', h(cert['ip']))}
        {kv('Port', h(cert['port']))}
        {kv('Protocol', h(cert['protocol']))}
        {kv('Scan ID', f'<a href="{SCRIPT_NAME}?view=scans">{h(cert["scan_id"])}</a>')}
        {kv('Scanned At', h(cert['scanned_at']))}
        {kv('Target', h(cert['target']))}
      </div>

      <div class="detail-card">
        <h3>Validity</h3>
        {kv('Not Before', h(cert['not_before']))}
        {kv('Not After',  h(cert['not_after']))}
        {kv('Status', expiry)}
      </div>

      <div class="detail-card">
        <h3>Subject</h3>
        {kv('CN',       h(cert['subject_cn']), mono=True)}
        {kv('Org',      h(cert['subject_org']))}
        {kv('Country',  h(cert['subject_country']))}
        {kv('State',    h(cert['subject_state']))}
        {kv('Locality', h(cert['subject_locality']))}
        <div class="kv"><span class="k">SANs</span><span class="v">{sans_html}</span></div>
      </div>

      <div class="detail-card">
        <h3>Issuer</h3>
        {kv('CN',      h(cert['issuer_cn']), mono=True)}
        {kv('Org',     h(cert['issuer_org']))}
        {kv('Country', h(cert['issuer_country']))}
      </div>

      <div class="detail-card">
        <h3>Key &amp; Algorithm</h3>
        {kv('Key Type',  h(cert['key_type']))}
        {kv('Key Bits',  h(cert['key_bits']))}
        {kv('Sig Algo',  h(cert['sig_algo']), mono=True)}
      </div>

      <div class="detail-card">
        <h3>Fingerprints</h3>
        {kv('SHA-1',   h(cert['fingerprint_sha1']),   mono=True)}
        {kv('SHA-256', h(cert['fingerprint_sha256']), mono=True)}
      </div>

    </div>

    <div class="detail-card" style="margin-top:20px">
      <h3>Raw nmap Output</h3>
      <pre>{h(cert['raw_output'])}</pre>
    </div>"""


def view_scans(conn) -> str:
    scans = list_scans(conn)
    if not scans:
        return '<div class="empty">No scans recorded yet.</div>'

    rows_html = ""
    for s in scans:
        rows_html += (f'<tr>'
                      f'<td>{h(s["id"])}</td>'
                      f'<td>{h(s["scanned_at"])}</td>'
                      f'<td class="mono">{h(s["target"])}</td>'
                      f'<td class="mono">{h(s["nmap_args"] or "")}</td>'
                      f'<td><a href="{SCRIPT_NAME}?scan_id={s["id"]}">'
                      f'{h(s["cert_count"])} cert(s)</a></td>'
                      f'</tr>')

    return f"""
    <table class="scans-table">
      <thead><tr>
        <th>ID</th><th>Scanned At</th><th>Target</th><th>Args</th><th>Certs</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""


def view_json(conn, params: dict) -> str:
    rows, _ = list_certificates(conn, {**params, "page": 1})
    # override PAGE_SIZE for export — re-query without limit
    rows = conn.execute("""
        SELECT c.* FROM certificates c JOIN scans s ON c.scan_id = s.id
        ORDER BY c.not_after ASC
    """).fetchall()
    data = []
    for r in rows:
        d = dict(r)
        if d.get("subject_alt_names"):
            try:
                d["subject_alt_names"] = json.loads(d["subject_alt_names"])
            except Exception:
                pass
        data.append(d)
    return f"Content-Type: application/json; charset=utf-8\r\n\r\n{json.dumps(data, indent=2, default=str)}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    params = qs()

    if not os.path.exists(DB_PATH):
        print("Content-Type: text/html\r\n\r\n"
              f"<h2>Database not found: {h(DB_PATH)}</h2>"
              "<p>Set the <code>SSL_DB_PATH</code> environment variable "
              "or place <code>ssl_certs.db</code> next to this script.</p>")
        return

    conn = get_db()

    # JSON export — output raw, no HTML wrapper
    if params.get("fmt") == "json":
        print(view_json(conn, params))
        return

    # Detail view
    if params.get("id"):
        try:
            cert_id = int(params["id"])
        except ValueError:
            cert_id = 0
        body  = view_detail(conn, cert_id)
        title = f"Certificate #{cert_id}"
        print(page_wrap(title, body, active_tab="certs"))
        return

    # Scans view
    if params.get("view") == "scans":
        body = view_scans(conn)
        print(page_wrap("Scans", body, active_tab="scans"))
        return

    # Default: certificate list
    body = view_certs(conn, params)
    print(page_wrap("Certificates", body, active_tab="certs"))

    conn.close()


if __name__ == "__main__":
    main()
