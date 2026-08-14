"""Pytest fixtures for the offboarding_workflow Lambda."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws

_HANDLER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HANDLER_DIR))

TEST_REGION = "us-west-1"
TEST_TABLE = "ohmgym-offboarding-logs"
TEST_OKTA_ORG = "https://test.okta.com"
TEST_TEAM = "T_TEST"
SECRET_NAMES = {
    "SLACK_BOT_TOKEN_SECRET_NAME": "test/slack-bot-token",
    "OKTA_API_CLIENT_ID_SECRET_NAME": "test/okta-api-client-id",
    "OKTA_API_KEY_ID_SECRET_NAME": "test/okta-api-key-id",
    "OKTA_API_PRIVATE_KEY_SECRET_NAME": "test/okta-api-private-key",
}

os.environ.update({
    "OKTA_ORG_URL": TEST_OKTA_ORG,
    "DYNAMODB_TABLE_NAME": TEST_TABLE,
    "SLACK_TEAM_ID": TEST_TEAM,
    "LEAVER_CHANNEL_NAME": "leaver-it-ops",
    "SECRETS_REGION": TEST_REGION,
    "AWS_DEFAULT_REGION": TEST_REGION,
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "DEACTIVATE_PACE_SECONDS": "0",
    "DYNAMODB_TTL_DAYS": "90",
    **SECRET_NAMES,
})


def _generate_rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


_mock = mock_aws()
_mock.start()

_sm = boto3.client("secretsmanager", region_name=TEST_REGION)
_sm.create_secret(Name=SECRET_NAMES["SLACK_BOT_TOKEN_SECRET_NAME"], SecretString="xoxb-test-token")
_sm.create_secret(Name=SECRET_NAMES["OKTA_API_CLIENT_ID_SECRET_NAME"], SecretString="0oa-test-client-id")
_sm.create_secret(Name=SECRET_NAMES["OKTA_API_KEY_ID_SECRET_NAME"], SecretString="kid-test")
_sm.create_secret(Name=SECRET_NAMES["OKTA_API_PRIVATE_KEY_SECRET_NAME"], SecretString=_generate_rsa_pem())

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


@pytest.fixture
def reset_token_cache():
    handler._okta_token_cache["token"] = None
    handler._okta_token_cache["expires_at"] = 0
    yield


@pytest.fixture
def empty_audit_table():
    table = boto3.resource("dynamodb", region_name=TEST_REGION).Table(TEST_TABLE)
    scan = table.scan()
    with table.batch_writer() as batch:
        for item in scan.get("Items", []):
            batch.delete_item(Key={"run_date": item["run_date"], "user_id": item["user_id"]})
    yield table


def make_okta_user(
    *,
    user_id: str,
    login: str,
    first_name: str = "Test",
    last_name: str = "User",
    department: str = "Engineering",
    role_title: str = "Engineer",
    end_date: str = "2026-05-14",
    github_username: str | None = None,
) -> dict:
    profile = {
        "login": login,
        "email": login,
        "firstName": first_name,
        "lastName": last_name,
        "department": department,
        "role_title": role_title,
        "endDate": end_date,
    }
    if github_username is not None:
        profile["githubUsername"] = github_username
    return {
        "id": user_id,
        "status": "ACTIVE",
        "profile": profile,
    }


@pytest.fixture
def okta_user_factory():
    return make_okta_user
