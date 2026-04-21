#!/usr/bin/env python3
"""
Bulk-unassign Google Workspace licenses via the Enterprise License Manager API.

Use case: before a Workspace trial expires, sweep the tenant and unassign
every license so no users auto-convert to paid seats. Also serves as a
reusable cost-control tool for real tenants (e.g., reclaim licenses from
suspended users, shrink headcount without canceling a subscription).

Prerequisites:
  1. pip install -r requirements.txt
  2. Service account with domain-wide delegation
  3. New scope in Admin Console > Domain-wide delegation:
       https://www.googleapis.com/auth/apps.licensing

Usage:
  python unassign_licenses.py --dry-run                              # Preview
  python unassign_licenses.py                                        # Unassign every license
  python unassign_licenses.py --exempt chris@ohmgym.com              # Keep chris licensed
  python unassign_licenses.py --exempt-file keep.txt --report        # Keep users in file, write report
  python unassign_licenses.py --product-id Google-Apps               # Scope to a specific product
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SERVICE_ACCOUNT_KEY = (
    Path(__file__).parent.parent.parent
    / os.getenv("GWS_SERVICE_ACCOUNT_KEY", "credentials/service-account-key.json")
)
GWS_DOMAIN = os.getenv("GWS_DOMAIN", "ohmgym.com").lower()

SCOPES = ["https://www.googleapis.com/auth/apps.licensing"]

# Product IDs covered by the Enterprise License Manager API.
#   Google-Apps   — every Workspace tier (Business/Enterprise/Education)
#   101031        — Cloud Identity (Free + Premium)
#   101005        — Cloud Identity Premium (legacy ID, some tenants)
#   101033        — Google Voice
DEFAULT_PRODUCT_IDS = ["Google-Apps", "101031", "101005"]


def get_service(admin_email: str):
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=SCOPES,
        subject=admin_email,
    )
    return build("licensing", "v1", credentials=credentials)


def list_all_assignments(service, product_id: str, domain: str):
    """
    Enumerate every license assignment for a product, across SKUs.
    Returns list of {productId, skuId, skuName, userId}.
    """
    assignments = []
    page_token = None
    while True:
        try:
            result = service.licenseAssignments().listForProduct(
                productId=product_id,
                customerId=domain,
                maxResults=500,
                pageToken=page_token,
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                return []
            raise
        for item in result.get("items", []):
            assignments.append({
                "productId": item["productId"],
                "skuId": item["skuId"],
                "skuName": item.get("skuName", item["skuId"]),
                "userId": item["userId"].lower(),
            })
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return assignments


def unassign(service, product_id: str, sku_id: str, user_id: str, dry_run=False):
    if dry_run:
        print(f"  [DRY RUN] Would unassign {sku_id} from {user_id}")
        return True
    try:
        service.licenseAssignments().delete(
            productId=product_id,
            skuId=sku_id,
            userId=user_id,
        ).execute()
        print(f"  Unassigned {sku_id} from {user_id}")
        return True
    except HttpError as e:
        print(f"  FAILED {sku_id} / {user_id}: {e}")
        return False


def load_exempt_file(path: Path) -> set[str]:
    if not path.exists():
        print(f"ERROR: exempt file not found: {path}")
        sys.exit(1)
    out = set()
    for line in path.read_text().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def generate_report(assignments, actions, dry_run):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_sku_before = defaultdict(int)
    for a in assignments:
        by_sku_before[a["skuName"]] += 1

    unassigned = [a for a in actions if a["status"] == "unassigned"]
    exempt = [a for a in actions if a["status"] == "exempt"]
    failed = [a for a in actions if a["status"] == "failed"]

    lines = [
        "# License Unassignment Report",
        f"\n**Generated:** {timestamp}",
        f"**Domain:** {GWS_DOMAIN}",
        f"**Mode:** {'DRY RUN' if dry_run else 'LIVE'}",
        f"**Total assignments found:** {len(assignments)}",
        f"**Unassigned:** {len(unassigned)}",
        f"**Exempt (kept):** {len(exempt)}",
        f"**Failed:** {len(failed)}",
        "",
        "## License Inventory Before",
        "",
        "| SKU | Count |",
        "|-----|-------|",
    ]
    for sku, count in sorted(by_sku_before.items()):
        lines.append(f"| {sku} | {count} |")
    lines.append("")

    if unassigned:
        lines.append("## Unassigned\n")
        lines.append("| User | SKU |")
        lines.append("|------|-----|")
        for a in unassigned:
            lines.append(f"| {a['userId']} | {a['skuName']} |")
        lines.append("")

    if exempt:
        lines.append("## Exempt (Kept Licensed)\n")
        lines.append("| User | SKU |")
        lines.append("|------|-----|")
        for a in exempt:
            lines.append(f"| {a['userId']} | {a['skuName']} |")
        lines.append("")

    if failed:
        lines.append("## Failed\n")
        for a in failed:
            lines.append(f"- {a['userId']} / {a['skuName']}: {a.get('error', 'unknown')}")
        lines.append("")

    lines.append("---")
    lines.append("\n*Report generated by `scripts/gws/unassign_licenses.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Unassign Workspace licenses in bulk"
    )
    parser.add_argument(
        "--admin-email",
        default=os.getenv("GWS_ADMIN_EMAIL"),
        help="Admin email to impersonate",
    )
    parser.add_argument(
        "--product-id",
        action="append",
        default=None,
        help=f"Product ID to scope to (repeatable). Default: {DEFAULT_PRODUCT_IDS}",
    )
    parser.add_argument(
        "--exempt",
        action="append",
        default=[],
        help="Email to keep licensed (repeatable)",
    )
    parser.add_argument("--exempt-file", help="File with exempt emails (one per line, # comments)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without unassigning")
    parser.add_argument("--report", action="store_true", help="Write markdown report")
    args = parser.parse_args()

    if not args.admin_email:
        print("ERROR: --admin-email or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    exempt = {e.strip().lower() for e in args.exempt}
    if args.exempt_file:
        exempt |= load_exempt_file(Path(args.exempt_file))

    product_ids = args.product_id or DEFAULT_PRODUCT_IDS

    print("Workspace License Unassignment")
    print(f"Admin: {args.admin_email}")
    print(f"Domain: {GWS_DOMAIN}")
    print(f"Products: {', '.join(product_ids)}")
    print(f"Exempt: {', '.join(sorted(exempt)) if exempt else '(none — will unassign all)'}")
    if args.dry_run:
        print("*** DRY RUN — no changes will be made ***")
    print()

    service = get_service(args.admin_email)
    print("Connected to Enterprise License Manager API")

    # Enumerate
    all_assignments = []
    for pid in product_ids:
        print(f"Listing assignments for product {pid}...")
        assignments = list_all_assignments(service, pid, GWS_DOMAIN)
        print(f"  Found {len(assignments)} assignments")
        all_assignments.extend(assignments)

    if not all_assignments:
        print("\nNo license assignments found — nothing to do.")
        return

    # Act
    actions = []
    print(f"\nProcessing {len(all_assignments)} assignments...")
    for a in all_assignments:
        if a["userId"] in exempt:
            print(f"  KEEP  {a['userId']} ({a['skuName']})")
            actions.append({**a, "status": "exempt"})
            continue
        ok = unassign(service, a["productId"], a["skuId"], a["userId"], args.dry_run)
        actions.append({**a, "status": "unassigned" if ok else "failed"})

    # Summary
    unassigned = sum(1 for a in actions if a["status"] == "unassigned")
    kept = sum(1 for a in actions if a["status"] == "exempt")
    failed = sum(1 for a in actions if a["status"] == "failed")
    print(f"\n{'=' * 50}")
    print("UNASSIGNMENT COMPLETE")
    print(f"  Unassigned: {unassigned}")
    print(f"  Kept:       {kept}")
    print(f"  Failed:     {failed}")
    print(f"{'=' * 50}")

    if args.report:
        report = generate_report(all_assignments, actions, args.dry_run)
        report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = report_dir / f"license-unassign-{date_str}.md"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
