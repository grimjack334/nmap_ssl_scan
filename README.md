# nmap SSL Certificate Scanner

Scans hosts with nmap's `ssl-cert` script and stores results in a local SQLite database. Includes a CGI web UI for browsing and filtering certificates.

## Installation

```bash
git clone https://github.com/grimjack334/nmap_ssl_scan.git
cd nmap_ssl_scan
```

No Python packages to install — stdlib only. Just ensure `nmap` is available:

```bash
# Debian/Ubuntu
sudo apt install nmap

# RHEL/Fedora
sudo dnf install nmap

# macOS
brew install nmap
```

## Requirements

- Python 3.10+
- `nmap` installed and in `$PATH`
- No third-party Python packages — stdlib only

## Usage

```bash
# Scan a single host
python3 nmap_ssl_scan.py example.com

# Scan a CIDR range (requires root for SYN scan)
sudo python3 nmap_ssl_scan.py 192.168.1.0/24 -p 443,8443

# Scan from a file of targets (one per line, # for comments)
python3 nmap_ssl_scan.py targets.txt --db certs.db

# Pass extra nmap flags
python3 nmap_ssl_scan.py example.com --nmap-args "-T4 -v"
```

Default ports: `443, 8443, 9443, 4443`

## NetBox integration

Prefixes can be pulled automatically from NetBox instead of (or in addition to) specifying targets manually. Tag any prefixes in NetBox with `nmap_ssl_scan` and they will be included in the scan.

```bash
# Via environment variables (recommended)
export NETBOX_URL=https://netbox.example.com
export NETBOX_TOKEN=your_token
python3 nmap_ssl_scan.py

# Via CLI flags
python3 nmap_ssl_scan.py --netbox-url https://netbox.example.com --netbox-token your_token

# Combined with manual targets
python3 nmap_ssl_scan.py --netbox-url https://netbox.example.com extra-host.com
```

Only prefixes with status `active` and the `nmap_ssl_scan` tag are fetched.

## Querying results

```bash
# Show all stored certificates
python3 nmap_ssl_scan.py --query

# Show only expired certificates
python3 nmap_ssl_scan.py --query --expired

# Filter by hostname or CN
python3 nmap_ssl_scan.py --query --filter example.com

# Export to JSON
python3 nmap_ssl_scan.py --query --export-json output.json
```

## Web UI

### SSL Certificate viewer (`ssl_certs.cgi`)

A CGI script provides a browser-based view of the database with filtering, pagination, and per-certificate detail pages.

```bash
# Test locally without a web server
python3 -m http.server --cgi 8080
# Place ssl_certs.cgi and ssl_certs.db in cgi-bin/ and open:
# http://localhost:8080/cgi-bin/ssl_certs.cgi
```

Override the database path via environment variable:
```bash
SSL_DB_PATH=/path/to/certs.db python3 ssl_certs.cgi
```

### NetBox inventory dashboard (`netbox_inventory.cgi`)

A CGI dashboard showing device and VM counts from NetBox, broken down by tenant. Features interactive donut charts with hover tooltips and a per-tenant breakdown table.

```bash
# Test locally with built-in example data (no NetBox needed)
python3 -m http.server --cgi 8080
# Place netbox_inventory.cgi in cgi-bin/ and open:
# http://localhost:8080/cgi-bin/netbox_inventory.cgi

# Connect to a live NetBox instance
NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=your_token python3 netbox_inventory.cgi
```

The dashboard falls back to built-in example data with an info banner when `NETBOX_URL` is not set, so it works out of the box for local testing.

### NetBox device list (`netbox_devices.cgi`)

A sortable, filterable combined list of all devices and virtual machines from NetBox. Columns: Name, Type, Tenant, Role, Status, Site. All sorting and filtering is client-side with no page reloads.

```bash
# Test locally with built-in example data (no NetBox needed)
python3 -m http.server --cgi 8080
# Place netbox_devices.cgi in cgi-bin/ and open:
# http://localhost:8080/cgi-bin/netbox_devices.cgi

# Connect to a live NetBox instance
NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=your_token python3 netbox_devices.cgi
```

Filter controls: free-text search across all columns, plus Type / Status / Tenant dropdowns populated from the live data. Click any column header to sort; click again to reverse.

## What gets stored

| Field | Description |
|---|---|
| Subject / Issuer | CN, Org, Country, State, Locality |
| Validity | `not_before`, `not_after`, expiry status |
| Key info | Type, bits, signature algorithm |
| SANs | Subject Alternative Names (JSON array) |
| Fingerprints | SHA-1, SHA-256 |
| Raw output | Full nmap script output block |

Certificates are deduplicated by SHA-256 fingerprint — rescanning the same host won't create duplicate entries.
