"""Shared pytest configuration for repo-level JML contract and integration tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: live AWS tests (set JML_INTEGRATION=1)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_integration = config.getoption("--run-integration") or os.environ.get("JML_INTEGRATION") == "1"
    if run_integration:
        return
    skip = pytest.mark.skip(reason="integration tests need --run-integration or JML_INTEGRATION=1")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run live AWS integration tests",
    )
