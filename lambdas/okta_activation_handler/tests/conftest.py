"""Pytest fixtures for the okta_activation_handler (reactive) Lambda.

Same load-order discipline as lambdas/onboarding_workflow/tests/conftest.py:
inject env vars, start moto, seed Secrets Manager (this Lambda needs 5
secrets — one more than the proactive Lambda, since it also verifies inbound
Okta webhook auth), THEN import handler.
"""
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

TEST_REGION = "us-east-1"
TEST_OKTA_ORG = "https://test.okta.com"
SECRET_NAMES = {
    "OKTA_SECRET_NAME": "test/okta-webhook-secret",
    "SLACK_BOT_TOKEN_SECRET_NAME": "test/slack-bot-token",
    "OKTA_API_CLIENT_ID_SECRET_NAME": "test/okta-api-client-id",
    "OKTA_API_KEY_ID_SECRET_NAME": "test/okta-api-key-id",
    "OKTA_API_PRIVATE_KEY_SECRET_NAME": "test/okta-api-private-key",
}

os.environ.update({
    "OKTA_ORG_URL": TEST_OKTA_ORG,
    "SLACK_TEAM_ID": "T_TEST",
    "JOINER_CHANNEL_NAME": "joiner-it-ops",
    "SECRETS_REGION": TEST_REGION,
    "AWS_DEFAULT_REGION": TEST_REGION,
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    **SECRET_NAMES,
})


def _rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


_mock = mock_aws()
_mock.start()

_sm = boto3.client("secretsmanager", region_name=TEST_REGION)
_sm.create_secret(Name=SECRET_NAMES["OKTA_SECRET_NAME"], SecretString="test-okta-shared-secret")
_sm.create_secret(Name=SECRET_NAMES["SLACK_BOT_TOKEN_SECRET_NAME"], SecretString="xoxb-test-token")
_sm.create_secret(Name=SECRET_NAMES["OKTA_API_CLIENT_ID_SECRET_NAME"], SecretString="0oa-test-client-id")
_sm.create_secret(Name=SECRET_NAMES["OKTA_API_KEY_ID_SECRET_NAME"], SecretString="kid-test")
_sm.create_secret(Name=SECRET_NAMES["OKTA_API_PRIVATE_KEY_SECRET_NAME"], SecretString=_rsa_pem())

# Module load happens here — fixtures above must be ready.
import handler  # noqa: E402


@pytest.fixture
def reset_token_cache():
    handler._okta_token_cache["token"] = None
    handler._okta_token_cache["expires_at"] = 0
    yield


def make_event(
    *,
    event_type: str = "user.account.update_password",
    outcome_result: str = "SUCCESS",
    user_id: str = "00uTEST",
    login: str = "test@ohmgym.com",
    full_name: str = "Test User",
    published: str = "2026-05-14T20:57:55.912Z",
) -> dict:
    """One element of data.events[] in the Okta webhook payload."""
    return {
        "eventType": event_type,
        "outcome": {"result": outcome_result},
        "actor": {
            "id": user_id,
            "alternateId": login,
            "displayName": full_name,
            "type": "User",
        },
        "published": published,
    }


@pytest.fixture
def event_factory():
    return make_event
