"""Offline contract tests for the Phase 3 reclaim broker infra.

Asserts the Terraform/IAM encoding of ADR-005 / ADR-006 / P3-R1..R6:
- Broker role (not the scanner role) can read write secrets.
- Scanner role remains untouched — still cannot read write secrets.
- Broker DynamoDB access is Query (GSI) + UpdateItem, never Scan/DeleteItem.
- Function URL is authorization_type=NONE with both public-invoke
  permissions, same pattern as terraform/aws/lambda.tf.
- Broker Errors alarm exists, mirroring the scanner's alarm shape.

Live Function URL / DynamoDB fire tests require `terraform apply`
(operator-gated, never run by this test suite).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STACK = REPO_ROOT / "terraform" / "aws-license-reclaim"
BROKER_HANDLER = REPO_ROOT / "lambdas" / "license_reclaim_broker" / "handler.py"


def _read(*parts: str) -> str:
    return (STACK.joinpath(*parts)).read_text()


def test_broker_role_can_read_write_secrets_scanner_role_still_cannot() -> None:
    broker_iam = _read("broker_iam.tf")
    scanner_iam = _read("iam.tf")
    assert "aws_secretsmanager_secret.write" in broker_iam
    assert "GetSecretValue" in broker_iam
    assert "github-write" in broker_iam
    assert "linear-write" in broker_iam
    assert "jira-write" in broker_iam

    scanner_policy_body = "\n".join(
        line for line in scanner_iam.splitlines() if not line.lstrip().startswith("#")
    )
    assert "aws_secretsmanager_secret.write" not in scanner_policy_body


def test_broker_has_its_own_execution_role_separate_from_scanner() -> None:
    broker_iam = _read("broker_iam.tf")
    assert 'aws_iam_role" "broker_exec"' in broker_iam
    assert "lambda_exec" not in broker_iam  # never reuses the scanner's role


def test_broker_dynamodb_is_query_and_updateitem_only_not_scan_or_delete() -> None:
    broker_iam = _read("broker_iam.tf")
    assert "dynamodb:Query" in broker_iam
    assert "dynamodb:UpdateItem" in broker_iam
    assert "jira_issue_key-index" in broker_iam
    assert "dynamodb:Scan" not in broker_iam
    assert "dynamodb:DeleteItem" not in broker_iam
    assert "dynamodb:PutItem" not in broker_iam


def test_dynamodb_table_has_jira_issue_key_gsi() -> None:
    dynamodb = _read("dynamodb.tf")
    assert "jira_issue_key-index" in dynamodb
    assert 'name            = "jira_issue_key-index"' in dynamodb
    assert 'hash_key        = "jira_issue_key"' in dynamodb


def test_broker_function_url_is_none_auth_with_public_invoke_permissions() -> None:
    broker_lambda = _read("broker_lambda.tf")
    assert 'authorization_type = "NONE"' in broker_lambda
    assert "FunctionURLAllowPublicAccess" in broker_lambda
    assert "FunctionURLAllowPublicInvoke" in broker_lambda
    assert 'function_url_auth_type = "NONE"' in broker_lambda


def test_broker_lambda_env_has_no_scanner_read_only_leakage() -> None:
    broker_lambda = _read("broker_lambda.tf")
    env_block = broker_lambda.split("environment")[1]
    assert "GITHUB_WRITE_SECRET_NAME" in env_block
    assert "LINEAR_WRITE_SECRET_NAME" in env_block
    assert "JIRA_WRITE_SECRET_NAME" in env_block
    assert "WEBHOOK_SECRET_NAME" in env_block
    assert "GITHUB_READ_SECRET_NAME" not in env_block
    assert "LINEAR_READ_SECRET_NAME" not in env_block


def test_broker_alarm_mirrors_scanner_alarm_shape() -> None:
    alarms = _read("alarms.tf")
    assert 'alarm_name          = "${var.broker_name_prefix}-errors"' in alarms
    assert "license_reclaim_broker.function_name" in alarms
    assert 'treat_missing_data  = "notBreaching"' in alarms


def test_broker_webhook_secret_is_a_dedicated_shell() -> None:
    secrets = _read("secrets.tf")
    assert "broker-webhook-secret" in secrets
    assert 'aws_secretsmanager_secret" "broker_webhook"' in secrets


def test_broker_handler_never_fetches_write_secrets_at_import_time() -> None:
    """Only the webhook secret may be fetched at module load; write secrets
    must be lazy so a dry-run request never touches Secrets Manager for
    revoke tokens (see handler.py module docstring)."""
    text = BROKER_HANDLER.read_text()
    module_level = text.split("def _load_apps_config")[0]
    assert "_fetch_secret(WEBHOOK_SECRET_NAME)" in module_level
    assert "_fetch_secret(GITHUB_WRITE_SECRET_NAME)" not in module_level
    assert "_fetch_secret(LINEAR_WRITE_SECRET_NAME)" not in module_level
    assert "_fetch_secret(JIRA_WRITE_SECRET_NAME)" not in module_level


def test_broker_never_revokes_error_or_identity_unresolved_findings() -> None:
    """P3-R5: plan_for_app only marks an app 'eligible' when its scan status
    is exactly 'active' — never 'error' or 'identity_unresolved'."""
    text = BROKER_HANDLER.read_text()
    assert 'finding.get("status") != "active"' in text
    assert "not_active_in_findings" in text


def test_broker_idempotent_already_reclaimed_skip() -> None:
    text = BROKER_HANDLER.read_text()
    assert "already_reclaimed" in text
    assert '"reclaimed"' in text
