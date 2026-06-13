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

- Python 3.9+
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

Prefixes can be pulled automatically from NetBox instead of (or in addition to) specifying targets manually. Tag prefixes in NetBox and pass the tag name with `--netbox-tag` — only `active` prefixes carrying that tag are fetched.

```bash
# Default tag (nmap_ssl_scan) via env vars
export NETBOX_URL=https://netbox.example.com
export NETBOX_TOKEN=your_token
python3 nmap_ssl_scan.py

# Specify a custom tag
python3 nmap_ssl_scan.py \
    --netbox-url https://netbox.example.com \
    --netbox-token your_token \
    --netbox-tag corp-infra

# Multiple tags — OR semantics (prefixes with any matching tag, deduplicated)
python3 nmap_ssl_scan.py \
    --netbox-url https://netbox.example.com \
    --netbox-token your_token \
    --netbox-tag prod-web \
    --netbox-tag prod-api \
    --netbox-tag dmz

# Combined with manual targets
python3 nmap_ssl_scan.py \
    --netbox-url https://netbox.example.com \
    --netbox-token your_token \
    --netbox-tag corp-infra \
    extra-host.example.com
```

`NETBOX_TAG` env var is also accepted (comma-separated for multiple tags):

```bash
export NETBOX_URL=https://netbox.example.com
export NETBOX_TOKEN=your_token
export NETBOX_TAG=prod-web,prod-api
python3 nmap_ssl_scan.py
```

The scanner prints a per-tag breakdown so you can see how many prefixes each tag contributed:

```
[*] Fetching prefixes from NetBox (tags: prod-web, prod-api, dmz)
[*]   tag='prod-web': 12 prefix(es)
[*]   tag='prod-api': 8 prefix(es)
[*]   tag='dmz': 4 prefix(es)
[*] Loaded 22 prefix(es) from NetBox
```

Prefixes shared across multiple tags are counted once.

| Option | Env var | Default |
|---|---|---|
| `--netbox-url URL` | `NETBOX_URL` | — |
| `--netbox-token TOKEN` | `NETBOX_TOKEN` | — |
| `--netbox-tag TAG` (repeatable) | `NETBOX_TAG` (comma-separated) | `nmap_ssl_scan` |

## Automation / cron

### /etc/cron.d

```cron
# Scan NetBox-tagged prefixes nightly at 02:00
0 2 * * * root NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=your_token \
    /usr/bin/python3 /opt/nmap_ssl_scan/nmap_ssl_scan.py \
    --netbox-tag corp-infra \
    --db /var/lib/nmap_ssl_scan/certs.db \
    >> /var/log/nmap_ssl_scan.log 2>&1

# Scan specific subnets weekly on Sunday at 03:30
30 3 * * 0 root \
    /usr/bin/python3 /opt/nmap_ssl_scan/nmap_ssl_scan.py \
    10.0.0.0/8 172.16.0.0/12 \
    -p 443,8443,4443 \
    --db /var/lib/nmap_ssl_scan/certs.db \
    >> /var/log/nmap_ssl_scan.log 2>&1
```

### User crontab (`crontab -e`)

```cron
# Nightly scan — multiple NetBox tags (OR)
0 2 * * * NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=your_token NETBOX_TAG=prod-web,prod-api \
    python3 ~/nmap_ssl_scan/nmap_ssl_scan.py --db ~/nmap_ssl_scan/certs.db >> ~/nmap_ssl_scan/scan.log 2>&1

# Export to JSON after each scan for the web UI
5 2 * * * python3 ~/nmap_ssl_scan/nmap_ssl_scan.py --no-scan \
    --db ~/nmap_ssl_scan/certs.db \
    --export-json /var/www/cgi-bin/certs.json >> ~/nmap_ssl_scan/scan.log 2>&1
```

### systemd timer

`/etc/systemd/system/nmap-ssl-scan.service`:
```ini
[Unit]
Description=nmap SSL certificate scan
After=network-online.target

[Service]
Type=oneshot
User=root
EnvironmentFile=/etc/nmap_ssl_scan/env
ExecStart=/usr/bin/python3 /opt/nmap_ssl_scan/nmap_ssl_scan.py \
    --netbox-tag corp-infra \
    --db /var/lib/nmap_ssl_scan/certs.db
StandardOutput=append:/var/log/nmap_ssl_scan.log
StandardError=append:/var/log/nmap_ssl_scan.log
```

`/etc/systemd/system/nmap-ssl-scan.timer`:
```ini
[Unit]
Description=Run nmap SSL scan nightly

[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
```

`/etc/nmap_ssl_scan/env` (mode 0600):
```
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your_token
```

```bash
systemctl daemon-reload
systemctl enable --now nmap-ssl-scan.timer
systemctl list-timers nmap-ssl-scan.timer
```

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

