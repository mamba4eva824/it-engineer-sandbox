"""West-only secrets configuration for the proactive offboarding Lambda."""
from __future__ import annotations

import handler


def test_secrets_region_is_us_west_1() -> None:
    assert handler.SECRETS_REGION == "us-west-1"


def test_dynamodb_client_region_matches_secrets() -> None:
    assert handler._dynamodb.meta.client.meta.region_name == "us-west-1"
