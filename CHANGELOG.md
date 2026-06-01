# Changelog

All notable changes to this project will be documented here.

## [Unreleased]

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
