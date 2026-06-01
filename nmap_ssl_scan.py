#!/usr/bin/env python3
"""
nmap SSL Certificate Scanner → SQLite
Runs nmap ssl-cert script against targets and stores results in a local database.

Usage:
    python3 nmap_ssl_scan.py <target> [target2 ...] [options]

Examples:
    python3 nmap_ssl_scan.py example.com
    python3 nmap_ssl_scan.py 192.168.1.0/24 -p 443,8443
    python3 nmap_ssl_scan.py targets.txt --db certs.db
    python3 nmap_ssl_scan.py example.com --query
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


# ── Database ──────────────────────────────────────────────────────────────────

DB_DEFAULT = "ssl_certs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at  TEXT    NOT NULL,
    target      TEXT    NOT NULL,
    nmap_args   TEXT
);

CREATE TABLE IF NOT EXISTS certificates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER NOT NULL REFERENCES scans(id),
    host            TEXT,
    ip              TEXT,
    port            INTEGER,
    protocol        TEXT,
    -- Subject fields
    subject_cn      TEXT,
    subject_org     TEXT,
    subject_country TEXT,
    subject_state   TEXT,
    subject_locality TEXT,
    subject_raw     TEXT,
    -- Issuer fields
    issuer_cn       TEXT,
    issuer_org      TEXT,
    issuer_country  TEXT,
    issuer_raw      TEXT,
    -- Validity
    not_before      TEXT,
    not_after       TEXT,
    is_expired      INTEGER DEFAULT 0,
    days_remaining  INTEGER,
    -- Key info
    key_type        TEXT,
    key_bits        INTEGER,
    sig_algo        TEXT,
    -- SANs
    subject_alt_names TEXT,  -- JSON array
    -- Fingerprints
    fingerprint_sha1   TEXT,
    fingerprint_sha256 TEXT,
    -- Raw output
    raw_output      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_certs_host    ON certificates(host);
CREATE INDEX IF NOT EXISTS idx_certs_cn      ON certificates(subject_cn);
CREATE INDEX IF NOT EXISTS idx_certs_expiry  ON certificates(not_after);
CREATE INDEX IF NOT EXISTS idx_certs_scan_id ON certificates(scan_id);
"""


def get_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ── nmap runner ───────────────────────────────────────────────────────────────

