#!/usr/bin/env python3
"""
Export NetBox devices and virtual machines to a JSON flat file.

The exported file can be loaded by netbox_devices.cgi and netbox_inventory.cgi
by setting the NETBOX_EXPORT_FILE environment variable to the file path.

Usage:
    python3 netbox_export.py --url https://netbox.example.com --token abc123
    NETBOX_URL=https://netbox.example.com NETBOX_TOKEN=abc123 python3 netbox_export.py
    python3 netbox_export.py --url ... --token ... --output /var/www/netbox_export.json
    python3 netbox_export.py --url ... --token ... --pretty
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Config (env-var fallbacks) ────────────────────────────────────────────────

NETBOX_URL   = os.environ.get("NETBOX_URL", "").rstrip("/")
NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN", "")

# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_all(base_url: str, token: str, endpoint: str) -> list:
    items = []
    url = f"{base_url}/api/{endpoint}/?limit=1000"
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    while url:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        items.extend(data.get("results", []))
        url = data.get("next")
        print(f"  {endpoint}: {len(items)} fetched ...", end="\r", file=sys.stderr)
    print(file=sys.stderr)
    return items

# ── Pruning ───────────────────────────────────────────────────────────────────
# Keep only the fields consumed by netbox_devices.cgi and netbox_inventory.cgi.

def _status(item: dict) -> dict:
    s = item.get("status") or {}
    if isinstance(s, dict):
        val   = s.get("value", "")
        label = s.get("label", val.replace("-", " ").title())
    else:
        val   = str(s)
        label = val.replace("-", " ").title()
    return {"value": val, "label": label}


def _prune_device(d: dict) -> dict:
    tenant = d.get("tenant")
    site   = d.get("site")
    role   = d.get("device_role")
    return {
        "name":        d.get("name", ""),
        "tenant":      {"name": (tenant or {}).get("name", "")} if tenant else None,
        "device_role": {"name": (role   or {}).get("name", "")},
        "site":        {"name": (site   or {}).get("name", "")} if site else None,
        "status":      _status(d),
    }


def _prune_vm(v: dict) -> dict:
    tenant       = v.get("tenant")
    site         = v.get("site")
    role         = v.get("role")
    cluster      = v.get("cluster")
    cluster_site = ((cluster or {}).get("site") or {}).get("name", "") if cluster else ""
    return {
        "name":    v.get("name", ""),
        "tenant":  {"name": (tenant or {}).get("name", "")} if tenant else None,
        "role":    {"name": (role   or {}).get("name", "")} if role   else None,
        "site":    {"name": (site   or {}).get("name", "")} if site   else None,
        "cluster": {"site": {"name": cluster_site}}         if cluster_site else None,
        "status":  _status(v),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Export NetBox inventory to a JSON flat file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  NETBOX_URL    NetBox base URL\n"
            "  NETBOX_TOKEN  NetBox API token\n\n"
            "The output file can be loaded by netbox_devices.cgi and\n"
            "netbox_inventory.cgi via the NETBOX_EXPORT_FILE environment variable."
        ),
    )
    parser.add_argument("--url",    default=NETBOX_URL,   metavar="URL",
                        help="NetBox base URL (default: $NETBOX_URL)")
    parser.add_argument("--token",  default=NETBOX_TOKEN, metavar="TOKEN",
                        help="NetBox API token (default: $NETBOX_TOKEN)")
    parser.add_argument("--output", default="netbox_export.json", metavar="FILE",
                        help="Output file path (default: netbox_export.json)")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON output")
    args = parser.parse_args()

    if not args.url:
        parser.error("NetBox URL required: use --url or set NETBOX_URL")
    if not args.token:
        parser.error("NetBox token required: use --token or set NETBOX_TOKEN")

    base_url = args.url.rstrip("/")

    print(f"Connecting to {base_url} ...", file=sys.stderr)

    try:
        raw_devices = _fetch_all(base_url, args.token, "dcim/devices")
        raw_vms     = _fetch_all(base_url, args.token, "virtualization/virtual-machines")
    except urllib.error.HTTPError as exc:
        print(f"HTTP error {exc.code}: {exc.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Connection error: {exc.reason}", file=sys.stderr)
        sys.exit(1)

    devices = [_prune_device(d) for d in raw_devices]
    vms     = [_prune_vm(v)     for v in raw_vms]

    export = {
        "exported_at":      datetime.now(timezone.utc).isoformat(),
        "source":           base_url,
        "devices":          devices,
        "virtual_machines": vms,
    }

    indent = 2 if args.pretty else None
    with open(args.output, "w") as f:
        json.dump(export, f, indent=indent)

    print(
        f"Exported {len(devices)} devices, {len(vms)} virtual machines "
        f"→ {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
