# Changelog

All notable changes to this project will be documented here.

## [1.7.3] - 2026-06-11

### Fixed
- `netbox_inventory.cgi`: chart tooltip now hides correctly when the cursor moves off a slice or legend item to a non-interactive part of the card

## [1.7.2] - 2026-06-11

### Fixed
- Added `from __future__ import annotations` to all scripts (`netbox_devices.cgi`, `netbox_inventory.cgi`, `ssl_certs.cgi`, `netbox_export.py`, `nmap_ssl_scan.py`) to support Python 3.9; `str | None` and `tuple[T, ...]` union/generic hints previously caused `TypeError` on Python < 3.10

### Changed
- Minimum Python version lowered from 3.10 to 3.9

## [1.7.1] - 2026-06-11

### Fixed
- `netbox_inventory.cgi`: added missing Devices &amp; VMs sidebar link to `netbox_devices.cgi`

## [1.7.0] - 2026-06-11

### Added
- `netbox_export.py`: CLI script to export NetBox devices and VMs to a JSON flat file
  - Fetches `dcim/devices` and `virtualization/virtual-machines` from the NetBox API with pagination
  - Prunes each record to only the fields required by the CGI viewers
  - Writes `{ exported_at, source, devices[], virtual_machines[] }` JSON
  - `--url` / `--token` CLI flags with `NETBOX_URL` / `NETBOX_TOKEN` env-var fallbacks
  - `--output` to specify the destination file (default: `netbox_export.json`)
  - `--pretty` for human-readable indented output
- `netbox_devices.cgi`: `NETBOX_EXPORT_FILE` environment variable support
  - When set, loads devices and VMs from the export file instead of hitting the live API
  - Info banner shows the file path and `exported_at` timestamp from the export
  - Topbar subtitle reflects the active data source (live URL, export file, or example data)
- `netbox_inventory.cgi`: same `NETBOX_EXPORT_FILE` support as `netbox_devices.cgi`

### Changed
- Data source priority in both NetBox CGI scripts: export file → live API → example data

## [1.6.0] - 2026-06-11

### Added
- `check_nfs_mounts.sh`: Nagios NRPE plugin to audit NFS mount consistency
  - Compares NFS entries across `/etc/fstab`, `/proc/mounts`, and `nrpe.cfg` `check_disk -p` paths
  - Parses both `nrpe.cfg` and all `nrpe.d/*.cfg` drop-in files
  - CRITICAL when a configured mount is not active, or nrpe monitors a non-existent mount
  - WARNING for unmonitored mounts, ad-hoc mounts missing from fstab, and `noauto` gaps
  - Treats `noauto` fstab entries as WARNING rather than CRITICAL when unmounted
  - Outputs Nagios performance data (`nfs_ok`, `nfs_warn`, `nfs_crit`, `nfs_fstab`, `nfs_active`, `nfs_nrpe`)
  - `-c`, `-d`, `-f` flags to override default config paths; `-v` for verbose OK listing

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
