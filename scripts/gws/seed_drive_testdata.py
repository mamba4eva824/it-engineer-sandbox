#!/usr/bin/env python3
"""
Seed Drive with three test files that exercise every exposure path
audit_sharing.py looks for. Lets you validate the audit end-to-end with
real findings.

Files created (owned by the impersonated user, default GWS_ADMIN_EMAIL):
  1. [PUBLIC LINK]     Anyone with the link can view
  2. [EXTERNAL USER]   Shared with a specific external email
  3. [DOMAIN WIDE]     Shared with the entire tenant domain (internal, informational)

Prerequisites:
  1. Drive API enabled in the GCP project
  2. Service account domain-wide delegation scopes:
       https://www.googleapis.com/auth/drive         (read-write, for create + share)
  3. pip install -r requirements.txt

Usage:
  python seed_drive_testdata.py                          # Uses GWS_ADMIN_EMAIL
  python seed_drive_testdata.py --as alice@ohmgym.com    # Create as a specific user
  python seed_drive_testdata.py --external my.gmail@gmail.com
  python seed_drive_testdata.py --cleanup                # Delete seeded files
"""

import argparse
import os
import sys
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

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

SEED_TAG = "[AUDIT-TEST-SEED]"


def get_drive(user_email: str):
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=DRIVE_SCOPES,
        subject=user_email,
    )
    return build("drive", "v3", credentials=credentials)


def create_doc(drive, title: str, body: str) -> dict:
    """Create a Google Doc with some text content and return its metadata."""
    # Create as plain text, Drive converts to Doc via MIME type
    metadata = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    # Workaround: create empty Doc, then we don't need media_body for sharing test
    f = drive.files().create(body=metadata, fields="id,name,webViewLink").execute()
    return f


def share(drive, file_id: str, permission_body: dict, send_notification=False):
    return drive.permissions().create(
        fileId=file_id,
        body=permission_body,
        sendNotificationEmail=send_notification,
        fields="id,type,role,emailAddress,domain,allowFileDiscovery",
    ).execute()


def seed(drive, external_email: str):
    """Create three files with distinct sharing exposures."""
    results = []

    # 1. Public link
    f1 = create_doc(drive, f"{SEED_TAG} Public Link Doc", "Public link demo")
    share(drive, f1["id"], {"type": "anyone", "role": "reader", "allowFileDiscovery": False})
    print(f"  1. [ANYONE_LINK]   {f1['name']}  ->  {f1['webViewLink']}")
    results.append(f1)

    # 2. External user share
    f2 = create_doc(drive, f"{SEED_TAG} External Share Doc", "External user demo")
    share(
        drive,
        f2["id"],
        {"type": "user", "role": "writer", "emailAddress": external_email},
        send_notification=False,
    )
    print(f"  2. [EXTERNAL_USER] {f2['name']}  ->  shared with {external_email} (writer)")
    results.append(f2)

    # 3. Domain-wide share (informational, internal)
    f3 = create_doc(drive, f"{SEED_TAG} Domain Share Doc", "Internal domain share demo")
    share(
        drive,
        f3["id"],
        {"type": "domain", "role": "reader", "domain": GWS_DOMAIN, "allowFileDiscovery": False},
    )
    print(f"  3. [DOMAIN]        {f3['name']}  ->  shared with @{GWS_DOMAIN}")
    results.append(f3)

    return results


def cleanup(drive):
    """Delete every file whose name starts with the seed tag."""
    page_token = None
    deleted = 0
    while True:
        result = drive.files().list(
            q=f"name contains '{SEED_TAG}' and 'me' in owners and trashed = false",
            pageSize=100,
            pageToken=page_token,
            fields="nextPageToken,files(id,name)",
        ).execute()
        for f in result.get("files", []):
            try:
                drive.files().delete(fileId=f["id"]).execute()
                print(f"  Deleted: {f['name']} ({f['id']})")
                deleted += 1
            except HttpError as e:
                print(f"  FAILED to delete {f['name']}: {e}")
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return deleted


def main():
    parser = argparse.ArgumentParser(description="Seed Drive with sharing-audit test files")
    default_creator = os.getenv("GWS_ADMIN_EMAIL")
    parser.add_argument("--as", dest="creator", default=default_creator, help="User to impersonate as creator")
    parser.add_argument(
        "--external",
        default="mamba4eva824@gmail.com",
        help="Personal/external email for the external-share test file",
    )
    parser.add_argument("--cleanup", action="store_true", help="Delete previously-seeded files")
    args = parser.parse_args()

    if not args.creator:
        print("ERROR: --as or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    print(f"Drive seed as: {args.creator}")
    drive = get_drive(args.creator)

    if args.cleanup:
        print("\nCleaning up seeded files...")
        n = cleanup(drive)
        print(f"\nDeleted {n} files.")
        return

    print(f"External share target: {args.external}\n")
    print("Creating test files...")
    files = seed(drive, args.external)
    print(f"\nSeeded {len(files)} files. Now run:")
    print("  python scripts/gws/audit_sharing.py --report")


if __name__ == "__main__":
    main()
