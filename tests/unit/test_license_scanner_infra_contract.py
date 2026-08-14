"""Offline contract tests for Phase 2 scanner infra error handling.

These assert the Terraform/IAM encoding of ADR-001, ADR-006, ADR-010, P2-R2,
and P2-R16: retries + DLQ, SNS on Lambda Errors only, read-only secrets,
scanner isolated from offboarding/Okta/write tokens.

Live SNS/DLQ fire tests require terraform apply (operator-gated).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STACK = REPO_ROOT / "terraform" / "aws-license-reclaim"
OFFBOARDING_IAM = REPO_ROOT / "terraform" / "aws-offboarding" / "iam.tf"
SCANNER_HANDLER = REPO_ROOT / "lambdas" / "license_scanner" / "handler.py"
OFFBOARDING_HANDLER = REPO_ROOT / "lambdas" / "offboarding_workflow" / "handler.py"


def _read(*parts: str) -> str:
    return (STACK.joinpath(*parts)).read_text()


def test_eventbridge_retries_twice_then_dlq() -> None:
    eventbridge = _read("eventbridge.tf")
    assert "maximum_retry_attempts       = 2" in eventbridge
    assert "ohmgym-license-scanner-dlq" in eventbridge
    assert "dead_letter_config" in eventbridge
    assert "events.amazonaws.com" in eventbridge
    assert "sqs:SendMessage" in eventbridge


def test_alarm_fires_on_single_lambda_error_not_missing_data() -> None:
    alarms = _read("alarms.tf")
    assert 'metric_name         = "Errors"' in alarms
    assert "threshold           = 1" in alarms
    assert 'treat_missing_data  = "notBreaching"' in alarms
    assert "alarm_actions" in alarms
    assert "aws_sns_topic.alarms.arn" in alarms
    assert 'protocol  = "email"' in alarms


def test_scanner_iam_cannot_read_write_secrets() -> None:
    iam = _read("iam.tf")
    secrets = _read("secrets.tf")
    policy_body = "\n".join(
        line for line in iam.splitlines() if not line.lstrip().startswith("#")
    )
    assert "aws_secretsmanager_secret.read" in policy_body
    assert "GetSecretValue" in policy_body
    assert "aws_secretsmanager_secret.write" not in policy_body
    assert "github-write" in secrets
    assert "linear-write" in secrets
    assert "jira-write" in secrets
    assert "okta" not in policy_body.lower()


def test_scanner_lambda_has_no_okta_or_write_secret_env() -> None:
    lambda_tf = _read("lambda.tf")
    env_block = lambda_tf.split("environment")[1]
    assert "OKTA" not in env_block
    assert "WRITE" not in env_block
    assert "github-read" in env_block
    assert "linear-read" in env_block
    assert "jira-read" in env_block


def test_scanner_dynamodb_is_getitem_putitem_only() -> None:
    iam = _read("iam.tf")
    assert "dynamodb:GetItem" in iam
    assert "dynamodb:PutItem" in iam
    assert "dynamodb:Scan" not in iam
    assert "dynamodb:DeleteItem" not in iam
    assert "license_reclaim_logs" in iam


def test_offboarding_can_put_events_for_scanner_trigger() -> None:
    iam = OFFBOARDING_IAM.read_text()
    assert "events:PutEvents" in iam
    assert "event-bus/default" in iam


def test_offboarding_handler_does_not_invoke_scanner_in_process() -> None:
    text = OFFBOARDING_HANDLER.read_text()
    assert "license_scanner" not in text
    assert "put_events" in text
    assert "leaver.completed" in text


def test_scanner_handler_raises_only_on_documented_infra_classes() -> None:
    text = SCANNER_HANDLER.read_text()
    assert 'error_class": "infra"' in text
    assert "work_queue" in text
    assert "all_connectors_failed" in text
    assert "license_scan_failed" in text
    assert "should_raise" in text


def test_license_reclaim_stack_defaults_to_us_west_1() -> None:
    variables = _read("variables.tf")
    assert 'default     = "us-west-1"' in variables
    handler = SCANNER_HANDLER.read_text()
    assert 'os.environ.get("SECRETS_REGION", "us-west-1")' in handler
    assert 'os.environ.get("SECRETS_REGION", "us-east-1")' not in handler
