"""Pytest fixtures for the license_scanner Lambda."""
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
TEST_TABLE = "ohmgym-license-reclaim-logs"
TEST_TEAM = "T_TEST"
TEST_CLOUD_ID = "test-cloud-id"
TEST_ORG = "ohmgym-sandbox"
SECRET_NAMES = {
    "SLACK_BOT_TOKEN_SECRET_NAME": "test/slack-bot-token",
    "GITHUB_READ_SECRET_NAME": "test/github-read",
    "LINEAR_READ_SECRET_NAME": "test/linear-read",
    "JIRA_READ_SECRET_NAME": "test/jira-read",
}

os.environ.update({
    "SECRETS_REGION": TEST_REGION,
    "AWS_DEFAULT_REGION": TEST_REGION,
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "DYNAMODB_TABLE_NAME": TEST_TABLE,
    "DYNAMODB_TTL_DAYS": "90",
    "SLACK_TEAM_ID": TEST_TEAM,
    "LEAVER_CHANNEL_NAME": "leaver-it-ops",
    "GITHUB_ORG": TEST_ORG,
    "JIRA_CLOUD_ID": TEST_CLOUD_ID,
    "JIRA_EMAIL": "it-ops@example.com",
    "JIRA_PROJECT_KEY": "SUP",
    "JIRA_REQUEST_TYPE_ID": "4",
    "JIRA_ISSUE_TYPE_ID": "10079",
    "LINEAR_ORG_UUID": "2cb9e2d3-f42b-42a1-a066-8bc4006c2624",
    "LICENSE_HTTP_MAX_ATTEMPTS": "2",
    "LICENSE_HTTP_BACKOFF_SECONDS": "0",
    **SECRET_NAMES,
})

_mock = mock_aws()
_mock.start()

_sm = boto3.client("secretsmanager", region_name=TEST_REGION)
_sm.create_secret(Name=SECRET_NAMES["SLACK_BOT_TOKEN_SECRET_NAME"], SecretString="xoxb-test-token")
_sm.create_secret(Name=SECRET_NAMES["GITHUB_READ_SECRET_NAME"], SecretString="ghp-test")
_sm.create_secret(Name=SECRET_NAMES["LINEAR_READ_SECRET_NAME"], SecretString="lin_api-test")
_sm.create_secret(Name=SECRET_NAMES["JIRA_READ_SECRET_NAME"], SecretString="jira-test-token")

_ddb = boto3.client("dynamodb", region_name=TEST_REGION)
_ddb.create_table(
    TableName=TEST_TABLE,
    AttributeDefinitions=[
        {"AttributeName": "run_date", "AttributeType": "S"},
        {"AttributeName": "user_id", "AttributeType": "S"},
    ],
    KeySchema=[
        {"AttributeName": "run_date", "KeyType": "HASH"},
        {"AttributeName": "user_id", "KeyType": "RANGE"},
    ],
    BillingMode="PAY_PER_REQUEST",
)
_ddb.update_time_to_live(
    TableName=TEST_TABLE,
    TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl_epoch"},
)

import handler  # noqa: E402
from github_client import scan_github  # noqa: E402
from jira_client import scan_jira  # noqa: E402
from linear_client import scan_linear  # noqa: E402

GATEWAY = f"https://api.atlassian.com/ex/jira/{TEST_CLOUD_ID}"
LINEAR_ORG = "2cb9e2d3-f42b-42a1-a066-8bc4006c2624"


@pytest.fixture
def empty_table():
    table = boto3.resource("dynamodb", region_name=TEST_REGION).Table(TEST_TABLE)
    scan = table.scan()
    with table.batch_writer() as batch:
        for item in scan.get("Items", []):
            batch.delete_item(Key={"run_date": item["run_date"], "user_id": item["user_id"]})
    yield table
