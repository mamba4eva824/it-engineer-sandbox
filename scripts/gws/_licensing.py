"""Shared Google Workspace Enterprise License Manager helpers.

Used by scripts/gws/unassign_licenses.py and the SaaS License Dashboard collector.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent.parent
SERVICE_ACCOUNT_KEY = REPO_ROOT / os.getenv(
    "GWS_SERVICE_ACCOUNT_KEY", "credentials/service-account-key.json"
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


def list_all_assignments(service, product_id: str, domain: str) -> list[dict]:
    """Enumerate every license assignment for a product, across SKUs."""
    assignments = []
    page_token = None
    while True:
        try:
            result = (
                service.licenseAssignments()
                .listForProduct(
                    productId=product_id,
                    customerId=domain,
                    maxResults=500,
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 404:
                return []
            raise
        for item in result.get("items", []):
            assignments.append(
                {
                    "productId": item["productId"],
                    "skuId": item["skuId"],
                    "skuName": item.get("skuName", item["skuId"]),
                    "userId": item["userId"].lower(),
                }
            )
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return assignments


def count_unique_users(assignments: list[dict]) -> int:
    return len({a["userId"] for a in assignments})


def sku_breakdown(assignments: list[dict]) -> dict[str, int]:
    return dict(Counter(a["skuName"] for a in assignments))
