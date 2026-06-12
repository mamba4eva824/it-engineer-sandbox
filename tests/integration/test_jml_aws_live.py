"""Integration tests against live AWS (sandbox account).

Run locally after migration:
  JML_INTEGRATION=1 pytest tests/integration -v
  # or: pytest tests/integration -v --run-integration

Skipped in CI unless credentials and --run-integration are provided.
"""
from __future__ import annotations

import boto3
import pytest

WEST = "us-west-1"

JML_SECRET_NAMES = (
    "ohmgym-jml/slack-bot-token",
    "ohmgym-jml/okta-api-client-id",
    "ohmgym-jml/okta-api-key-id",
    "ohmgym-jml/okta-api-private-key",
    "ohmgym-jml/okta-webhook-secret",
)

LAMBDA_NAMES = (
    "ohmgym-activation-workflow",
    "ohmgym-onboarding-workflow",
    "ohmgym-offboarding-workflow",
)

DYNAMODB_TABLES = (
    "ohmgym-onboarding-logs",
    "ohmgym-offboarding-logs",
)

LEGACY_PREFIX = "novatech-okta-hook/"


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def secrets_client():
    return boto3.client("secretsmanager", region_name=WEST)


@pytest.fixture(scope="module")
def lambda_client():
    return boto3.client("lambda", region_name=WEST)


@pytest.fixture(scope="module")
def dynamodb_client():
    return boto3.client("dynamodb", region_name=WEST)


def test_ohmgym_jml_secrets_exist_in_us_west_1(secrets_client) -> None:
    for name in JML_SECRET_NAMES:
        desc = secrets_client.describe_secret(SecretId=name)
        assert desc["Name"] == name
        assert desc.get("DeletedDate") is None
        assert "us-west-1" in desc["ARN"]


def test_ohmgym_jml_secrets_have_current_version(secrets_client) -> None:
    for name in JML_SECRET_NAMES:
        resp = secrets_client.get_secret_value(SecretId=name)
        assert resp.get("SecretString"), f"{name} has empty SecretString"


def test_no_legacy_novatech_secrets_in_us_west_1(secrets_client) -> None:
    paginator = secrets_client.get_paginator("list_secrets")
    names = []
    for page in paginator.paginate():
        names.extend(s["Name"] for s in page.get("SecretList", []))
    legacy = [n for n in names if n.startswith(LEGACY_PREFIX)]
    assert legacy == [], f"legacy secrets still present: {legacy}"


def test_no_legacy_novatech_secrets_in_us_east_1() -> None:
    client = boto3.client("secretsmanager", region_name="us-east-1")
    paginator = client.get_paginator("list_secrets")
    names = []
    for page in paginator.paginate():
        names.extend(s["Name"] for s in page.get("SecretList", []))
    legacy = [n for n in names if n.startswith(LEGACY_PREFIX)]
    assert legacy == [], f"legacy east secrets still present: {legacy}"


@pytest.mark.parametrize("function_name", LAMBDA_NAMES)
def test_jml_lambdas_deployed_in_us_west_1(lambda_client, function_name: str) -> None:
    cfg = lambda_client.get_function_configuration(FunctionName=function_name)
    assert cfg["FunctionName"] == function_name
    assert WEST in lambda_client.meta.region_name


def test_activation_lambda_env_uses_ohmgym_jml_secret_names(lambda_client) -> None:
    cfg = lambda_client.get_function_configuration(FunctionName="ohmgym-activation-workflow")
    env = cfg.get("Environment", {}).get("Variables", {})
    assert env.get("SECRETS_REGION") == WEST
    assert env.get("SLACK_BOT_TOKEN_SECRET_NAME") == "ohmgym-jml/slack-bot-token"
    assert env.get("OKTA_SECRET_NAME") == "ohmgym-jml/okta-webhook-secret"


@pytest.mark.parametrize("table_name", DYNAMODB_TABLES)
def test_audit_tables_in_us_west_1(dynamodb_client, table_name: str) -> None:
    desc = dynamodb_client.describe_table(TableName=table_name)
    assert desc["Table"]["TableName"] == table_name
    assert WEST in desc["Table"]["TableArn"]
