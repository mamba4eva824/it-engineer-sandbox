"""Unit tests: west-only JML migration invariants (Terraform + handler defaults).

These are fast, offline checks that the repo does not regress to east-primary
secrets, cross-region replicas, or the old novatech-okta-hook naming.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TERRAFORM_ROOT = REPO_ROOT / "terraform"

OHMGYM_JML_SECRETS = (
    "ohmgym-jml/slack-bot-token",
    "ohmgym-jml/okta-api-client-id",
    "ohmgym-jml/okta-api-key-id",
    "ohmgym-jml/okta-api-private-key",
    "ohmgym-jml/okta-webhook-secret",
)

PROACTIVE_SECRET_DEFAULTS = OHMGYM_JML_SECRETS[:4]

HANDLER_MODULES = (
    REPO_ROOT / "lambdas/onboarding_workflow/handler.py",
    REPO_ROOT / "lambdas/offboarding_workflow/handler.py",
    REPO_ROOT / "lambdas/okta_activation_handler/handler.py",
)


def _terraform_files() -> list[Path]:
    return sorted(p for p in TERRAFORM_ROOT.rglob("*.tf") if ".terraform" not in p.parts)


@pytest.mark.parametrize("tf_path", _terraform_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_terraform_has_no_replica_blocks(tf_path: Path) -> None:
    assert "replica {" not in tf_path.read_text(), f"{tf_path} must not define Secrets Manager replicas"


@pytest.mark.parametrize("tf_path", _terraform_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_terraform_has_no_legacy_novatech_prefix(tf_path: Path) -> None:
    assert "novatech-okta-hook" not in tf_path.read_text()
    assert "replica_arn" not in tf_path.read_text()


def test_aws_secrets_stack_uses_ohmgym_jml_prefix() -> None:
    variables = (TERRAFORM_ROOT / "aws-secrets/variables.tf").read_text()
    secrets = (TERRAFORM_ROOT / "aws-secrets/secrets.tf").read_text()
    assert 'default     = "ohmgym-jml"' in variables
    for suffix in ("slack-bot-token", "okta-webhook-secret", "okta-api-client-id"):
        assert f'ohmgym-jml/{suffix}' in secrets or f"${{var.name_prefix}}/{suffix}" in secrets


def test_activation_stack_name_and_region_defaults() -> None:
    variables = (TERRAFORM_ROOT / "aws/variables.tf").read_text()
    assert 'default     = "ohmgym-activation-workflow"' in variables
    assert 'default     = "us-west-1"' in variables
    assert "okta_webhook_secret_arn" in variables
    assert "okta_webhook_secret =" not in variables  # values live in aws-secrets


@pytest.mark.parametrize(
    "stack,expected_region",
    [
        ("aws-onboarding", "us-west-1"),
        ("aws-offboarding", "us-west-1"),
        ("aws-secrets", "us-west-1"),
    ],
)
def test_proactive_stacks_default_to_us_west_1(stack: str, expected_region: str) -> None:
    text = (TERRAFORM_ROOT / stack / "variables.tf").read_text()
    assert f'default     = "{expected_region}"' in text


@pytest.mark.parametrize(
    "stack",
    ["aws-onboarding", "aws-offboarding"],
)
def test_proactive_stacks_use_secret_arn_variables(stack: str) -> None:
    text = (TERRAFORM_ROOT / stack / "variables.tf").read_text()
    for name in PROACTIVE_SECRET_DEFAULTS:
        assert name in text
    assert "slack_bot_token_secret_arn" in text


@pytest.mark.parametrize("handler_path", HANDLER_MODULES, ids=lambda p: p.parent.name)
def test_handler_secrets_region_default_is_us_west_1(handler_path: Path) -> None:
    text = handler_path.read_text()
    assert 'os.environ.get("SECRETS_REGION", "us-west-1")' in text


@pytest.mark.parametrize("handler_path", HANDLER_MODULES, ids=lambda p: p.parent.name)
def test_handler_does_not_default_secrets_region_to_us_east_1(handler_path: Path) -> None:
    text = handler_path.read_text()
    assert 'os.environ.get("SECRETS_REGION", "us-east-1")' not in text


def test_terraform_aws_has_no_secrets_tf() -> None:
    assert not (TERRAFORM_ROOT / "aws/secrets.tf").exists()


def test_tfvars_examples_reference_ohmgym_jml_arns() -> None:
    for example in (
        "aws/terraform.tfvars.example",
        "aws-onboarding/terraform.tfvars.example",
        "aws-offboarding/terraform.tfvars.example",
    ):
        text = (TERRAFORM_ROOT / example).read_text()
        assert "ohmgym-jml/" in text
        assert "us-west-1" in text
