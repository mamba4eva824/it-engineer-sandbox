"""Pytest fixtures for the license_reclaim_orchestrator Lambda."""
from __future__ import annotations

import json
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
TEST_TABLE = "test-orch-ohmgym-license-reclaim-logs"
TEST_INDEX = "jira_issue_key-index"
TEST_CLOUD_ID = "test-cloud-id"
BROKER_URL = "https://broker.example.invalid/reclaim"
OPENAI_URL = "https://api.openai.com/v1/responses"
SECRET_NAMES = {
    "SLACK_BOT_TOKEN_SECRET_NAME": "orch-test/slack-bot-token",
    "JIRA_READ_SECRET_NAME": "orch-test/jira-read",
    "WEBHOOK_SECRET_NAME": "orch-test/broker-webhook-secret",
    "OPENAI_SECRET_NAME": "orch-test/openai",
}

os.environ.update({
    "SECRETS_REGION": TEST_REGION,
    "AWS_DEFAULT_REGION": TEST_REGION,
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "DYNAMODB_TABLE_NAME": TEST_TABLE,
    "DYNAMODB_ISSUE_KEY_INDEX": TEST_INDEX,
    "JIRA_CLOUD_ID": TEST_CLOUD_ID,
    "JIRA_EMAIL": "it-ops@example.com",
    "SLACK_TEAM_ID": "T_TEST",
    "LEAVER_CHANNEL_NAME": "leaver-it-ops",
    "BROKER_FUNCTION_URL": BROKER_URL,
    "OPENAI_MODEL_ID": "gpt-5.6-luna",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MAX_TOKENS": "512",
    "ORCHESTRATOR_AUTO_RUN": "true",
    "ORCHESTRATOR_REQUESTED_BY": "orchestrator@ohmgym.com",
    **SECRET_NAMES,
})

_mock = mock_aws()
_mock.start()

_sm = boto3.client("secretsmanager", region_name=TEST_REGION)
_sm.create_secret(Name=SECRET_NAMES["SLACK_BOT_TOKEN_SECRET_NAME"], SecretString="xoxb-test-token")
_sm.create_secret(Name=SECRET_NAMES["JIRA_READ_SECRET_NAME"], SecretString="jira-read-test-token")
_sm.create_secret(Name=SECRET_NAMES["WEBHOOK_SECRET_NAME"], SecretString="test-shared-secret")
_sm.create_secret(Name=SECRET_NAMES["OPENAI_SECRET_NAME"], SecretString="sk-test-openai")

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
import policy  # noqa: E402

GATEWAY = f"https://api.atlassian.com/ex/jira/{TEST_CLOUD_ID}"
WEBHOOK_SECRET = "test-shared-secret"


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
    issue_key: str = "SUP-10",
    run_date: str = "2026-08-14",
    user_id: str = "00u1",
    login: str = "leaver@ohmgym.com",
    apps: list[dict] | None = None,
) -> dict:
    return {
        "run_date": run_date,
        "user_id": user_id,
        "login": login,
        "okta_id": user_id,
        "jira_issue_key": issue_key,
        "status": "ticketed",
        "correlation_id": f"JIRA-{issue_key}",
        "apps": apps if apps is not None else [
            {"app": "github", "status": "active"},
            {"app": "linear", "status": "not_member"},
            {"app": "jira", "status": "active"},
        ],
    }


def ticket_fields(
    *,
    email: str = "leaver@ohmgym.com",
    apps: str = "github, jira",
    notes: str = "",
) -> dict:
    return {
        "fields": {
            "summary": f"License reclamation: {email}",
            "status": {"name": "Waiting for support", "statusCategory": {"key": "new"}},
            handler.CF_LEAVER_EMAIL: email,
            handler.CF_OKTA_USER_ID: "00u1",
            handler.CF_OFFBOARDING_RUN_ID: "run-1",
            handler.CF_APPS: apps,
            handler.CF_NOTES: notes,
        }
    }


def openai_response(
    *,
    issue_key: str = "SUP-10",
    user_email: str = "leaver@ohmgym.com",
    apps: list[str] | None = None,
    action: str = "reclaim",
    include_usage: bool = True,
    extra_decisions: list[dict] | None = None,
) -> dict:
    decisions = [
        {"app": app, "action": action, "reason": "active seat after offboarding"}
        for app in (apps or ["github", "jira"])
    ]
    if extra_decisions:
        decisions.extend(extra_decisions)
    arguments = {
        "issue_key": issue_key,
        "user_email": user_email,
        "confidence": 0.9,
        "decisions": decisions,
    }
    body = {
        "id": "resp_test",
        "model": "gpt-5.6-luna",
        "output": [{
            "type": "function_call",
            "id": "fc_test",
            "call_id": "call_test",
            "name": "submit_reclaim_plan",
            "arguments": json.dumps(arguments),
        }],
    }
    if include_usage:
        body["usage"] = {
            "input_tokens": 412,
            "output_tokens": 86,
            "total_tokens": 498,
            "input_tokens_details": {"cached_tokens": 0},
        }
    return body


def mock_openai(rm, body: dict | None = None, **kwargs) -> None:
    rm.post(OPENAI_URL, json=body if body is not None else openai_response(**kwargs))


def mock_slack(rm) -> None:
    rm.post(
        "https://slack.com/api/conversations.create",
        json={"ok": True, "channel": {"id": "C_TEST"}},
    )
    rm.post(
        "https://slack.com/api/chat.postMessage",
        json={"ok": True, "ts": "1700000000.000100"},
    )


BROKER_URL = BROKER_URL
WEBHOOK_SECRET = WEBHOOK_SECRET
openai_response = openai_response
make_row = make_row
mock_slack = mock_slack
ticket_fields = ticket_fields