# Load from a pre-exported flat file instead of the live API
NETBOX_EXPORT_FILE=/path/to/netbox_export.json python3 netbox_inventory.cgi
```

Data source priority: `NETBOX_EXPORT_FILE` → live API (`NETBOX_URL` + `NETBOX_TOKEN`) → built-in example data. An info banner identifies which source is active. The sidebar links to `netbox_devices.cgi`.

Displays a Domains stat card, an Inventory by Domain donut chart, and a Breakdown by Domain table alongside the tenant breakdown. Domain is read from the `domain` NetBox custom field on each device and VM.

### NetBox device list (`netbox_devices.cgi`)

A sortable, filterable combined list of all devices and virtual machines from NetBox. Columns: Name, Type, Tenant, Role, Status, Site. All sorting and filtering is client-side with no page reloads.

```bash
# Test locally with built-in example data (no NetBox needed)
python3 -m http.server --cgi 8080
# Place netbox_devices.cgi in cgi-bin/ and open:
# http://localhost:8080/cgi-bin/netbox_devices.cgi

# Connect to a live NetBox instance
NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=your_token python3 netbox_devices.cgi

# Load from a pre-exported flat file instead of the live API
NETBOX_EXPORT_FILE=/path/to/netbox_export.json python3 netbox_devices.cgi
```

Columns: Name, Type, Tenant, Domain, Role, Status, Site. Filter controls: free-text search across all columns, plus Type, Status, Tenant, and Domain dropdowns populated from the live data. Click any column header to sort; click again to reverse. Domain is read from the `domain` NetBox custom field. Data source priority is the same as `netbox_inventory.cgi`.

Export CSV and Export JSON buttons in the toolbar download the currently visible (filtered) rows as `netbox_devices.csv` or `netbox_devices.json`.

### NetBox export (`netbox_export.py`)

Fetches devices and VMs from NetBox and writes a JSON flat file that both CGI viewers can load offline via `NETBOX_EXPORT_FILE`. Useful for environments where the web server has no direct access to NetBox.

```bash
# Export using CLI flags
python3 netbox_export.py --url https://netbox.example.com --token your_token

# Export using environment variables
NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=your_token python3 netbox_export.py

# Custom output path and pretty-printed JSON
python3 netbox_export.py --url ... --token ... --output /var/www/cgi-bin/netbox_export.json --pretty
```

The output file contains `exported_at` (ISO 8601 UTC timestamp), `source` (NetBox URL), `devices`, and `virtual_machines`. Each record is pruned to the fields the CGI scripts require, including the `domain` NetBox custom field.

## Nagios NRPE plugin (`check_nfs_mounts.sh`)

A Nagios/NRPE plugin that audits NFS mount consistency across three sources and reports mismatches as `WARNING` or `CRITICAL`.

**Sources compared:**

| Source | Meaning |
|---|---|
| `/etc/fstab` | Mounts that *should* be present |
| `/proc/mounts` | Mounts that *are* currently active |
| `nrpe.cfg` `check_disk -p` | Mounts that are being *monitored* |

**Severity matrix:**

| fstab | mounted | nrpe | Result |
|---|---|---|---|
| ✓ | ✓ | ✓ | OK |
| ✓ | ✗ | — | CRITICAL — fstab entry not mounted (`noauto` → WARNING) |
| ✓ | ✗ | ✓ | CRITICAL — configured everywhere but not mounted |
| ✗ | ✗ | ✓ | CRITICAL — nrpe monitoring a non-existent mount |
| ✓ | ✓ | ✗ | WARNING — mounted but not monitored |
| ✗ | ✓ | ✗ | WARNING — ad-hoc mount, not in fstab, not monitored |
| ✗ | ✓ | ✓ | WARNING — monitored but missing from fstab (won't survive reboot) |

### Installation

```bash
cp check_nfs_mounts.sh /usr/lib/nagios/plugins/check_nfs_mounts

# Add to /etc/nagios/nrpe.cfg
command[check_nfs_mounts]=/usr/lib/nagios/plugins/check_nfs_mounts

# Non-default paths
command[check_nfs_mounts]=/usr/lib/nagios/plugins/check_nfs_mounts \
  -c /etc/nagios/nrpe.cfg -d /etc/nagios/nrpe.d
```

### Options

```
-c FILE   Path to nrpe.cfg          (default: /etc/nagios/nrpe.cfg)
-d DIR    Path to nrpe.d directory  (default: /etc/nagios/nrpe.d)
-f FILE   Path to fstab             (default: /etc/fstab)
-v        Verbose: also list OK mounts
-h        Show help
```

Both `nrpe.cfg` and `nrpe.d/*.cfg` are parsed. Either can be absent — the plugin reads whichever exist.

### Example output

```
NFS_MOUNTS CRITICAL: 2 OK, 1 warning(s), 1 critical(s) | nfs_ok=2 nfs_warn=1 nfs_crit=1 nfs_fstab=3 nfs_active=3 nfs_nrpe=2
CRITICAL: /mnt/backup: fstab entry + nrpe check_disk [check_disk_backup] but NOT mounted
WARNING:  /mnt/archive: mounted per fstab but missing from nrpe check_disk
```

Performance data (`nfs_ok`, `nfs_warn`, `nfs_crit`, `nfs_fstab`, `nfs_active`, `nfs_nrpe`) can be graphed by Nagios/PNP4Nagios.

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
