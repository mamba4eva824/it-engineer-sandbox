"""Overall status rollup for ohmgym-license-reclaim-logs."""
from __future__ import annotations

import sys
from pathlib import Path

LICENSES = Path(__file__).resolve().parents[2] / "scripts" / "licenses"
sys.path.insert(0, str(LICENSES))

from row_status import (  # noqa: E402
    NO_LICENSES_TO_RECLAIM,
    compute_reclaim_row_status,
    compute_scan_row_status,
)


def test_all_not_member_is_no_licenses():
    status, err = compute_scan_row_status([
        {"app": "github", "status": "not_member"},
        {"app": "linear", "status": "not_member"},
        {"app": "jira", "status": "not_member"},
        {"app": "figma", "status": "skipped"},
    ])
    assert status == NO_LICENSES_TO_RECLAIM
    assert err is None


def test_identity_unresolved_without_active_seats_is_no_licenses():
    status, err = compute_scan_row_status([
        {"app": "github", "status": "error", "error_class": "identity_unresolved"},
        {"app": "linear", "status": "not_member"},
        {"app": "jira", "status": "not_member"},
    ])
    assert status == NO_LICENSES_TO_RECLAIM
    assert err is None


def test_not_assigned_without_active_seats_is_no_licenses():
    status, err = compute_scan_row_status([
        {"app": "github", "status": "not_assigned"},
        {"app": "linear", "status": "not_member"},
        {"app": "jira", "status": "not_member"},
        {"app": "figma", "status": "skipped"},
    ])
    assert status == NO_LICENSES_TO_RECLAIM
    assert err is None


def test_connector_error_without_active_seats_stays_partial():
    status, err = compute_scan_row_status([
        {"app": "github", "status": "error", "error_class": "misconfig"},
        {"app": "linear", "status": "not_member"},
        {"app": "jira", "status": "not_member"},
    ])
    assert status == "partial"
    assert err is None


def test_all_connector_errors_is_error():
    status, err = compute_scan_row_status([
        {"app": "github", "status": "error", "error_class": "retryable"},
        {"app": "linear", "status": "error", "error_class": "retryable"},
        {"app": "jira", "status": "error", "error_class": "misconfig"},
    ])
    assert status == "error"
    assert err == "all_connectors_failed"


def test_active_seats_are_ticketed():
    status, err = compute_scan_row_status([
        {"app": "github", "status": "active"},
        {"app": "linear", "status": "not_member"},
    ])
    assert status == "ticketed"
    assert err is None


def test_reclaim_rollup_no_active_apps():
    assert compute_reclaim_row_status(
        [
            {"app": "github", "status": "error", "error_class": "identity_unresolved"},
            {"app": "linear", "status": "not_member"},
        ],
        {},
    ) == NO_LICENSES_TO_RECLAIM


def test_reclaim_rollup_all_active_reclaimed():
    assert compute_reclaim_row_status(
        [{"app": "github", "status": "active"}],
        {"github": {"app": "github", "status": "reclaimed"}},
    ) == "reclaimed"


def test_reclaim_rollup_partial():
    assert compute_reclaim_row_status(
        [
            {"app": "github", "status": "active"},
            {"app": "linear", "status": "active"},
        ],
        {"github": {"app": "github", "status": "reclaimed"}},
    ) == "partial"
