"""Pytest fixtures for the license_reclaim_broker Lambda."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

_HANDLER_DIR = Path(__file__).resolve().parent.parent
_LICENSES_DIR = _HANDLER_DIR.parent.parent / "scripts" / "licenses"
sys.path.insert(0, str(_LICENSES_DIR))
sys.path.insert(0, str(_HANDLER_DIR))

TEST_REGION = "us-west-1"
# Distinct names from lambdas/license_scanner/tests/conftest.py — both
# conftest modules call mock_aws().start() without stopping it, so if both
# test suites are ever collected in the *same* pytest process (they are not
# in CI, which runs them as separate `pytest` invocations/steps, but local
# `pytest lambdas/` runs would be) identically-named moto resources collide.
TEST_TABLE = "test-broker-ohmgym-license-reclaim-logs"
TEST_INDEX = "jira_issue_key-index"
TEST_CLOUD_ID = "test-cloud-id"
TEST_ORG = "ohmgym-sandbox"
SECRET_NAMES = {
    "WEBHOOK_SECRET_NAME": "broker-test/broker-webhook-secret",
    "GITHUB_WRITE_SECRET_NAME": "broker-test/github-write",
    "LINEAR_WRITE_SECRET_NAME": "broker-test/linear-write",
    "JIRA_WRITE_SECRET_NAME": "broker-test/jira-write",
    "JIRA_READ_SECRET_NAME": "broker-test/jira-read",
}

os.environ.update({
    "SECRETS_REGION": TEST_REGION,
    "AWS_DEFAULT_REGION": TEST_REGION,
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "DYNAMODB_TABLE_NAME": TEST_TABLE,
    "DYNAMODB_ISSUE_KEY_INDEX": TEST_INDEX,
    "GITHUB_ORG": TEST_ORG,
    "JIRA_CLOUD_ID": TEST_CLOUD_ID,
    "JIRA_EMAIL": "it-ops@example.com",
    "LINEAR_ORG_UUID": "2cb9e2d3-f42b-42a1-a066-8bc4006c2624",
    "LICENSE_HTTP_MAX_ATTEMPTS": "2",
    "LICENSE_HTTP_BACKOFF_SECONDS": "0",
    **SECRET_NAMES,
})

_mock = mock_aws()
_mock.start()

_sm = boto3.client("secretsmanager", region_name=TEST_REGION)
_sm.create_secret(Name=SECRET_NAMES["WEBHOOK_SECRET_NAME"], SecretString="test-shared-secret")
_sm.create_secret(Name=SECRET_NAMES["GITHUB_WRITE_SECRET_NAME"], SecretString="ghp-write-test")
_sm.create_secret(Name=SECRET_NAMES["LINEAR_WRITE_SECRET_NAME"], SecretString="lin_api-write-test")
_sm.create_secret(Name=SECRET_NAMES["JIRA_WRITE_SECRET_NAME"], SecretString="jira-write-test-token")
_sm.create_secret(Name=SECRET_NAMES["JIRA_READ_SECRET_NAME"], SecretString="jira-read-test-token")

_ddb = boto3.client("dynamodb", region_name=TEST_REGION)
_ddb.create_table(
    TableName=TEST_TABLE,
    AttributeDefinitions=[
        {"AttributeName": "run_date", "AttributeType": "S"},
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "jira_issue_key", "AttributeType": "S"},
    ],
    KeySchema=[
        {"AttributeName": "run_date", "KeyType": "HASH"},
        {"AttributeName": "user_id", "KeyType": "RANGE"},
    ],
    GlobalSecondaryIndexes=[
        {
            "IndexName": TEST_INDEX,
            "KeySchema": [{"AttributeName": "jira_issue_key", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
    BillingMode="PAY_PER_REQUEST",
)

import handler  # noqa: E402

WEBHOOK_SECRET = "test-shared-secret"
GATEWAY = f"https://api.atlassian.com/ex/jira/{TEST_CLOUD_ID}"


def _lambda_url_event(*, method: str = "POST", body: dict | None = None, auth: str | None = WEBHOOK_SECRET) -> dict:
    import json as _json

    headers = {}
    if auth is not None:
        headers["authorization"] = auth
    return {
        "requestContext": {"http": {"method": method}},
        "headers": headers,
        "body": _json.dumps(body or {}),
    }


@pytest.fixture
def lambda_url_event():
    return _lambda_url_event


@pytest.fixture
def table():
    return boto3.resource("dynamodb", region_name=TEST_REGION).Table(TEST_TABLE)


@pytest.fixture(autouse=True)
def _clean_table(table):
    scan = table.scan()
    with table.batch_writer() as batch:
        for item in scan.get("Items", []):
            batch.delete_item(Key={"run_date": item["run_date"], "user_id": item["user_id"]})
    yield


def make_row(
    *,
    issue_key: str = "SUP-2",
    run_date: str = "2026-08-14",
    user_id: str = "00u1",
    login: str = "marcus.reyes@ohmgym.com",
    github_username: str = "marcusreyes",
    apps: list[dict] | None = None,
    reclaim: list[dict] | None = None,
) -> dict:
    row = {
        "run_date": run_date,
        "user_id": user_id,
        "login": login,
        "okta_id": user_id,
        "github_username": github_username,
        "jira_issue_key": issue_key,
        "status": "ticketed",
        "apps": apps if apps is not None else [
            {"app": "github", "status": "active"},
            {"app": "linear", "status": "active"},
            {"app": "jira", "status": "active"},
        ],
    }
    if reclaim is not None:
        row["reclaim"] = reclaim
    return row
