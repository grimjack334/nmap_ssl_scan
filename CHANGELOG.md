# Changelog

All notable changes to this project will be documented here.

## [1.5.0] - 2026-06-11

### Added
- `netbox_devices.cgi`: sortable, filterable combined list of NetBox devices and VMs
  - Columns: Name, Type, Tenant, Role, Status, Site
  - Client-side sort on all columns with ▲▼ indicators
  - Live filter by free text plus Type, Status, and Tenant dropdowns (options populated from data)
  - Color-coded status badges (active, offline, staged, planned, decommissioning)
  - Device / VM type badges
  - Sidebar link back to `netbox_inventory.cgi`
  - Falls back to built-in example data when `NETBOX_URL` is not configured

## [1.4.0] - 2026-06-10

### Added
- `netbox_inventory.cgi`: CGI dashboard for NetBox inventory summary
  - Device and VM counts broken down by tenant
  - Interactive SVG donut charts with hover tooltips and slice highlighting
  - Per-tenant breakdown table with share-of-inventory bars and device/VM split bars
  - Fetches from NetBox `dcim/devices` and `virtualization/virtual-machines` APIs with pagination
  - Falls back to built-in example data when `NETBOX_URL` is not configured
  - `NETBOX_URL` and `NETBOX_TOKEN` environment variable configuration
- Sidebar/topbar layout redesign for `ssl_certs.cgi` (CSS variables, collapsible sidebar, sticky topbar, responsive mobile toggle)

## [1.3.0] - 2026-06-01

### Added
- Installation section to README with `git clone` and `nmap` install instructions

## [1.2.0] - 2026-06-01

### Added
- `NETBOX_URL` environment variable fallback for `--netbox-url`

## [1.1.0] - 2026-06-01

### Added
- NetBox integration: fetch scan targets from NetBox prefixes tagged `nmap_ssl_scan`
  - `--netbox-url` and `--netbox-token` CLI flags
  - `NETBOX_TOKEN` environment variable fallback for `--netbox-token`
  - Handles paginated NetBox API responses automatically
  - NetBox prefixes are merged with any manually specified targets

## [1.0.0] - 2026-06-01

### Added
- `nmap_ssl_scan.py`: CLI scanner using nmap `ssl-cert` and `ssl-enum-ciphers` scripts
  - Supports hosts, IPs, CIDRs, and `.txt` target list files
  - Configurable ports (default: 443, 8443, 9443, 4443)
  - Parses subject, issuer, validity dates, key info, SANs, and SHA-1/SHA-256 fingerprints
  - Stores results in SQLite with scan audit log
  - Deduplication by SHA-256 fingerprint (within scan and against existing database)
  - `--query`, `--expired`, `--filter`, `--export-json` flags for querying without rescanning
- `ssl_certs.cgi`: CGI web UI over the SQLite database
  - Certificate list with filtering, pagination, and expiry badges
  - Per-certificate detail page with full field breakdown and raw nmap output
  - Scan history view
  - JSON export endpoint (`?fmt=json`)
  - Expiry status computed dynamically from `not_after` at request time