def run_nmap(targets: list[str], ports: str, extra_args: list[str]) -> str:
    """Run nmap ssl-cert scan and return XML output."""
    cmd = [
        "nmap",
        "-p", ports,
        "--script", "ssl-cert,ssl-enum-ciphers",
        "-sV",
        "--open",
        "-oX", "-",          # XML to stdout
        "--script-args", "ssl-cert.showciphers=false",
    ] + extra_args + targets

    print(f"[*] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        sys.exit("[!] nmap not found. Install it: https://nmap.org/download.html")
    except subprocess.TimeoutExpired:
        sys.exit("[!] nmap timed out after 5 minutes.")

    if result.returncode not in (0, 1):  # nmap returns 1 on partial results
        print(f"[!] nmap stderr:\n{result.stderr}", file=sys.stderr)

    return result.stdout


# ── XML parser ────────────────────────────────────────────────────────────────

def _text(el, path, default=""):
    node = el.find(path)
    return (node.text or "").strip() if node is not None else default


def parse_script_output(output: str) -> dict:
    """Parse the raw ssl-cert script output block into a structured dict."""
    cert = {}
    lines = output.splitlines()

    subject, issuer, validity, pubkey, alts = {}, {}, {}, {}, []
    section = None

    for line in lines:
        line = line.strip()

        if line.startswith("Subject:"):
            section = "subject"
            rest = line[len("Subject:"):].strip()
            for kv in rest.split("/"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    subject[k.strip().lower()] = v.strip()

        elif line.startswith("Issuer:"):
            section = "issuer"
            rest = line[len("Issuer:"):].strip()
            for kv in rest.split("/"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    issuer[k.strip().lower()] = v.strip()

        elif line.startswith("Not valid before:"):
            validity["before"] = line.split(":", 1)[1].strip()
        elif line.startswith("Not valid after:"):
            validity["after"] = line.split(":", 1)[1].strip()

        elif line.startswith("Public Key type:"):
            pubkey["type"] = line.split(":", 1)[1].strip()
        elif line.startswith("Public Key bits:"):
            pubkey["bits"] = line.split(":", 1)[1].strip()
        elif line.startswith("Signature Algorithm:"):
            pubkey["sig_algo"] = line.split(":", 1)[1].strip()

        elif line.startswith("Subject Alternative Name:"):
            raw_sans = line.split(":", 1)[1].strip()
            alts = [s.strip().removeprefix("DNS:").removeprefix("IP:")
                    for s in raw_sans.split(",") if s.strip()]

        elif "SHA-1:" in line or "sha-1" in line.lower():
            m = re.search(r"[0-9a-fA-F:]{59}", line)
            if m:
                cert["fingerprint_sha1"] = m.group(0)
        elif "SHA-256:" in line or "sha-256" in line.lower():
            m = re.search(r"[0-9a-fA-F:]{95}", line)
            if m:
                cert["fingerprint_sha256"] = m.group(0)

    cert["subject"] = subject
    cert["issuer"] = issuer
    cert["validity"] = validity
    cert["pubkey"] = pubkey
    cert["sans"] = alts
    return cert


def days_remaining(not_after_str: str) -> tuple[bool, int]:
    """Return (is_expired, days_remaining) from an nmap date string."""
    fmt_candidates = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%b %d %H:%M:%S %Y GMT",
    ]
    for fmt in fmt_candidates:
        try:
            exp = datetime.strptime(not_after_str, fmt).replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            delta = (exp - now).days
            return delta < 0, delta
        except ValueError:
            continue
    return False, None


def parse_nmap_xml(xml_str: str) -> list[dict]:
    """Extract certificate records from nmap XML output."""
    records = []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        print(f"[!] Failed to parse nmap XML: {e}", file=sys.stderr)
        return records

    for host_el in root.findall("host"):
        hostname_el = host_el.find("hostnames/hostname[@type='user']")
        rdns_el     = host_el.find("hostnames/hostname[@type='PTR']")
        host_name   = (hostname_el.attrib.get("name") if hostname_el is not None
                       else (rdns_el.attrib.get("name") if rdns_el is not None else ""))
        ip_addr     = _text(host_el, "address[@addrtype='ipv4']/@addr") or \
                      host_el.find("address").attrib.get("addr", "")

        for port_el in host_el.findall("ports/port"):
            port_num  = int(port_el.attrib.get("portid", 0))
            protocol  = port_el.attrib.get("protocol", "tcp")
            state_el  = port_el.find("state")
            if state_el is not None and state_el.attrib.get("state") != "open":
                continue

            for script_el in port_el.findall("script[@id='ssl-cert']"):
                raw_output = script_el.attrib.get("output", "")
                cert       = parse_script_output(raw_output)

                subj = cert.get("subject", {})
                issu = cert.get("issuer", {})
                vali = cert.get("validity", {})
                pkey = cert.get("pubkey", {})
                sans = cert.get("sans", [])

                not_after_str = vali.get("after", "")
                expired, days = days_remaining(not_after_str) if not_after_str else (False, None)

                record = {
                    "host":             host_name or ip_addr,
                    "ip":               ip_addr,
                    "port":             port_num,
                    "protocol":         protocol,
                    "subject_cn":       subj.get("cn", subj.get("commonname", "")),
                    "subject_org":      subj.get("o", subj.get("organization", "")),
                    "subject_country":  subj.get("c", subj.get("country", "")),
                    "subject_state":    subj.get("st", subj.get("stateorprovincename", "")),
                    "subject_locality": subj.get("l", subj.get("locality", "")),
                    "subject_raw":      json.dumps(subj),
                    "issuer_cn":        issu.get("cn", issu.get("commonname", "")),
                    "issuer_org":       issu.get("o", issu.get("organization", "")),
                    "issuer_country":   issu.get("c", issu.get("country", "")),
                    "issuer_raw":       json.dumps(issu),
                    "not_before":       vali.get("before", ""),
                    "not_after":        not_after_str,
                    "is_expired":       int(expired),
                    "days_remaining":   days,
                    "key_type":         pkey.get("type", ""),
                    "key_bits":         int(pkey.get("bits", 0)) if pkey.get("bits", "").isdigit() else None,
                    "sig_algo":         pkey.get("sig_algo", ""),
                    "subject_alt_names": json.dumps(sans),
                    "fingerprint_sha1":  cert.get("fingerprint_sha1", ""),
                    "fingerprint_sha256":cert.get("fingerprint_sha256", ""),
                    "raw_output":       raw_output,
                }
                records.append(record)

    return records


# ── Database writer ───────────────────────────────────────────────────────────

def dedup_records(records: list[dict]) -> list[dict]:
    """Remove duplicates within a scan result, keyed by SHA-256 fingerprint or host:port:cn."""
    seen: set[str] = set()
    unique = []
    for r in records:
        key = r["fingerprint_sha256"] or f"{r['host']}:{r['port']}:{r['subject_cn']}"
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def save_to_db(conn: sqlite3.Connection, targets: list[str],
               nmap_args: str, records: list[dict]) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scans (scanned_at, target, nmap_args) VALUES (?, ?, ?)",
        (datetime.now(tz=timezone.utc).isoformat(), ", ".join(targets), nmap_args),
    )
    scan_id = cur.lastrowid

    skipped = 0
    for rec in records:
        if rec["fingerprint_sha256"]:
            exists = cur.execute(
                "SELECT 1 FROM certificates WHERE fingerprint_sha256 = ?",
                [rec["fingerprint_sha256"]],
            ).fetchone()
            if exists:
                skipped += 1
                continue

        cur.execute("""
            INSERT INTO certificates (
                scan_id, host, ip, port, protocol,
                subject_cn, subject_org, subject_country, subject_state, subject_locality, subject_raw,
                issuer_cn, issuer_org, issuer_country, issuer_raw,
                not_before, not_after, is_expired, days_remaining,
                key_type, key_bits, sig_algo,
                subject_alt_names, fingerprint_sha1, fingerprint_sha256, raw_output
            ) VALUES (
                :scan_id, :host, :ip, :port, :protocol,
                :subject_cn, :subject_org, :subject_country, :subject_state, :subject_locality, :subject_raw,
                :issuer_cn, :issuer_org, :issuer_country, :issuer_raw,
                :not_before, :not_after, :is_expired, :days_remaining,
                :key_type, :key_bits, :sig_algo,
                :subject_alt_names, :fingerprint_sha1, :fingerprint_sha256, :raw_output
            )
        """, {"scan_id": scan_id, **rec})

    conn.commit()
    if skipped:
        print(f"[*] Skipped {skipped} duplicate certificate(s) already in database")
    return scan_id


# ── Query / report ────────────────────────────────────────────────────────────

def query_db(conn: sqlite3.Connection, show_expired: bool = False,
             host_filter: str = None, limit: int = 50):
    """Print a summary report from the database."""
    where_clauses = []
    params = []

    if show_expired:
        where_clauses.append("c.is_expired = 1")
    if host_filter:
        where_clauses.append("(c.host LIKE ? OR c.subject_cn LIKE ?)")
        params += [f"%{host_filter}%", f"%{host_filter}%"]

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = conn.execute(f"""
        SELECT c.host, c.ip, c.port, c.subject_cn, c.issuer_org,
               c.not_after, c.is_expired, c.days_remaining,
               c.key_type, c.key_bits, c.sig_algo, s.scanned_at
        FROM   certificates c
        JOIN   scans s ON c.scan_id = s.id
        {where}
        ORDER  BY c.not_after ASC
        LIMIT  ?
    """, params + [limit]).fetchall()

    if not rows:
        print("No records found.")
        return

    print(f"\n{'HOST':<30} {'PORT':<6} {'SUBJECT CN':<35} {'EXPIRES':<22} {'STATUS':<12} {'KEY':<12}")
    print("-" * 120)
    for r in rows:
        status = "EXPIRED" if r["is_expired"] else f"{r['days_remaining']}d left" if r["days_remaining"] is not None else "unknown"
        key    = f"{r['key_type']} {r['key_bits'] or '?'}b" if r["key_type"] else ""
        host   = f"{r['host'] or r['ip']}:{r['port']}"
        print(f"{host:<30} {str(r['port']):<6} {(r['subject_cn'] or ''):<35} {(r['not_after'] or ''):<22} {status:<12} {key:<12}")

    print(f"\nTotal: {len(rows)} record(s)")


def export_json(conn: sqlite3.Connection, out_path: str):
    rows = conn.execute("""
        SELECT c.*, s.scanned_at, s.target
        FROM certificates c JOIN scans s ON c.scan_id = s.id
        ORDER BY c.id DESC
    """).fetchall()
    data = [dict(r) for r in rows]
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"[+] Exported {len(data)} records to {out_path}")


