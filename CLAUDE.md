# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Two-file Python project: a CLI scanner and a CGI web viewer for SSL certificate data.

- **`nmap_ssl_scan.py`** — CLI tool that shells out to `nmap --script ssl-cert,ssl-enum-ciphers`, parses the XML output, and stores results in SQLite.
- **`ssl_certs.cgi`** — CGI script providing a dark-themed web UI over the same SQLite database. No framework — pure stdlib CGI with inline CSS/HTML generation.

## Running the scanner

```bash
# Basic scan (requires nmap in $PATH; CIDR ranges need root)
python3 nmap_ssl_scan.py example.com
python3 nmap_ssl_scan.py 192.168.1.0/24 -p 443,8443
python3 nmap_ssl_scan.py targets.txt --db certs.db

# Query stored results without rescanning
python3 nmap_ssl_scan.py --query --db certs.db
python3 nmap_ssl_scan.py --query --expired
python3 nmap_ssl_scan.py --query --filter example.com

# Export to JSON
python3 nmap_ssl_scan.py --query --export-json output.json

# Pass extra nmap flags
python3 nmap_ssl_scan.py example.com --nmap-args "-T4 -v"
```

Default ports scanned: `443,8443,9443,4443`.

## Running the web UI

```bash
# Test locally without a web server
python3 -m http.server --cgi 8080
# Open http://localhost:8080/cgi-bin/ssl_certs.cgi
# (requires ssl_certs.cgi and ssl_certs.db in cgi-bin/)

# Override DB path via environment
SSL_DB_PATH=/path/to/certs.db python3 ssl_certs.cgi
```

## Architecture

### Data flow (scanner)

```
targets → run_nmap() → XML string → parse_nmap_xml() → list[dict] → save_to_db()
```

`parse_nmap_xml` delegates per-certificate text parsing to `parse_script_output`, which line-walks the nmap script output block (not further XML). Expiry calculation happens here via `days_remaining()`, which tries three date format candidates.

### Database schema

Two tables: `scans` (one row per invocation) and `certificates` (one row per cert found). Every certificate row carries a `scan_id` FK. SANs are stored as a JSON array string. `subject_raw` / `issuer_raw` store the full parsed dict as JSON for fields not broken out into columns.

### CGI web UI routing

`ssl_certs.cgi` dispatches entirely on query-string params — no URL path routing:
- `?id=N` → certificate detail view
- `?view=scans` → scan history
- `?fmt=json` → raw JSON export (ignores filters, dumps all certs)
- default → paginated certificate list (`PAGE_SIZE = 50`)

All HTML is generated via f-strings; `h()` is the HTML-escape helper used throughout. The `expiry_badge()` helper drives the color-coded status badges (ok/warn/caution/danger).

## Testing

Do not run tests after making code changes.

## Dependencies

No Python packages beyond stdlib. Requires `nmap` installed and in `$PATH` for scanning. The CGI script uses the deprecated `cgi` / `cgitb` modules (removed in Python 3.13) — keep this in mind if upgrading Python.