# ── NetBox ────────────────────────────────────────────────────────────────────

def fetch_netbox_prefixes(base_url: str, token: str, tag: str = "nmap_ssl_scan") -> list[str]:
    """Return all active prefixes from NetBox that carry the given tag."""
    prefixes = []
    url = f"{base_url.rstrip('/')}/api/ipam/prefixes/?tag={tag}&status=active&limit=1000"

    while url:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            sys.exit(f"[!] NetBox API error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            sys.exit(f"[!] Could not reach NetBox at {base_url}: {e.reason}")

        for result in data.get("results", []):
            prefixes.append(result["prefix"])

        url = data.get("next")

    return prefixes


# ── CLI ───────────────────────────────────────────────────────────────────────

def load_targets_from_file(path: str) -> list[str]:
    with open(path) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def main():
    parser = argparse.ArgumentParser(
        description="Scan hosts with nmap ssl-cert and store results in SQLite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("targets", nargs="*", help="Hosts, IPs, CIDRs, or a .txt file of targets")
    parser.add_argument("-p", "--ports",   default="443,8443,9443,4443", help="Ports to scan (default: 443,8443,9443,4443)")
    parser.add_argument("--db",            default=DB_DEFAULT, help=f"SQLite database path (default: {DB_DEFAULT})")
    parser.add_argument("--nmap-args",     default="", help="Extra nmap arguments (quoted string)")
    parser.add_argument("--query",         action="store_true", help="Show stored certificates and exit")
    parser.add_argument("--expired",       action="store_true", help="Show only expired certificates (with --query)")
    parser.add_argument("--filter",        help="Filter by hostname or CN (with --query)")
    parser.add_argument("--export-json",   metavar="FILE", help="Export all records to JSON")
    parser.add_argument("--limit",         type=int, default=100, help="Max rows returned by --query")
    parser.add_argument("--no-scan",       action="store_true", help="Skip scanning; only query/export")
    parser.add_argument("--netbox-url",    metavar="URL", help="NetBox base URL (e.g. https://netbox.example.com)")
    parser.add_argument("--netbox-token",  metavar="TOKEN",
                        default=os.environ.get("NETBOX_TOKEN"),
                        help="NetBox API token (or set NETBOX_TOKEN env var)")
    args = parser.parse_args()

    conn = get_db(args.db)
    print(f"[*] Database: {os.path.abspath(args.db)}")

    # ── Query / export only ──
    if args.query or args.no_scan:
        query_db(conn, show_expired=args.expired, host_filter=args.filter, limit=args.limit)
        if args.export_json:
            export_json(conn, args.export_json)
        return

    if args.export_json and not args.targets:
        export_json(conn, args.export_json)
        return

    # ── Resolve targets ──
    targets = []

    if args.netbox_url:
        if not args.netbox_token:
            sys.exit("[!] --netbox-url requires a token via --netbox-token or NETBOX_TOKEN env var.")
        nb_prefixes = fetch_netbox_prefixes(args.netbox_url, args.netbox_token)
        if not nb_prefixes:
            sys.exit("[!] NetBox returned no prefixes tagged 'nmap_ssl_scan'.")
        print(f"[*] Loaded {len(nb_prefixes)} prefix(es) from NetBox")
        targets.extend(nb_prefixes)

    for t in args.targets:
        if os.path.isfile(t):
            targets.extend(load_targets_from_file(t))
            print(f"[*] Loaded targets from {t}")
        else:
            targets.append(t)

    if not targets:
        parser.print_help()
        sys.exit(1)

    # ── Scan ──
    extra = args.nmap_args.split() if args.nmap_args else []
    xml_output = run_nmap(targets, args.ports, extra)

    if not xml_output.strip():
        sys.exit("[!] nmap produced no output. Are you root/Administrator?")

    records = dedup_records(parse_nmap_xml(xml_output))
    print(f"[+] Parsed {len(records)} certificate(s)")

    if records:
        scan_id = save_to_db(conn, targets, f"-p {args.ports} {args.nmap_args}", records)
        print(f"[+] Saved to database (scan_id={scan_id})")

        # Print a quick summary
        query_db(conn, limit=args.limit)
    else:
        print("[!] No SSL certificates found. Verify ports are open and nmap has network access.")

    if args.export_json:
        export_json(conn, args.export_json)

    conn.close()


if __name__ == "__main__":
    main()
